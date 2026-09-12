"""Owner-worker integration: real sources, SQL, leases and metering; fake text provider."""

import asyncio
from types import SimpleNamespace

import pytest

from tests.platform.qa_helpers import ask, new_session
from tests.platform.qa_helpers import qa_context as qa_context


def install_answer_provider(ctx, monkeypatch, *, history_log=None, before_return=None):
    async def answer(
        question, history, actor, context, scope, config=None, *, progress=None
    ):
        from app.qa.contracts import ChatAnswerArtifact

        if history_log is not None:
            history_log.append(history)
        if progress:
            await progress("generating")
        result = await ctx["engine"].retrieve(question, scope, config)
        selected = result.evidence[0]
        artifact = ChatAnswerArtifact(
            run_id=context.run_id,
            answer_status="answered",
            blocks=[
                {
                    "block_id": "b1",
                    "kind": "fact",
                    "text": selected.excerpt,
                    "citation_refs": [selected.evidence_id],
                }
            ],
            evidence=[selected],
            retrieval_query=question,
            scope_fingerprint=scope.fingerprint,
            pipeline_config_hash=config.pipeline_config_hash,
            model_fingerprint="fixture-no-external-provider",
        )
        if before_return:
            await before_return()
        return artifact

    monkeypatch.setattr(ctx["engine"], "answer", answer, raising=False)


@pytest.mark.asyncio
async def test_qa_worker_publishes_once_with_source_and_no_learning_side_effects(
    qa_context, monkeypatch
):
    from app.core.db import fetch_one

    ctx = qa_context
    history = []
    install_answer_provider(ctx, monkeypatch, history_log=history)
    session = await new_session(ctx)
    task = (await ask(ctx, session)).json()["data"]
    assert await ctx["worker"].run_once(task_id=task["task_id"])
    result = await ctx["api"].get(f"/api/v1/qa/tasks/{task['task_id']}")
    assert result.status_code == 200, result.text
    task = result.json()["data"]
    assert task["status"] == "completed", task
    answer = task["answer"]
    assert answer["answer_status"] == "answered"
    assert task["queue_ms"] >= 0 and task["execution_ms"] >= 0
    citation = answer["blocks"][0]["citation_refs"][0]
    evidence = await ctx["api"].get(
        f"/api/v1/qa/answers/{answer['answer_id']}/evidence/{citation}"
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["data"]["excerpt"] == answer["blocks"][0]["text"]
    replay = await ask(ctx, session)
    assert (
        replay.status_code == 202
        and replay.json()["data"]["answer"]["answer_id"] == answer["answer_id"]
    )
    assert await ctx["worker"].run_once(task_id=task["task_id"]) is False
    row = await fetch_one(
        "SELECT COUNT(*) AS n FROM qa_answers WHERE task_id=%s", (task["task_id"],)
    )
    assert row["n"] == 1
    for table, column in (("quiz_sessions", "user_id"), ("reports", "user_id")):
        row = await fetch_one(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {column}=%s",
            (ctx["actor"].owner_id,),
        )
        assert row["n"] == 0
    assert (
        await fetch_one(
            "SELECT total_xp FROM users WHERE id=%s", (ctx["actor"].owner_id,)
        )
    )["total_xp"] == 0
    feedback = await ctx["api"].post(
        f"/api/v1/qa/answers/{answer['answer_id']}/feedback",
        json={"rating": "helpful", "evaluation_consent": False},
    )
    assert feedback.status_code == 200
    saved = await fetch_one(
        "SELECT evaluation_consent FROM qa_feedback WHERE answer_id=%s",
        (answer["answer_id"],),
    )
    assert saved["evaluation_consent"] == 0
    updated = await ctx["api"].post(
        f"/api/v1/qa/answers/{answer['answer_id']}/feedback",
        json={
            "rating": "unhelpful",
            "reason": "incomplete",
            "comment": "还想了解更多条件",
            "evaluation_consent": True,
        },
    )
    assert updated.status_code == 200
    assert (
        updated.json()["data"]["feedback_id"] == feedback.json()["data"]["feedback_id"]
    )
    saved = await fetch_one(
        "SELECT rating,reason,comment,evaluation_consent FROM qa_feedback WHERE answer_id=%s",
        (answer["answer_id"],),
    )
    assert saved == {
        "rating": "unhelpful",
        "reason": "incomplete",
        "comment": "还想了解更多条件",
        "evaluation_consent": 1,
    }
    followup = (
        await ask(ctx, session, key="followup", content="它有什么作用？")
    ).json()["data"]
    await ctx["worker"].run_once(task_id=followup["task_id"])
    assert len(history) == 2 and history[0] == []
    assert history[1][0].question == "光合作用需要什么？"
    assert history[1][0].answer == answer["blocks"][0]["text"]


@pytest.mark.asyncio
async def test_qa_technical_failure_is_not_an_insufficient_evidence_answer(
    qa_context, monkeypatch
):
    from app.core.db import fetch_one

    ctx = qa_context

    async def failed(*args, **kwargs):
        raise TimeoutError("sensitive provider response must not escape")

    monkeypatch.setattr(ctx["engine"], "answer", failed, raising=False)
    session = await new_session(ctx)
    task = (await ask(ctx, session)).json()["data"]
    await ctx["worker"].run_once(task_id=task["task_id"])
    response = await ctx["api"].get(f"/api/v1/qa/tasks/{task['task_id']}")
    view = response.json()["data"]
    assert view["status"] == "failed" and view["answer"] is None
    assert view["error_code"] == "deadline_exceeded"
    assert "sensitive" not in response.text
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM qa_answers WHERE task_id=%s", (task["task_id"],)
        )
    )["n"] == 0
    history = (
        await ctx["api"].get(f"/api/v1/qa/sessions/{session['session_id']}/messages")
    ).json()["data"]
    assert history["items"][1]["status"] == "failed"
    assert (await ask(ctx, session, key="explicit-retry")).status_code == 202


