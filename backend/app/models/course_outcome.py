"""Public course goals and their evidence-backed, conservative projection."""

from typing import Literal

from pydantic import Field

from app.rag.contracts import Contract

EvidenceType = Literal["recognition", "recall", "application", "explanation", "creation"]
OutcomeStatus = Literal["unverified", "needs_practice", "verified", "stale"]


class CourseCriterion(Contract):
    course_criterion_id: str
    course_criterion_ref: str
    criteria_revision: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=1000)
    evidence_type: EvidenceType
    expectation: str = Field(min_length=1, max_length=1500)
    lesson_ids: list[str] = Field(default_factory=list)
    origin: Literal["generated_v2", "legacy_unmapped"]


class CourseEvidenceRef(Contract):
    origin_kind: Literal["quiz", "practice", "course_application", "self_check"]
    origin_id: str
    attempt_id: str | None = None
    assessment_id: str | None = None
    question_version: str | None = None
    lesson_id: str | None = None
    content_version: int | None = None
    occurred_at: str


class CourseCriterionOutcome(Contract):
    course_criterion_id: str
    criteria_revision: int
    title: str
    status: OutcomeStatus
    reason: str
    evidence_refs: list[CourseEvidenceRef] = Field(default_factory=list)


class CourseOutcomeSummary(Contract):
    course_id: str
    criteria_revision: int
    criteria: list[CourseCriterionOutcome] = Field(default_factory=list)
