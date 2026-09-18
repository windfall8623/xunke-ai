"""Learning preferences, review pause/reschedule and today limits (B05)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.course_review_service import due_candidate_visible, effective_due_at
from app.services.course_today_service import select_today_items
from tests.platform.course_assessment_helpers import published_course


async def _scheduled_review(owner, course_id, lesson_id, *, due_at=None):
    """一条已到期的当前复习安排（直接落库，走 view/调整事务）。"""
    from datetime import datetime as dt

    from app.core.db import execute
    from app.core.values import dump, uid

    await execute(
        "INSERT INTO learning_course_review_states(owner_id,course_id,lesson_id,content_version,"
        "last_question_versions_json,seen_question_versions_json) VALUES(%s,%s,%s,1,%s,%s)",
        (owner, course_id, lesson_id, dump([]), dump([])),
    )
    review_id = uid("rev")
    due = (due_at or dt.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.%f")
    await execute(
        "INSERT INTO learning_course_reviews(review_id,owner_id,course_id,lesson_id,"
        "content_version,schedule_seq,due_at,timezone,reason,status,revision,is_current,"
        "rule_due_at) VALUES(%s,%s,%s,%s,1,1,%s,'Asia/Shanghai','scheduled_review',"
        "'scheduled',1,1,%s)",
        (review_id, owner, course_id, lesson_id, due, due),
    )
    return review_id


@pytest.mark.asyncio
async def test_preferences_default_without_persistence_and_patch_flow(learner):
    api, session = learner
    first = await api.get("/api/v1/study/preferences")
    assert first.status_code == 200, first.text
    view = first.json()["data"]
    assert view["revision"] == 1 and view["daily_minutes"] == 20
    assert view["daily_review_limit"] == 1 and view["difficulty"] == "mixed"

    stale = await api.patch(
        "/api/v1/study/preferences",
        json={"expected_revision": 3, "daily_minutes": 30, "daily_review_limit": 2,
              "difficulty": "easy", "timezone": "Asia/Shanghai"},
    )
    assert stale.status_code == 409

    saved = await api.patch(
        "/api/v1/study/preferences",
        json={"expected_revision": 1, "daily_minutes": 30, "daily_review_limit": 2,
              "difficulty": "easy", "timezone": "Asia/Shanghai"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["revision"] == 2
    reread = await api.get("/api/v1/study/preferences")
    assert reread.json()["data"]["daily_minutes"] == 30


@pytest.mark.asyncio
async def test_review_pause_hides_from_today_and_blocks_start(learner):
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(
        owner, [("cc1", "能解释返回值", "recognition", "返回值", "ready")])
    course_id = course["course_id"]
    lesson_id = course["goals"]["cc1"]["lesson_id"]
    review_id = await _scheduled_review(owner, course_id, lesson_id)
    reviews = (await api.get(f"/api/v1/courses/{course_id}/reviews")).json()["data"]
    review = next(item for item in reviews if item["review_id"] == review_id)

    paused = await api.patch(
        f"/api/v1/courses/{course_id}/reviews/{review['review_id']}",
        json={"expected_revision": review["revision"],
              "expected_content_version": review["content_version"],
              "action": "pause"},
        headers={"Idempotency-Key": "adj-1"},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["data"]["paused"] is True

    replay = await api.patch(
        f"/api/v1/courses/{course_id}/reviews/{review['review_id']}",
        json={"expected_revision": review["revision"],
              "expected_content_version": review["content_version"],
              "action": "pause"},
        headers={"Idempotency-Key": "adj-1"},
    )
    assert replay.status_code == 200
    row = paused.json()["data"]
    assert replay.json()["data"]["revision"] == row["revision"]

    today = (await api.get("/api/v1/courses/today")).json()["data"]
    assert not any(
        item.get("review_id") == review["review_id"] for item in today["items"])

    blocked = await api.post(
        f"/api/v1/courses/{course_id}/lessons/{lesson_id}/review-jobs",
        headers={"Idempotency-Key": "start-paused"},
        json={"review_id": review["review_id"],
              "expected_revision": row["revision"],
              "expected_content_version": review["content_version"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "course_review_paused"

    resumed = await api.patch(
        f"/api/v1/courses/{course_id}/reviews/{review['review_id']}",
        json={"expected_revision": row["revision"],
              "expected_content_version": review["content_version"],
              "action": "resume"},
        headers={"Idempotency-Key": "adj-2"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["data"]["paused"] is False


@pytest.mark.asyncio
async def test_reschedule_overrides_rule_time_and_audits(learner):
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(
        owner, [("cc1", "能解释参数", "recall", "参数", "ready")])
    course_id = course["course_id"]
    lesson_id = course["goals"]["cc1"]["lesson_id"]
    review_id = await _scheduled_review(owner, course_id, lesson_id)
    reviews = (await api.get(f"/api/v1/courses/{course_id}/reviews")).json()["data"]
    review = next(item for item in reviews if item["review_id"] == review_id)

    past = await api.patch(
        f"/api/v1/courses/{course_id}/reviews/{review['review_id']}",
        json={"expected_revision": review["revision"],
              "expected_content_version": review["content_version"],
              "action": "reschedule",
              "due_at": "2020-01-01T09:00:00+00:00"},
        headers={"Idempotency-Key": "adj-past"},
    )
    assert past.status_code == 422

    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    moved = await api.patch(
        f"/api/v1/courses/{course_id}/reviews/{review['review_id']}",
        json={"expected_revision": review["revision"],
              "expected_content_version": review["content_version"],
              "action": "reschedule", "due_at": future},
        headers={"Idempotency-Key": "adj-move"},
    )
    assert moved.status_code == 200, moved.text
    view = moved.json()["data"]
    assert view["override_due_at"] is not None
    assert view["due_at"] == view["override_due_at"]


def test_effective_due_and_visibility_rules():
    rule, override = 1, 2
    assert effective_due_at(rule, None) == rule
    assert effective_due_at(rule, override) == override
    assert due_candidate_visible(paused=True, status="scheduled", due_at=1, now_utc=2) is False
    assert due_candidate_visible(paused=False, status="scheduled", due_at=1, now_utc=2) is True
    assert due_candidate_visible(paused=False, status="completed", due_at=1, now_utc=2) is False


def test_today_limit_only_hides_new_review_suggestions():
    unfinished = {"kind": "continue_quiz", "title": "继续检查", "estimated_minutes": 5,
                  "reason": "未完成", "course_id": "c1", "lesson_id": "l1"}
    reviews = [
        {"kind": "course_review", "title": f"复习 {index}", "estimated_minutes": 5,
         "reason": "到期", "course_id": "c1", "lesson_id": f"l{index}", "review_id": f"r{index}"}
        for index in range(1, 4)
    ]
    selected, warnings = select_today_items([unfinished, *reviews], 60, daily_review_limit=1)
    kinds = [item["kind"] for item in selected]
    assert kinds.count("course_review") == 1
    assert kinds[0] == "continue_quiz"
    assert any("复习上限" in warning for warning in warnings)

    none_allowed, _ = select_today_items(reviews, 60, daily_review_limit=0)
    assert none_allowed == []
