"""Real native SDK ranking protocol plus durable overlapping usage counters."""

import json

import pytest

from tests.helpers.provider_http import (
    ProviderHTTPServer,
    ProviderReply,
    anthropic_message,
)
from tests.rag.test_llm_reranker import candidates
from tests.test_claude_native import _settings


@pytest.mark.asyncio
async def test_native_runtime_uses_messages_api_and_independent_ranking_output_cap(
    tmp_path, monkeypatch
):
    from app.rag.providers.reranker import rerank
    from app.workers import providers

    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    meters = []

    def unmetered_for_protocol_test(llm, **kwargs):
        # SQL admission has separate integration coverage. Keep the factory,
        # binding, SDK, payload, transport, and response parser real here.
        meters.append(kwargs)
        return llm

    monkeypatch.setattr(providers, "MeteredChat", unmetered_for_protocol_test)
    with ProviderHTTPServer(
        lambda request: ProviderReply(anthropic_message('{"ranking":[1,0]}'))
    ) as server:
        runtime = providers.build_runtime(
            _settings(server.base_url, data_dir=str(tmp_path))
        )
        try:
            ranker = runtime.engine.retriever.llm_reranker
            assert ranker is not None
            assert ranker.llm.bound is runtime.engine.generator.llm
            assert runtime.engine.generator.llm.max_tokens == 4096
            result = await rerank(
                "photosynthesis", candidates(), ranker.config, provider=ranker
            )
            assert [e.evidence_id for e in result.evidence] == ["ev_1", "ev_0"]
            # Runtime also creates the lazy QA adapters. Check the ranking cap
            # by purpose; constructing another adapter must not make a request.
            assert [
                meter for meter in meters if meter.get("purpose") == "reranker"
            ] == [{"purpose": "reranker", "output_upper": 512,
                   "config_source": "system", "api_key": "test-native-key"}]
            assert len(server.requests) == 1
            request = server.requests[0]
            assert request.path == "/v1/messages"
            assert request.body["model"] == "claude-local-test"
            assert request.body["max_tokens"] == 512
            assert request.body["temperature"] == 0
            assert "tools" not in request.body
            assert (
                json.loads(request.body["messages"][0]["content"])["query"]
                == "photosynthesis"
            )
        finally:
            await runtime.close()


@pytest.mark.asyncio
async def test_llm_ranking_is_in_both_counters_without_double_counting_journal_completeness(
    monkeypatch,
):
    from app.core.values import dump
    from app.workers import rag_owner

    async def rows(*args):
        return [
            {
                "call_id": str(index),
                "stage": stage,
                "status": "completed",
                "usage_json": dump({"purpose": purpose}),
            }
            for index, (stage, purpose) in enumerate(
                [
                    ("llm", "reranker"),
                    ("llm", "generation"),
                    ("llm", "generation"),
                    ("reranker", "generation"),
                    ("embedding", "generation"),
                ]
            )
        ]

    monkeypatch.setattr(rag_owner, "fetch_all", rows)
    usage = await rag_owner._metered_usage({"task_id": "test-job"}, {})
    assert usage["llm_calls"] == 3
    assert usage["reranker_calls"] == 2
    assert usage["embedding_calls"] == 1
    assert usage["ledger_complete"] is True and len(usage["calls"]) == 5
