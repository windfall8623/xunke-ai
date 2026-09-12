"""HTTP through the real QA pipeline and durable meter; only chat I/O is synthetic."""

import json
import uuid

import httpx
from tests.platform.conftest import register_email_account
import pytest
from langchain_core.messages import AIMessage

from tests.platform.qa_helpers import ask, new_session
from tests.platform.qa_helpers import qa_context as qa_context


class SourceEchoTransport:
    max_retries = 0
    model_name = "synthetic-qa-integration"

    def __init__(self, before_reply=None):
        self.before_reply = before_reply
        self.calls = []

    async def ainvoke(self, messages):
        request = json.loads(messages[-1].content)
        self.calls.append(request)
        if request["task"] == "qa_rewrite":
            reply = {
                "retrieval_query": "光合作用需要什么？",
                "needs_clarification": False,
            }
        elif request["task"] == "qa_answer":
            evidence = request["evidence"][0]
            reply = {
                "answer_status": "answered",
                "blocks": [
                    {
                        "block_id": "b1",
                        "kind": "fact",
                        "text": evidence["excerpt"],
                        "citation_refs": [evidence["evidence_id"]],
                    }
                ],
            }
        elif request["task"] == "qa_validate":
            reply = {
                "passed": True,
                "answer_status_valid": True,
                "conflict_supported": False,
                "checks": [
                    {
                        "block_id": block["block_id"],
                        "source_supported": True,
                        "citation_refs": block["citation_refs"],
                    }
                    for block in request["answer"]["blocks"]
                ],
                "errors": [],
            }
        else:
            raise AssertionError("Unexpected model task")
        if self.before_reply:
            await self.before_reply(request)
        return AIMessage(
            content=json.dumps(reply, ensure_ascii=False),
            usage_metadata={
                "input_tokens": 80,
                "output_tokens": 40,
                "total_tokens": 120,
            },
        )


def connect_metered_generator(ctx, settings, transport):
    from app.qa.generator import LangChainQaGenerator
    from app.services.provider_meter import MeteredChat

    settings.rag_pipeline_id = "bm25-v1"
    settings.llm_input_cny_per_million = 1
    settings.llm_output_cny_per_million = 1
    ctx["engine"].qa_generator = LangChainQaGenerator(
        MeteredChat(transport, purpose="qa_answer"),
        rewrite_llm=MeteredChat(transport, purpose="qa_rewrite"),
        semantic_llm=MeteredChat(transport, purpose="qa_validate"),
    )


@pytest.mark.asyncio
async def test_http_qa_pipeline_persists_metered_answer_and_private_citations(
    qa_context, platform_settings
):
    from app.core.db import fetch_all
    from app.main import app

    ctx, transport = qa_context, SourceEchoTransport()
    connect_metered_generator(ctx, platform_settings, transport)
    session = await new_session(ctx)
    task = (await ask(ctx, session)).json()["data"]
    await ctx["worker"].run_once(task_id=task["task_id"])
    completed = await ctx["api"].get(f"/api/v1/qa/tasks/{task['task_id']}")
    assert completed.status_code == 200, completed.text
    view = completed.json()["data"]
    assert view["status"] == "completed", completed.text
    answer = view["answer"]
    assert answer["answer_status"] == "answered"
    assert answer["usage"]["llm_calls"] == 2
    assert answer["usage"]["ledger_complete"] is True
    calls = answer["usage"]["calls"]
    assert {call["purpose"] for call in calls} == {"qa_answer", "qa_validate"}
    assert all(
        call["cost_status"] == "estimated" and call["cost_cny"] > 0 for call in calls
    )
    evidence = answer["evidence"][0]
    path = (
        f"/api/v1/qa/answers/{answer['answer_id']}/evidence/{evidence['evidence_id']}"
    )
    assert (await ctx["api"].get(path)).json()["data"]["excerpt"] == evidence["excerpt"]
    rows = await fetch_all(
        "SELECT stage,status FROM provider_calls WHERE operation_id=%s",
        (task["task_id"],),
    )
    assert rows == [{"stage": "llm", "status": "completed"}] * 2

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as other:
        reg_session, _ = await register_email_account(other, nickname="另一个账号")
        other.headers.update(
            {
                "Origin": "http://testserver",
                "X-CSRF-Token": reg_session["csrf_token"],
            }
        )
        assert (
            await other.get(f"/api/v1/qa/tasks/{task['task_id']}")
        ).status_code == 404
        assert (
            await other.post(f"/api/v1/qa/tasks/{task['task_id']}/cancel")
        ).status_code == 404
        assert (await other.get(path)).status_code == 404
        assert (
            await other.post(
                f"/api/v1/qa/answers/{answer['answer_id']}/feedback",
                json={"rating": "helpful"},
            )
        ).status_code == 404

    followup = (
        await ask(ctx, session, key="context-followup", content="它需要什么？")
    ).json()["data"]
    await ctx["worker"].run_once(task_id=followup["task_id"])
    result = (await ctx["api"].get(f"/api/v1/qa/tasks/{followup['task_id']}")).json()[
        "data"
    ]
    assert result["status"] == "completed", result
    assert result["answer"]["usage"]["llm_calls"] == 3
    rewrite = next(call for call in transport.calls if call["task"] == "qa_rewrite")
    assert rewrite["history"] == [
        {"question": "光合作用需要什么？", "answer": answer["blocks"][0]["text"]}
    ]
    assert all(
        "history" not in call
        for call in transport.calls
        if call["task"] != "qa_rewrite"
    )


