"""V01 验收：源归档往返一致、查询热路径零全量导出、检索与引用行为不变。"""

import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.asyncio
async def test_source_archive_roundtrip_is_identical(tmp_path):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.vector_archive import (
        iter_source_vectors,
        load_source_vectors,
    )
    from tests.rag.helpers import FixtureEmbedding, request_for

    embedding = FixtureEmbedding()
    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        result = await store.build(request_for(tmp_path), embedding)
        archive = load_source_vectors(
            store, result.projection_key + "/source-vectors.json"
        )
        assert archive.count == result.node_count
        assert archive.dimensions == result.embedding_dimensions
        reloaded = [row for batch in iter_source_vectors(store, archive) for row in batch]
        original = {
            node.node_id: vector
            for node, vector in zip(
                [n for n in result.nodes if not n.is_parent],
                _vectors_of(result, store),
            )
        }
        assert {row.node_id for row in reloaded} == set(original)
        for row in reloaded:
            assert row.vector == original[row.node_id]


def _vectors_of(result, store):
    from app.rag.providers.chroma_projection import collection_name_for

    stored = store._client.get_collection(
        collection_name_for(result.projection_key), embedding_function=None
    ).get(include=["embeddings"])
    by_id = dict(zip(stored["ids"], stored["embeddings"]))
    return [
        [float(value) for value in by_id[n.node_id]]
        for n in result.nodes
        if not n.is_parent
    ]


@pytest.mark.asyncio
async def test_query_path_never_exports_full_vectors(tmp_path, monkeypatch):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import PipelineConfig
    from app.rag.providers.llamaindex_retriever import LlamaIndexRetriever
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for

    embedding = FixtureEmbedding()
    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        result = await store.build(request_for(tmp_path), embedding)

        def forbidden(*args, **kwargs):
            raise AssertionError("查询路径触发了全量向量导出")

        monkeypatch.setattr(store.projection, "verify_attempt", forbidden)
        retriever = LlamaIndexRetriever(store, embedding)
        retrieval = await retriever.retrieve_evidence(
            "光", scope_for(result), PipelineConfig(retriever="llamaindex_dense")
        )
        assert retrieval.evidence, "检索应命中证据"
        # 引用与不可变原文一致（engine.verify_evidence 的等价检查）
        manifest = result.to_source_manifest(1)
        built = store.read_build(manifest)
        node_by_id = {n.node_id: n for n in built.nodes}
        for evidence in retrieval.evidence:
            node = next(
                n for n in node_by_id.values() if n.evidence.evidence_id == evidence.evidence_id
            )
            assert node.evidence.excerpt == evidence.excerpt


def test_projection_key_is_unchanged_for_existing_manifests():
    """历史 manifest 的 projection_key 与 collection 命名不受重构影响。"""
    from app.rag.artifact_store import projection_key
    from app.rag.index_artifacts import ref_from_manifest
    from types import SimpleNamespace

    manifest = SimpleNamespace(
        owner_id=7,
        namespace="production",
        doc_id="d1",
        document_version_id="v1",
        parse_artifact_id="p1",
        index_build_id="b1",
        attempt_id="a1",
        projection_key="rag/projections/abc",
        index_profile_hash="hash-1",
        canonical_text_hash="cth",
    )
    ref = ref_from_manifest(manifest)
    assert ref.projection_key == "rag/projections/abc"
    assert ref.collection_name.startswith("rag_") and len(ref.collection_name) == 52
    assert ref.backend == "chroma"
    assert ref.target_revision == "legacy-v1"
    # projection_key 的确定性计算与旧实现一致
    key = projection_key(7, "production", "d1", "v1", "p1", "b1", "a1")
    assert ref_from_manifest(
        SimpleNamespace(
            owner_id=7, namespace="production", doc_id="d1", document_version_id="v1",
            parse_artifact_id="p1", index_build_id="b1", attempt_id="a1",
            projection_key="", index_profile_hash="", canonical_text_hash="",
        )
    ).projection_key == key
