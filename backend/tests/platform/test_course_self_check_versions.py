"""Versioned saved checks survive the real save → tutor feedback path."""

import json

import pytest

from app.core.db import execute, fetch_all, fetch_one
from app.core.values import dump, load
from app.services.provider_meter import MeteredChat
from app.teaching.protocol import draft_hash, parse_lesson_draft
from app.teaching.tutor import CourseTutorGenerator
from tests.platform.teaching_job_helpers import (  # noqa: F401 - fixture
    ScriptedTeachingChat, lesson_draft, outline_draft, reply, teaching_worker,
)
from tests.platform.test_course_preload import make_course


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["zhixue-teach.v1", "xunke-teach.v1", "xunke-teach.v2"])
async def test_saved_check_keeps_its_versioned_goal_context_through_tutor_feedback(
    learner, teaching_worker, version,
):
    api, session = learner
    owner = session["user"]["id"]
    outline, lesson = outline_draft(), lesson_draft()
    outline["schema_version"] = lesson["schema_version"] = version
    unit = outline["payload"]["units"][0]
    if version.endswith("v1"):
        outline["payload"].pop("course_criteria")
        unit.pop("course_criterion_refs")
        lesson["payload"].pop("alignments")
        for block in lesson["payload"]["blocks"]:
            block.pop("block_ref")
            block.pop("course_criterion_refs")
        for check in lesson["payload"]["checks"]:
            check.pop("course_criterion_refs")
    checked = parse_lesson_draft(lesson)
    course_id, _, lessons = await make_course(owner, [unit], preload=False)
    lesson_id = lessons[0]
    metadata = {**outline, "payload": {key: value for key, value in outline["payload"].items() if key != "units"}}
    await execute("UPDATE learning_courses SET outline_json=%s WHERE course_id=%s", (dump(metadata), course_id))
    await execute(
        "UPDATE learning_course_lessons SET content_json=%s,status='ready',content_version=1 WHERE lesson_id=%s",
        (dump(lesson), lesson_id),
    )
    chat = ScriptedTeachingChat(reply({
        "source_policy": "topic", "mode": "check", "answer": None,
        "feedback": {"expressed_points": ["已说明参数与返回值的区别"], "gaps": [],
                     "suggestions": ["再用另一组输入说明返回结果如何被调用方使用"]},
        "source_refs": [], "insufficient_evidence": False, "warnings": [],
    }))
    runner = teaching_worker(chat)
    runner.course_tutor_generator = CourseTutorGenerator(
        MeteredChat(chat, purpose="course_tutor", output_upper=1500),
    )
    base = f"/api/v1/courses/{course_id}/lessons/{lesson_id}"
    original_hashes = (draft_hash(metadata), draft_hash(lesson))
    outline_view = await api.get(f"/api/v1/courses/{course_id}")
    content_view = await api.get(base)
    assert outline_view.status_code == 200, outline_view.text
    assert content_view.status_code == 200, content_view.text
    assert outline_view.json()["data"]["lessons"][0]["title"] == unit["title"]
    assert content_view.json()["data"]["checks"][0]["prompt"] == lesson["payload"]["checks"][0]["prompt"]
    body = {"expected_content_version": 1, "check_ref": "check1", "answer": "参数接收输入，return 把结果交给调用方。"}
    saved = await api.post(base + "/self-check-attempts", headers={"Idempotency-Key": "versioned-check"}, json=body)
    assert saved.status_code == 201, saved.text
    attempt_id = saved.json()["data"]["attempt_id"]
    repeated = await api.post(base + "/self-check-attempts", headers={"Idempotency-Key": "versioned-check"}, json=body)
    assert repeated.status_code == 201 and repeated.json()["data"]["attempt_id"] == attempt_id
    assert chat.calls == []  # Saving alone must not invoke a model.

    queued = await api.post(base + "/tutor-turns", headers={"Idempotency-Key": "versioned-feedback"}, json={
        "expected_content_version": 1, "mode": "check", "check_attempt_id": attempt_id,
    })
    assert queued.status_code == 202, queued.text
    task_id = queued.json()["data"]["task"]["task_id"]
    assert await runner.run_once(task_id=task_id)
    if runner.execution_errors:
        raise runner.execution_errors[0]
    assert (await fetch_one("SELECT status FROM quiz_tasks WHERE task_id=%s", (task_id,)))["status"] == "completed"
    assert len(chat.calls) == 1
    provider_input = json.loads(chat.calls[0][1])
    assert provider_input["check_context"] == {
        "check": checked.payload.checks[0].model_dump(mode="json"), "answer": body["answer"],
    }
    if version.endswith("v2"):
        assert provider_input["check_context"]["check"]["course_criterion_refs"] == ["cc1"]
    view = await api.get(base + "/self-check-attempts", params={"content_version": 1})
    assert view.status_code == 200, view.text
    attempts = view.json()["data"]
    assert len(attempts) == 1 and attempts[0]["answer"] == body["answer"]
    turn = attempts[0]["latest_tutor_turn"]
    assert turn["task"]["status"] == "completed" and "已说明参数" in turn["answer"]
    assert any("不计入正式成绩" in warning for warning in turn["warnings"])
    stored_outline = load((await fetch_one("SELECT outline_json FROM learning_courses WHERE course_id=%s", (course_id,)))["outline_json"])
    stored_lesson = load((await fetch_one("SELECT content_json FROM learning_course_lessons WHERE lesson_id=%s", (lesson_id,)))["content_json"])
    assert stored_lesson == lesson and stored_outline == metadata
    assert (draft_hash(stored_outline), draft_hash(stored_lesson)) == original_hashes
    assert not await fetch_all("SELECT id FROM answer_records WHERE user_id=%s", (owner,))
