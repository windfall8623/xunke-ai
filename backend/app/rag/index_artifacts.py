"""构建编排与产物校验的分层：编排（writer）与只读校验分离。

- build_index_artifacts：准备候选 → 源归档 → 投影写入 → 完整核验 → manifest。
- read_manifest：查询热路径只做身份与校验和检查，不做全量向量导出。
- deep_validate：构建/重放/修复路径的深度产物核验。
"""

from __future__ import annotations

import json
import math

from app.rag.artifact_store import ArtifactStore, projection_key
from app.rag.blocking_io import run_file_io
from app.rag.contracts import (
    BuildRequest,
    BuildResult,
    SourceManifest,
    stable_hash,
)
from app.rag.errors import SourceUnavailable
from app.rag.ingestion import load_canonical_document_bounded
from app.rag.providers.chroma_projection import collection_name_for
from app.rag.providers.lexical import LexicalIndex
from app.rag.structure import chunk_document
from app.rag.vector_archive import (
    NORMALIZATION_IDENTITY,
    node_set_hash,
    save_source_vectors,
)
from app.rag.vector_store import (
    BACKEND_CHROMA,
    LEGACY_TARGET_REVISION,
    ProjectionDigest,
    ProjectionRef,
    VectorRecord,
)


def ref_from_manifest(
    manifest: SourceManifest, *, embedding_signature_hash: str | None = None,
    backend: str = BACKEND_CHROMA, target_revision: str = LEGACY_TARGET_REVISION,
    collection_prefix: str = "xunke_dense",
) -> ProjectionRef:
    key = manifest.projection_key or projection_key(
        manifest.owner_id,
        manifest.namespace,
        manifest.doc_id,
        manifest.document_version_id,
        manifest.parse_artifact_id,
        manifest.index_build_id,
        manifest.attempt_id,
    )
    profile_hash = getattr(manifest, "index_profile_hash", "") or ""
    signature = embedding_signature_hash or profile_hash
    if backend == "qdrant":
        from app.rag.providers.qdrant_projection import collection_name_for as remote_collection
        collection = remote_collection(signature, target_revision, prefix=collection_prefix)
    else:
        collection = collection_name_for(key)
    return ProjectionRef(
        backend=backend,
        target_revision=target_revision,
        collection_name=collection,
        projection_key=key,
        owner_id=manifest.owner_id,
        namespace=manifest.namespace,
        doc_id=manifest.doc_id,
        document_version_id=manifest.document_version_id,
        parse_artifact_id=manifest.parse_artifact_id,
        index_build_id=manifest.index_build_id,
        attempt_id=manifest.attempt_id,
        index_profile_hash=profile_hash,
        embedding_signature_hash=signature,
    )


def embedding_space_signature(profile) -> str:
    # Preserve the declared historical space. Migration copies measured vectors;
    # it does not assert a frozen provider model revision absent from old data.
    return stable_hash({
        "model": profile.embedding_model, "dimensions": profile.embedding_dimensions,
        "space": profile.embedding_space, "input_version": profile.embedding_input_version,
    })


def ref_for_store(store, manifest, profile) -> ProjectionRef:
    return ref_from_manifest(
        manifest, embedding_signature_hash=embedding_space_signature(profile),
        backend=getattr(store, "backend", BACKEND_CHROMA),
        target_revision=getattr(store, "target_revision", LEGACY_TARGET_REVISION),
        collection_prefix=getattr(store, "collection_prefix", "xunke_dense"),
    )


