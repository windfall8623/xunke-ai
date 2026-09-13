"""Public assessment DTOs never contain answer keys or private rubrics."""

from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from app.rag.contracts import Contract

HelpUsage = Literal["none", "hints", "unknown"]


class CourseAssessmentCreate(Contract):
    expected_course_revision: int = Field(ge=1)
    expected_criteria_revision: int = Field(ge=1)
    course_criterion_ids: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("course_criterion_ids")
    @classmethod
    def distinct_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Course criterion IDs must be distinct")
        return value


class CourseAssessmentComplete(Contract):
    expected_revision: int = Field(ge=1)
    help_usage: HelpUsage = "unknown"


class CourseApplicationAnswer(Contract):
    expected_revision: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=4000)
    help_usage: HelpUsage = "unknown"

    @field_validator("answer")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Answer cannot be blank")
        return value


class CourseAssessmentTask(Contract):
    task_id: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    stage: str
    error_code: str | None = None
    error_message: str | None = None
    business_settled: bool = False


class CourseApplicationJobView(CourseAssessmentTask):
    kind: Literal["course_application_generate", "course_application_feedback"]
    course_id: str
    course_assessment_id: str
    application_task_id: str | None = None
    attempt_id: str | None = None


class CourseApplicationTaskView(Contract):
    application_task_id: str
    revision: int = Field(ge=1)
    prompt: str
    response_format: Literal["text"] = "text"
    public_expectations: list[str]
    source_policy: Literal["topic", "strict_docs"]
    source_refs: list[str] = Field(default_factory=list)
    support_quotes: list[str] = Field(default_factory=list)
    course_criterion_ids: list[str] = Field(default_factory=list)
    latest_attempt_id: str | None = None


class CourseApplicationFeedbackView(Contract):
    assessment_id: str
    supersedes_assessment_id: str | None = None
    status: Literal["graded", "needs_review", "failed", "cancelled"]
    confirmation: Literal["confirmed", "provisional"]
    score: Decimal | None = None
    feedback: str | None = None
    criterion_results: list[dict] = Field(default_factory=list)
    created_at: str


class CourseApplicationAttemptView(Contract):
    attempt_id: str
    application_task_id: str
    course_assessment_id: str
    course_id: str
    revision: int
    question_version: str
    answer: str
    help_usage: HelpUsage
    help_usage_source: Literal["learner_declaration", "unknown"]
    saved_at: str
    feedback_task_id: str | None = None
    feedback_task: CourseAssessmentTask | None = None
    feedback: CourseApplicationFeedbackView | None = None


class CourseAssessmentView(Contract):
    course_assessment_id: str
    course_id: str
    criteria_revision: int
    revision: int = Field(ge=1)
    status: Literal["generating", "ready", "in_progress", "completed", "failed", "cancelled"]
    task_id: str | None = None
    task: CourseAssessmentTask | None = None
    quiz_id: str | None = None
    quiz_status: str | None = None
    quiz_settled: bool = False
    application_generation_task_id: str | None = None
    application_generation_task: CourseAssessmentTask | None = None
    application_task_ids: list[str] = Field(default_factory=list)
    applications: list[CourseApplicationTaskView] = Field(default_factory=list)
    covered_course_criterion_ids: list[str] = Field(default_factory=list)
    uncovered_course_criterion_ids: list[str] = Field(default_factory=list)
