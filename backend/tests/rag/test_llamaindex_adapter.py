import logging

import pytest


@pytest.mark.asyncio
async def test_llamaindex_roundtrip_keeps_exact_source_and_explicit_embedding(tmp_path):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import PipelineConfig
    from app.rag.providers.llamaindex_retriever import LlamaIndexRetriever
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for

    embedding = FixtureEmbedding()
    store = OwnerIndexStore(tmp_path / "data", process_role="rag_owner")
    result = await store.build(request_for(tmp_path), embedding)
    scope = scope_for(result)
    assert [text for batch in embedding.calls for text in batch] == [
        n.embedding_text for n in result.nodes if not n.is_parent
    ]
    store.close()
    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as recovered:
        retrieved = await LlamaIndexRetriever(recovered, embedding).retrieve_evidence(
            "协方差", scope, PipelineConfig(retriever="llamaindex_dense")
        )
        assert "协方差" in retrieved.evidence[0].excerpt
        assert all(e.owner_id == 7 for e in retrieved.evidence)
        canonical = recovered.load_canonical(result.canonical_artifact_key)
        for evidence in retrieved.evidence:
            assert (
                canonical.text[evidence.locator.start_char : evidence.locator.end_char]
                == evidence.excerpt
            )
        assert recovered.read_docstore(scope.documents[0])


@pytest.mark.asyncio
async def test_dense_top_k_applies_owner_document_and_section_before_ranking(tmp_path):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import PipelineConfig
    from app.rag.providers.llamaindex_retriever import LlamaIndexRetriever
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for

    embedding = FixtureEmbedding()
    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        mine = await store.build(request_for(tmp_path), embedding)
        await store.build(
            request_for(
                tmp_path, doc_id="other", owner_id=8, build="b2", text="光光光光"
            ),
            embedding,
        )
        canonical = store.load_canonical(mine.canonical_artifact_key)
        chosen = canonical.sections[1].section_id
        result = await LlamaIndexRetriever(store, embedding).retrieve_evidence(
            "光",
            scope_for(mine, [chosen]),
            PipelineConfig(retriever="llamaindex_dense", dense_top_k=1),
        )
        assert len(result.evidence) == 1
        assert result.evidence[0].locator.section_id == chosen
        assert result.evidence[0].doc_id == "d1"
        assert "协方差" in result.evidence[0].excerpt


@pytest.mark.asyncio
async def test_incompatible_profile_never_falls_back_to_another_embedding_space(
    tmp_path,
):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import PipelineConfig
    from app.rag.errors import SourceUnavailable
    from app.rag.providers.llamaindex_retriever import LlamaIndexRetriever
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for

    embedding = FixtureEmbedding()
    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        built = await store.build(request_for(tmp_path), embedding)
        with pytest.raises(SourceUnavailable):
            await LlamaIndexRetriever(store, embedding).retrieve_evidence(
                "光", scope_for(built), PipelineConfig(index_profile_id="other-space")
            )


@pytest.mark.asyncio
async def test_chroma_adapter_does_not_log_raw_source_at_debug(tmp_path, caplog):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import PipelineConfig
    from app.rag.providers.llamaindex_retriever import LlamaIndexRetriever
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for

    embedding = FixtureEmbedding()
    with (
        caplog.at_level(logging.DEBUG),
        OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store,
    ):
        built = await store.build(
            request_for(tmp_path, text="PRIVATE_EVIDENCE_DO_NOT_LOG"), embedding
        )
        await LlamaIndexRetriever(store, embedding).retrieve_evidence(
            "query", scope_for(built), PipelineConfig()
        )
    assert "PRIVATE_EVIDENCE_DO_NOT_LOG" not in caplog.text
