import asyncio
import uuid
from datetime import timedelta

import pytest


@pytest.mark.asyncio
async def test_idempotency_lease_fencing_and_fixed_quiz_identity(learner):
    api, session = learner
    from app.core.db import execute, fetch_one
    from app.core.errors import AppError
    from app.core.values import now
    from app.services import job_service

    owner = session["user"]["id"]
    key = "quiz_" + uuid.uuid4().hex
    first = await job_service.enqueue_job(
        owner, "quiz", {"user_input": "test", "question_count": 3}, key
    )
    same = await job_service.enqueue_job(
        owner, "quiz", {"question_count": 3, "user_input": "test"}, key
    )
    assert first["task_id"] == same["task_id"] and first["quiz_id"] == same["quiz_id"]
    with pytest.raises(AppError) as exc:
        await job_service.enqueue_job(
            owner, "quiz", {"user_input": "different", "question_count": 3}, key
        )
    assert exc.value.status == 409
    claimed = await job_service.claim_job("worker-a", task_id=first["task_id"])
    await execute(
        "UPDATE quiz_tasks SET lease_expires_at=%s WHERE task_id=%s",
        (now() - timedelta(seconds=1), first["task_id"]),
    )
    replacement = await job_service.claim_job("worker-b", task_id=first["task_id"])
    assert replacement["attempt"] == 2 and replacement["quiz_id"] == first["quiz_id"]
    with pytest.raises(AppError):
        await job_service.complete_job(claimed, {"stale": True})
    await job_service.complete_job(replacement, {"ok": True})
    row = await fetch_one(
        "SELECT status,result_json FROM quiz_tasks WHERE task_id=%s",
        (first["task_id"],),
    )
    assert row["status"] == "completed" and "stale" not in row["result_json"]


@pytest.mark.asyncio
async def test_claim_is_atomic_and_cancellation_fences_publication(learner):
    _, session = learner
    from app.core.errors import AppError
    from app.services import job_service

    job = await job_service.enqueue_job(
        session["user"]["id"],
        "quiz",
        {"user_input": "cancel", "question_count": 3},
        uuid.uuid4().hex,
    )
    claims = await asyncio.gather(
        *(job_service.claim_job(f"w-{i}", task_id=job["task_id"]) for i in range(3))
    )
    active = [c for c in claims if c]
    assert len(active) == 1
    await job_service.cancel_job(session["user"]["id"], job["task_id"])
    with pytest.raises(AppError):
        await job_service.complete_job(active[0], {})


@pytest.mark.asyncio
async def test_atomic_shared_budget_never_oversubscribes(database):
    from app.core.errors import AppError
    from app.services import budget_service

    account = "test:" + uuid.uuid4().hex

    async def reserve(i):
        try:
            return await budget_service.reserve_budget(
                f"{account}:{i}", "calls", 1, [(account, 2)]
            )
        except AppError as exc:
            return exc.code

    outcomes = await asyncio.gather(*(reserve(i) for i in range(5)))
    assert outcomes.count("budget_exceeded") == 3
    from app.core.db import fetch_one

    row = await fetch_one(
        "SELECT used,reserved FROM budget_accounts WHERE account_key=%s", (account,)
    )
    assert row["reserved"] == 2 and row["used"] == 0
