"""Per-execution admission ledger, including failed external attempts."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from app.rag.contracts import BudgetLimits, Usage
from app.rag.errors import BudgetExceeded


def count_tokens(text: str) -> int:
    """Offline conservative token upper bound; never labeled as observed billing.

    UTF-8 byte count bounds byte-level model tokenization, handles Chinese/emoji,
    and avoids a hidden tokenizer vocabulary download in an offline deployment.
    Provider usage replaces estimates for accounting when returned.
    """
    return len(text.encode("utf-8"))


class BudgetLedger:
    def __init__(
        self, limits: BudgetLimits, *, clock: Callable[[], float] = time.monotonic
    ):
        self.limits = limits
        self.usage = Usage()
        self._clock = clock
        self._deadline = clock() + limits.deadline_seconds
        self._reserved_cost = 0.0
        self._lock = threading.RLock()

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self._deadline - self._clock())

    def check(self) -> None:
        if self.remaining_seconds <= 0:
            raise BudgetExceeded("Execution deadline exceeded")

    def reserve(
        self,
        kind: str,
        *,
        input_tokens: int = 0,
        estimated_cost_usd: float | None = None,
    ) -> None:
        field = {
            "llm": "llm_calls",
            "embedding": "embedding_calls",
            "reranker": "reranker_calls",
            "search": "search_calls",
            "fetch": "fetch_calls",
        }.get(kind)
        if (
            field is None
            or input_tokens < 0
            or (estimated_cost_usd is not None and estimated_cost_usd < 0)
        ):
            raise ValueError("Invalid budget reservation")
        with self._lock:
            self.check()
            if getattr(self.usage, field) >= getattr(self.limits, "max_" + field):
                raise BudgetExceeded(
                    "External call limit reached", details={"resource": kind}
                )
            if self.usage.input_tokens + input_tokens > self.limits.max_input_tokens:
                raise BudgetExceeded("Input token limit reached")
            if self.limits.max_cost_usd is not None:
                if estimated_cost_usd is None:
                    raise BudgetExceeded(
                        "Configured monetary cap requires a provider cost estimate"
                    )
                if self._reserved_cost + estimated_cost_usd > self.limits.max_cost_usd:
                    raise BudgetExceeded("Monetary budget exhausted")
            setattr(self.usage, field, getattr(self.usage, field) + 1)
            self.usage.input_tokens += input_tokens
            self._reserved_cost += estimated_cost_usd or 0.0
            if estimated_cost_usd is not None:
                self.usage.cost_usd = self._reserved_cost
                self.usage.cost_status = "estimated"

    def record_output(self, output_tokens: int, *, embedding_tokens: int = 0) -> None:
        with self._lock:
            self.usage.output_tokens += max(0, output_tokens)
            self.usage.embedding_tokens += max(0, embedding_tokens)
            if self.usage.output_tokens > self.limits.max_output_tokens:
                raise BudgetExceeded("Output token limit exceeded")
            self.check()

    def reserve_llm_reranker(
        self, *, input_tokens: int, estimated_cost_usd: float | None = None
    ) -> None:
        """One admission uses both quotas, with one token/cost reservation."""
        with self._lock:
            self.check()
            if self.usage.reranker_calls >= self.limits.max_reranker_calls:
                raise BudgetExceeded(
                    "External call limit reached", details={"resource": "reranker"}
                )
            self.reserve(
                "llm", input_tokens=input_tokens, estimated_cost_usd=estimated_cost_usd
            )
            self.usage.reranker_calls += 1

    def snapshot(self) -> Usage:
        with self._lock:
            return self.usage.model_copy(deep=True)