@pytest.mark.asyncio
async def test_qa_cancel_fences_inflight_answer(qa_context, monkeypatch):
    from app.core.db import fetch_one

    ctx = qa_context
    ready, release = asyncio.Event(), asyncio.Event()

    async def pause():
        ready.set()
        await release.wait()

    install_answer_provider(ctx, monkeypatch, before_return=pause)
    session = await new_session(ctx)
    task = (await ask(ctx, session)).json()["data"]
    execution = asyncio.create_task(ctx["worker"].run_once(task_id=task["task_id"]))
    try:
        await asyncio.wait_for(ready.wait(), 10)
        result = await ctx["api"].post(f"/api/v1/qa/tasks/{task['task_id']}/cancel")
        assert result.json()["data"]["status"] == "cancelled"
    finally:
        release.set()
        await execution
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM qa_answers WHERE task_id=%s", (task["task_id"],)
        )
    )["n"] == 0
    assert (await ctx["api"].get(f"/api/v1/qa/tasks/{task['task_id']}")).json()["data"][
        "answer"
    ] is None


@pytest.mark.asyncio
async def test_qa_recovery_uses_original_identity_and_fences_old_lease(
    qa_context, monkeypatch
):
    from app.core.db import execute, fetch_one
    from app.core.errors import AppError
    from app.services import job_service

    ctx = qa_context
    install_answer_provider(ctx, monkeypatch)
    session = await new_session(ctx)
    task = (await ask(ctx, session)).json()["data"]
    old = await job_service.claim_job("stopped-owner", task_id=task["task_id"])
    await execute(
        "UPDATE quiz_tasks SET lease_expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE task_id=%s",
        (task["task_id"],),
    )
    await ctx["worker"].run_once(task_id=task["task_id"])
    response = await ctx["api"].get(f"/api/v1/qa/tasks/{task['task_id']}")
    assert response.json()["data"]["status"] == "completed", response.text
    with pytest.raises(AppError) as stale:
        await job_service.complete_job(old, {})
    assert stale.value.code == "stale_lease"
    assert (
        await fetch_one(
            "SELECT attempt FROM quiz_tasks WHERE task_id=%s", (task["task_id"],)
        )
    )["attempt"] == 2
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM qa_answers WHERE task_id=%s", (task["task_id"],)
        )
    )["n"] == 1


@pytest.mark.asyncio
async def test_qa_scope_change_starts_new_history_and_cleanup_erases_derivatives(
    qa_context, monkeypatch
):
    from app.core.db import fetch_one

    ctx = qa_context
    history = []
    install_answer_provider(ctx, monkeypatch, history_log=history)
    session = await new_session(ctx)
    first = (await ask(ctx, session)).json()["data"]
    await ctx["worker"].run_once(task_id=first["task_id"])
    first = (await ctx["api"].get(f"/api/v1/qa/tasks/{first['task_id']}")).json()[
        "data"
    ]
    assert first["status"] == "completed", first
    changed = (
        await ctx["api"].patch(
            f"/api/v1/qa/sessions/{session['session_id']}/scope",
            json={
                "scope": {"documents": [{"doc_id": ctx["document"]["doc_id"]}]},
                "expected_revision": 1,
            },
        )
    ).json()["data"]
    second = (await ask(ctx, changed, key="new-scope-question")).json()["data"]
    await ctx["worker"].run_once(task_id=second["task_id"])
    assert history == [[], []]
    deletion = await ctx["api"].delete(
        "/api/v1/knowledge/documents/" + ctx["document"]["doc_id"]
    )
    revoked = await ctx["api"].get(
        f"/api/v1/qa/answers/{first['answer']['answer_id']}/evidence/{first['answer']['evidence'][0]['evidence_id']}"
    )
    assert revoked.status_code == 404
    await ctx["worker"].run_once(task_id=deletion.json()["data"]["task_id"])
    saved = await fetch_one(
        "SELECT artifact_json FROM qa_answers WHERE answer_id=%s",
        (first["answer"]["answer_id"],),
    )
    assert saved["artifact_json"] is None
    row = await fetch_one(
        "SELECT COUNT(*) AS n FROM qa_messages WHERE session_id=%s AND content<>''",
        (session["session_id"],),
    )
    assert row["n"] == 0


