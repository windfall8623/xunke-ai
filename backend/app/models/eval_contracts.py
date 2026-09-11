"""Neutral dataset exchange schemas; semantic/source validation lives in rag_eval."""

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.learning.contracts import AssessmentStatus
from app.practice.contracts import (
    PracticeQuestion,
    PracticeSpec,
    QuestionType,
    TypedAnswer,
)
from app.rag.contracts import Hash


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = "1"
    dataset_id: str | None = None
    version: int = Field(default=1, ge=1)
    state: Literal["draft", "reviewed", "frozen", "revoked"] = "draft"
    annotation_version: str = "v1"
    sources: list[dict] = Field(default_factory=list)
    review: dict = Field(default_factory=dict)


class SampleBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = "1"
    sample_id: str = Field(min_length=1, max_length=128)
    split: Literal["dev", "judge_calibration", "locked_test"]
    source_refs: list[dict] = Field(default_factory=list, max_length=5)
    family_ids: list[str] = Field(default_factory=list)
    annotation: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class RetrievalSample(SampleBase):
    case_type: Literal["retrieval"] = "retrieval"
    query: str = Field(min_length=1)
    gold_evidence_groups: list[dict] = Field(default_factory=list)


class QuizSample(SampleBase):
    case_type: Literal["quiz"] = "quiz"
    user_input: str = Field(min_length=1)
    question_count: int = Field(ge=3, le=10)
    expected_outcome: Literal["generate", "refuse"]
    source_policy: Literal["topic", "strict_docs", "doc_plus_web"] = "strict_docs"
    gold_evidence_groups: list[dict] = Field(default_factory=list)


class QaHistoryTurn(BaseModel):
    """A complete pair in this sample's source scope, bound by the eval runner.

    Dataset authors cannot provide an arbitrary runtime scope fingerprint. A new
    sample/source scope is required for history from a different document set.
    """

    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=16000)

    @field_validator("question", "answer")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("QA history requires a complete nonblank pair")
        return value


class QaSample(SampleBase):
    case_type: Literal["qa"] = "qa"
    source_refs: list[dict] = Field(min_length=1, max_length=5)
    question: str = Field(min_length=1, max_length=2000)
    history: list[QaHistoryTurn] = Field(default_factory=list, max_length=6)
    expected_answer_status: (
        Literal[
            "answered",
            "partial",
            "needs_clarification",
            "insufficient_evidence",
            "conflicting_sources",
        ]
        | None
    ) = None
    expected_error_code: str | None = Field(default=None, min_length=1, max_length=128)
    gold_evidence_groups: list[dict] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value):
        if not value.strip():
            raise ValueError("QA question cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def valid_history_and_expectation(self):
        if (
            sum(
                len(turn.question.encode("utf-8"))
                + len(turn.answer.encode("utf-8"))
                + 64
                for turn in self.history
            )
            > 8000
        ):
            raise ValueError("QA evaluation history exceeds 8000 UTF-8 bytes")
        if (self.expected_answer_status is None) != bool(self.expected_error_code):
            raise ValueError("QA expects either an answer status or a technical error")
        if self.expected_error_code and not self.expected_error_code.strip():
            raise ValueError("QA expected error code cannot be blank")
        return self


class PolicySample(SampleBase):
    case_type: Literal["policy"] = "policy"
    harness: dict


GenerationCriterion = Literal[
    "answer_correctness",
    "source_support",
    "solvability",
    "explanation_correctness",
    "scope_compliance",
    "citation_support",
    "citation_completeness",
]
GENERATION_CRITERIA = [
    "answer_correctness",
    "source_support",
    "solvability",
    "explanation_correctness",
    "scope_compliance",
    "citation_support",
    "citation_completeness",
]


class PracticeGenerationRubric(BaseModel):
    """Review instructions, never a model's claim that review has passed."""

    model_config = ConfigDict(extra="forbid")
    version: Literal["practice-generation-rubric.v1"] = "practice-generation-rubric.v1"
    required_semantics: list[GenerationCriterion] = Field(
        default_factory=lambda: list(GENERATION_CRITERIA), min_length=7, max_length=7
    )
    notes: str = Field(default="", max_length=4000)

    @field_validator("required_semantics")
    @classmethod
    def complete_criteria(cls, value):
        if set(value) != set(GENERATION_CRITERIA):
            raise ValueError("Generation review requires all seven distinct criteria")
        return value


class PracticeGenerationSample(SampleBase):
    case_type: Literal["practice_generation"] = "practice_generation"
    source_refs: list[dict] = Field(min_length=1, max_length=5)
    spec: PracticeSpec
    expected_outcome: Literal["generate", "refuse", "failed"]
    expected_error_code: str | None = Field(default=None, min_length=1, max_length=128)
    gold_evidence_groups: list[dict] = Field(default_factory=list)
    generation_rubric: PracticeGenerationRubric = Field(
        default_factory=PracticeGenerationRubric
    )

    @model_validator(mode="after")
    def valid_expectation(self):
        if self.expected_outcome == "generate" and self.expected_error_code:
            raise ValueError("Successful generation cannot expect a technical error")
        if self.expected_outcome == "failed" and not self.expected_error_code:
            raise ValueError("Failed generation requires an expected error code")
        if (
            self.expected_error_code is not None
            and not self.expected_error_code.strip()
        ):
            raise ValueError("Expected error code cannot be blank")
        return self


class ReferenceGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: AssessmentStatus
    score: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$",
    )
    provenance: Literal["synthetic_fixture", "human"]

    @field_validator("score", mode="before")
    @classmethod
    def finite_decimal_string(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("Reference scores require a decimal string or null")
        try:
            score = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Reference score must be a finite decimal") from exc
        if not score.is_finite() or not 0 <= score <= 1:
            raise ValueError("Reference score must be between zero and one")
        return value

    @model_validator(mode="after")
    def unresolved_score_is_missing(self):
        if self.status != "graded" and self.score is not None:
            raise ValueError("An unresolved reference grade cannot carry a score")
        return self


class AnswerGradingSample(SampleBase):
    case_type: Literal["answer_grading"] = "answer_grading"
    source_refs: list[dict] = Field(min_length=1, max_length=5)
    question: PracticeQuestion
    question_type: QuestionType
    question_version: Hash
    rubric_hash: Hash
    answer: TypedAnswer
    response_hash: Hash
    expected_grade_status: AssessmentStatus
    expected_error_code: str | None = Field(default=None, min_length=1, max_length=128)
    reference_grade: ReferenceGrade | None = None
    gold_evidence_groups: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def paired_question_and_answer(self):
        if (
            self.question_type != self.question.type
            or self.answer.type != self.question_type
        ):
            raise ValueError("Question, answer and declared question type must match")
        if self.expected_error_code is not None:
            if (
                not self.expected_error_code.strip()
                or self.expected_grade_status not in {"failed", "cancelled"}
            ):
                raise ValueError(
                    "A technical error requires a failed or cancelled grade"
                )
        return self


EvalSample = Annotated[
    RetrievalSample
    | QuizSample
    | QaSample
    | PolicySample
    | PracticeGenerationSample
    | AnswerGradingSample,
    Field(discriminator="case_type"),
]