def _shallow_identity_check(result: BuildResult, manifest: SourceManifest) -> None:
    if manifest.projection_key and manifest.projection_key != result.projection_key:
        raise SourceUnavailable("Projection key does not match authorized manifest")
    expected = (
        manifest.owner_id,
        manifest.namespace,
        manifest.doc_id,
        manifest.document_version_id,
        manifest.parse_artifact_id,
        manifest.index_build_id,
        manifest.attempt_id,
        manifest.canonical_text_hash,
    )
    actual = (
        result.owner_id,
        result.namespace,
        result.doc_id,
        result.document_version_id,
        result.parse_artifact_id,
        result.index_build_id,
        result.attempt_id,
        result.canonical_text_hash,
    )
    if expected != actual or (
        manifest.index_profile_hash
        and manifest.index_profile_hash != result.index_profile_hash
    ):
        raise SourceUnavailable("Index manifest differs from the authorized source")


def _checksum_check(result: BuildResult) -> None:
    if result.checksum != stable_hash(
        [n.model_dump(mode="json") for n in result.nodes]
    ):
        raise SourceUnavailable("Index node checksum does not match")


def read_manifest(store: ArtifactStore, manifest: SourceManifest) -> BuildResult:
    """查询热路径：读取 manifest 并做身份/校验和检查。

    不执行全量向量导出与 docstore/lexical 重读；授权由调用方完成，
    证据与不可变原文的逐条核对仍在 engine.verify_evidence 进行。
    """
    key = projection_key(
        manifest.owner_id,
        manifest.namespace,
        manifest.doc_id,
        manifest.document_version_id,
        manifest.parse_artifact_id,
        manifest.index_build_id,
        manifest.attempt_id,
    )
    if manifest.projection_key and manifest.projection_key != key:
        raise SourceUnavailable("Projection key does not match authorized manifest")
    try:
        result = BuildResult.model_validate_json(
            store.resolve_key(key + "/manifest.json").read_bytes()
        )
        _shallow_identity_check(result, manifest)
        _checksum_check(result)
        return result
    except SourceUnavailable:
        raise
    except Exception as exc:
        raise SourceUnavailable(
            "Required index build is missing, corrupt, or awaiting rebuild"
        ) from exc


def deep_artifact_checks(store: ArtifactStore, result: BuildResult) -> None:
    """构建/重放/修复路径的产物级核验（不含向量存储）。"""
    if (
        result.projection_key
        != projection_key(
            result.owner_id,
            result.namespace,
            result.doc_id,
            result.document_version_id,
            result.parse_artifact_id,
            result.index_build_id,
            result.attempt_id,
        )
        or result.index_profile_hash != result.profile.profile_hash
    ):
        raise SourceUnavailable("Index manifest identity does not match")
    _checksum_check(result)
    document = store.load_canonical(result.canonical_artifact_key)
    if document.canonical_text_hash != result.canonical_text_hash:
        raise SourceUnavailable("Canonical and index versions do not match")
    children = [n for n in result.nodes if not n.is_parent]
    for node in result.nodes:
        evidence = node.evidence
        if (
            document.text[evidence.locator.start_char : evidence.locator.end_char]
            != evidence.excerpt
        ):
            raise SourceUnavailable("Index quote differs from canonical source")
    from llama_index.core.storage.docstore import SimpleDocumentStore

    docstore = SimpleDocumentStore.from_dict(
        json.loads(
            store.resolve_key(result.projection_key + "/docstore.json").read_bytes()
        )
    )
    for node in result.nodes:
        restored = docstore.get_document(node.node_id)
        if restored.text != node.embedding_text:
            raise SourceUnavailable("Docstore text does not match source")
    lexical = LexicalIndex.load(
        store.resolve_key(result.projection_key + "/lexical.json")
    )
    if set(lexical.tokens) != {n.node_id for n in children}:
        raise SourceUnavailable("Lexical projection identity does not match")


def _digest_for(
    node_count: int,
    dimensions: int,
    node_ids: list[str],
    archive,  # SourceVectorArchive | None
) -> ProjectionDigest:
    return ProjectionDigest(
        expected_node_count=node_count,
        dimensions=dimensions,
        node_set_hash=node_set_hash(node_ids),
        source_vectors_hash=archive.source_vectors_hash if archive else "",
        normalization_version=NORMALIZATION_IDENTITY,
    )


