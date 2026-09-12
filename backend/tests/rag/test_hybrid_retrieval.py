"""Retrieval controls the search scope before ranking and merges ranks only."""

import pytest


def test_chinese_and_ascii_tokenization_preserves_terms_numbers_and_negation():
    from app.rag.providers.lexical import tokenize_for_retrieval

    tokens = tokenize_for_retrieval("协方差 C++ API_v2 2026 不满足否定条件")
    for term in ["协方差", "c++", "api_v2", "2026", "不", "否定", "条件"]:
        assert term in tokens
    assert "apiv2" not in tokens


def test_tokenizer_unknown_version_fails_instead_of_silently_rebuilding():
    from app.rag.providers.lexical import tokenize_for_retrieval

    with pytest.raises(ValueError):
        tokenize_for_retrieval("协方差", "unregistered-v999")


def test_rrf_is_rank_based_and_deterministic():
    from app.rag.retrieval import rrf_merge

    result = rrf_merge([["a", "b"], ["b", "a"]], k=60, limit=2)
    assert [item.id for item in result] == ["a", "b"]
    assert result[0].score == pytest.approx(1 / 61 + 1 / 62)


def test_rrf_does_not_count_duplicate_id_twice_in_one_ranking():
    from app.rag.retrieval import rrf_merge

    result = rrf_merge([["a", "a", "b"], ["b"]], k=60, limit=40)
    assert result[0].id == "b"
    assert next(x for x in result if x.id == "a").score == pytest.approx(1 / 61)


def test_bm25_scope_is_applied_before_statistics_and_top_k():
    from app.rag.providers.lexical import LexicalIndex

    records = [{"id": str(i), "text": "协方差 API_v2 2026"} for i in range(50)]
    records.append({"id": "mine", "text": "协方差"})
    index = LexicalIndex(records)
    assert [x.id for x in index.search("协方差", allowed_ids={"mine"}, top_k=20)] == [
        "mine"
    ]


def test_bm25_roundtrip_restores_terms_without_retokenizing(tmp_path):
    from app.rag.providers.lexical import LexicalIndex

    index = LexicalIndex(
        [{"id": "a", "text": "光合作用需要光。"}, {"id": "b", "text": "协方差为零。"}]
    )
    path = tmp_path / "lexical.json"
    index.persist(path)
    restored = LexicalIndex.load(path)
    assert restored.search("协方差")[0].id == "b"
    assert restored.search("完全无关的其它概念") == []


@pytest.mark.asyncio
async def test_hybrid_retrieval_records_dense_lexical_and_fused_candidates(tmp_path):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import PipelineConfig
    from app.rag.retrieval import HybridRetriever
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for

    embedding = FixtureEmbedding()
    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        built = await store.build(request_for(tmp_path), embedding)
        result = await HybridRetriever(store, embedding).retrieve_evidence(
            "协方差", scope_for(built), PipelineConfig()
        )
        assert result.rankings["dense"] and result.rankings["lexical"]
        assert "协方差" in result.evidence[0].excerpt
        assert result.effective_config["reranker"]["effective_provider"] == "none"
        assert len(result.evidence) <= 8 and len(result.candidates) <= 40
