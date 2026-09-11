"""Public course contracts. Provider data and private storage keys stay on the server."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.models.learning import TaskView
from app.models.sources import PublicResolvedScope
from app.rag.contracts import Contract, DocumentLocator, RequestedScope
from app.teaching.contracts import LessonBlock, LessonCheck, TeachMission, TeachSource, TeachSourcePolicy, TeachUnit

CourseStatus = Literal["generating", "ready", "partial", "failed", "cancelled", "source_revoked"]
LessonStatus = Literal["not_generated", "generating", "ready", "material_gap", "failed", "cancelled", "source_revoked"]


class CourseCreate(Contract):
    topic: str = Field(min_length=1, max_length=2000)
    goal: str = Field(default="", max_length=1000)
    prior_knowledge: str = Field(default="", max_length=1000)
    daily_minutes: int = Field(default=20, ge=5, le=120)
    lesson_count: int = Field(default=6, ge=1, le=10)
    source_policy: TeachSourcePolicy = "topic"
    scope: RequestedScope | None = None

    @field_validator("topic", "goal", "prior_knowledge", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def valid_source_mode(self):
        if (self.source_policy == "strict_docs") != (self.scope is not None):
            raise ValueError("Select documents only for strict_docs courses")
        return self


class CourseTaskView(Contract):
    task_id: str
    course_id: str
    lesson_id: str | None = None
    kind: Literal["course_outline", "course_lesson"]
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    stage: str = "queued"
    error_code: str | None = None
    error_message: str | None = None


class CourseLessonSummary(TeachUnit):
    lesson_id: str
    position: int
    status: LessonStatus
    revision: int
    content_version: int
    read_at: str | None = None
    last_opened_at: str | None = None


class CourseView(Contract):
    course_id: str
    title: str
    source_policy: TeachSourcePolicy
    source_status: Literal["active", "revoked"]
    scope: PublicResolvedScope | None = None
    status: CourseStatus
    revision: int
    mission: TeachMission | None = None
    lessons: list[CourseLessonSummary] = Field(default_factory=list)
    sources: list[TeachSource] = Field(default_factory=list)
    active_task: CourseTaskView | None = None
    latest_task: CourseTaskView | None = None
    resume_lesson_id: str | None = None
    outline_editable: bool = False
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CourseList(Contract):
    items: list[CourseView]
    total: int
    page: int
    page_size: int


class CourseLessonTitle(Contract):
    lesson_id: str
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class CourseOutlineUpdate(Contract):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    lesson_titles: list[CourseLessonTitle] = Field(default_factory=list, max_length=10)

    @field_validator("title", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class CourseLessonGenerate(Contract):
    expected_course_revision: int = Field(ge=1)


class CourseReadUpdate(Contract):
    expected_revision: int = Field(ge=1)
    read: bool


class CourseQuizCreate(Contract):
    expected_content_version: int = Field(ge=1)
    kind: Literal["initial", "review"] = "initial"
    parent_link_id: str | None = None

    @model_validator(mode="after")
    def review_parent(self):
        if (self.kind == "review") != (self.parent_link_id is not None):
            raise ValueError("Review needs a parent link; initial cannot have one")
        return self


class CourseQuizLinkView(Contract):
    link_id: str
    lesson_id: str
    kind: Literal["initial", "review"]
    parent_link_id: str | None = None
    content_version: int
    created_at: str
    task: TaskView


class CourseLessonView(Contract):
    lesson_id: str
    course_id: str
    title: str
    objective: str | None = None
    estimated_minutes: int | None = None
    status: LessonStatus
    revision: int
    content_version: int
    blocks: list[LessonBlock] = Field(default_factory=list)
    checks: list[LessonCheck] = Field(default_factory=list)
    next_step: str | None = None
    warnings: list[str] = Field(default_factory=list)
    sources: list[TeachSource] = Field(default_factory=list)
    read_at: str | None = None
    last_opened_at: str | None = None
    active_task: CourseTaskView | None = None
    latest_task: CourseTaskView | None = None
    quiz_links: list[CourseQuizLinkView] = Field(default_factory=list)


class CourseEvidenceView(Contract):
    source_ref: str
    title: str
    excerpt: str
    doc_id: str
    document_version_id: str
    locator: DocumentLocator


class CourseNextAction(Contract):
    type: Literal["continue_quiz", "review_lesson", "learn_lesson", "practice_lesson", "view_summary"]
    lesson_id: str | None = None
    quiz_id: str | None = None
    link_id: str | None = None
    task_id: str | None = None
    reason: str


class CourseReviewRun(Contract):
    link_id: str
    lesson_id: str
    quiz_id: str | None = None
    status: str
    answered: int
    correct: int
    total: int
    accuracy: float | None = None
    created_at: str


class CourseWeakPoint(Contract):
    lesson_id: str
    link_id: str
    quiz_id: str
    question_id: str
    knowledge_point: str


class CourseProgressView(Contract):
    course_id: str
    total_lessons: int
    available_lessons: int
    generated_lessons: int
    read_lessons: int
    practiced_lessons: int
    initial_answered: int
    initial_correct: int
    initial_accuracy: float | None = None
    review_runs: list[CourseReviewRun] = Field(default_factory=list)
    weak_points: list[CourseWeakPoint] = Field(default_factory=list)
    next_action: CourseNextAction
