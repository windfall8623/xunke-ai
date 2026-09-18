"""Personal outcome export: authorization, hygiene and escaping (C01)."""

import pytest

from app.services.course_export_service import (
    export_filename,
    literal_answer_block,
    markdown_label,
)
from tests.platform.course_assessment_helpers import published_course


def test_markdown_and_filename_escaping():
    assert markdown_label("<script>alert(1)</script>") != "<script>alert(1)</script>"
    assert "<script>" not in markdown_label("<script>")
    assert literal_answer_block("line1\nline2").splitlines()[0].startswith("    ")
    assert export_filename("../course/a") == "xunke-learning-___course_a.md"
    assert len(export_filename("x" * 300)) <= len("xunke-learning-") + 64 + 3


@pytest.mark.asyncio
async def test_export_contains_own_records_only(learner):
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(
        owner, [("cc1", "能解释返回值", "recognition", "返回值", "ready")])
    course_id = course["course_id"]
    lesson_id = course["goals"]["cc1"]["lesson_id"]
    from app.core.db import execute
    from app.core.values import dump, uid

    await execute(
        "INSERT INTO learning_course_check_attempts(attempt_id,course_id,lesson_id,owner_id,"
        "content_version,check_ref,answer_json,idempotency_key,request_hash) "
        "VALUES(%s,%s,%s,%s,1,'check-1',%s,%s,%s)",
        (uid("att"), course_id, lesson_id, owner,
         dump({"answer": "<script>我的理解</script>"}), uid("k"), uid("h")),
    )
    result = await api.get(f"/api/v1/courses/{course_id}/export?format=markdown")
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["filename"] == export_filename(course_id)
    assert "我的理解" in data["markdown"]
    # 个人回答按字面块导出，HTML 被转义，不成为可执行内容。
    assert "<script>" not in data["markdown"]
    assert "&lt;script&gt;我的理解" in data["markdown"] or "    &lt;script&gt;" in data["markdown"]
    # 标准答案与 rubric 不出现。
    assert "rubric" not in data["markdown"]
    assert data["snapshot"]["include_history"] is False

    from tests.platform.conftest import register_email_account

    stranger_session, _ = await register_email_account(api)
    api.headers["X-CSRF-Token"] = stranger_session["csrf_token"]
    foreign = await api.get(f"/api/v1/courses/{course_id}/export")
    assert foreign.status_code == 404
