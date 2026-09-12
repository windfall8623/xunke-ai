"""Course review and daily suggestions expose facts and internal target IDs only."""

from typing import Literal

from pydantic import Field

from app.learning.contracts import IanaTimezone
from app.rag.contracts import Contract


class CourseReviewStart(Contract):
    review_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=1)
    expected_content_version: int = Field(ge=1)
    early: bool = False


class CourseReviewView(Contract):
    review_id: str
    course_id: str
    lesson_id: str
    content_version: int
    schedule_seq: int
    due_at: str
    timezone: IanaTimezone
    status: Literal[
        "scheduled", "generating", "ready", "failed", "completed",
        "superseded", "source_revoked",
    ]
    revision: int
    active_link_id: str | None = None
    reason: str


class CourseTodayItem(Contract):
    kind: Literal[
        "continue_quiz", "course_review", "study_review", "learn_lesson",
        "practice_lesson", "review_lesson",
    ]
    title: str
    estimated_minutes: int = Field(ge=1)
    reason: str
    course_id: str | None = None
    lesson_id: str | None = None
    quiz_id: str | None = None
    link_id: str | None = None
    task_id: str | None = None
    review_id: str | None = None
    review_task_id: str | None = None
    space_id: str | None = None


class CourseTodayView(Contract):
    local_date: str
    timezone: IanaTimezone
    minutes_budget: int = Field(ge=5, le=120)
    items: list[CourseTodayItem] = Field(default_factory=list, max_length=3)
    warnings: list[str] = Field(default_factory=list)
