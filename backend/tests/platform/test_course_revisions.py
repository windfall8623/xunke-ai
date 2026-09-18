"""Limited course revisions: preview, candidate apply and version history (B06)."""

import pytest

from app.core.config import get_settings
from app.core.db import fetch_one
from app.services.course_revision_service import (
    mark_revision_candidate,
    revision_can_apply,
)
from tests.platform.course_assessment_helpers import published_course
from tests.platform.teaching_job_helpers import lesson_draft


def test_revision_can_apply_matrix():
    assert revision_can_apply(
        current_course_revision=4, expected_course_revision=4,
        current_versions={"lesson-a": 2}, frozen_versions={"lesson-a": 2},
        all_drafts_ready=True, any_active_lesson_generation=False,
    ) is True
    assert revision_can_apply(
        current_course_revision=5, expected_course_revision=4,
        current_versions={"lesson-a": 2}, frozen_versions={"lesson-a": 2},
        all_drafts_ready=True, any_active_lesson_generation=False,
    ) is False
    assert revision_can_apply(
        current_course_revision=4, expected_course_revision=4,
        current_versions={"lesson-a": 3}, frozen_versions={"lesson-a": 2},
        all_drafts_ready=True, any_active_lesson_generation=False,
    ) is False
    assert revision_can_apply(
        current_course_revision=4, expected_course_revision=4,
        current_versions={"lesson-a": 2}, frozen_versions={"lesson-a": 2},
        all_drafts_ready=False, any_active_lesson_generation=False,
    ) is False


@pytest.mark.asyncio
async def test_revision_preview_apply_and_history(learner):
    get_settings().enable_course_revisions = True
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, [
        ("cc1", "能解释返回值", "recognition", "返回值", "ready"),
        ("cc2", "能解释参数", "recall", "参数", "ready"),
    ])
    course_id = course["course_id"]
    first = course["goals"]["cc1"]["lesson_id"]
    second = course["goals"]["cc2"]["lesson_id"]

    preview = await api.post(
        f"/api/v1/courses/{course_id}/revision-previews",
        headers={"Idempotency-Key": "rev-1"},
        json={"expected_course_revision": 2, "expected_criteria_revision": 1,
              "lessons": [{"lesson_id": first, "expected_content_version": 1,
                           "instruction": "补充一个返回值示例"}]},
    )
    assert preview.status_code == 201, preview.text
    view = preview.json()["data"]
    revision_id = view["revision_id"]
    assert view["impacts"][0]["next_content_version"] == 2

    # 其他课时不受影响：预览只包含所选课。
    assert view["impacts"][0]["lesson_id"] == first

    stale = await api.post(
        f"/api/v1/courses/{course_id}/revision-previews",
        headers={"Idempotency-Key": "rev-2"},
        json={"expected_course_revision": 99, "expected_criteria_revision": 1,
              "lessons": [{"lesson_id": first, "expected_content_version": 1,
                           "instruction": "x"}]},
    )
    assert stale.status_code == 409

    # 未生成候选时不能发布。
    early = await api.post(
        f"/api/v1/courses/{course_id}/revisions/{revision_id}/apply",
        headers={"Idempotency-Key": "apply-early"},
        json={"expected_course_revision": 2, "expected_revision": 1},
    )
    assert early.status_code == 409

    # 候选稿（真实路径由 course_lesson worker 写回；此处直接写回同一函数）。
    from app.core.db import execute

    draft = lesson_draft()
    await mark_revision_candidate(course_id, owner, revision_id, first,
                                  draft, conn=None)
    marked = await api.get(f"/api/v1/courses/{course_id}/revisions/{revision_id}")
    assert marked.json()["data"]["status"] == "ready"

    applied = await api.post(
        f"/api/v1/courses/{course_id}/revisions/{revision_id}/apply",
        headers={"Idempotency-Key": "apply-1"},
        json={"expected_course_revision": 2, "expected_revision": marked.json()["data"]["revision"]},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["data"]["status"] == "applied"

    # 旧正文已快照；当前版本 +1 且 read_at 清空；第二课不受影响。
    lesson_row = await fetch_one(
        "SELECT content_version,status,read_at FROM learning_course_lessons "
        "WHERE lesson_id=%s AND owner_id=%s", (first, owner))
    assert lesson_row["content_version"] == 2 and lesson_row["read_at"] is None
    other = await fetch_one(
        "SELECT content_version,content_json FROM learning_course_lessons "
        "WHERE lesson_id=%s AND owner_id=%s", (second, owner))
    assert other["content_version"] == 1 and other["content_json"] is not None

    versions = (await api.get(
        f"/api/v1/courses/{course_id}/lessons/{first}/versions")).json()["data"]
    assert [item["content_version"] for item in versions] == [1]
    history = await api.get(
        f"/api/v1/courses/{course_id}/lessons/{first}/versions/1")
    assert history.status_code == 200
    assert history.json()["data"]["read_only"] is True

    # 幂等：重复 apply 返回 applied 状态，不再推进版本。
    again = await api.post(
        f"/api/v1/courses/{course_id}/revisions/{revision_id}/apply",
        headers={"Idempotency-Key": "apply-2"},
        json={"expected_course_revision": 3, "expected_revision": 3},
    )
    assert again.status_code == 200
    assert again.json()["data"]["status"] == "applied"
