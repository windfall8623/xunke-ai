"""T02 多 Agent 教学任务的持久行为：租约、重复提交、预算、取消与版本发布。

场景 V02：Planner 产物被 Teacher 使用；Reviewer 可以返回问题；一次任务只有一个
共享返修位，新租约不能把它放宽；未通过复核的 guided 稿不得标为已审核；角色与用途
调用上限由持久 meter 执行；冻结的 policy hash 不能被改写来扩大预算。
"""

import json

import pytest
from langchain_core.messages import AIMessageChunk

from app.core.db import execute, fetch_all, fetch_one
from app.core.errors import AppError
from app.core.values import load
from app.services import job_service

from tests.platform.teaching_job_helpers import (  # noqa: F401 - teaching_worker fixture
    ScriptedTeachingChat, blocking_review, guided_course, lesson_draft, outline_draft,
    passing_review, reply, teaching_worker,
)


async def _run(runner, task_id):
    assert await runner.run_once(task_id=task_id)


async def _task(task_id):
    return await fetch_one("SELECT status,stage,error_code,attempt FROM quiz_tasks WHERE task_id=%s", (task_id,))


async def _run_row(task_id):
    return await fetch_one("SELECT * FROM learning_teaching_quality_runs WHERE task_id=%s", (task_id,))


async def _slots(task_id):
    rows = await fetch_all(
        "SELECT s.stage_slot,s.role,s.status,s.generation_revision FROM learning_teaching_agent_steps s "
        "WHERE s.task_id=%s ORDER BY s.started_at,s.step_id", (task_id,),
    )
    return [(row["stage_slot"], row["role"], row["status"]) for row in rows]


async def _calls(task_id):
    rows = await fetch_all(
        "SELECT status,usage_json FROM provider_calls WHERE operation_id=%s ORDER BY created_at,call_id", (task_id,))
    return [(row["status"], load(row["usage_json"], {}).get("purpose")) for row in rows]


async def _published_outline(api, teaching_worker, *, chat=None):
    """Planner draft + passing review → one published outline and its lesson row."""
    chat = chat or ScriptedTeachingChat(reply(outline_draft()), reply(passing_review(kind="outline")))
    task = await guided_course(api, teaching_worker, chat=chat)
    runner = teaching_worker(chat)
    await _run(runner, task["task_id"])
    if runner.execution_errors:
        raise runner.execution_errors[0]
    assert (await _task(task["task_id"]))["status"] == "completed"
    lesson = await fetch_one(
        "SELECT lesson_id FROM learning_course_lessons WHERE course_id=%s ORDER BY position",
        (task["course_id"],))
    return task, lesson["lesson_id"]


async def _lesson_job(api, course_id, lesson_id, *, key="t02-lesson", revision=3):
    return await api.post(
        f"/api/v1/courses/{course_id}/lessons/{lesson_id}/generation-jobs",
        headers={"Idempotency-Key": key}, json={"expected_course_revision": revision},
    )


async def _queued_lesson(api, teaching_worker, *, key="t02-lesson"):
    task, lesson_id = await _published_outline(api, teaching_worker)
    course = await fetch_one("SELECT revision FROM learning_courses WHERE course_id=%s", (task["course_id"],))
    queued = await _lesson_job(api, task["course_id"], lesson_id, key=key, revision=course["revision"])
    assert queued.status_code == 202, queued.text
    return task["course_id"], lesson_id, queued.json()["data"]["task_id"]


