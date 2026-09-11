from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.models.sources import DocumentView


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=1, max_length=64)
    reason: Literal[
        "incorrect_answer",
        "unsupported_explanation",
        "citation_mismatch",
        "duplicate",
        "other",
    ]
    comment: str = Field(default="", max_length=2000)
    allow_evaluation_use: StrictBool = False


class FeedbackReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    verdict: Literal["approved", "rejected", "needs_changes"]
    comment: str = Field(default="", max_length=2000)


class FeedbackPromote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    dataset_id: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    redacted_request: str = Field(min_length=1, max_length=2000)
    question_count: int = Field(default=3, ge=3, le=10)


class FeedbackView(BaseModel):
    feedback_id: str
    quiz_id: str
    question_id: str
    reason: str
    comment: str
    allow_evaluation_use: bool
    status: str
    revision: int
    created_at: str
    review: dict | None = None
    promotion: dict | None = None
    access_scope: Literal["owner_only"] = "owner_only"


class FeedbackList(BaseModel):
    items: list[FeedbackView]
    total: int


class PromotionView(BaseModel):
    status: Literal["preparing", "promoted"]
    feedback: FeedbackView
    documents: list[DocumentView] = Field(default_factory=list)
    dataset_id: str | None = None
    dataset_version: int | None = None
