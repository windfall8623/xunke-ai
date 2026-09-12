"""原始向量归档：送入向量后端之前的 float32 原值。

每个投影一份归档，文件保存在应用产物层并与投影同生命周期。
源摘要（source_vectors_hash）覆盖规范身份、节点顺序与原始字节，
用于迁移一致性与保真回滚；不能拿后端归一化后的向量冒充原始值。
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Iterator, Sequence

from app.rag.artifact_store import ArtifactStore
from app.rag.contracts import stable_hash
from app.rag.errors import SourceUnavailable
from app.rag.vector_store import SourceVectorArchive, VectorRecord

FORMAT_VERSION = "source-vectors.v2"
NORMALIZATION_IDENTITY = "identity-f32-v1"


def node_set_hash(node_ids: Sequence[str]) -> str:
    return stable_hash(sorted(node_ids))


def _identity_payload(archive_like) -> list:
    return [
        archive_like.projection_key,
        archive_like.owner_id,
        archive_like.namespace,
        archive_like.doc_id,
        archive_like.document_version_id,
        archive_like.parse_artifact_id,
        archive_like.index_build_id,
        archive_like.attempt_id,
        getattr(archive_like, "index_profile_hash", ""),
        getattr(archive_like, "embedding_signature_hash", ""),
        archive_like.format_version if hasattr(archive_like, "format_version") else FORMAT_VERSION,
    ]


def _pack_vectors(vectors: Sequence[Sequence[float]]) -> bytes:
    flat = bytearray()
    for vector in vectors:
        for value in vector:
            if not math.isfinite(value):
                raise SourceUnavailable("Source vector contains a non-finite value")
            try:
                flat += struct.pack("<f", value)
            except (OverflowError, struct.error) as exc:
                raise SourceUnavailable("Source value is outside finite float32 range") from exc
    return bytes(flat)


def _unpack_vectors(data: bytes, dimensions: int, count: int) -> list[list[float]]:
    if len(data) != dimensions * count * 4:
        raise SourceUnavailable("Source vector archive size does not match metadata")
    values = struct.unpack(f"<{dimensions * count}f", data)
    return [
        list(values[index * dimensions : (index + 1) * dimensions])
        for index in range(count)
    ]


def source_vectors_hash(ref_or_archive, rows: Sequence[VectorRecord]) -> str:
    """Bind every original float32 value to its logical node and model space."""
    ordered = sorted(rows, key=lambda row: row.node_id)
    header = [_identity_payload(ref_or_archive), [row.node_id for row in ordered]]
    return hashlib.sha256(
        json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\x00" + _pack_vectors([row.vector for row in ordered])
    ).hexdigest()


def save_source_vectors(
    store: ArtifactStore, ref, rows: Sequence[VectorRecord]
) -> SourceVectorArchive:
    """按 node_id 固定排序写入 f32 与元数据；全部原子落盘。"""
    if not rows:
        raise SourceUnavailable("Source vector archive requires at least one row")
    dimensions = len(rows[0].vector)
    if any(len(row.vector) != dimensions for row in rows):
        raise SourceUnavailable("Source vectors have inconsistent dimensions")
    ordered = sorted(rows, key=lambda row: row.node_id)
    if len({row.node_id for row in ordered}) != len(ordered):
        raise SourceUnavailable("Source vectors contain duplicate node ids")
    payload = _pack_vectors([row.vector for row in ordered])
    vector_file_key = ref.projection_key + "/source-vectors.f32"
    metadata_file_key = ref.projection_key + "/source-vectors.json"
    digest = source_vectors_hash(ref, ordered)
    store.put_bytes(vector_file_key, payload)
    metadata = {
        "format_version": FORMAT_VERSION,
        "projection_key": ref.projection_key,
        "owner_id": ref.owner_id,
        "namespace": ref.namespace,
        "doc_id": ref.doc_id,
        "document_version_id": ref.document_version_id,
        "parse_artifact_id": ref.parse_artifact_id,
        "index_build_id": ref.index_build_id,
        "attempt_id": ref.attempt_id,
        "index_profile_hash": getattr(ref, "index_profile_hash", ""),
        "embedding_signature_hash": getattr(ref, "embedding_signature_hash", ""),
        "dimensions": dimensions,
        "count": len(ordered),
        "node_ids": [row.node_id for row in ordered],
        "node_set_hash": node_set_hash([row.node_id for row in ordered]),
        "source_vectors_hash": digest,
    }
    store.put_json(metadata_file_key, metadata)
    return SourceVectorArchive(
        projection_key=ref.projection_key,
        owner_id=ref.owner_id,
        namespace=ref.namespace,
        doc_id=ref.doc_id,
        document_version_id=ref.document_version_id,
        parse_artifact_id=ref.parse_artifact_id,
        index_build_id=ref.index_build_id,
        attempt_id=ref.attempt_id,
        index_profile_hash=getattr(ref, "index_profile_hash", ""),
        embedding_signature_hash=getattr(ref, "embedding_signature_hash", ""),
        vector_file_key=vector_file_key,
        metadata_file_key=metadata_file_key,
        count=len(ordered),
        dimensions=dimensions,
        source_vectors_hash=digest,
        node_set_hash=node_set_hash([row.node_id for row in ordered]),
        format_version=FORMAT_VERSION,
    )


def load_source_vectors(store: ArtifactStore, key: str) -> SourceVectorArchive:
    try:
        metadata = json.loads(store.resolve_key(key).read_bytes())
    except SourceUnavailable:
        raise
    except Exception as exc:
        raise SourceUnavailable("Source vector archive metadata is unavailable") from exc
    if metadata.get("format_version") != FORMAT_VERSION:
        raise SourceUnavailable("Unknown source vector archive format")
    return SourceVectorArchive.model_validate(
        {**metadata, "metadata_file_key": key,
         "vector_file_key": key.replace("source-vectors.json", "source-vectors.f32")}
    )


def iter_source_vectors(
    store: ArtifactStore, archive: SourceVectorArchive, batch_size: int = 128
) -> Iterator[list[VectorRecord]]:
    """按归档顺序分批产出原始向量；重读结果与保存顺序逐值一致。"""
    metadata = json.loads(store.resolve_key(archive.metadata_file_key).read_bytes())
    node_ids = metadata["node_ids"]
    if (
        batch_size < 1 or len(node_ids) != archive.count
        or node_ids != sorted(set(node_ids))
        or node_set_hash(node_ids) != archive.node_set_hash
        or metadata.get("node_set_hash") != archive.node_set_hash
        or metadata.get("format_version") != FORMAT_VERSION
    ):
        raise SourceUnavailable("Source vector archive metadata is inconsistent")
    data = store.resolve_key(archive.vector_file_key).read_bytes()
    vectors = _unpack_vectors(data, archive.dimensions, archive.count)
    rows = [VectorRecord(node_id=node_id, vector=vector) for node_id, vector in zip(node_ids, vectors)]
    digest = source_vectors_hash(archive, rows)
    if digest != archive.source_vectors_hash:
        raise SourceUnavailable("Source vector archive hash does not match metadata")
    for start in range(0, archive.count, max(1, batch_size)):
        chunk = node_ids[start : start + batch_size]
        yield [
            VectorRecord(node_id=node_id, vector=vectors[start + offset])
            for offset, node_id in enumerate(chunk)
        ]
