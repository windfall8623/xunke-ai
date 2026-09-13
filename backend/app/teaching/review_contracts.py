"""Private proposals and host-bound reports. These never grade a learner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, TypedDict

from pydantic import Field, model_validator

from app.models.course import CourseCreate
from app.rag.contracts import Contract
from app.rag.graph_trace import SummarySink
from app.teaching.context import TeachingMaterial
from app.teaching.contracts import TeachUnit
from app.teaching.contracts_v2 import CourseCriterionDraft, TeachUnitV2
from app.teaching.generator import GeneratedTeachingArtifact

ReviewDimension = Literal["goal_alignment", "prerequisite_order", "example_correctness", "check_fit", "source_support", "answer_leakage"]
FindingCode = Literal["goal_mismatch", "unsupported_prerequisite", "wrong_worked_example", "misleading_check", "unsupported_core_claim", "contradictory_core_claim", "answer_leaked", "terminology_dense", "example_too_abstract"]
REVIEW_DIMENSIONS = frozenset({"goal_alignment", "prerequisite_order", "example_correctness", "check_fit", "source_support", "answer_leakage"})
BLOCKING_DIMENSIONS = {
    "goal_mismatch": "goal_alignment", "unsupported_prerequisite": "prerequisite_order",
    "wrong_worked_example": "example_correctness", "misleading_check": "check_fit",
    "unsupported_core_claim": "source_support", "contradictory_core_claim": "source_support",
    "answer_leaked": "answer_leakage",
}


class ReviewFinding(Contract):
    code: FindingCode
    dimension: ReviewDimension
    severity: Literal["blocking", "suggestion"]
    course_criterion_refs: list[str] = Field(default_factory=list, max_length=3)
    block_refs: list[str] = Field(default_factory=list, max_length=5)
    check_refs: list[str] = Field(default_factory=list, max_length=5)
    source_refs: list[str] = Field(default_factory=list, max_length=4)
    explanation: str = Field(min_length=1, max_length=300)
    suggestion: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def severity_matches_code(self):
        expected = BLOCKING_DIMENSIONS.get(self.code)
        if expected and (self.severity != "blocking" or self.dimension != expected):
            raise ValueError("review_finding_inconsistent")
        if not expected and self.severity != "suggestion":
            raise ValueError("review_finding_inconsistent")
        return self


class ReviewDimensionResult(Contract):
    dimension: ReviewDimension
    result: Literal["pass", "fail", "not_applicable"]


class ReviewProposal(Contract):
    dimensions: list[ReviewDimensionResult] = Field(min_length=6, max_length=6)
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def complete_and_consistent(self):
        by_dimension = {item.dimension: item.result for item in self.dimensions}
        if set(by_dimension) != REVIEW_DIMENSIONS:
            raise ValueError("review_dimensions_incomplete")
        blocked = {finding.dimension for finding in self.findings if finding.severity == "blocking"}
        failed = {dimension for dimension, result in by_dimension.items() if result == "fail"}
        if blocked != failed:
            raise ValueError("review_findings_incomplete")
        return self

    @property
    def status(self):
        return "needs_revision" if any(item.severity == "blocking" for item in self.findings) else "passed"


class TeachingReviewReport(Contract):
    schema_version: Literal["xunke-teaching-review.v1"] = "xunke-teaching-review.v1"
    draft_hash: str
    plan_hash: str | None
    skill_hash: str
    scope_fingerprint: str
    criteria_revision: int | None
    policy_hash: str
    reviewer_prompt_version: str
    status: Literal["passed", "needs_revision", "unreviewed"]
    proposal: ReviewProposal | None
    reason_code: str | None = None

    @model_validator(mode="after")
    def status_follows_proposal(self):
        if (self.status == "unreviewed") != (self.proposal is None):
            raise ValueError("review_report_inconsistent")
        if self.proposal is not None and self.status != self.proposal.status:
            raise ValueError("review_report_inconsistent")
        return self


@dataclass(frozen=True)
class TeachingAgentInput:
    kind: Literal["outline", "lesson"]
    spec: CourseCreate
    unit: TeachUnit | TeachUnitV2 | None
    course_criteria: tuple[CourseCriterionDraft, ...]
    material: TeachingMaterial
    plan_hash: str | None
    criteria_revision: int | None
    scope_fingerprint: str
    generation_revision: int = 1
    feedback_codes: tuple[str, ...] = ()
    findings: tuple[ReviewFinding, ...] = ()
    frozen_plan: dict | None = None


class TeachingAgentState(TypedDict, total=False):
    request: TeachingAgentInput
    candidate: GeneratedTeachingArtifact | None
    deterministic_codes: tuple[str, ...]
    report: TeachingReviewReport | None
    generation_revision: int
    repair_used: bool
    review_calls_started: int
    known_blocking: bool
    next_node: str
    terminal_reason: str | None
    reason_code: str | None
    completed_slot: str | None
    trace: list[str]


@dataclass(frozen=True)
class TeachingAgentPorts:
    planner: Callable[..., Awaitable[GeneratedTeachingArtifact]]
    teacher: Callable[..., Awaitable[GeneratedTeachingArtifact]]
    reviewer: Callable[..., Awaitable[TeachingReviewReport]]
    authorize: Callable[..., Awaitable[None]]
    claim_stage: Callable[..., Awaitable[None]]
    checkpoint: Callable[..., Awaitable[None]]
    heartbeat: Callable[..., Awaitable[None]]
    record_summary: SummarySink | None = None


def require_review_binding(report, candidate, request, *, skill_hash, policy_hash):
    expected = (candidate["draft_hash"], request.plan_hash, skill_hash, request.criteria_revision, request.scope_fingerprint, policy_hash)
    actual = (report.draft_hash, report.plan_hash, report.skill_hash, report.criteria_revision, report.scope_fingerprint, report.policy_hash)
    if actual != expected:
        raise ValueError("teaching_review_binding_mismatch")
