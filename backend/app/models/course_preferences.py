"""Learning preferences and course review adjustment contracts (B05)."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.learning.contracts import IanaTimezone


class LearningPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    daily_minutes: int = Field(ge=5, le=120, strict=True)
    daily_review_limit: int = Field(ge=0, le=3, strict=True)
    difficulty: str = Field(pattern="^(easy|medium|hard|mixed)$")
    timezone: IanaTimezone


class LearningPreferencesView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    daily_minutes: int = Field(ge=5, le=120)
    daily_review_limit: int = Field(ge=0, le=3)
    difficulty: str = Field(pattern="^(easy|medium|hard|mixed)$")
    timezone: IanaTimezone


class CourseReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    expected_content_version: int = Field(ge=1)
    action: str = Field(pattern="^(pause|resume|reschedule)$")
    due_at: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def explicit_reschedule(self):
        if (self.action == "reschedule") != (self.due_at is not None):
            raise ValueError("Only reschedule requires due_at")
        return self
