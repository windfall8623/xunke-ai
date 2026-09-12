"""向量投影契约：后端可替换的投影存储协议与数据类型。

三层边界中的"向量投影层"。写回执不是业务 ready；核验摘要区分
源归档（送入后端前的原始 float32）与目标（后端实际存储的表示）。
物理 ID 与 collection 名称由具体后端确定性计算，不接受浏览器输入。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from pydantic import BaseModel, Field

BACKEND_CHROMA = "chroma"
BACKEND_QDRANT = "qdrant"
LEGACY_TARGET_REVISION = "legacy-v1"
PROJECTION_SCHEMA_VERSION = "rag-projection-v1"


class ProjectionRef(BaseModel):
    """一个物理投影的完整身份；查询与写入都必须携带。"""

    backend: str
    target_revision: str
    collection_name: str
    schema_version: str = PROJECTION_SCHEMA_VERSION
    projection_key: str
    owner_id: int
    namespace: str
    doc_id: str
    document_version_id: str
    parse_artifact_id: str
    index_build_id: str
    attempt_id: str
    index_profile_hash: str
    embedding_signature_hash: str


class VectorRecord(BaseModel):
    node_id: str
    vector: list[float]


class SourceVectorArchive(BaseModel):
    """原始向量归档的登记信息；文件保存在应用产物层。"""

    projection_key: str
    owner_id: int
    namespace: str
    doc_id: str
    document_version_id: str
    parse_artifact_id: str
    index_build_id: str
    attempt_id: str
    index_profile_hash: str = ""
    embedding_signature_hash: str = ""
    vector_file_key: str
    metadata_file_key: str
    count: int = Field(ge=1)
    dimensions: int = Field(gt=0)
    source_vectors_hash: str
    node_set_hash: str
    format_version: str = "source-vectors.v2"


class ProjectionDigest(BaseModel):
    expected_node_count: int = Field(ge=1)
    dimensions: int = Field(gt=0)
    node_set_hash: str
    source_vectors_hash: str
    # chroma 原样保存源向量；cosine 后端存储归一化表示，另记版本。
    normalization_version: str = "identity-f32-v1"
    target_vectors_hash: str | None = None
    max_abs_error: float | None = None


class WriteReceipt(BaseModel):
    """仅是写入回执，不代表业务 ready。"""

    projection_key: str
    provider_operation_id: str | None = None
    status: str
    batch_count: int


class VerifiedProjection(BaseModel):
    projection_key: str
    digest: ProjectionDigest
    verified_at: str


class VectorSearch(BaseModel):
    query_vector: list[float]
    ref: ProjectionRef
    allowed_node_ids: frozenset[str]
    top_k: int = Field(ge=1)
    deadline_seconds: float | None = None


class VectorHit(BaseModel):
    physical_id: str
    node_id: str
    projection_key: str
    raw_score: float
    # raw_score 的换算由调用方按 metric 完成；store 不二次转换。
    metric: str
    score_version: str


class DeleteReceipt(BaseModel):
    projection_key: str
    status: str
    remaining_visible: int | None = None


class VectorProjectionStore(Protocol):
    """后端无关的投影存储协议；Chroma 与 Qdrant 分别实现。"""

    async def write_attempt(
        self, ref: ProjectionRef, rows: Sequence[VectorRecord]
    ) -> WriteReceipt: ...

    async def verify_attempt(
        self,
        ref: ProjectionRef,
        expected: ProjectionDigest,
        source: SourceVectorArchive,
    ) -> VerifiedProjection: ...

    async def search(self, request: VectorSearch) -> list[VectorHit]: ...

    def iter_vectors(
        self, ref: ProjectionRef, batch_size: int = 128
    ) -> AsyncIterator[VectorRecord]: ...

    async def delete_attempt(self, ref: ProjectionRef) -> DeleteReceipt: ...

    async def close(self) -> None: ...
