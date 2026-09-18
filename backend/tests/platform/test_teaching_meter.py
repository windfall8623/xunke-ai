import uuid
from types import SimpleNamespace

import pytest

from app.core.db import execute, fetch_all
from app.core.errors import AppError
from app.services import job_service, provider_meter
from app.teaching.policy import freeze_teaching_policy


async def teaching_job(owner):
    policy = freeze_teaching_policy("outline", "guided", False, "topic")
    job = await job_service.enqueue_job(owner, "course_outline", {
        "spec": {"source_policy": "topic"}, "teaching_mode": "guided",
        "teaching_policy": policy.model_dump(mode="json"), "teaching_policy_hash": policy.policy_hash,
    }, uuid.uuid4().hex)
    return await job_service.claim_job("teaching-meter", task_id=job["task_id"])


@pytest.mark.asyncio
async def test_role_caps_and_overall_calls_survive_new_attempt(learner):
    _, session = learner
    job = await teaching_job(session["user"]["id"])
    invoked = []

    async def reply():
        invoked.append(1)
        return SimpleNamespace(content="mock", usage_metadata={"input_tokens": 60, "output_tokens": 20, "total_tokens": 80})

    async def call(purpose):
        with provider_meter.execution(job):
            return await provider_meter.call_external("llm", reply, purpose=purpose, input_upper=80, output_upper=200)

    await call("course_outline")
    with pytest.raises(AppError) as repeated:
        await call("course_outline")
    assert repeated.value.code == "budget_exceeded"
    for purpose in ("course_teaching_review", "course_teaching_repair", "course_teaching_review"):
        await call(purpose)
    assert len(invoked) == 4
    await execute("UPDATE quiz_tasks SET lease_expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE task_id=%s", (job["task_id"],))
    job = await job_service.claim_job("teaching-meter-recovered", task_id=job["task_id"])
    assert job["attempt"] == 2
    with pytest.raises(AppError) as exhausted:
        await call("course_teaching_repair")
    assert exhausted.value.code == "budget_exceeded"
    assert len(invoked) == len(await fetch_all("SELECT call_id FROM provider_calls WHERE operation_id=%s", (job["task_id"],))) == 4


@pytest.mark.asyncio
async def test_unknown_model_outcome_is_not_automatically_replayed(learner):
    _, session = learner
    job = await teaching_job(session["user"]["id"])

    async def unknown():
        raise TimeoutError("synthetic unknown transport result")

    with provider_meter.execution(job):
        with pytest.raises(TimeoutError):
            await provider_meter.call_external("llm", unknown, purpose="course_outline", input_upper=80, output_upper=200)
        with pytest.raises(AppError) as blocked:
            await provider_meter.call_external("llm", unknown, purpose="course_teaching_repair", input_upper=80, output_upper=200)
    assert blocked.value.code == "teaching_call_outcome_unknown"
    assert len(await fetch_all("SELECT call_id FROM provider_calls WHERE operation_id=%s", (job["task_id"],))) == 1
