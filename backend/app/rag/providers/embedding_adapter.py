"""Explicit DashScope/OpenAI-compatible embedding calls with no hidden retries.

String input, float encoding, explicit dimensions, batches <= 10. No environment
provider discovery and no default OpenAI key/embedding are permitted.
"""

from __future__ import annotations

import math
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from app.rag.budget import BudgetLedger, count_tokens
from app.rag.errors import RetrievalUnavailable


class EmbeddingPort(Protocol):
    model: str
    dimensions: int

    async def embed_documents(
        self, texts: list[str], *, budget: BudgetLedger | None = None
    ) -> list[list[float]]: ...
    async def embed_query(
        self, text: str, *, budget: BudgetLedger | None = None
    ) -> list[float]: ...


class DashScopeEmbedding:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-v4",
        dimensions: int = 1024,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
        max_input_bytes: int = 8192,
        usd_per_million_tokens: float | None = None,
    ):
        url = urlsplit(base_url)
        if not api_key or not model or dimensions < 1:
            raise ValueError(
                "Embedding credentials, model and dimensions must be explicit"
            )
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Embedding endpoint must use explicit HTTPS")
        if not 0 < timeout_seconds <= 60 or max_input_bytes < 1:
            raise ValueError("Invalid embedding limits")
        self.model, self.dimensions, self.base_url = (
            model,
            dimensions,
            base_url.rstrip("/"),
        )
        self._api_key, self._client = api_key, client
        self.timeout_seconds, self.max_input_bytes = timeout_seconds, max_input_bytes
        self.usd_per_million_tokens = usd_per_million_tokens

    def _validate_texts(self, texts):
        if any(
            not isinstance(text, str)
            or not text.strip()
            or count_tokens(text) > self.max_input_bytes
            for text in texts
        ):
            raise ValueError(
                "Embedding requires nonempty strings within the explicit length limit"
            )

    async def embed_documents(
        self, texts: list[str], *, budget: BudgetLedger | None = None
    ) -> list[list[float]]:
        self._validate_texts(texts)
        vectors = []
        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=False
        )
        try:
            for start in range(0, len(texts), 10):
                batch = texts[start : start + 10]
                estimated = sum(count_tokens(text) for text in batch)
                if budget:
                    cost = (
                        estimated * self.usd_per_million_tokens / 1_000_000
                        if self.usd_per_million_tokens is not None
                        else None
                    )
                    budget.reserve(
                        "embedding", input_tokens=estimated, estimated_cost_usd=cost
                    )
                response = await client.post(
                    self.base_url + "/embeddings",
                    headers={"Authorization": "Bearer " + self._api_key},
                    json={
                        "model": self.model,
                        "input": batch,
                        "dimensions": self.dimensions,
                        "encoding_format": "float",
                    },
                    timeout=min(self.timeout_seconds, budget.remaining_seconds)
                    if budget
                    else self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                items = sorted(payload["data"], key=lambda item: item["index"])
                if [item["index"] for item in items] != list(range(len(batch))):
                    raise ValueError("Embedding result count/indices mismatch")
                for item in items:
                    vector = item["embedding"]
                    if len(vector) != self.dimensions or any(
                        isinstance(v, bool)
                        or not isinstance(v, (int, float))
                        or not math.isfinite(v)
                        for v in vector
                    ):
                        raise ValueError("Embedding result dimension/value mismatch")
                    vectors.append([float(v) for v in vector])
                if budget:
                    budget.record_output(
                        0,
                        embedding_tokens=int(
                            payload.get("usage", {}).get("total_tokens", estimated)
                        ),
                    )
            return vectors
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            raise RetrievalUnavailable(
                "Embedding provider failed",
                details={"provider_error": type(exc).__name__},
            ) from exc
        finally:
            if owned_client:
                await client.aclose()

    async def embed_query(
        self, text: str, *, budget: BudgetLedger | None = None
    ) -> list[float]:
        return (await self.embed_documents([text], budget=budget))[0]
