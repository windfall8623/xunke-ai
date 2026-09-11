"""Public source and cost projections for the learning UI."""

from decimal import Decimal
from typing import Literal

from pydantic import Field, field_serializer

from app.learning.contracts import HelpUsage
from app.models.sources import PublicResolvedScope
from app.practice.contracts import ShortAnswer, Weight
from app.rag.contracts import Contract, DocumentLocator, Identity


class PublicPracticeEvidence(Contract):
    practice_id: Identity
    question_id: Identity
    evidence_id: Identity
    source_type: Literal["document"] = "document"
    title: str
    excerpt: str
    doc_id: Identity
    document_version_id: Identity
    locator: DocumentLocator


class PracticeCostPreview(Contract):
    generation_llm_call_upper: int = Field(default=5, ge=0)
    grading_llm_call_upper: int = Field(ge=0)
    input_token_upper: int = Field(ge=0)
    output_token_upper: int = Field(ge=0)
    embedding_token_upper: int = Field(ge=0)
    cost_cny_upper: Decimal | None
    cost_status: Literal["estimated", "unknown"]
    pricing_version: str

    @field_serializer("cost_cny_upper", when_used="json")
    def decimal_cost(self, value):
        return str(value) if value is not None else None


class PracticeReviewPoint(Contract):
    criterion_id: Identity
    reference_point: str
    weight: Weight
    evidence_refs: list[Identity]

    @field_serializer("weight", when_used="json")
    def decimal_weight(self, value):
        return str(value)


class PracticeReviewContext(Contract):
    """Private rubric points exposed only to the owning evaluator after submission."""

    practice_id: Identity
    attempt_id: Identity
    question_id: Identity
    question_version: str
    stem: str
    answer: ShortAnswer
    rubric_version: str
    criteria: list[PracticeReviewPoint] = Field(min_length=2, max_length=4)
    current_assessment_id: Identity | None
    grading_revision: int = Field(ge=0)
    help_usage: HelpUsage
    scope: PublicResolvedScope