def _load_archive(store: ArtifactStore, ref: ProjectionRef):
    """读取投影的源归档；历史构建（本版本之前）没有归档时返回 None。"""
    from app.rag.vector_archive import load_source_vectors

    key = ref.projection_key + "/source-vectors.json"
    if not store.resolve_key(key).exists():
        return None
    return load_source_vectors(store, key)


async def build_index_artifacts(
    store: ArtifactStore,
    projection,
    request: BuildRequest,
    embedding,
    budget=None,
) -> BuildResult:
    """完整构建：分块、嵌入、源归档、投影写入、核验与 manifest 持久化。"""
    document = request.canonical or await run_file_io(
        load_canonical_document_bounded, request.source
    )
    registered = getattr(store, "registry_enabled", False)
    from app.services import vector_projection_service as registry
    if (
        request.profile.embedding_model != embedding.model
        or request.profile.embedding_dimensions != embedding.dimensions
    ):
        raise SourceUnavailable("Embedding adapter and index profile are incompatible")
    key = projection_key(
        document.owner_id,
        document.namespace,
        document.doc_id,
        document.document_version_id,
        document.parse_artifact_id,
        request.index_build_id,
        request.attempt_id,
    )
    manifest_path = store.resolve_key(key + "/manifest.json")
    if manifest_path.exists():
        prior = BuildResult.model_validate_json(manifest_path.read_bytes())
        if prior.index_profile_hash != request.profile.profile_hash:
            raise SourceUnavailable("Attempt already uses a different index profile")
        ref = ref_for_store(store, prior.to_source_manifest(1), prior.profile)
        archive = _load_archive(store, ref)
        child_ids = [n.node_id for n in prior.nodes if not n.is_parent]
        if archive is not None:
            source_rows = [
                row
                for batch in _iter_archive_rows(store, archive)
                for row in batch
            ]
            await projection.verify_attempt(
                ref,
                _digest_for(prior.node_count, prior.embedding_dimensions, child_ids, archive),
                archive,
                source_rows=source_rows,
            )
        else:
            # 历史构建没有源归档：退化为数量/身份/维度核验。
            await projection.verify_attempt(
                ref,
                _digest_for(prior.node_count, prior.embedding_dimensions, child_ids, None),
                None,
                source_rows=None,
            )
        deep_artifact_checks(store, prior)
        return prior
    nodes = chunk_document(
        document, request.profile, request.index_build_id, request.attempt_id
    )
    children = [n for n in nodes if not n.is_parent]
    if not children:
        raise SourceUnavailable("No indexable source spans")
    vectors = await embedding.embed_documents(
        [n.embedding_text for n in children], budget=budget
    )
    if len(vectors) != len(children) or any(
        len(v) != embedding.dimensions or any(not math.isfinite(x) for x in v)
        for v in vectors
    ):
        raise SourceUnavailable("Embedding vector count or dimensions do not match")
    intent = {
        "owner_id": document.owner_id,
        "namespace": document.namespace,
        "doc_id": document.doc_id,
        "document_version_id": document.document_version_id,
        "parse_artifact_id": document.parse_artifact_id,
        "index_build_id": request.index_build_id,
        "attempt_id": request.attempt_id,
        "projection_key": key,
    }
    from types import SimpleNamespace
    ref = ref_for_store(
        store, SimpleNamespace(**intent, index_profile_hash=request.profile.profile_hash), request.profile
    )
    if registered:
        await registry.register_candidate(ref)
    canonical_key = store.save_canonical(document, request.canonical_artifact_key)
    store.put_json(key + "/attempt.json", intent)
    rows = [
        VectorRecord(node_id=node.node_id, vector=vector)
        for node, vector in zip(children, vectors)
    ]
    archive = await run_file_io(save_source_vectors, store, ref, rows)
    expected = _digest_for(len(children), embedding.dimensions, [n.node_id for n in children], archive)
    if registered:
        await registry.attach_archive(ref, archive, expected)

    def persist_artifacts():
        from llama_index.core.schema import (
            NodeRelationship,
            RelatedNodeInfo,
            TextNode,
        )
        from llama_index.core.storage.docstore import SimpleDocumentStore

        vector_by_id = {n.node_id: v for n, v in zip(children, vectors)}
        llama_nodes = []
        for node in nodes:
            metadata = {
                "owner_id": document.owner_id,
                "namespace": document.namespace,
                "scope_doc_id": document.doc_id,
                "document_version_id": document.document_version_id,
                "parse_artifact_id": document.parse_artifact_id,
                "index_build_id": request.index_build_id,
                "attempt_id": request.attempt_id,
                "scope_node_id": node.node_id,
            }
            relationships = {
                NodeRelationship.SOURCE: RelatedNodeInfo(
                    node_id=document.document_version_id
                )
            }
            if node.parent_id:
                relationships[NodeRelationship.PARENT] = RelatedNodeInfo(
                    node_id=node.parent_id
                )
            llama_nodes.append(
                TextNode(
                    id_=node.node_id,
                    text=node.embedding_text,
                    embedding=vector_by_id.get(node.node_id),
                    metadata=metadata,
                    excluded_embed_metadata_keys=list(metadata),
                    excluded_llm_metadata_keys=list(metadata),
                    relationships=relationships,
                    start_char_idx=node.evidence.locator.start_char,
                    end_char_idx=node.evidence.locator.end_char,
                )
            )
        docstore = SimpleDocumentStore()
        docstore.add_documents(llama_nodes)
        docstore.persist(str(store.resolve_key(key + "/docstore.json")))
        LexicalIndex(
            [{"id": n.node_id, "text": n.embedding_text} for n in children],
            tokenizer_version=request.profile.tokenizer_version,
        ).persist(store.resolve_key(key + "/lexical.json"))

    await run_file_io(persist_artifacts)
    if hasattr(projection, "initialize_collection"):
        await projection.initialize_collection(ref, embedding.dimensions)
    batches = projection.iter_write_batches(ref, rows) if hasattr(projection, "iter_write_batches") else [rows]
    for batch in batches:
        if registered:
            await registry.recorded_call(ref, "write", lambda: projection.write_attempt(ref, batch), rows=batch)
        else:
            receipt = await projection.write_attempt(ref, batch)
            if receipt.status != "completed":
                raise SourceUnavailable("Vector projection write was not confirmed")
    verified = await projection.verify_attempt(
        ref,
        expected,
        archive,
        source_rows=rows,
    )
    if verified.digest.target_vectors_hash is None:
        raise SourceUnavailable("Vector projection verification is incomplete")
    if registered:
        await registry.record_verified(ref, verified)
    result = BuildResult(
        owner_id=document.owner_id,
        namespace=document.namespace,
        doc_id=document.doc_id,
        document_version_id=document.document_version_id,
        source_sha256=document.source_sha256,
        parse_artifact_id=document.parse_artifact_id,
        canonical_text_hash=document.canonical_text_hash,
        index_build_id=request.index_build_id,
        attempt_id=request.attempt_id,
        profile=request.profile,
        index_profile_hash=request.profile.profile_hash,
        node_count=len(children),
        embedding_dimensions=embedding.dimensions,
        projection_key=key,
        canonical_artifact_key=canonical_key,
        nodes=nodes,
        checksum=stable_hash([n.model_dump(mode="json") for n in nodes]),
        expected_document_revision=request.expected_document_revision,
        title=document.title,
    )
    deep_artifact_checks(store, result)
    store.put_json(key + "/manifest.json", result.model_dump(mode="json"))
    return result


def _iter_archive_rows(store: ArtifactStore, archive):
    from app.rag.vector_archive import iter_source_vectors

    return iter_source_vectors(store, archive)
