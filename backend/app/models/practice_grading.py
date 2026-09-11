"""Review commands accept evidence judgments, never caller-selected authority."""

from typing import Literal

from pydantic import Field

from app.learning.contracts import LearningId
from app.rag.contracts import Contract, Identity


class PracticeReviewCriterion(Contract):
    criterion_id: LearningId
    credit: Literal["full", "half", "none"]
    rationale: str = Field(min_length=1, max_length=1000)
    evidence_refs: list[Identity] = Field(min_length=1, max_length=10)
    answer_quotes: list[str] = Field(default_factory=list, max_length=5)


class PracticeReviewBody(Contract):
    expected_assessment_id: LearningId | None
    expected_grading_revision: int = Field(ge=0)
    criterion_results: list[PracticeReviewCriterion] = Field(min_length=2, max_length=4)
    feedback: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[Identity] = Field(min_length=1, max_length=10)


class PracticeSelfReviewBody(Contract):
    self_rating: Literal["understood", "needs_practice", "unsure"]
    notes: str = Field(default="", max_length=1000)


class PracticeSelfReviewReceipt(Contract):
    annotation_id: LearningId
