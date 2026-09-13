"""Small, explicit interaction diagnostics; these are never learning facts."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.rag.contracts import Contract

ExperienceEventName = Literal[
    "course_create_viewed", "course_create_submitted", "lesson_opened",
    "learning_session_finished", "task_retry_clicked",
    "response_helpfulness_submitted", "content_first_visible", "content_stream_interrupted",
]
ResourceId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class ExperienceEventInput(Contract):
    event_id: ResourceId
    name: ExperienceEventName
    course_id: ResourceId | None = None
    lesson_id: ResourceId | None = None
    task_id: ResourceId | None = None
    elapsed_ms: int | None = Field(default=None, ge=0, le=86_400_000, strict=True)
    helpful: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def event_context(self):
        if self.helpful is not None and self.name != "response_helpfulness_submitted":
            raise ValueError("helpful is only valid on a helpfulness event")
        return self


class ExperienceEventReceipt(Contract):
    event_id: str
    accepted: bool
    received_at: str | None = None
