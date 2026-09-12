"""Chroma 投影实现：单写者独占，过滤在 top-k 之前生效。

集合命名与元数据键和既有 chroma_data 卷完全兼容；向量以源向量原样
写入（raw_score 为 Chroma 的 cosine distance，换算由调用方完成）。
所有同步 Chroma 调用经有界线程执行，不阻塞事件循环与租约心跳。
"""

from __future__ import annotations

import math
import threading
from collections.abc import AsyncIterator, Sequence

from app.core.values import iso, now
from app.rag.blocking_io import run_file_io
from app.rag.contracts import stable_hash
from app.rag.errors import SourceUnavailable
from app.rag.vector_store import (
    DeleteReceipt,
    ProjectionRef,
    SourceVectorArchive,
    VectorHit,
    VectorRecord,
    VectorSearch,
    VerifiedProjection,
    WriteReceipt,
)

SCORE_VERSION = "chroma-cosine-distance-v1"
METRIC = "cosine"
VERIFY_RTOL = 1e-5
VERIFY_ATOL = 1e-6


def collection_name_for(projection_key: str) -> str:
    return "rag_" + stable_hash(projection_key)[:48]


def _close_to(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= VERIFY_ATOL + VERIFY_RTOL * abs(expected)


class ChromaProjectionStore:
    """持有 Chroma client 的写者侧投影实现；由 rag-owner 进程独占打开。"""

    def __init__(self, client, *, io_lock: threading.RLock | None = None):
        self._client = client
        self._io_lock = io_lock or threading.RLock()

    def _collection(self, ref: ProjectionRef):
        from chromadb.errors import NotFoundError

        name = ref.collection_name or collection_name_for(ref.projection_key)
        try:
            return self._client.get_collection(name, embedding_function=None)
        except NotFoundError as exc:
            raise SourceUnavailable("Index vector collection is missing") from exc

    def _metadata(self, ref: ProjectionRef, node_id: str) -> dict:
        return {
            "owner_id": ref.owner_id,
            "namespace": ref.namespace,
            "scope_doc_id": ref.doc_id,
            "document_version_id": ref.document_version_id,
            "parse_artifact_id": ref.parse_artifact_id,
            "index_build_id": ref.index_build_id,
            "attempt_id": ref.attempt_id,
            "scope_node_id": node_id,
        }

    def _where(self, ref: ProjectionRef, allowed_node_ids) -> dict:
        if not allowed_node_ids:
            raise SourceUnavailable("Empty scope must return before querying")
        return {
            "$and": [
                {"owner_id": ref.owner_id},
                {"namespace": ref.namespace},
                {"scope_doc_id": ref.doc_id},
                {"document_version_id": ref.document_version_id},
                {"parse_artifact_id": ref.parse_artifact_id},
                {"index_build_id": ref.index_build_id},
                {"attempt_id": ref.attempt_id},
                {"scope_node_id": {"$in": sorted(allowed_node_ids)}},
            ]
        }

    async def write_attempt(
        self, ref: ProjectionRef, rows: Sequence[VectorRecord]
    ) -> WriteReceipt:
        if not rows:
            raise SourceUnavailable("Vector write requires at least one row")

        def write():
            with self._io_lock:
                from llama_index.core.schema import TextNode
                from llama_index.vector_stores.chroma import ChromaVectorStore

                name = ref.collection_name
                existing = {c.name for c in self._client.list_collections()}
                if name in existing:
                    # Exact attempt retry only; no active pointer is changed.
                    self._client.delete_collection(name)
                collection = self._client.create_collection(
                    name=name,
                    embedding_function=None,
                    # Small immutable collections never reach Chroma's default
                    # 1000-vector sync threshold. A segment can then be evicted
                    # before files exist, causing "Nothing found on disk" in
                    # later reads from this same owner. Materialize at least one
                    # complete batch before validating/publishing the build.
                    configuration={
                        "hnsw": {
                            "space": "cosine",
                            "batch_size": min(100, len(rows)),
                            "sync_threshold": min(100, len(rows)),
                        }
                    },
                    metadata={
                        "projection_key": ref.projection_key,
                        "owner_id": ref.owner_id,
                        "namespace": ref.namespace,
                        "doc_id": ref.doc_id,
                    },
                )
                nodes = [
                    TextNode(
                        id_=row.node_id,
                        text="",
                        embedding=row.vector,
                        metadata=self._metadata(ref, row.node_id),
                        excluded_embed_metadata_keys=list(
                            self._metadata(ref, row.node_id)
                        ),
                        excluded_llm_metadata_keys=list(
                            self._metadata(ref, row.node_id)
                        ),
                    )
                    for row in rows
                ]
                ChromaVectorStore(chroma_collection=collection).add(nodes)

        await run_file_io(write)
        return WriteReceipt(
            projection_key=ref.projection_key,
            provider_operation_id=None,
            status="completed",
            batch_count=1,
        )

    async def verify_attempt(
        self,
        ref: ProjectionRef,
        expected,  # ProjectionDigest
        source: SourceVectorArchive | None = None,
        *,
        source_rows: Sequence[VectorRecord] | None = None,
    ) -> VerifiedProjection:
        """完整核验：数量、身份、维度、有限值与逐向量容差比对。

        source_rows 是源归档的原始向量（与 expected.node_set_hash 对应的
        排序集合）；投影层不读文件，由调用方从归档展开后传入。
        source 为 None 时退化为数量/身份/维度核验（历史构建无源归档）。
        """
        expected_by_id = {row.node_id: row.vector for row in source_rows or []}
        if source_rows is not None and len(expected_by_id) != expected.expected_node_count:
            raise SourceUnavailable("Source rows do not match expected node count")

        def verify():
            with self._io_lock:
                return self._collection(ref).get(include=["embeddings", "metadatas"])

        stored = await run_file_io(verify)
        metadatas = stored.get("metadatas") or []
        if len(metadatas) != len(stored["ids"]):
            raise SourceUnavailable("Index vector metadata is missing")
        for identity, metadata in zip(stored["ids"], metadatas):
            if not isinstance(metadata, dict) or any(
                metadata.get(key) != value
                for key, value in self._metadata(ref, identity).items()
            ):
                raise SourceUnavailable("Index vector belongs to a different source")
        if len(stored["ids"]) != expected.expected_node_count or (
            source_rows is not None and set(stored["ids"]) != set(expected_by_id)
        ):
            raise SourceUnavailable("Index vector count or identity does not match")
        if source_rows is None:
            from app.rag.vector_archive import node_set_hash

            if node_set_hash(stored["ids"]) != expected.node_set_hash:
                raise SourceUnavailable("Index vector identity does not match")
        if any(len(v) != expected.dimensions for v in stored["embeddings"]):
            raise SourceUnavailable("Index embedding dimensions do not match")
        if any(
            not math.isfinite(value)
            for vector in stored["embeddings"]
            for value in vector
        ):
            raise SourceUnavailable("Index embedding contains a non-finite value")
        max_error = 0.0
        if source_rows is not None:
            for identity, vector in zip(stored["ids"], stored["embeddings"]):
                expected_vector = expected_by_id[identity]
                for actual, wanted in zip(vector, expected_vector):
                    if not _close_to(actual, wanted):
                        raise SourceUnavailable(
                            "Stored vector differs from its source archive"
                        )
                    max_error = max(max_error, abs(actual - wanted))
        digest = expected.model_copy(
            update={
                "target_vectors_hash": _target_hash(stored) if source_rows is not None else None,
                "max_abs_error": max_error or None,
            }
        )
        return VerifiedProjection(
            projection_key=ref.projection_key,
            digest=digest,
            verified_at=iso(now()),
        )

    async def search(self, request: VectorSearch) -> list[VectorHit]:
        where = self._where(request.ref, request.allowed_node_ids)

        def query():
            with self._io_lock:
                collection = self._collection(request.ref)
                return collection.query(
                    query_embeddings=[request.query_vector],
                    n_results=request.top_k,
                    where=where,
                    include=["distances"],
                )

        result = await run_file_io(query)
        return [
            VectorHit(
                physical_id=identity,
                node_id=identity,
                projection_key=request.ref.projection_key,
                raw_score=float(distance),
                metric=METRIC,
                score_version=SCORE_VERSION,
            )
            for identity, distance in zip(result["ids"][0], result["distances"][0])
        ]

    def iter_vectors(self, ref: ProjectionRef, batch_size: int = 128) -> AsyncIterator[VectorRecord]:
        async def generator():
            offset = 0
            while True:
                def page(start=offset):
                    with self._io_lock:
                        return self._collection(ref).get(
                            include=["embeddings"], limit=batch_size, offset=start
                        )

                stored = await run_file_io(page)
                ids = stored["ids"]
                if not ids:
                    return
                for identity, vector in zip(ids, stored["embeddings"]):
                    yield VectorRecord(node_id=identity, vector=list(vector))
                if len(ids) < batch_size:
                    return
                offset += len(ids)

        return generator()

    async def delete_attempt(self, ref: ProjectionRef) -> DeleteReceipt:
        return await run_file_io(self.delete_attempt_sync, ref)

    def delete_attempt_sync(self, ref: ProjectionRef) -> DeleteReceipt:
        with self._io_lock:
            name = ref.collection_name
            if name in {c.name for c in self._client.list_collections()}:
                self._client.delete_collection(name)
        return DeleteReceipt(
            projection_key=ref.projection_key, status="completed", remaining_visible=0
        )

    async def close(self) -> None:
        await run_file_io(self._client.close)


def _target_hash(stored) -> str:
    ordered = sorted(zip(stored["ids"], stored["embeddings"]), key=lambda pair: pair[0])
    return stable_hash(
        [[identity, [float(value) for value in vector]] for identity, vector in ordered]
    )
