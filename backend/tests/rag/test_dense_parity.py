import pytest


@pytest.mark.asyncio
async def test_same_canonical_nodes_and_vectors_have_legacy_llamaindex_dense_parity(
    tmp_path,
):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import PipelineConfig
    from app.rag.providers.legacy_retriever import LegacyDenseRetriever
    from app.rag.providers.llamaindex_retriever import LlamaIndexRetriever
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for

    embedding = FixtureEmbedding()
    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        built = await store.build(request_for(tmp_path), embedding)
        scope = scope_for(built)
        config = PipelineConfig(retriever="llamaindex_dense")
        legacy = await LegacyDenseRetriever(store, embedding).retrieve_evidence(
            "光", scope, config
        )
        migrated = await LlamaIndexRetriever(store, embedding).retrieve_evidence(
            "光", scope, config
        )
        assert [e.chunk_id for e in legacy.evidence] == [
            e.chunk_id for e in migrated.evidence
        ]
        assert [e.score for e in legacy.evidence] == pytest.approx(
            [e.score for e in migrated.evidence]
        )
        assert all(
            e.excerpt == m.excerpt for e, m in zip(legacy.evidence, migrated.evidence)
        )
