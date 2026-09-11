"""Public practice DTOs use explicit projections, never private artifact shapes."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.learning.contracts import (
    AssessmentDraft,
    AssessmentStatus,
    ConceptIds,
    Confirmation,
    HelpUsage,
    LearningId,
    Score,
)
from app.models.sources import PublicResolvedScope
from app.practice.contracts import (
    Difficulty,
    EvidenceRefs,
    PracticeQuestion,
    QuestionTypes,
    RequestedDifficulty,
    TypedAnswer,
)
from app.rag.contracts import Contract, Hash, Identity

TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
PracticeStatus = Literal["generating", "ready", "completed", "failed", "cancelled"]
ProjectionStatus = Literal["not_ready", "pending", "applied", "failed"]
Revision = Annotated[int, Field(ge=1)]


class PracticeAnswerBody(Contract):
    answer: TypedAnswer
    duration_ms: int = Field(ge=0, le=86400000)


class PracticeCompleteBody(Contract):
    expected_revision: Revision


class PracticeHelpView(Contract):
    practice_id: LearningId
    question_id: LearningId
    help_usage: Literal["hints"] = "hints"
    evidence_ids: EvidenceRefs


class PublicQuestionBase(Contract):
    id: LearningId
    question_version: Hash
    stem: str = Field(min_length=1)
    difficulty: Difficulty
    concept_ids: ConceptIds
    citation_refs: list[Identity] = Field(min_length=1, max_length=10)


class PublicClozeQuestion(PublicQuestionBase):
    type: Literal["cloze"] = "cloze"
    blank_ids: list[LearningId] = Field(min_length=1, max_length=5)


class PublicNumericQuestion(PublicQuestionBase):
    type: Literal["numeric"] = "numeric"
    unit: str = Field(max_length=32)


class PublicShortAnswerQuestion(PublicQuestionBase):
    type: Literal["short_answer"] = "short_answer"


PublicPracticeQuestion = Annotated[
    PublicClozeQuestion | PublicNumericQuestion | PublicShortAnswerQuestion,
    Field(discriminator="type"),
]


def public_question(
    question: PracticeQuestion, question_version: str
) -> PublicPracticeQuestion:
    """Only the fields needed to answer an unsubmitted question cross HTTP."""
    common = {
        "id": question.id,
        "question_version": question_version,
        "type": question.type,
        "stem": question.stem,
        "difficulty": question.difficulty,
        "concept_ids": list(question.concept_ids),
        "citation_refs": list(question.citation_refs),
    }
    if question.type == "cloze":
        return PublicClozeQuestion(
            **common, blank_ids=[slot.blank_id for slot in question.rubric.slots]
        )
    if question.type == "numeric":
        return PublicNumericQuestion(**common, unit=question.rubric.unit)
    return PublicShortAnswerQuestion(**common)


class PracticeSubmissionReceipt(Contract):
    """The original response to a submission; current grading is queried separately."""

    practice_id: LearningId
    question_id: LearningId
    attempt_id: LearningId
    accepted_revision: Revision
    grading_request_id: LearningId | None = None
    task_id: LearningId | None = None
    assessment_id: LearningId | None = None

    @model_validator(mode="after")
    def async_identity_is_complete(self):
        if (self.grading_request_id is None) != (self.task_id is None):
            raise ValueError(
                "Async receipts require both the logical grading request and original task"
            )
        return self


class PracticeCompletionReceipt(Contract):
    practice_id: LearningId
    completion_id: LearningId
    accepted_revision: Revision
    answer_set_hash: Hash
    attempt_ids: list[LearningId] = Field(min_length=1, max_length=10)
    completed_at: AwareDatetime

    @field_validator("attempt_ids")
    @classmethod
    def distinct_attempts(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Completion attempt IDs must be unique")
        return values


class PracticeCriterionResultView(Contract):
    criterion_id: LearningId
    credit: Literal["full", "half", "none", "uncertain"]
    rationale: str = Field(default="", max_length=4000)
    evidence_refs: EvidenceRefs = Field(default_factory=list)
    answer_quotes: list[str] = Field(default_factory=list)


class PracticeAssessmentView(Contract):
    assessment_id: LearningId
    attempt_id: LearningId
    revision: Revision
    status: AssessmentStatus
    score: Score | None = None
    source: Literal["deterministic", "model", "human"]
    confirmation: Confirmation
    feedback: str = Field(default="", max_length=12000)
    evidence_refs: EvidenceRefs = Field(default_factory=list)
    criterion_results: list[PracticeCriterionResultView] = Field(default_factory=list)
    supersedes_assessment_id: LearningId | None = None
    independent_eligible: bool = False
    created_at: AwareDatetime | None = None

    @field_serializer("score", when_used="json")
    def exact_score(self, value: Decimal | None) -> str | None:
        if value is None:
            return None
        if value == 0:
            return "0"
        if value == 1:
            return "1"
        return str(value)

    @model_validator(mode="after")
    def consistent_grading_state(self):
        if self.status == "graded":
            if self.score is None:
                raise ValueError("A graded result requires a score")
        elif self.score is not None or self.confirmation != "provisional":
            raise ValueError("An ungraded result must have no score and be provisional")
        confirmed_grade = self.status == "graded" and self.confirmation == "confirmed"
        if self.independent_eligible and not confirmed_grade:
            raise ValueError("Independent evidence requires a confirmed graded result")
        if self.source == "deterministic" and not confirmed_grade:
            raise ValueError("Deterministic grading requires a confirmed graded result")
        return self


def public_assessment(
    assessment: AssessmentDraft,
    *,
    assessment_id: str,
    attempt_id: str,
    revision: int,
    created_at: AwareDatetime | None = None,
) -> PracticeAssessmentView:
    """Project one stored assessment after the owner has submitted this question."""
    criteria = [
        PracticeCriterionResultView(
            criterion_id=item["criterion_id"],
            credit=item["credit"],
            rationale=item.get("rationale", ""),
            evidence_refs=list(item.get("evidence_refs", [])),
            answer_quotes=list(item.get("answer_quotes", [])),
        )
        for item in assessment.criterion_results
    ]
    return PracticeAssessmentView(
        assessment_id=assessment_id,
        attempt_id=attempt_id,
        revision=revision,
        status=assessment.status,
        score=assessment.score,
        source=assessment.source,
        confirmation=assessment.confirmation,
        feedback=assessment.feedback,
        evidence_refs=list(assessment.evidence_refs),
        criterion_results=criteria,
        supersedes_assessment_id=assessment.supersedes_assessment_id,
        independent_eligible=assessment.independent_eligible,
        created_at=created_at,
    )


class PracticeSelfReviewView(Contract):
    annotation_id: LearningId
    self_rating: Literal["understood", "needs_practice", "unsure"]
    notes: str = Field(default="", max_length=1000)
    independent_eligible: Literal[False] = False
    created_at: AwareDatetime


class PracticeAttemptView(Contract):
    practice_id: LearningId
    question_id: LearningId
    attempt_id: LearningId
    question_version: Hash
    answer: TypedAnswer
    duration_ms: int = Field(ge=0, le=86400000)
    help_usage: HelpUsage
    receipt: PracticeSubmissionReceipt
    current_assessment: PracticeAssessmentView | None = None
    assessment_history: list[PracticeAssessmentView] = Field(default_factory=list)
    self_reviews: list[PracticeSelfReviewView] = Field(default_factory=list)
    grading_status: TaskStatus | None = None
    active_task_id: LearningId | None = None
    grading_revision: int = Field(default=0, ge=0)
    created_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def one_immutable_attempt(self):
        if (
            self.receipt.practice_id != self.practice_id
            or self.receipt.question_id != self.question_id
            or self.receipt.attempt_id != self.attempt_id
        ):
            raise ValueError("Attempt and receipt identities must agree")
        assessments = list(self.assessment_history)
        if self.current_assessment is not None:
            assessments.append(self.current_assessment)
        for assessment in assessments:
            if assessment.attempt_id != self.attempt_id:
                raise ValueError("Assessment must belong to this immutable attempt")
            if assessment.independent_eligible and self.help_usage != "none":
                raise ValueError("Independent evidence requires known absence of help")
        return self


class PracticeView(Contract):
    practice_id: LearningId
    space_id: LearningId
    scope_revision: Revision
    title: str = Field(min_length=1)
    summary: str
    status: PracticeStatus
    revision: int = Field(ge=0)
    questions: list[PublicPracticeQuestion] = Field(default_factory=list, max_length=10)
    submissions: list[PracticeAttemptView] = Field(default_factory=list, max_length=10)
    submitted_count: int = Field(default=0, ge=0, le=10)
    confirmed_count: int = Field(default=0, ge=0, le=10)
    pending_grading_count: int = Field(default=0, ge=0, le=10)
    needs_review_count: int = Field(default=0, ge=0, le=10)
    completed_at: AwareDatetime | None = None
    projection_status: ProjectionStatus = "not_ready"
    completion: PracticeCompletionReceipt | None = None
    scope: PublicResolvedScope | None = None
    source_status: Literal["active", "revoked"] = "active"


class PracticeTaskView(Contract):
    task_id: LearningId
    practice_id: LearningId
    operation: Literal["generate", "grade"]
    status: TaskStatus
    stage: str = Field(default="queued", max_length=64)
    error_code: LearningId | None = None
    error_message: str | None = Field(default=None, max_length=2000)
    result: PracticeView | PracticeAttemptView | None = None
    queue_ms: int | None = Field(default=None, ge=0)
    execution_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def result_matches_operation(self):
        if self.result is not None:
            expected = (
                PracticeView if self.operation == "generate" else PracticeAttemptView
            )
            if not isinstance(self.result, expected):
                raise ValueError("Task operation must match its public result type")
        return self


class ReviewPracticeBody(Contract):
    """The service derives space, scope, objectives, concepts and review origin."""

    review_task_ids: list[LearningId] = Field(min_length=1, max_length=3)
    expected_revisions: dict[LearningId, Revision]
    question_types: QuestionTypes
    question_count: int = Field(default=5, ge=3, le=10)
    difficulty: RequestedDifficulty = "mixed"

    @model_validator(mode="after")
    def exact_occurrence_revisions(self):
        if len(self.review_task_ids) != len(set(self.review_task_ids)):
            raise ValueError("Review task IDs must be unique")
        if set(self.expected_revisions) != set(self.review_task_ids):
            raise ValueError(
                "Each selected review requires exactly one expected revision"
            )
        return self
