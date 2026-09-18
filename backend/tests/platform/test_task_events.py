"""任务公开事件（R02）：同事务追加、回滚无残留、终态收敛与游标读取。"""

import uuid
from datetime import timedelta

import pytest

from tests.platform.conftest import database, platform_settings  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _count_events(task_id):
    from app.core.db import fetch_one

    row = await fetch_one(
        "SELECT COUNT(*) AS n, COALESCE(MAX(seq),0) AS max_seq FROM task_public_events WHERE task_id=%s",
        (task_id,),
    )
    return int(row["n"]), int(row["max_seq"])


async def _events(task_id):
    from app.core.db import fetch_all
    from app.core.values import load

    rows = await fetch_all(
        "SELECT seq,attempt,event_type,payload_json FROM task_public_events "
        "WHERE task_id=%s ORDER BY seq",
        (task_id,),
    )
    events = []
    for r in rows:
        stored = load(r["payload_json"])
        events.append(
            {
                "seq": r["seq"],
                "attempt": r["attempt"],
                "type": r["event_type"],
                "payload": stored["payload"],
            }
        )
    return events


@pytest.mark.asyncio
async def test_qa_task_event_lifecycle_is_atomic_and_sequenced(learner):
    _, session = learner
    from app.services import job_service

    owner = session["user"]["id"]
    job = await job_service.enqueue_job(
        owner,
        "qa",
        {"session_id": "sess_x", "question": "q"},
        "qa-events-" + uuid.uuid4().hex,
    )
    assert job["kind"] == "qa"
    claimed = await job_service.claim_job("worker-a", task_id=job["task_id"])
    await job_service.complete_job(claimed, {"answer_id": "a1"})
    events = await _events(job["task_id"])
    assert [e["type"] for e in events] == ["phase", "phase", "completed"]
    assert [e["payload"]["status"] for e in events] == ["queued", "running", "completed"]
    assert events[0]["attempt"] == 0 and events[1]["attempt"] == 1
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    assert events[2]["payload"]["business_settled"] is True
    # 执行身份只由 task 与 attempt 组成
    from app.models.task_event import execution_id

    assert events[1]["payload"]["status"] == "running"
    assert execution_id(job["task_id"], 1) == f"{job['task_id']}.a1"


@pytest.mark.asyncio
async def test_quiz_kind_writes_events_and_evaluation_mode_writes_none(learner):
    _, session = learner
    from app.services import job_service

    owner = session["user"]["id"]
    job = await job_service.enqueue_job(
        owner, "quiz", {"user_input": "x", "question_count": 3}, "quiz-ev-" + uuid.uuid4().hex
    )
    claimed = await job_service.claim_job("worker-a", task_id=job["task_id"])
    await job_service.complete_job(claimed, {})
    events = await _events(job["task_id"])
    assert [event["type"] for event in events] == ["phase", "phase", "completed"]
    assert [event["payload"]["status"] for event in events] == ["queued", "running", "completed"]
    assert events[-1]["payload"]["business_settled"] is True
    eval_job = await job_service.enqueue_job(
        owner,
        "qa",
        {"session_id": "s"},
        "qa-eval-" + uuid.uuid4().hex,
        mode="evaluation",
    )
    assert await _count_events(eval_job["task_id"]) == (0, 0)


@pytest.mark.asyncio
async def test_rollback_writes_no_task_and_no_events(learner):
    _, session = learner
    from app.core.db import fetch_one, transaction
    from app.services import job_service

    owner = session["user"]["id"]
    with pytest.raises(RuntimeError):
        async with transaction() as conn:
            job = await job_service.enqueue_job(
                owner,
                "qa",
                {"session_id": "s"},
                "rollback-" + uuid.uuid4().hex,
                conn=conn,
            )
            raise RuntimeError("force rollback")
    row = await fetch_one(
        "SELECT task_id FROM quiz_tasks WHERE task_id=%s", (job["task_id"],)
    )
    assert row is None
    assert await _count_events(job["task_id"]) == (0, 0)


