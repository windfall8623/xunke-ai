"""Native asynchronous Qdrant storage for immutable vector projections.

Only identity fields enter Qdrant. Source text and original float32 vectors
remain in application artifacts. Every mutation is one tracked operation;
completed writes still require an independent reader's full verification.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import struct
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator, Sequence
from typing import Any, TypeVar
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.values import iso, now
from app.rag.contracts import stable_hash
from app.rag.errors import RetrievalUnavailable, SourceUnavailable
from app.rag.vector_store import (
    BACKEND_QDRANT,
    DeleteReceipt,
    ProjectionDigest,
    ProjectionRef,
    SourceVectorArchive,
    VectorHit,
    VectorRecord,
    VectorSearch,
    VerifiedProjection,
    WriteReceipt,
)

DENSE_VECTOR_NAME = "dense"
STORAGE_SCHEMA = "qdrant-dense-v1"
ID_SCHEME = "uuid5-v1"
SCORE_VERSION = "qdrant-cosine-similarity-v1"
NORMALIZATION_VERSION = "cosine-l2-f32-v1"
VERIFY_RTOL = 1e-5
VERIFY_ATOL = 1e-6
POINT_NAMESPACE = uuid5(NAMESPACE_URL, "urn:xunke-ai:qdrant:point-id:v1")
IDENTITY_FIELDS = tuple(ProjectionRef.model_fields)
PAYLOAD_FIELDS = [*IDENTITY_FIELDS, "node_id", "id_scheme", "storage_schema"]
PAYLOAD_INDEXES = {
    "owner_id": models.PayloadSchemaType.INTEGER,
    "namespace": models.PayloadSchemaType.KEYWORD,
    "projection_key": models.PayloadSchemaType.KEYWORD,
    "node_id": models.PayloadSchemaType.KEYWORD,
}
_ARCHIVE_IDENTITY_FIELDS = (
    "projection_key", "owner_id", "namespace", "doc_id", "document_version_id",
    "parse_artifact_id", "index_build_id", "attempt_id", "index_profile_hash",
    "embedding_signature_hash",
)
_T = TypeVar("_T")


class VectorOperationUnconfirmed(RetrievalUnavailable):
    """The remote operation may have applied; this is not a failed/no-write receipt."""

    code = "VECTOR_OPERATION_UNCONFIRMED"

    def __init__(
        self,
        message: str = "Vector operation completion is unknown",
        *,
        provider_operation_id: str | int | None = None,
        provider_status: str | None = None,
    ):
        self.provider_operation_id = (
            str(provider_operation_id) if provider_operation_id is not None else None
        )
        self.provider_status = provider_status
        super().__init__(
            message,
            details={"provider_operation_id": self.provider_operation_id},
        )


def _identifier(value: Any, field: str, *, limit: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > limit
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise SourceUnavailable(f"Invalid vector identity field: {field}")
    return value


def _validate_ref(ref: ProjectionRef) -> None:
    if ref.backend != BACKEND_QDRANT:
        raise SourceUnavailable("Projection does not belong to Qdrant")
    if type(ref.owner_id) is not int or not 0 < ref.owner_id <= 2**63 - 1:
        raise SourceUnavailable("Vector owner id must be a positive signed 64-bit integer")
    for field in IDENTITY_FIELDS:
        if field != "owner_id":
            _identifier(getattr(ref, field), field, limit=1024 if field == "projection_key" else 512)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", ref.collection_name):
        raise SourceUnavailable("Invalid Qdrant collection name")


def collection_name_for(
    embedding_signature_hash: str,
    target_revision: str,
    *,
    prefix: str = "xunke_dense",
) -> str:
    """Share one collection per verified vector space and storage revision."""
    _identifier(embedding_signature_hash, "embedding_signature_hash")
    _identifier(target_revision, "target_revision")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", prefix):
        raise SourceUnavailable("Invalid Qdrant collection prefix")
    space = stable_hash([embedding_signature_hash, target_revision, STORAGE_SCHEMA])
    return f"{prefix}_{space[:48]}_v1"


def make_point_id(ref: ProjectionRef, node_id: str) -> str:
    _validate_ref(ref)
    _identifier(node_id, "node_id")
    identity = [
        ref.target_revision, ref.embedding_signature_hash,
        ref.owner_id, ref.namespace, ref.doc_id, ref.document_version_id,
        ref.parse_artifact_id, ref.index_build_id, ref.attempt_id, node_id,
    ]
    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return str(uuid5(POINT_NAMESPACE, encoded))


def _scope_fields(ref: ProjectionRef) -> dict[str, str | int]:
    _validate_ref(ref)
    return {**ref.model_dump(), "id_scheme": ID_SCHEME, "storage_schema": STORAGE_SCHEMA}


def build_filter(
    ref: ProjectionRef, allowed_node_ids: Iterable[str] | None = None
) -> models.Filter:
    """None selects one exact attempt; an explicitly empty search scope is invalid."""
    conditions = [
        models.FieldCondition(key=key, match=models.MatchValue(value=value))
        for key, value in _scope_fields(ref).items()
    ]
    if allowed_node_ids is not None:
        allowed = sorted({_identifier(node_id, "node_id") for node_id in allowed_node_ids})
        if not allowed:
            raise ValueError("Empty scope must return before querying Qdrant")
        conditions.append(models.FieldCondition(key="node_id", match=models.MatchAny(any=allowed)))
    return models.Filter(must=conditions)


def _vector(values: Sequence[float], dimensions: int | None = None) -> list[float]:
    if not values or (dimensions is not None and len(values) != dimensions):
        raise SourceUnavailable("Vector dimensions do not match the collection")
    if any(not math.isfinite(value) for value in values):
        raise SourceUnavailable("Vector contains a non-finite value")
    try:
        # The source archive and Qdrant's unquantized representation are float32.
        converted = list(struct.unpack(f"<{len(values)}f", struct.pack(f"<{len(values)}f", *values)))
    except (OverflowError, struct.error) as exc:
        raise SourceUnavailable("Vector is outside finite float32 range") from exc
    norm = math.sqrt(math.fsum(value * value for value in converted))
    if not math.isfinite(norm) or norm == 0:
        raise SourceUnavailable("Cosine vectors require a finite nonzero norm")
    return converted


def _json_size(model: Any) -> int:
    # Matches the pinned REST SDK's encoder (not Python's spaced JSON default).
    return len(model.model_dump_json(by_alias=True, exclude_unset=True, exclude_none=True).encode("utf-8"))


def _point(ref: ProjectionRef, row: VectorRecord, dimensions: int | None = None) -> models.PointStruct:
    return models.PointStruct(
        id=make_point_id(ref, row.node_id),
        vector={DENSE_VECTOR_NAME: _vector(row.vector, dimensions)},
        payload={**_scope_fields(ref), "node_id": row.node_id},
    )


def _point_node(point: Any, ref: ProjectionRef, allowed: set[str] | frozenset[str] | None = None) -> str:
    payload = point.payload
    if not isinstance(payload, dict):
        raise SourceUnavailable("Qdrant point identity is missing")
    for field, expected in _scope_fields(ref).items():
        actual = payload.get(field)
        if type(actual) is not type(expected) or actual != expected:
            raise SourceUnavailable("Qdrant point belongs to a different projection identity")
    node_id = _identifier(payload.get("node_id"), "node_id")
    try:
        physical_id = str(UUID(str(point.id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise SourceUnavailable("Qdrant point id is not a UUID") from exc
    if physical_id != make_point_id(ref, node_id):
        raise SourceUnavailable("Qdrant point UUID does not match its logical identity")
    if allowed is not None and node_id not in allowed:
        raise SourceUnavailable("Qdrant point is outside the authorized node scope")
    return node_id


class QdrantProjectionStore:
    """One process-owned store with independent reader/writer clients and bounded RPCs."""

    def __init__(
        self,
        url: str,
        *,
        api_key: str = "",
        read_only_api_key: str = "",
        writable: bool = False,
        search_timeout_seconds: float = 5,
        write_timeout_seconds: float = 30,
        rpc_concurrency: int = 4,
        batch_size: int = 128,
        max_request_bytes: int = 2097152,
        hnsw_ef_search: int = 64,
        vector_on_disk: bool = True,
        hnsw_m: int = 16,
        hnsw_ef_construct: int = 128,
    ):
        endpoint = urlsplit(url)
        if (
            endpoint.scheme not in {"http", "https"} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
        ):
            raise ValueError("Qdrant requires an HTTP(S) service URL without embedded credentials")
        if not read_only_api_key or (writable and not api_key):
            raise ValueError("Qdrant requires a reader key and a separate key for writable stores")
        if (api_key and api_key == read_only_api_key) or (not writable and api_key):
            raise ValueError("Read-only Qdrant stores must not receive the writer credential")
        for value in (search_timeout_seconds, write_timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Qdrant timeouts must be finite and positive")
        for name, value in (
            ("rpc_concurrency", rpc_concurrency), ("batch_size", batch_size),
            ("max_request_bytes", max_request_bytes), ("hnsw_ef_search", hnsw_ef_search),
            ("hnsw_m", hnsw_m), ("hnsw_ef_construct", hnsw_ef_construct),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"Qdrant {name} must be a positive integer")
        self._search_timeout = float(search_timeout_seconds)
        self._write_timeout = float(write_timeout_seconds)
        self._batch_size = batch_size
        self._max_request_bytes = max_request_bytes
        self._hnsw_ef_search = max(64, hnsw_ef_search)
        self._vector_on_disk = vector_on_disk
        self._hnsw_m = hnsw_m
        self._hnsw_ef_construct = hnsw_ef_construct
        self._rpc_slots = asyncio.Semaphore(min(4, rpc_concurrency))
        self._collection_dimensions: dict[tuple[str, str, str, str], int] = {}
        self._closed = False
        # Disable the constructor's compatibility probe: all network I/O below
        # is asynchronous and explicitly bounded. The SDK and server are pinned.
        client_options = dict(
            url=url, prefer_grpc=False, check_compatibility=False,
            pool_size=min(4, rpc_concurrency), trust_env=False,
        )
        self._reader = AsyncQdrantClient(
            **client_options, api_key=read_only_api_key, timeout=math.ceil(self._search_timeout),
        )
        self._writer = (
            AsyncQdrantClient(**client_options, api_key=api_key, timeout=math.ceil(self._write_timeout))
            if writable else None
        )

    def _require_writer(self) -> AsyncQdrantClient:
        if self._writer is None:
            raise PermissionError("This Qdrant store is read-only")
        return self._writer

    async def _rpc(
        self, method: Callable[..., Awaitable[_T]], *, mutation: bool = False,
        seconds: float | None = None, **kwargs: Any,
    ) -> _T:
        if self._closed:
            raise RetrievalUnavailable("Qdrant store is closed")
        budget = seconds if seconds is not None else (self._write_timeout if mutation else self._search_timeout)
        try:
            async with asyncio.timeout(budget):
                async with self._rpc_slots:
                    return await method(**kwargs)
        except (asyncio.CancelledError, TimeoutError, httpx.TransportError, ResponseHandlingException) as exc:
            if mutation:
                raise VectorOperationUnconfirmed() from exc
            raise
        except UnexpectedResponse as exc:
            if mutation and (exc.status_code is None or exc.status_code >= 500 or exc.status_code == 408):
                operation_id = None
                try:
                    result = json.loads(exc.content).get("result")
                    if isinstance(result, dict):
                        operation_id = result.get("operation_id")
                except (ValueError, AttributeError, TypeError):
                    pass
                raise VectorOperationUnconfirmed(provider_operation_id=operation_id) from exc
            raise

    @staticmethod
    def _completed(result: models.UpdateResult) -> str | None:
        operation_id = str(result.operation_id) if result.operation_id is not None else None
        if result.status != models.UpdateStatus.COMPLETED:
            raise VectorOperationUnconfirmed(
                provider_operation_id=operation_id, provider_status=result.status.value,
            )
        return operation_id

    @staticmethod
    def _space_key(ref: ProjectionRef) -> tuple[str, str, str, str]:
        return (ref.collection_name, ref.embedding_signature_hash, ref.target_revision, ref.schema_version)

    @staticmethod
    def _space_metadata(ref: ProjectionRef) -> dict[str, str]:
        return {
            "storage_schema": STORAGE_SCHEMA,
            "embedding_signature_hash": ref.embedding_signature_hash,
            "target_revision": ref.target_revision,
            "schema_version": ref.schema_version,
        }

    def _check_collection(
        self, ref: ProjectionRef, info: models.CollectionInfo,
        dimensions: int | None = None, *, require_indexes: bool = True,
    ) -> int:
        vectors = info.config.params.vectors
        if not isinstance(vectors, dict) or set(vectors) != {DENSE_VECTOR_NAME}:
            raise SourceUnavailable("Qdrant collection must have exactly one named dense vector")
        params = vectors[DENSE_VECTOR_NAME]
        if (
            params.size <= 0 or (dimensions is not None and params.size != dimensions)
            or params.distance != models.Distance.COSINE
            or params.datatype not in {None, models.Datatype.FLOAT32}
            or params.multivector_config is not None
            or params.quantization_config is not None
            or info.config.quantization_config is not None
            or bool(info.config.params.sparse_vectors)
        ):
            raise SourceUnavailable("Qdrant collection vector schema is incompatible")
        metadata = info.config.metadata or {}
        if any(metadata.get(key) != value for key, value in self._space_metadata(ref).items()):
            raise SourceUnavailable("Qdrant collection vector space metadata does not match")
        for field, kind in PAYLOAD_INDEXES.items():
            index = info.payload_schema.get(field)
            if index is None:
                if require_indexes:
                    raise SourceUnavailable("Qdrant collection requires explicit payload index initialization")
            elif index.data_type != kind:
                raise SourceUnavailable("Qdrant payload index schema is incompatible")
        return params.size

    async def _dimensions(self, ref: ProjectionRef) -> int:
        _validate_ref(ref)
        key = self._space_key(ref)
        if key not in self._collection_dimensions:
            try:
                info = await self._rpc(self._reader.get_collection, collection_name=ref.collection_name)
            except UnexpectedResponse as exc:
                if exc.status_code == 404:
                    raise SourceUnavailable("Qdrant collection has not been initialized") from exc
                raise
            self._collection_dimensions[key] = self._check_collection(ref, info)
        return self._collection_dimensions[key]

    async def initialize_collection(self, ref: ProjectionRef, dimensions: int) -> None:
        """Create/check one fixed space and required indexes; never reset existing data."""
        writer = self._require_writer()
        _validate_ref(ref)
        if type(dimensions) is not int or dimensions <= 0:
            raise SourceUnavailable("Collection dimensions must be a positive integer")
        self._collection_dimensions.pop(self._space_key(ref), None)
        try:
            info = await self._rpc(self._reader.get_collection, collection_name=ref.collection_name)
        except UnexpectedResponse as exc:
            if exc.status_code != 404:
                raise
            try:
                created = await self._rpc(
                    writer.create_collection, mutation=True,
                    collection_name=ref.collection_name,
                    vectors_config={DENSE_VECTOR_NAME: models.VectorParams(
                        size=dimensions, distance=models.Distance.COSINE,
                        datatype=models.Datatype.FLOAT32, on_disk=self._vector_on_disk,
                    )},
                    hnsw_config=models.HnswConfigDiff(m=self._hnsw_m, ef_construct=self._hnsw_ef_construct),
                    metadata=self._space_metadata(ref), timeout=math.ceil(self._write_timeout),
                )
                if created is not True:
                    raise VectorOperationUnconfirmed("Collection creation was not confirmed")
            except UnexpectedResponse as create_error:
                if create_error.status_code != 409:
                    raise
            info = await self._rpc(self._reader.get_collection, collection_name=ref.collection_name)
        self._check_collection(ref, info, dimensions, require_indexes=False)
        for field, kind in PAYLOAD_INDEXES.items():
            if field not in info.payload_schema:
                result = await self._rpc(
                    writer.create_payload_index, mutation=True,
                    collection_name=ref.collection_name, field_name=field,
                    field_schema=kind, wait=True, timeout=math.ceil(self._write_timeout),
                )
                self._completed(result)
        # The reader must see the final schema before any point can be imported.
        info = await self._rpc(self._reader.get_collection, collection_name=ref.collection_name)
        self._collection_dimensions[self._space_key(ref)] = self._check_collection(ref, info, dimensions)

    def iter_write_batches(
        self, ref: ProjectionRef, rows: Sequence[VectorRecord]
    ) -> Iterator[list[VectorRecord]]:
        """Partition before the service registers one SQL operation for each batch."""
        _validate_ref(ref)
        seen: set[str] = set()
        batch: list[VectorRecord] = []
        base_size = _json_size(models.PointsList(points=[]))
        size = base_size
        dimensions = len(rows[0].vector) if rows else None
        for row in rows:
            if row.node_id in seen:
                raise SourceUnavailable("Vector write contains duplicate node ids")
            seen.add(row.node_id)
            point_size = _json_size(_point(ref, row, dimensions))
            if point_size + base_size > self._max_request_bytes:
                raise SourceUnavailable("One vector exceeds the configured request byte limit")
            if batch and (len(batch) >= self._batch_size or size + point_size + 1 > self._max_request_bytes):
                yield batch
                batch, size = [], base_size
            size += point_size + (1 if batch else 0)
            batch.append(row)
        if batch:
            yield batch

    async def write_attempt(self, ref: ProjectionRef, rows: Sequence[VectorRecord]) -> WriteReceipt:
        writer = self._require_writer()
        _validate_ref(ref)
        if not rows or len(rows) > self._batch_size:
            raise SourceUnavailable("Vector write must contain one bounded nonempty batch")
        dimensions = await self._dimensions(ref)
        if len({row.node_id for row in rows}) != len(rows):
            raise SourceUnavailable("Vector write contains duplicate node ids")
        points = await asyncio.to_thread(lambda: [_point(ref, row, dimensions) for row in rows])
        if _json_size(models.PointsList(points=points)) > self._max_request_bytes:
            raise SourceUnavailable("Vector write exceeds the configured request byte limit")
        # A retry may replace only the same complete logical identity. The
        # single-writer deployment prevents a competing writer between this
        # preflight and upsert; a UUID alone is never an authorization check.
        existing = await self._rpc(
            self._reader.retrieve, collection_name=ref.collection_name,
            ids=[point.id for point in points], with_payload=PAYLOAD_FIELDS,
            with_vectors=False, timeout=math.ceil(self._search_timeout),
        )
        allowed = {row.node_id for row in rows}
        for point in existing:
            _point_node(point, ref, allowed)
        result = await self._rpc(
            writer.upsert, mutation=True, collection_name=ref.collection_name,
            points=points, wait=True, timeout=math.ceil(self._write_timeout),
        )
        operation_id = self._completed(result)
        return WriteReceipt(
            projection_key=ref.projection_key, provider_operation_id=operation_id,
            status="completed", batch_count=1,
        )

    async def verify_attempt(
        self, ref: ProjectionRef, expected: ProjectionDigest,
        source: SourceVectorArchive | None = None, *,
        source_rows: Sequence[VectorRecord] | None = None,
    ) -> VerifiedProjection:
        """Recheck the supplied archive rows, then verify every independently read point."""
        _validate_ref(ref)
        if source is None or source_rows is None:
            raise SourceUnavailable("Qdrant verification requires reread original source vectors")

        def verify_source() -> dict[str, list[float]]:
            from app.rag.vector_archive import FORMAT_VERSION, node_set_hash, source_vectors_hash

            if source.format_version != FORMAT_VERSION or any(
                getattr(source, field) != getattr(ref, field) for field in _ARCHIVE_IDENTITY_FIELDS
            ):
                raise SourceUnavailable("Source vector archive identity does not match the projection")
            if (
                source.count != expected.expected_node_count or len(source_rows) != source.count
                or source.dimensions != expected.dimensions
            ):
                raise SourceUnavailable("Source vector archive dimensions or count do not match")
            node_ids = [row.node_id for row in source_rows]
            if len(set(node_ids)) != len(node_ids) or node_set_hash(node_ids) != expected.node_set_hash or source.node_set_hash != expected.node_set_hash:
                raise SourceUnavailable("Source vector archive node identity does not match")
            if source.source_vectors_hash != expected.source_vectors_hash or source_vectors_hash(source, source_rows) != expected.source_vectors_hash:
                raise SourceUnavailable("Source vector archive hash does not match")
            normalized = {}
            for row in source_rows:
                _identifier(row.node_id, "node_id")
                vector = _vector(row.vector, expected.dimensions)
                norm = math.sqrt(math.fsum(value * value for value in vector))
                normalized[row.node_id] = [value / norm for value in vector]
            return normalized

        expected_by_id = await asyncio.to_thread(verify_source)
        actual_by_id: dict[str, list[float]] = {}
        max_error = 0.0
        async for row in self.iter_vectors(ref, batch_size=self._batch_size):
            if row.node_id not in expected_by_id or row.node_id in actual_by_id:
                raise SourceUnavailable("Qdrant vector node set does not match the source archive")
            wanted = expected_by_id[row.node_id]
            if len(row.vector) != expected.dimensions:
                raise SourceUnavailable("Qdrant vector dimensions do not match the source archive")
            for actual, value in zip(row.vector, wanted):
                error = abs(actual - value)
                if error > VERIFY_ATOL + VERIFY_RTOL * abs(value):
                    raise SourceUnavailable("Qdrant vector does not match source cosine normalization")
                max_error = max(max_error, error)
            actual_by_id[row.node_id] = row.vector
        if set(actual_by_id) != set(expected_by_id) or len(actual_by_id) != expected.expected_node_count:
            raise SourceUnavailable("Qdrant vector count or identity does not match the source archive")
        target_hash = await asyncio.to_thread(
            lambda: stable_hash([[node_id, actual_by_id[node_id]] for node_id in sorted(actual_by_id)])
        )
        return VerifiedProjection(
            projection_key=ref.projection_key,
            digest=expected.model_copy(update={
                "normalization_version": NORMALIZATION_VERSION,
                "target_vectors_hash": target_hash, "max_abs_error": max_error,
            }),
            verified_at=iso(now()),
        )

    def _query_batches(self, request: VectorSearch, vector: list[float]) -> Iterator[models.QueryRequest]:
        base_filter = build_filter(request.ref)
        search_params = models.SearchParams(hnsw_ef=max(self._hnsw_ef_search, request.top_k))

        def query_for(node_ids: list[str]) -> models.QueryRequest:
            scoped = models.Filter(must=[
                *(base_filter.must or []),
                models.FieldCondition(key="node_id", match=models.MatchAny(any=node_ids)),
            ])
            return models.QueryRequest(
                query=models.NearestQuery(nearest=vector), using=DENSE_VECTOR_NAME,
                filter=scoped, params=search_params, limit=request.top_k, offset=0,
                with_vector=False, with_payload=PAYLOAD_FIELDS,
            )

        base_size = _json_size(query_for([]))
        node_ids: list[str] = []
        size = base_size
        for node_id in sorted(request.allowed_node_ids):
            _identifier(node_id, "node_id")
            node_size = len(json.dumps(node_id, ensure_ascii=False).encode("utf-8"))
            if node_size + base_size > self._max_request_bytes:
                raise SourceUnavailable("Vector query exceeds the configured request byte limit")
            if node_ids and size + node_size + 1 > self._max_request_bytes:
                yield query_for(node_ids)
                node_ids, size = [], base_size
            size += node_size + (1 if node_ids else 0)
            node_ids.append(node_id)
        if node_ids:
            yield query_for(node_ids)

    async def search(self, request: VectorSearch) -> list[VectorHit]:
        if not request.allowed_node_ids:
            return []
        _validate_ref(request.ref)
        budget = self._search_timeout
        if request.deadline_seconds is not None:
            if not math.isfinite(request.deadline_seconds) or request.deadline_seconds <= 0:
                raise RetrievalUnavailable("Vector search deadline has expired")
            budget = min(budget, request.deadline_seconds)
        try:
            async with asyncio.timeout(budget):
                dimensions = await self._dimensions(request.ref)
                vector = _vector(request.query_vector, dimensions)
                deadline = asyncio.get_running_loop().time() + budget
                hits: dict[str, VectorHit] = {}
                # Sequential batches bound memory and retain all authorized
                # nodes. The semaphore also bounds concurrent callers.
                for query in self._query_batches(request, vector):
                    if _json_size(query) > self._max_request_bytes:
                        raise SourceUnavailable("Vector query exceeds the configured request byte limit")
                    remaining = max(0.001, deadline - asyncio.get_running_loop().time())
                    result = await self._rpc(
                        self._reader.query_points, seconds=remaining,
                        collection_name=request.ref.collection_name,
                        query=query.query, using=DENSE_VECTOR_NAME, query_filter=query.filter,
                        search_params=query.params, limit=request.top_k, offset=0,
                        with_payload=PAYLOAD_FIELDS, with_vectors=False,
                        timeout=max(1, math.ceil(remaining)),
                    )
                    # Check the exact batch, not only the union of whitelists.
                    allowed = set(query.filter.must[-1].match.any)
                    for point in result.points:
                        node_id = _point_node(point, request.ref, allowed)
                        score = float(point.score)
                        if not math.isfinite(score) or not -1 - VERIFY_RTOL <= score <= 1 + VERIFY_RTOL:
                            raise SourceUnavailable("Qdrant returned an invalid cosine score")
                        hit = VectorHit(
                            physical_id=str(point.id), node_id=node_id,
                            projection_key=request.ref.projection_key, raw_score=score,
                            metric="cosine", score_version=SCORE_VERSION,
                        )
                        previous = hits.get(node_id)
                        if previous is None or hit.raw_score > previous.raw_score:
                            hits[node_id] = hit
                return sorted(hits.values(), key=lambda hit: (-hit.raw_score, hit.physical_id))[:request.top_k]
        except TimeoutError as exc:
            raise RetrievalUnavailable("Vector search deadline exceeded") from exc

    async def iter_vectors(self, ref: ProjectionRef, batch_size: int = 128) -> AsyncIterator[VectorRecord]:
        _validate_ref(ref)
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("Vector scroll batch size must be positive")
        dimensions = await self._dimensions(ref)
        offset = None
        seen_nodes: set[str] = set()
        seen_cursors: set[str] = set()
        while True:
            records, next_offset = await self._rpc(
                self._reader.scroll, collection_name=ref.collection_name,
                scroll_filter=build_filter(ref), limit=min(batch_size, self._batch_size),
                offset=offset, with_payload=PAYLOAD_FIELDS, with_vectors=[DENSE_VECTOR_NAME],
                timeout=math.ceil(self._search_timeout),
            )
            for point in records:
                node_id = _point_node(point, ref)
                if node_id in seen_nodes:
                    raise SourceUnavailable("Qdrant scroll returned duplicate logical nodes")
                seen_nodes.add(node_id)
                if not isinstance(point.vector, dict) or set(point.vector) != {DENSE_VECTOR_NAME}:
                    raise SourceUnavailable("Qdrant dense vector is missing")
                yield VectorRecord(node_id=node_id, vector=_vector(point.vector[DENSE_VECTOR_NAME], dimensions))
            if next_offset is None:
                return
            cursor = str(next_offset)
            if not records or cursor in seen_cursors:
                raise SourceUnavailable("Qdrant scroll cursor did not advance")
            seen_cursors.add(cursor)
            offset = next_offset

    async def delete_attempt(self, ref: ProjectionRef) -> DeleteReceipt:
        writer = self._require_writer()
        scoped = build_filter(ref)
        try:
            result = await self._rpc(
                writer.delete, mutation=True, collection_name=ref.collection_name,
                points_selector=models.FilterSelector(filter=scoped), wait=True,
                timeout=math.ceil(self._write_timeout),
            )
        except UnexpectedResponse as exc:
            if exc.status_code != 404:
                raise
            # Registration precedes collection creation. A failed first build
            # can therefore own an attempt whose collection never existed.
            try:
                exists = await self._rpc(
                    self._reader.collection_exists, collection_name=ref.collection_name,
                )
            except (Exception, asyncio.CancelledError) as confirmation_error:
                raise VectorOperationUnconfirmed(
                    "Vector collection absence could not be confirmed",
                ) from confirmation_error
            if exists is not False:
                raise VectorOperationUnconfirmed(
                    "Vector collection absence was not confirmed by the independent reader",
                ) from exc
            return DeleteReceipt(projection_key=ref.projection_key, status="completed", remaining_visible=0)
        operation_id = self._completed(result)
        try:
            records, next_offset = await self._rpc(
                self._reader.scroll, collection_name=ref.collection_name,
                scroll_filter=scoped, limit=1, with_payload=PAYLOAD_FIELDS,
                with_vectors=False, timeout=math.ceil(self._search_timeout),
            )
        except (Exception, asyncio.CancelledError) as exc:
            raise VectorOperationUnconfirmed(
                "Vector deletion visibility could not be confirmed",
                provider_operation_id=operation_id,
            ) from exc
        if records or next_offset is not None:
            raise VectorOperationUnconfirmed(
                "Vector deletion is still visible to the independent reader",
                provider_operation_id=operation_id,
            )
        return DeleteReceipt(projection_key=ref.projection_key, status="completed", remaining_visible=0)

    async def healthcheck(self) -> bool:
        try:
            await self._rpc(self._reader.get_collections, seconds=min(3, self._search_timeout))
        except Exception:
            return False
        return True

    async def server_startup(self):
        """Read the server's actual startup epoch for explicit maintenance recovery."""
        response = await self._rpc(
            self._reader.http.service_api.telemetry, details_level=0,
            timeout=math.ceil(self._search_timeout),
        )
        if response.result.app is None:
            raise SourceUnavailable("Qdrant did not report its server startup epoch")
        return response.result.app.startup

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        clients = [self._reader] + ([self._writer] if self._writer is not None else [])
        results = await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
