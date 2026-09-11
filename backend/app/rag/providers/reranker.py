"""Optional pinned-model rerank service adapters; no model downloads on import.

The authorized service must implement the common /rerank JSON API with `results`
entries containing index and relevance_score. BGE and Qwen model names are explicit;
weights/runtime/licenses must be provisioned and reviewed by the operator.
"""

from __future__ import annotations

import asyncio
import logging
import math
from urllib.parse import urlsplit

import httpx

from app.core.errors import AppError
from app.rag.budget import count_tokens
from app.rag.contracts import RerankerConfig, RetrievalResult
from app.rag.errors import (
    BudgetExceeded,
    ProviderRateLimited,
    ProviderTimeout,
    RerankerTimeout,
    RetrievalUnavailable,
    SourceUnavailable,
)

logger = logging.getLogger(__name__)


class RemoteReranker:
    def __init__(
        self,
        config: RerankerConfig,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        estimated_call_cost_usd: float | None = None,
    ):
        if (
            config.provider not in ("bge-v2-m3", "qwen3-reranker-0.6b")
            or not config.endpoint
        ):
            raise ValueError("An explicitly configured reranker endpoint is required")
        target = urlsplit(config.endpoint)
        if (
            target.scheme not in ("http", "https")
            or not target.hostname
            or target.username
            or target.password
        ):
            raise ValueError("Invalid reranker endpoint")
        if target.scheme == "http" and target.hostname not in (
            "localhost",
            "127.0.0.1",
            "::1",
        ):
            raise ValueError("Remote reranker endpoint requires HTTPS")
        self.config, self._api_key, self._client = config, api_key, client
        self.estimated_call_cost_usd = estimated_call_cost_usd

    async def __call__(self, query, evidence):
        models = {
            "bge-v2-m3": "BAAI/bge-reranker-v2-m3",
            "qwen3-reranker-0.6b": "Qwen/Qwen3-Reranker-0.6B",
        }
        owned = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.config.timeout_seconds, follow_redirects=False
        )
        try:
            headers = (
                {"Authorization": "Bearer " + self._api_key} if self._api_key else {}
            )
            response = await client.post(
                self.config.endpoint,
                headers=headers,
                json={
                    "model": models[self.config.provider],
                    "query": query,
                    "documents": [e.excerpt for e in evidence],
                    "top_n": len(evidence),
                },
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
            results = response.json()["results"]
            if len(results) != len(evidence) or {x["index"] for x in results} != set(
                range(len(evidence))
            ):
                raise ValueError(
                    "Reranker result is not a complete candidate permutation"
                )
            scores = [
                (entry["index"], float(entry["relevance_score"])) for entry in results
            ]
            if any(not math.isfinite(score) for _, score in scores):
                raise ValueError("Reranker scores are not finite")
            return [
                evidence[index].model_copy(
                    update={
                        "score": score,
                        "retrieval_scores": {
                            **evidence[index].retrieval_scores,
                            "reranker": score,
                        },
                    }
                )
                for index, score in sorted(
                    scores, key=lambda item: (-item[1], evidence[item[0]].evidence_id)
                )
            ]
        finally:
            if owned:
                await client.aclose()


async def rerank(
    query, evidence, config: RerankerConfig, *, provider=None, budget=None, limit=8
) -> RetrievalResult:
    if len(evidence) > 40:
        raise ValueError("Reranker candidate limit exceeded")
    effective = {
        "requested_provider": config.provider,
        "effective_provider": config.provider,
        "model_revision": config.model_revision,
        "license": config.license,
    }
    if config.llm is not None:
        effective.update(
            llm=config.llm.model_dump(mode="json"), score_kind="reciprocal_rank"
        )
    if config.provider == "none" or not evidence:
        effective["effective_provider"] = "none"
        return RetrievalResult(
            evidence=evidence[:limit], candidates=evidence, effective_config=effective
        )
    if budget and config.provider != "llm":
        budget.reserve(
            "reranker",
            input_tokens=count_tokens(query)
            + sum(count_tokens(e.excerpt) for e in evidence),
            estimated_cost_usd=getattr(provider, "estimated_call_cost_usd", None),
        )
    wait_deadline = None
    budget_limited = False
    try:
        if provider is None:
            raise RetrievalUnavailable("Reranker provider is not configured")
        timeout = config.timeout_seconds
        if budget:
            remaining = budget.remaining_seconds
            budget_limited = remaining <= timeout
            timeout = min(timeout, remaining)
        if config.provider == "llm":
            if getattr(getattr(provider, "config", None), "llm", None) != config.llm:
                raise RetrievalUnavailable("Chat reranker configuration has changed")
            operation = provider(query, evidence, budget=budget)
        else:
            operation = provider(query, evidence)
        # Track this deadline separately from a provider-raised TimeoutError.
        async with asyncio.timeout(timeout) as wait_deadline:
            ranked = await operation
        if {e.evidence_id for e in ranked} != {e.evidence_id for e in evidence} or len(
            ranked
        ) != len(evidence):
            raise ValueError("Reranker changed candidate identities")
        originals = {e.evidence_id: e for e in evidence}
        for item in ranked:
            original = originals[item.evidence_id]
            if item.model_dump(
                exclude={"score", "retrieval_scores"}
            ) != original.model_dump(exclude={"score", "retrieval_scores"}):
                raise ValueError("Reranker altered source evidence")
        return RetrievalResult(
            evidence=ranked[:limit], candidates=ranked, effective_config=effective
        )
    except (BudgetExceeded, SourceUnavailable, AppError):
        raise
    except Exception as exc:
        if budget:
            # An expired execution cannot be reported as successful RRF fallback.
            budget.check()
        if (
            isinstance(exc, (ProviderTimeout, ProviderRateLimited))
            and not config.allow_rrf_fallback
        ):
            raise
        timed_out = wait_deadline is not None and wait_deadline.expired()
        if timed_out and budget_limited:
            # Timer resolution may precede the budget clock observing expiry.
            raise BudgetExceeded("Execution deadline exceeded") from exc
        failure = RerankerTimeout if timed_out else RetrievalUnavailable
        logger.warning(
            "Reranker failed provider=%s code=%s error_type=%s",
            config.provider,
            failure.code,
            type(exc).__name__,
        )
        if not config.allow_rrf_fallback:
            message = (
                "Configured reranker exceeded its wait limit"
                if timed_out
                else "Configured reranker is unavailable"
            )
            raise failure(message) from exc
        effective["effective_provider"] = "none"
        return RetrievalResult(
            evidence=evidence[:limit],
            candidates=evidence,
            effective_config=effective,
            warnings=["reranker_unavailable_rrf_fallback"],
        )