@pytest.mark.asyncio
async def test_guided_outline_publishes_a_reviewed_plan_the_teacher_then_reuses(learner, teaching_worker):
    """Planner 稿经复核通过后发布，课时任务绑定同一 plan_hash 与新 draft hash。"""
    api, session = learner
    owner = session["user"]["id"]
    task, lesson_id = await _published_outline(api, teaching_worker)

    outline_run = await _run_row(task["task_id"])
    assert outline_run["status"] == "published" and outline_run["kind"] == "outline"
    assert outline_run["artifact_hash"] and outline_run["candidate_json"] is None
    assert outline_run["reason_code"] is None and outline_run["repair_used"] == 0
    assert await _slots(task["task_id"]) == [
        ("initial", "planner", "completed"), ("review_initial", "reviewer", "completed")]
    assert await _calls(task["task_id"]) == [
        ("completed", "course_outline"), ("completed", "course_teaching_review")]
    summary = await api.get(f"/api/v1/courses/{task['course_id']}")
    assert summary.status_code == 200, summary.text
    assert summary.json()["data"]["quality_summary"]["status"] == "reviewed"

    # 课时任务消费 Planner 的已发布规划：plan_hash 就是纲要的 draft 身份。
    chat = ScriptedTeachingChat(reply(lesson_draft()), reply(passing_review()))
    course = await fetch_one("SELECT revision FROM learning_courses WHERE course_id=%s", (task["course_id"],))
    queued = await _lesson_job(api, task["course_id"], lesson_id, revision=course["revision"])
    assert queued.status_code == 202, queued.text
    lesson_task = queued.json()["data"]["task_id"]
    runner = teaching_worker(chat)
    await _run(runner, lesson_task)
    if runner.execution_errors:
        raise runner.execution_errors[0]
    assert (await _task(lesson_task))["status"] == "completed"

    lesson_run = await _run_row(lesson_task)
    from app.services import course_read
    from app.teaching.protocol import draft_hash

    plan = await course_read.load_course_plan(
        await course_read.owned_course(owner, task["course_id"]))
    assert lesson_run["plan_hash"] == draft_hash(plan)
    assert lesson_run["kind"] == "lesson" and lesson_run["lesson_id"] == lesson_id
    assert lesson_run["status"] == "published" and lesson_run["current_draft_hash"] != outline_run["current_draft_hash"]
    assert await _slots(lesson_task) == [
        ("initial", "teacher", "completed"), ("review_initial", "reviewer", "completed")]
    view = await api.get(f"/api/v1/courses/{task['course_id']}/lessons/{lesson_id}")
    assert view.status_code == 200, view.text
    assert view.json()["data"]["quality_summary"]["status"] == "reviewed"


def _lesson_chunks(draft):
    raw = json.dumps(draft, ensure_ascii=False)
    cut = raw.index('"block_ref": "b2"')
    return [AIMessageChunk(content=part, usage_metadata={
        "input_tokens": 60, "output_tokens": output, "total_tokens": 60 + output,
    }) for part, output in ((raw[:cut], 30), (raw[cut:], 120))]


