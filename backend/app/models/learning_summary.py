"""Weekly learning summary contracts (B07).

周报只叙述已经算好的事实；没有可信分母就不给出比率，也不推断学习时长。
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.learning.contracts import IanaTimezone
from app.models.course_review import CourseTodayItem
from app.models.course_feedback import CourseCorrectionView
from app.models.course_outcome import CourseOutcomeSummary


class LearningActivityFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(min_length=1, max_length=160)
    kind: Literal[
        "self_check_saved", "quiz_settled", "practice_completed",
        "course_application_submitted",
    ]
    occurred_at: str
    course_id: str | None = None
    lesson_id: str | None = None
    content_version: int | None = Field(default=None, ge=1)
    origin_id: str = Field(min_length=1, max_length=64)
    check_ref: str | None = None
    is_scheduled_review: bool = False

    @model_validator(mode="after")
    def self_check_has_identity(self):
        if self.kind == "self_check_saved" and any(value is None for value in (
            self.course_id, self.lesson_id, self.content_version, self.check_ref,
        )):
            raise ValueError("A self-check activity needs its frozen lesson identity")
        return self


class WeeklyLearningCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_checks_saved: int = Field(ge=0)
    quizzes_settled: int = Field(ge=0)
    practices_completed: int = Field(ge=0)
    applications_submitted: int = Field(ge=0)
    scheduled_reviews_completed: int = Field(ge=0)


class WeeklyLearningSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: date
    week_end_exclusive: date
    timezone: IanaTimezone
    counts: WeeklyLearningCounts
    course_outcomes: list[CourseOutcomeSummary] = Field(default_factory=list, max_length=10)
    confirmed_corrections: list[CourseCorrectionView] = Field(default_factory=list, max_length=20)
    next_actions: list[CourseTodayItem] = Field(default_factory=list, max_length=3)
    warnings: list[str] = Field(default_factory=list, max_length=6)