@pytest.mark.asyncio
async def test_source_revoked_during_model_validation_never_publishes(
    qa_context, platform_settings
):
    from app.core.db import fetch_one

    ctx = qa_context

    async def revoke(request):
        if request["task"] == "qa_validate":
            response = await ctx["api"].delete(
                "/api/v1/knowledge/documents/" + ctx["document"]["doc_id"]
            )
            assert response.status_code == 202, response.text

    transport = SourceEchoTransport(before_reply=revoke)
    connect_metered_generator(ctx, platform_settings, transport)
    session = await new_session(ctx)
    task = (await ask(ctx, session)).json()["data"]
    await ctx["worker"].run_once(task_id=task["task_id"])
    assert [call["task"] for call in transport.calls] == ["qa_answer", "qa_validate"]
    assert (
        await ctx["api"].get(f"/api/v1/qa/tasks/{task['task_id']}")
    ).status_code == 404
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM qa_answers WHERE task_id=%s", (task["task_id"],)
        )
    )["n"] == 0
    messages = (
        await ctx["api"].get(f"/api/v1/qa/sessions/{session['session_id']}/messages")
    ).json()["data"]["items"]
    assert len(messages) == 2 and all(
        item["status"] == "revoked" and item["answer"] is None for item in messages
    )


@pytest.mark.asyncio
async def test_existing_session_keeps_original_source_version_after_update(
    qa_context, platform_settings
):
    ctx = qa_context
    connect_metered_generator(ctx, platform_settings, SourceEchoTransport())
    session = await new_session(ctx)
    original_version = session["scope"]["documents"][0]["document_version_id"]
    update = await ctx["api"].post(
        f"/api/v1/knowledge/documents/{ctx['document']['doc_id']}/versions",
        files={
            "file": (
                "changed.md",
                "# 新版本\n这里只讨论月球。".encode(),
                "text/markdown",
            )
        },
    )
    assert update.status_code == 202, update.text
    await ctx["worker"].run_once(task_id=update.json()["data"]["task_id"])
    task = (await ask(ctx, session)).json()["data"]
    await ctx["worker"].run_once(task_id=task["task_id"])
    response = await ctx["api"].get(f"/api/v1/qa/tasks/{task['task_id']}")
    assert response.status_code == 200, response.text
    view = response.json()["data"]
    assert view["status"] == "completed", view
    assert all(
        item["document_version_id"] == original_version
        for item in view["answer"]["evidence"]
    )
    assert "月球" not in json.dumps(view, ensure_ascii=False)
    new = await new_session(ctx)
    assert new["scope"]["documents"][0]["document_version_id"] != original_version


@pytest.mark.asyncio
async def test_expired_queued_question_recovers_to_failed_history_without_model_calls(
    qa_context, platform_settings
):
    from app.core.db import execute

    ctx, transport = qa_context, SourceEchoTransport()
    connect_metered_generator(ctx, platform_settings, transport)
    session = await new_session(ctx)
    task = (await ask(ctx, session)).json()["data"]
    await execute(
        "UPDATE quiz_tasks SET queued_expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE task_id=%s",
        (task["task_id"],),
    )
    assert await ctx["worker"].run_once(task_id=task["task_id"]) is False
    view = (await ctx["api"].get(f"/api/v1/qa/tasks/{task['task_id']}")).json()["data"]
    assert (
        view["status"] == "failed"
        and view["answer"] is None
        and view["error_code"] == "deadline_exceeded"
    )
    assert transport.calls == []
    history = (
        await ctx["api"].get(f"/api/v1/qa/sessions/{session['session_id']}/messages")
    ).json()["data"]["items"]
    assert history[-1]["status"] == "failed"
    assert (await ask(ctx, session, key="fresh-after-queue-expiry")).status_code == 202