@pytest.mark.asyncio
async def test_qa_five_call_cap_survives_restart_and_unknown_cost_stays_reserved(
    qa_context, platform_settings
):
    from app.core.db import execute, fetch_all
    from app.core.errors import AppError
    from app.services import job_service, provider_meter

    ctx = qa_context
    platform_settings.llm_input_cny_per_million = 1
    platform_settings.llm_output_cny_per_million = 1
    session = await new_session(ctx)
    task = (await ask(ctx, session)).json()["data"]
    job = await job_service.claim_job("meter-owner-1", task_id=task["task_id"])

    async def completed():
        return SimpleNamespace(usage_metadata={"input_tokens": 1, "output_tokens": 1})

    async def unknown():
        raise TimeoutError("response lost")

    with provider_meter.execution(job):
        with pytest.raises(TimeoutError):
            await provider_meter.call_external(
                "llm", unknown, input_upper=100, output_upper=100
            )
        for _ in range(2):
            await provider_meter.call_external(
                "llm", completed, input_upper=100, output_upper=100
            )
    await execute(
        "UPDATE quiz_tasks SET lease_expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE task_id=%s",
        (task["task_id"],),
    )
    resumed = await job_service.claim_job("meter-owner-2", task_id=task["task_id"])
    with provider_meter.execution(resumed):
        for _ in range(2):
            await provider_meter.call_external(
                "llm", completed, input_upper=100, output_upper=100
            )
        with pytest.raises(AppError) as limit:
            await provider_meter.call_external(
                "llm", completed, input_upper=100, output_upper=100
            )
    assert limit.value.code == "budget_exceeded"
    rows = await fetch_all(
        "SELECT call_id,status FROM provider_calls WHERE operation_id=%s",
        (task["task_id"],),
    )
    assert len(rows) == 5 and sum(row["status"] == "unknown" for row in rows) == 1
    unknown_call = next(row["call_id"] for row in rows if row["status"] == "unknown")
    pending = await fetch_all(
        "SELECT status,reserved FROM budget_reservations "
        "WHERE operation_id=%s AND resource_type='cny'",
        (unknown_call,),
    )
    assert pending and all(
        row["status"] == "unknown" and row["reserved"] > 0 for row in pending
    )


@pytest.mark.asyncio
async def test_qa_artifact_hash_uses_persisted_json_and_still_detects_tampering(
    qa_context, monkeypatch
):
    from app.core.db import execute

    ctx = qa_context
    install_answer_provider(ctx, monkeypatch)
    original = ctx["engine"].answer

    async def with_precise_duration(*args, **kwargs):
        artifact = await original(*args, **kwargs)
        # MySQL binary JSON converts this float to 113.44075096390536.
        artifact.usage.stage_ms["total"] = 113.44075096390537
        return artifact

    monkeypatch.setattr(ctx["engine"], "answer", with_precise_duration)
    session = await new_session(ctx)
    task = (await ask(ctx, session)).json()["data"]
    await ctx["worker"].run_once(task_id=task["task_id"])
    path = f"/api/v1/qa/tasks/{task['task_id']}"
    response = await ctx["api"].get(path)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "completed"
    await execute(
        "UPDATE qa_answers SET artifact_json=JSON_SET(artifact_json,'$.blocks[0].text','tampered fact') WHERE task_id=%s",
        (task["task_id"],),
    )
    assert (await ctx["api"].get(path)).status_code == 404


@pytest.mark.asyncio
async def test_long_valid_answer_is_omitted_from_followup_history(
    qa_context, monkeypatch
):
    from app.qa.contracts import ChatAnswerArtifact

    ctx, histories = qa_context, []
    install_answer_provider(ctx, monkeypatch, history_log=histories)
    original = ctx["engine"].answer

    async def long_first_answer(*args, **kwargs):
        artifact = await original(*args, **kwargs)
        if len(histories) == 1:
            artifact = ChatAnswerArtifact.model_validate(
                {
                    **artifact.model_dump(),
                    "blocks": [
                        {
                            "block_id": f"b{index}",
                            "kind": "fact",
                            "text": "x" * 5800,
                            "citation_refs": [artifact.evidence[0].evidence_id],
                        }
                        for index in range(3)
                    ],
                }
            )
        return artifact

    monkeypatch.setattr(ctx["engine"], "answer", long_first_answer)
    session = await new_session(ctx)
    first = (await ask(ctx, session)).json()["data"]
    await ctx["worker"].run_once(task_id=first["task_id"])
    first_view = (await ctx["api"].get(f"/api/v1/qa/tasks/{first['task_id']}")).json()[
        "data"
    ]
    assert first_view["status"] == "completed"
    assert sum(len(block["text"]) for block in first_view["answer"]["blocks"]) > 16000
    second = (
        await ask(ctx, session, key="after-long-answer", content="光合作用需要什么？")
    ).json()["data"]
    await ctx["worker"].run_once(task_id=second["task_id"])
    result = (await ctx["api"].get(f"/api/v1/qa/tasks/{second['task_id']}")).json()[
        "data"
    ]
    assert result["status"] == "completed", result
    assert histories == [[], []]
