"""Small, private-text-free observations of the existing bounded graphs.

``course_teaching`` consumers use the registered teaching nodes and set
``generation_revision`` to the candidate revision (1 or 2). They share only this
summary contract with RAG; their durable stages and recovery remain their own.
SummarySink is synchronous and observational: use an in-memory collector or a
controlled local logger, never queries, provider calls, or business updates.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.rag.contracts import Contract, Usage
from app.rag.errors import RagError, RetrievalUnavailable


logger = logging.getLogger(__name__)

GraphName = Literal["rag_quiz", "course_teaching"]
GraphStatus = Literal["completed", "failed", "cancelled"]
GraphBranch = Literal[
    "next", "retry_retrieval", "retry_generation", "quality_repair", "stop"
]

GRAPH_STAGES = {
    "rag_quiz": frozenset({
        "prepare", "retrieve", "assemble", "generate", "validate", "finish",
    }),
    "course_teaching": frozenset({
        "planner", "teacher", "reviewer", "repair", "validate", "revalidate",
        "finish", "stop",
    }),
}
ERROR_CODES = frozenset({
    "budget_exceeded", "insufficient_evidence", "generation_validation_failed",
    "source_unavailable", "retrieval_unavailable", "provider_timeout",
    "provider_unavailable", "provider_rate_limited", "invalid_scope",
    "cancelled", "unexpected_error", "course_generation_invalid",
    "course_quality_unavailable", "course_quality_blocked", "material_gap",
    "source_revoked", "task_cancelled", "task_deadline_exceeded", "lease_lost",
    "criteria_revision_changed",
    "teaching_call_outcome_unknown", "teaching_policy_changed", "teaching_call_forbidden",
})
TERMINAL_REASONS = ERROR_CODES | {"completed"}
_ALL_STAGES = frozenset().union(*GRAPH_STAGES.values())
_USAGE_STAGES = _ALL_STAGES | {"retrieval", "generation", "semantic", "rerank", "total"}
_TOKEN_METHODS = frozenset({
    "provider-reported-or-utf8-upper-bound-v1", "provider-reported",
    "utf8-upper-bound-v1", "durable-provider-reported-v1",
    "synthetic-payload-utf8-upper-bound-v1", "unreported",
})


class GraphStageSummary(Contract):
    seq: int = Field(ge=1)
    stage: str = Field(min_length=1, max_length=40)
    status: GraphStatus
    retrieval_round: int = Field(default=0, ge=0, le=2)
    generation_attempt: int = Field(default=0, ge=0, le=2)
    generation_revision: int | None = Field(default=None, ge=1, le=2)
    duration_ms: int = Field(ge=0)
    llm_calls_delta: int = Field(ge=0, le=5)
    input_tokens_delta: int = Field(ge=0)
    output_tokens_delta: int = Field(ge=0)
    branch: GraphBranch | None = None
    error_code: str | None = None

    @field_validator("stage")
    @classmethod
    def registered_stage(cls, value: str) -> str:
        if value not in _ALL_STAGES:
            raise ValueError("Unregistered graph stage")
        return value

    @field_validator("error_code")
    @classmethod
    def fixed_error_code(cls, value: str | None) -> str | None:
        if value is not None and value not in ERROR_CODES:
            raise ValueError("Unregistered graph error code")
        return value


class GraphExecutionSummary(Contract):
    schema_version: Literal["xunke-graph-summary.v1"] = "xunke-graph-summary.v1"
    graph: GraphName
    run_id: str
    status: GraphStatus
    terminal_reason: str
    stages: list[GraphStageSummary] = Field(default_factory=list, max_length=24)
    usage: Usage

    @field_validator("terminal_reason")
    @classmethod
    def fixed_terminal_reason(cls, value: str) -> str:
        if value not in TERMINAL_REASONS:
            raise ValueError("Unregistered graph terminal reason")
        return value

    @field_validator("usage")
    @classmethod
    def safe_usage_metadata(cls, value: Usage) -> Usage:
        # Usage also accepts provider-defined strings outside this contract.
        # Preserve counts/cost uncertainty, but expose only known metadata.
        return value.model_copy(deep=True, update={
            "stage_ms": {
                name: duration for name, duration in value.stage_ms.items()
                if name in _USAGE_STAGES
            },
            "token_count_method": (
                value.token_count_method
                if value.token_count_method in _TOKEN_METHODS else "unreported"
            ),
        })

    @model_validator(mode="after")
    def stages_belong_to_graph(self):
        if any(stage.stage not in GRAPH_STAGES[self.graph] for stage in self.stages):
            raise ValueError("Stage is not registered for this graph")
        if [stage.seq for stage in self.stages] != list(range(1, len(self.stages) + 1)):
            raise ValueError("Graph stages must have consecutive sequence numbers")
        return self


SummarySink = Callable[[GraphExecutionSummary], None]


def terminal_reason_for(error: BaseException) -> str:
    """Use only domain codes; never copy exception messages or provider bodies."""
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    if isinstance(error, RagError):
        code = error.code.lower()
        if code in ERROR_CODES:
            return code
        if isinstance(error, RetrievalUnavailable):
            return "retrieval_unavailable"
    return "unexpected_error"


def emit_summary(sink: SummarySink | None, summary: GraphExecutionSummary) -> None:
    if sink is None:
        return
    try:
        sink(summary)
    except Exception:
        logger.warning("graph_summary_sink_failed")


@dataclass(frozen=True)
class _StartedStage:
    stage: str
    started: float
    counts: tuple[int, int, int]
    retrieval_round: int
    generation_attempt: int
    generation_revision: int | None


def _counts(usage: Usage) -> tuple[int, int, int]:
    return usage.llm_calls, usage.input_tokens, usage.output_tokens


class GraphSummaryRecorder:
    """One item per executed node visit, including a failed/cancelled visit."""

    def __init__(
        self, graph: GraphName, run_id: str, *, clock: Callable[[], float] = time.monotonic
    ):
        if graph not in GRAPH_STAGES:
            raise ValueError("Unregistered graph")
        self.graph = graph
        self.run_id = run_id
        self._clock = clock
        self._active: _StartedStage | None = None
        self._stages: list[GraphStageSummary] = []

    def begin(
        self, stage: str, usage_before: Usage, *, retrieval_round: int = 0,
        generation_attempt: int = 0, generation_revision: int | None = None,
    ) -> None:
        if stage not in GRAPH_STAGES[self.graph]:
            raise ValueError("Stage is not registered for this graph")
        if self._active is not None or len(self._stages) >= 24:
            raise ValueError("Graph summary stage boundary is invalid")
        self._active = _StartedStage(
            stage, self._clock(), _counts(usage_before), retrieval_round,
            generation_attempt, generation_revision,
        )

    def end(
        self, stage: str, usage_after: Usage, *, status: GraphStatus = "completed",
        branch: GraphBranch | None = None, error_code: str | None = None,
        retrieval_round: int | None = None, generation_attempt: int | None = None,
        generation_revision: int | None = None,
    ) -> None:
        active = self._active
        if active is None or active.stage != stage:
            raise ValueError("Graph summary stage boundary is invalid")
        delta = tuple(after - before for before, after in zip(
            active.counts, _counts(usage_after)
        ))
        if any(value < 0 for value in delta):
            logger.warning("graph_summary_usage_decreased")
        self._stages.append(GraphStageSummary(
            seq=len(self._stages) + 1, stage=stage, status=status,
            retrieval_round=(
                active.retrieval_round if retrieval_round is None else retrieval_round
            ),
            generation_attempt=(
                active.generation_attempt
                if generation_attempt is None else generation_attempt
            ),
            generation_revision=(
                active.generation_revision
                if generation_revision is None else generation_revision
            ),
            duration_ms=max(0, int((self._clock() - active.started) * 1000)),
            llm_calls_delta=max(0, delta[0]), input_tokens_delta=max(0, delta[1]),
            output_tokens_delta=max(0, delta[2]), branch=branch, error_code=error_code,
        ))
        self._active = None

    def finish(
        self, *, status: GraphStatus, terminal_reason: str, usage: Usage,
    ) -> GraphExecutionSummary:
        if self._active is not None:
            if status == "completed":
                raise ValueError("Completed graph has an unfinished stage")
            # Cancellation may arrive between a node and its conditional edge.
            self.end(
                self._active.stage, usage, status=status, branch="stop",
                error_code=terminal_reason,
            )
        return GraphExecutionSummary(
            graph=self.graph, run_id=self.run_id, status=status,
            terminal_reason=terminal_reason,
            stages=[stage.model_copy(deep=True) for stage in self._stages], usage=usage,
        )