@pytest.mark.asyncio
@pytest.mark.parametrize("recheck_passes", [True, False])
async def test_guided_repair_streams_before_publication_and_rechecks_its_new_hash(
    learner, teaching_worker, platform_settings, recheck_passes,
):
    api, session = learner
    course_id, lesson_id, task_id = await _queued_lesson(api, teaching_worker)
    platform_settings.content_events_enabled = True
    observations = []

    class StreamingChat(ScriptedTeachingChat):
        disable_streaming = False
        streams = 0

        async def astream(self, messages):
            self.calls.append([message.content for message in messages])
            self.streams += 1
            chunks = self.queue.pop(0)
            for chunk in chunks:
                yield chunk
                # The real SDK adapter has already consumed this chunk and
                # persisted blocks, while this same paid call is unfinished.
                frames = await fetch_all(
                    "SELECT generation_revision,payload_json FROM task_content_frames WHERE task_id=%s ORDER BY seq",
                    (task_id,),
                )
                lesson = await fetch_one(
                    "SELECT content_json FROM learning_course_lessons WHERE lesson_id=%s", (lesson_id,),
                )
                assert lesson["content_json"] is None
                assert frames and {frame["generation_revision"] for frame in frames} == {self.streams}
                observations.append((self.streams, any(load(frame["payload_json"])["type"] == "block" for frame in frames)))

    revised = lesson_draft(example="教学构造：输入 3，执行乘以 2，返回 6 给调用处用于下一步计算。")
    chat = StreamingChat(
        _lesson_chunks(lesson_draft()), reply(blocking_review()), _lesson_chunks(revised),
        reply(passing_review() if recheck_passes else {"dimensions": [], "findings": []}),
    )
    runner = teaching_worker(chat)
    await _run(runner, task_id)
    assert observations == [(1, True), (1, True), (2, True), (2, True)]
    assert chat.streams == 2 and len(chat.calls) == 4
    assert len(await _calls(task_id)) == 4
    steps = await fetch_all(
        "SELECT stage_slot,draft_hash,status FROM learning_teaching_agent_steps WHERE task_id=%s", (task_id,),
    )
    by_slot = {step["stage_slot"]: step for step in steps}
    assert set(by_slot) == {"initial", "review_initial", "repair", "review_recheck"}
    assert by_slot["initial"]["draft_hash"] != by_slot["repair"]["draft_hash"]
    run = await _run_row(task_id)
    assert run["repair_used"] and run["generation_revision"] == 2
    assert load(run["report_json"])["draft_hash"] == by_slot["repair"]["draft_hash"]
    lesson = await fetch_one("SELECT content_json,content_version FROM learning_course_lessons WHERE lesson_id=%s", (lesson_id,))
    head = await fetch_one("SELECT status,generation_revision FROM task_content_heads WHERE task_id=%s", (task_id,))
    task = await api.get(f"/api/v1/courses/tasks/{task_id}")
    assert task.status_code == 200, task.text
    if recheck_passes:
        if runner.execution_errors:
            raise runner.execution_errors[0]
        assert run["status"] == "published" and lesson["content_version"] == 1
        assert load(lesson["content_json"])["payload"]["blocks"][1] == revised["payload"]["blocks"][1]
        assert head == {"status": "finalized", "generation_revision": 2}
        assert task.json()["data"]["quality_summary"]["status"] == "reviewed"
    else:
        assert (await _task(task_id))["error_code"] == "course_quality_blocked"
        assert run["status"] == "failed" and lesson["content_json"] is None and lesson["content_version"] == 0
        assert head["status"] == "unavailable"
        assert task.json()["data"]["quality_summary"]["status"] == "needs_revision"


@pytest.mark.asyncio
async def test_cancel_during_review_fences_late_lesson_publication(learner, teaching_worker):
    api, session = learner
    _, lesson_id, task_id = await _queued_lesson(api, teaching_worker)

    class CancelOnReview(ScriptedTeachingChat):
        async def ainvoke(self, messages):
            response = await super().ainvoke(messages)
            if len(self.calls) == 2:
                await job_service.cancel_job(session["user"]["id"], task_id)
            return response

    chat = CancelOnReview(reply(lesson_draft()), reply(passing_review()))
    runner = teaching_worker(chat)
    await _run(runner, task_id)
    assert (await _task(task_id))["status"] == "cancelled"
    lesson = await fetch_one("SELECT content_json,content_version FROM learning_course_lessons WHERE lesson_id=%s", (lesson_id,))
    assert lesson["content_json"] is None and lesson["content_version"] == 0
    assert (await _run_row(task_id))["status"] == "failed"
    assert len(chat.calls) == len(await _calls(task_id)) == 2


@pytest.mark.asyncio
async def test_unknown_teaching_call_is_not_replayed_after_lease_recovery(learner, teaching_worker):
    api, _ = learner
    _, lesson_id, task_id = await _queued_lesson(api, teaching_worker)
    chat = ScriptedTeachingChat(TimeoutError("isolated interrupted transport"))
    runner = teaching_worker(chat)
    job = await job_service.claim_job(runner.worker_id, task_id=task_id)
    with pytest.raises(TimeoutError):
        await runner._execute(job)
    assert (await _calls(task_id)) == [("unknown", "course_lesson")]
    await execute("UPDATE quiz_tasks SET lease_expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE task_id=%s", (task_id,))
    recovered = await job_service.claim_job(runner.worker_id, task_id=task_id)
    assert recovered["attempt"] == job["attempt"] + 1
    with pytest.raises(AppError) as blocked:
        await runner._execute(recovered)
    assert blocked.value.code == "teaching_call_outcome_unknown"
    assert len(chat.calls) == len(await _calls(task_id)) == 1
    assert (await fetch_one("SELECT content_json FROM learning_course_lessons WHERE lesson_id=%s", (lesson_id,)))["content_json"] is None
    await job_service.fail_job(recovered, blocked.value.code)
    await runner.reconcile(task_id=task_id)
