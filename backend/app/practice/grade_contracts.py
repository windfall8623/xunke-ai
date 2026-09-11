"""Frozen grader inputs and model proposals; proposals never choose authority."""

from typing import Literal

from pydantic import Field, field_validator

from app.learning.contracts import HelpUsage, LearningId
from app.practice.contracts import ShortAnswer, ShortAnswerQuestion
from app.rag.contracts import Contract, DocumentEvidence, ExecutionMode, Hash, Identity


class GradeInputSnapshot(Contract):
    owner_id: int = Field(gt=0)
    mode: ExecutionMode
    run_id: Identity
    attempt_id: LearningId
    grading_request_id: LearningId
    space_id: LearningId
    scope_revision: int = Field(ge=1)
    scope_fingerprint: Hash
    question: ShortAnswerQuestion
    answer: ShortAnswer
    question_version: Hash
    rubric_version: LearningId
    rubric_hash: Hash
    response_hash: Hash
    evidence: list[DocumentEvidence] = Field(min_length=1, max_length=30)
    help_usage: HelpUsage
    model_fingerprint: Identity
    prompt_hash: Hash
    prompt_version: LearningId = "short-answer-grading-v1"
    grader_version: LearningId = "short-answer-grader-v1"
    rubric_family: Literal["short_explanation"] = "short_explanation"
    language: str = Field(default="zh", min_length=2, max_length=16)
    calibration_profile_hash: Hash | None = None

    @field_validator("language")
    @classmethod
    def normalized_language(cls, value):
        if value != value.strip().lower() or not all(
            part.isalpha() for part in value.split("-")
        ):
            raise ValueError("Grading language must be a normalized language tag")
        return value


class CriterionProposal(Contract):
    criterion_id: LearningId
    credit: Literal["full", "half", "none", "uncertain"]
    rationale: str = Field(min_length=1, max_length=1000)
    evidence_refs: list[Identity] = Field(min_length=1, max_length=10)
    answer_quotes: list[str] = Field(default_factory=list, max_length=5)


class ShortAnswerProposal(Contract):
    status: Literal["graded", "needs_review"]
    criterion_results: list[CriterionProposal] = Field(min_length=2, max_length=4)
    feedback: str = Field(min_length=1, max_length=2000)
    uncertainty_reasons: list[str] = Field(default_factory=list, max_length=5)
