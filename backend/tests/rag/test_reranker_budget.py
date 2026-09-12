import json

import httpx
import pytest


@pytest.mark.asyncio
async def test_reranker_failure_only_falls_back_when_configured_and_records_effective_config():
    from app.rag.contracts import DocumentEvidence, RerankerConfig
    from app.rag.errors import RetrievalUnavailable
    from app.rag.providers.reranker import rerank
    from tests.rag.test_contracts import document_payload

    evidence = [DocumentEvidence.model_validate(document_payload())]

    async def unavailable(*args, **kwargs):
        raise TimeoutError("private_provider_details")

    config = RerankerConfig(
        provider="bge-v2-m3", model_revision="abc123", license="Apache-2.0"
    )
    with pytest.raises(RetrievalUnavailable):
        await rerank("query", evidence, config, provider=unavailable)
    result = await rerank(
        "query",
        evidence,
        config.model_copy(update={"allow_rrf_fallback": True}),
        provider=unavailable,
    )
    assert result.evidence == evidence
    assert result.effective_config["requested_provider"] == "bge-v2-m3"
    assert result.effective_config["effective_provider"] == "none"
    assert result.warnings == ["reranker_unavailable_rrf_fallback"]


@pytest.mark.asyncio
async def test_remote_reranker_maps_relevance_by_candidate_index_and_preserves_evidence():
    from app.rag.contracts import DocumentEvidence, RerankerConfig
    from app.rag.providers.reranker import RemoteReranker, rerank
    from tests.rag.test_contracts import document_payload

    a = DocumentEvidence.model_validate(document_payload())
    b = a.model_copy(update={"evidence_id": "ev2", "chunk_id": "c2"})
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            },
        )

    config = RerankerConfig(
        provider="qwen3-reranker-0.6b",
        model_revision="fixed-revision",
        license="Apache-2.0",
        endpoint="https://authorized-reranker.example/rerank",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await rerank(
            "query", [a, b], config, provider=RemoteReranker(config, client=client)
        )
    assert [e.evidence_id for e in result.evidence] == ["ev2", "ev_1"]
    assert result.evidence[0].excerpt == b.excerpt
    assert seen[0]["documents"] == [a.excerpt, b.excerpt]


@pytest.mark.asyncio
async def test_exhausted_reranker_budget_is_not_reported_as_a_successful_degradation():
    from app.rag.budget import BudgetLedger
    from app.rag.contracts import BudgetLimits, DocumentEvidence, RerankerConfig
    from app.rag.errors import BudgetExceeded
    from app.rag.providers.reranker import rerank
    from tests.rag.test_contracts import document_payload

    config = RerankerConfig(
        provider="bge-v2-m3",
        model_revision="abc",
        license="Apache-2.0",
        allow_rrf_fallback=True,
    )
    with pytest.raises(BudgetExceeded):
        await rerank(
            "query",
            [DocumentEvidence.model_validate(document_payload())],
            config,
            provider=lambda *a, **kw: [],
            budget=BudgetLedger(BudgetLimits(max_reranker_calls=0)),
        )