@pytest.mark.asyncio
async def test_stale_lease_completes_nothing_and_writes_no_completed_event(learner):
    _, session = learner
    from app.core.errors import AppError
    from app.core.values import now
    from app.services import job_service

    owner = session["user"]["id"]
    job = await job_service.enqueue_job(
        owner, "qa", {"session_id": "s"}, "stale-" + uuid.uuid4().hex
    )
    from app.core.db import execute

    claimed = await job_service.claim_job("worker-a", task_id=job["task_id"])
    await execute(
        "UPDATE quiz_tasks SET lease_expires_at=%s WHERE task_id=%s",
        (now() - timedelta(seconds=1), job["task_id"]),
    )
    replacement = await job_service.claim_job("worker-b", task_id=job["task_id"])
    with pytest.raises(AppError):
        await job_service.complete_job(claimed, {})
    await job_service.complete_job(replacement, {})
    events = await _events(job["task_id"])
    completed = [e for e in events if e["type"] == "completed"]
    assert len(completed) == 1 and completed[0]["attempt"] == replacement["attempt"]


@pytest.mark.asyncio
async def test_finalize_terminal_rows_records_cancel_and_deadline(learner):
    _, session = learner
    from app.core.db import execute, transaction
    from app.core.values import now
    from app.services import job_service

    owner = session["user"]["id"]
    cancelled = await job_service.enqueue_job(
        owner, "qa", {"session_id": "s"}, "fin-c-" + uuid.uuid4().hex
    )
    await job_service.claim_job("worker-a", task_id=cancelled["task_id"])
    await execute(
        "UPDATE quiz_tasks SET cancel_requested=TRUE WHERE task_id=%s",
        (cancelled["task_id"],),
    )
    expired = await job_service.enqueue_job(
        owner, "qa", {"session_id": "s"}, "fin-d-" + uuid.uuid4().hex
    )
    await execute(
        "UPDATE quiz_tasks SET queued_expires_at=%s WHERE task_id=%s",
        (now() - timedelta(seconds=1), expired["task_id"]),
    )
    async with transaction() as conn:
        # Other verification processes may share the isolated database.
        await job_service.finalize_terminal_rows(conn, task_id=cancelled["task_id"])
        await job_service.finalize_terminal_rows(conn, task_id=expired["task_id"])
    cancel_events = await _events(cancelled["task_id"])
    assert cancel_events[-1]["type"] == "cancelled"
    assert cancel_events[-1]["payload"]["business_settled"] is False
    deadline_events = await _events(expired["task_id"])
    assert deadline_events[-1]["type"] == "failed"
    assert deadline_events[-1]["payload"]["error_code"] == "deadline_exceeded"


@pytest.mark.asyncio
async def test_read_task_events_filters_attempt_and_seq_range(learner):
    _, session = learner
    from app.core.db import execute
    from app.core.values import now
    from app.services import job_service, task_event_service

    owner = session["user"]["id"]
    job = await job_service.enqueue_job(
        owner, "qa", {"session_id": "s"}, "read-" + uuid.uuid4().hex
    )
    first = await job_service.claim_job("worker-a", task_id=job["task_id"])
    await execute(
        "UPDATE quiz_tasks SET lease_expires_at=%s WHERE task_id=%s",
        (now() - timedelta(seconds=1), job["task_id"]),
    )
    second = await job_service.claim_job("worker-b", task_id=job["task_id"])
    a1_events = await task_event_service.read_task_events(
        owner, job["task_id"], attempt=1
    )
    a2_events = await task_event_service.read_task_events(
        owner, job["task_id"], attempt=2
    )
    assert [e.seq for e in a1_events] == [2]  # queued 是 a0，starting 是 a1
    assert [e.seq for e in a2_events] == [3]
    ranged = await task_event_service.read_task_events(
        owner, job["task_id"], attempt=1, after_seq=2, through_seq=2
    )
    assert ranged == []
    assert first["attempt"] == 1 and second["attempt"] == 2


def test_notifier_merges_same_task_to_max_seq():
    from app.models.task_event import TaskSignal
    from app.services.task_event_notifier import merge_signals

    merged = merge_signals(
        [
            TaskSignal(task_id="t1", owner_id=1, execution_id="t1.a1", seq=2),
            TaskSignal(task_id="t1", owner_id=1, execution_id="t1.a1", seq=5),
            TaskSignal(task_id="t2", owner_id=1, execution_id="t2.a1", seq=1),
        ]
    )
    assert sorted((s.task_id, s.seq) for s in merged) == [("t1", 5), ("t2", 1)]


def test_business_settled_requires_reconciled_stage():
    from app.models.task_event import business_settled_from as settled

    assert settled("completed", "completed") is True
    assert settled("failed", "failed") is False
    assert settled("failed", "failed_reconciled") is True
    assert settled("cancelled", "cancelled_reconciled") is True
    assert settled("running", "generating") is False
