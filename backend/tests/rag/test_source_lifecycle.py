import json

import pytest


def test_api_and_second_owner_cannot_open_persistent_store(tmp_path):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.errors import OwnerRequired

    with pytest.raises(OwnerRequired):
        OwnerIndexStore(tmp_path, process_role="api")
    with (
        OwnerIndexStore(tmp_path, process_role="rag_owner"),
        pytest.raises(OwnerRequired),
    ):
        OwnerIndexStore(tmp_path, process_role="rag_owner")


@pytest.mark.asyncio
async def test_attempt_cleanup_does_not_delete_winning_projection(tmp_path):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import PipelineConfig
    from app.rag.providers.llamaindex_retriever import LlamaIndexRetriever
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for

    embedding = FixtureEmbedding()
    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        losing = await store.build(request_for(tmp_path, attempt="a1"), embedding)
        winning = await store.build(request_for(tmp_path, attempt="a2"), embedding)
        assert {n.node_id for n in losing.nodes}.isdisjoint(
            {n.node_id for n in winning.nodes}
        )
        store.delete_attempt(losing)
        result = await LlamaIndexRetriever(store, embedding).retrieve_evidence(
            "光", scope_for(winning), PipelineConfig()
        )
        assert result.evidence and all(e.attempt_id == "a2" for e in result.evidence)
        assert not store.projection_exists(losing)
        assert store.projection_exists(winning)


@pytest.mark.asyncio
async def test_build_replay_is_idempotent_and_projection_tamper_is_detected(tmp_path):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.errors import SourceUnavailable
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for

    embedding = FixtureEmbedding()
    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        request = request_for(tmp_path)
        first = await store.build(request, embedding)
        calls = len(embedding.calls)
        second = await store.build(request, embedding)
        assert first.checksum == second.checksum
        assert len(embedding.calls) == calls
        manifest_file = store.root / first.projection_key / "manifest.json"
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        payload["nodes"][0]["evidence"]["excerpt"] = "改写"
        manifest_file.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SourceUnavailable):
            store.read_build(scope_for(first).documents[0])


@pytest.mark.asyncio
async def test_document_sweep_removes_both_attempts_and_lexical_docstore_files(
    tmp_path,
):
    from app.rag.artifact_store import OwnerIndexStore
    from tests.rag.helpers import FixtureEmbedding, request_for

    embedding = FixtureEmbedding()
    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        one = await store.build(request_for(tmp_path, attempt="a1"), embedding)
        two = await store.build(request_for(tmp_path, attempt="a2"), embedding)
        unrelated = await store.build(
            request_for(tmp_path, doc_id="d2", build="b2"), embedding
        )
        store.purge_document(owner_id=7, namespace="production", doc_id="d1")
        assert not store.projection_exists(one) and not store.projection_exists(two)
        assert (
            store.attempts_for_document(owner_id=7, namespace="production", doc_id="d1")
            == []
        )
        assert store.projection_exists(unrelated)
