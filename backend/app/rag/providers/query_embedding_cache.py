"""Optional, scoped query-vector caching outside the metered embedding provider.

Pass a dedicated redis-cache client, never the rate-limit/notification client.
This wrapper owns that cache client and its own circuit state. It does not own
the embedding provider, alter provider accounting, or cache document vectors.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import math
import struct
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import structlog

from app.core.redis_client import _CircuitBreaker
from app.rag.budget import BudgetLedger
from app.rag.errors import RetrievalUnavailable
from app.rag.providers.embedding_adapter import EmbeddingPort

logger = structlog.get_logger()
_VECTOR_ENCODING = "f64le-base64"
_MAX_VALUE_BYTES = 65536


def _normalized_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Embedding cache signature requires an explicit base URL")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    if port is not None and (parsed.scheme, port) not in {("http", 80), ("https", 443)}:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


@dataclass(frozen=True)
class EmbeddingSignature:
    """Explicit output identity; request parameters are snapshotted at creation."""

    provider: str
    base_url: str
    model: str
    model_revision: str | None
    dimensions: int
    input_version: str = "raw-utf8-v1"
    request_params: Mapping[str, Any] = field(default_factory=dict)
    schema: int = 1
    _canonical: bytes = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.provider, self.model, self.input_version)
        ):
            raise ValueError("Embedding cache signature fields must be explicit")
        if (
            type(self.dimensions) is not int
            or self.dimensions < 1
            or type(self.schema) is not int
            or self.schema < 1
            or (
                self.model_revision is not None
                and not isinstance(self.model_revision, str)
            )
        ):
            raise ValueError("Invalid embedding cache dimensions, schema or revision")
        normalized = _normalized_base_url(self.base_url)
        params = json.loads(
            json.dumps(dict(self.request_params), sort_keys=True, allow_nan=False)
        )
        object.__setattr__(self, "base_url", normalized)
        object.__setattr__(self, "request_params", params)
        payload = {
            "provider": self.provider,
            "base_url": normalized,
            "model": self.model,
            "model_revision": self.model_revision,
            "dimensions": self.dimensions,
            "input_version": self.input_version,
            "request_params": params,
            "schema": self.schema,
        }
        object.__setattr__(
            self,
            "_canonical",
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self._canonical).hexdigest()


class QueryCacheClient(Protocol):
    async def get(self, key: str) -> bytes | str | None: ...

    async def set(self, key: str, value: bytes, *, ex: int) -> Any: ...

    async def aclose(self) -> None: ...


def _validated_vector(value: Any, dimensions: int) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != dimensions:
        raise ValueError("Embedding vector dimensions do not match")
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(item)
        for item in value
    ):
        raise ValueError("Embedding vector must contain finite numbers")
    return [float(item) for item in value]


class QueryCachedEmbedding:
    """EmbeddingPort with explicit scoped caching and ordinary unscoped bypass.

    The caller supplies a dedicated cache Redis connection pool with automatic
    retries disabled. Each cache GET/SET has its own short operation deadline.
    Only production queries with a manual model revision are cacheable. Cache
    hits do not enter the original EmbeddingPort or provider_meter at all.
    """

    def __init__(
        self,
        inner: EmbeddingPort,
        *,
        client: QueryCacheClient | None,
        signature: EmbeddingSignature,
        hmac_secret: str | bytes,
        ttl_seconds: int = 86400,
        max_value_bytes: int = _MAX_VALUE_BYTES,
        operation_timeout_ms: int = 200,
        key_prefix: str = "xunke:development:v1",
    ) -> None:
        if signature.model != inner.model or signature.dimensions != inner.dimensions:
            raise ValueError("Cache signature must match the embedding provider")
        if (
            type(ttl_seconds) is not int
            or ttl_seconds < 1
            or type(max_value_bytes) is not int
            or not 1 <= max_value_bytes <= _MAX_VALUE_BYTES
            or type(operation_timeout_ms) is not int
            or not 1 <= operation_timeout_ms <= 10000
            or not isinstance(key_prefix, str)
            or not key_prefix.strip(": ")
            or not isinstance(hmac_secret, (str, bytes))
        ):
            raise ValueError("Invalid query embedding cache limits or key settings")
        self.inner, self.signature = inner, signature
        self._client = client
        self._secret = (
            hmac_secret.encode("utf-8") if isinstance(hmac_secret, str) else hmac_secret
        )
        self._ttl_seconds = ttl_seconds
        self._max_value_bytes = max_value_bytes
        self._operation_seconds = operation_timeout_ms / 1000
        self._key_prefix = key_prefix.rstrip(":")
        self._signature_hash = signature.fingerprint
        # Reuse the breaker policy, never the rate-limit runtime/client/state.
        self._breaker = _CircuitBreaker()
        self._closed = False

    @property
    def model(self) -> str:
        return self.inner.model

    @property
    def dimensions(self) -> int:
        return self.inner.dimensions

    async def embed_documents(
        self, texts: list[str], *, budget: BudgetLedger | None = None
    ) -> list[list[float]]:
        return await self.inner.embed_documents(texts, budget=budget)

    async def embed_query(
        self, text: str, *, budget: BudgetLedger | None = None
    ) -> list[float]:
        # EmbeddingPort carries no owner or namespace; never infer global scope.
        return await self.inner.embed_query(text, budget=budget)

    def _key(self, text: str, owner_id: int, namespace: str) -> str:
        namespace_hash = hmac.new(
            self._secret, b"namespace\x00" + namespace.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        input_hash = hmac.new(
            self._secret, b"query\x00" + text.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return (
            f"{self._key_prefix}:embedding-query:{owner_id}:{namespace_hash}:"
            f"{self._signature_hash}:{input_hash}"
        )

    async def _cache_call(
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        name: str,
        budget: BudgetLedger | None,
    ) -> Any:
        if self._closed or self._client is None:
            return None
        timeout = self._operation_seconds
        if budget is not None:
            timeout = min(timeout, budget.remaining_seconds)
        if timeout <= 0 or not self._breaker.allow():
            return None
        try:
            result = await asyncio.wait_for(operation(), timeout=timeout)
        except asyncio.CancelledError:
            self._breaker.cancel_probe()
            raise
        except Exception as exc:  # Cache failures never invalidate provider work.
            self._breaker.record_failure()
            logger.warning(
                "query_embedding_cache_degraded",
                operation=name,
                error_type=type(exc).__name__,
            )
            return None
        self._breaker.record_success()
        return result

    def _decode(self, raw: Any) -> list[float] | None:
        if not isinstance(raw, (bytes, str)):
            return None
        try:
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
            if len(raw) > self._max_value_bytes:
                return None
            payload = json.loads(raw.decode("utf-8"))
            if (
                not isinstance(payload, dict)
                or type(payload.get("schema")) is not int
                or payload["schema"] != self.signature.schema
                or payload.get("signature") != self._signature_hash
                or type(payload.get("dimensions")) is not int
                or payload["dimensions"] != self.dimensions
                or payload.get("encoding") != _VECTOR_ENCODING
                or not isinstance(payload.get("vector"), str)
            ):
                return None
            packed = base64.b64decode(payload["vector"], validate=True)
            if len(packed) != self.dimensions * 8:
                return None
            vector = struct.unpack(f"<{self.dimensions}d", packed)
            return _validated_vector(vector, self.dimensions)
        except (
            ValueError,
            TypeError,
            OverflowError,
            RecursionError,
            UnicodeError,
            binascii.Error,
            struct.error,
        ):
            return None

    def _encode(self, vector: list[float]) -> bytes | None:
        # Little-endian float64 preserves Python float values exactly. A 4096-D
        # vector needs about 44 KiB including Base64, safely within the 64 KiB cap.
        packed = struct.pack(f"<{len(vector)}d", *vector)
        payload = {
            "schema": self.signature.schema,
            "signature": self._signature_hash,
            "dimensions": self.dimensions,
            "encoding": _VECTOR_ENCODING,
            "vector": base64.b64encode(packed).decode("ascii"),
        }
        encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        return encoded if len(encoded) <= self._max_value_bytes else None

    async def cached_embed_query(
        self,
        text: str,
        *,
        owner_id: int,
        namespace: str,
        mode: str = "production",
        budget: BudgetLedger | None = None,
    ) -> list[float]:
        if type(owner_id) is not int or owner_id < 1 or not namespace:
            raise ValueError("Query caching requires an explicit owner and namespace")
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("Query caching requires an explicit namespace")
        if (
            mode != "production"
            or not (self.signature.model_revision or "").strip()
            or not self._secret
            or self._client is None
            or self._closed
            or self.model != self.signature.model
            or self.dimensions != self.signature.dimensions
            or not isinstance(text, str)
            or not text.strip()
        ):
            logger.info("query_embedding_cache", result="bypass")
            return await self.inner.embed_query(text, budget=budget)
        if budget is not None:
            budget.check()
        key = self._key(text, owner_id, namespace)
        raw = await self._cache_call(
            lambda: self._client.get(key),
            name="get",
            budget=budget,
        )
        cached = self._decode(raw)
        if cached is not None:
            if budget is not None:
                budget.check()
            logger.info("query_embedding_cache", result="hit")
            return cached
        logger.info("query_embedding_cache", result="miss")
        # This is the only provider invocation. GET failures and SET failures
        # cannot retry it, and all original budget/metering side effects remain.
        value = await self.inner.embed_query(text, budget=budget)
        try:
            vector = _validated_vector(value, self.dimensions)
        except (ValueError, TypeError, OverflowError) as exc:
            raise RetrievalUnavailable(
                "Embedding provider returned an invalid vector"
            ) from exc
        encoded = self._encode(vector)
        if encoded is not None:
            await self._cache_call(
                lambda: self._client.set(key, encoded, ex=self._ttl_seconds),
                name="set",
                budget=budget,
            )
        return vector

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        client, self._client = self._client, None
        if client is not None:
            try:
                await asyncio.wait_for(client.aclose(), timeout=self._operation_seconds)
            except Exception as exc:
                logger.warning(
                    "query_embedding_cache_degraded",
                    operation="close",
                    error_type=type(exc).__name__,
                )
