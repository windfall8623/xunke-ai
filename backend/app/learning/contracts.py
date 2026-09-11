"""Server-owned learning facts shared by objective quizzes and practice.

These contracts do not authorize resources. Services validate actual parent
ownership, immutable scope, and the current assessment head inside a transaction.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    AwareDatetime,
    Field,
    JsonValue,
    field_serializer,
    model_validator,
)

from app.qa.contracts import AnswerBlock
from app.rag.contracts import Contract, Hash, Identity, ResolvedScope

LearningId = Annotated[str, Field(min_length=1, max_length=64)]
OriginKind = Literal["quiz", "practice"]
AnswerKind = Literal["single", "multiple", "judge", "cloze", "numeric", "short_answer"]
AssessmentStatus = Literal["graded", "needs_review", "failed", "cancelled"]
Confirmation = Literal["confirmed", "provisional"]
HelpUsage = Literal["none", "hints", "unknown"]
Score = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Text cannot be blank")
    return value.strip()


LearningTitle = Annotated[
    str, Field(min_length=1, max_length=80), AfterValidator(_nonblank)
]
ObjectiveText = Annotated[
    str, Field(min_length=1, max_length=500), AfterValidator(_nonblank)
]


def _iana_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("A valid IANA timezone name is required") from exc
    return value


IanaTimezone = Annotated[
    str, Field(min_length=1, max_length=64), AfterValidator(_iana_timezone)
]


def _distinct(values: list) -> list:
    if len(values) != len(set(values)):
        raise ValueError("Duplicate identities are not allowed")
    return values


QuestionVersions = Annotated[list[Hash], AfterValidator(_distinct)]
ConceptIds = Annotated[
    list[LearningId], Field(min_length=1, max_length=3), AfterValidator(_distinct)
]


class ObjectiveRef(Contract):
    concept_id: LearningId
    title: ObjectiveText


def _distinct_objectives(values: list[ObjectiveRef]) -> list[ObjectiveRef]:
    _distinct([value.concept_id for value in values])
    return values


Objectives = Annotated[
    list[ObjectiveRef],
    Field(min_length=1, max_length=3),
    AfterValidator(_distinct_objectives),
]


class QuestionConceptBinding(Contract):
    question_id: LearningId
    question_version: Hash
    concept_ids: ConceptIds


class LearningAttemptDraft(Contract):
    origin_kind: OriginKind
    origin_id: LearningId
    question_id: LearningId
    question_version: Hash
    space_id: LearningId
    scope_revision: int = Field(ge=1)
    answer_kind: AnswerKind
    answer_json: dict[str, JsonValue]
    response_hash: Hash
    duration_ms: int = Field(ge=0, le=2147483647)
    help_usage: HelpUsage
    occurred_at: AwareDatetime


class AttemptRef(Contract):
    attempt_id: LearningId
    owner_id: int = Field(gt=0)
    origin_kind: OriginKind
    origin_id: LearningId
    question_id: LearningId


class _ScoredResult(Contract):
    status: AssessmentStatus
    score: Score | None = None
    confirmation: Confirmation
    independent_eligible: bool = False

    @field_serializer("score", when_used="json")
    def serialize_score(self, score: Decimal | None) -> str | None:
        # MySQL stores this exact text. Never round via normalize(), a Decimal
        # context or a SQL numeric cast, and never expand tiny exponents.
        if score is None:
            return None
        if score == 0:
            return "0"
        if score == 1:
            return "1"
        return str(score)

    @model_validator(mode="after")
    def valid_result(self):
        if self.status == "graded":
            if self.score is None:
                raise ValueError("A graded result requires a score")
        elif self.score is not None or self.confirmation != "provisional":
            raise ValueError("An ungraded result must have no score and be provisional")
        if self.independent_eligible and (
            self.status != "graded" or self.confirmation != "confirmed"
        ):
            raise ValueError("Independent evidence requires a confirmed graded result")
        return self


class AssessmentDraft(_ScoredResult):
    source: Literal["deterministic", "model", "human"]
    grader_version: LearningId
    rubric_version: LearningId
    rubric_hash: Hash
    feedback: str = Field(default="", max_length=12000)
    evidence_refs: Annotated[list[Identity], AfterValidator(_distinct)] = Field(
        default_factory=list
    )
    criterion_results: list[dict[str, JsonValue]] = Field(default_factory=list)
    supersedes_assessment_id: LearningId | None = None

    @model_validator(mode="after")
    def deterministic_results_are_confirmed(self):
        if self.source == "deterministic" and (
            self.status != "graded" or self.confirmation != "confirmed"
        ):
            raise ValueError("Deterministic grading requires a confirmed graded result")
        return self


class AssessmentRef(Contract):
    assessment_id: LearningId
    attempt_id: LearningId
    revision: int = Field(ge=1)
    status: AssessmentStatus
    confirmation: Confirmation

    @model_validator(mode="after")
    def ungraded_is_provisional(self):
        if self.status != "graded" and self.confirmation != "provisional":
            raise ValueError("An ungraded result cannot be confirmed")
        return self


class LearningCompletionRef(Contract):
    completion_id: LearningId
    origin_kind: OriginKind
    origin_id: LearningId
    answer_set_hash: Hash


class QaPracticeContext(Contract):
    owner_id: int = Field(gt=0)
    answer_id: LearningId
    session_id: LearningId
    scope_revision: int = Field(ge=1)
    artifact_hash: Hash
    scope: ResolvedScope
    retrieval_query: str = Field(min_length=1, max_length=2000)
    selected_fact_blocks: list[AnswerBlock] = Field(min_length=1, max_length=12)
    evidence_ids: Annotated[list[Identity], AfterValidator(_distinct)] = Field(
        min_length=1, max_length=40
    )

    @model_validator(mode="after")
    def same_owner_and_cited_facts(self):
        if self.owner_id != self.scope.owner_id or not self.scope.documents:
            raise ValueError(
                "Practice context requires the owner's nonempty source scope"
            )
        _distinct([block.block_id for block in self.selected_fact_blocks])
        for block in self.selected_fact_blocks:
            if block.kind != "fact" or not set(block.citation_refs) <= set(
                self.evidence_ids
            ):
                raise ValueError(
                    "Practice context requires selected, evidenced fact blocks"
                )
        return self


class ConceptState(Contract):
    stage: int = Field(default=0, ge=0, le=4)
    last_activity_local_date: date | None = None
    last_success_local_date: date | None = None
    last_question_versions: QuestionVersions = Field(default_factory=list)
    seen_question_versions: QuestionVersions = Field(default_factory=list)
    due_at: AwareDatetime | None = None
    revision: int = Field(default=0, ge=0)


class LearningOutcome(_ScoredResult):
    help_usage: HelpUsage
    question_versions: QuestionVersions = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def independent_help_is_known_absent(self):
        if self.independent_eligible and self.help_usage != "none":
            raise ValueError("Independent evidence requires known absence of help")
        return self


class ReviewDecision(Contract):
    stage: int = Field(ge=0, le=4)
    due_at: AwareDatetime | None
    reason: str = Field(min_length=1, max_length=80)
    advance: bool
