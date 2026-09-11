"""Public study DTOs. Owners, frozen sources and grading are server-derived."""

from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from app.learning.contracts import IanaTimezone, LearningId, LearningTitle, Objectives
from app.models.sources import PublicResolvedScope
from app.models.learning import QuestionView
from app.models.practice import PracticeAssessmentView, PublicPracticeQuestion
from app.qa.contracts import AnswerBlock
from app.rag.contracts import Contract, Identity, RequestedScope

PlanStatus = Literal["planned", "active", "completed", "paused"]
Revision = Annotated[int, Field(ge=1)]


class StudySpaceCreate(Contract):
    title: LearningTitle
    timezone: IanaTimezone = "Asia/Shanghai"
    scope: RequestedScope | None = None
    answer_id: LearningId | None = None

    @model_validator(mode="after")
    def one_source_entry(self):
        if (self.scope is None) == (self.answer_id is None):
            raise ValueError("Choose exactly one requested scope or QA answer")
        return self


class StudySpaceUpdate(Contract):
    expected_revision: Revision
    title: LearningTitle | None = None
    timezone: IanaTimezone | None = None
    status: Literal["active", "archived"] | None = None


class StudyScopeUpdate(Contract):
    expected_revision: Revision
    scope: RequestedScope


class StudyScopeView(Contract):
    space_id: LearningId
    scope_revision: Revision
    scope: PublicResolvedScope


class StudySpaceView(Contract):
    space_id: LearningId
    title: LearningTitle
    timezone: IanaTimezone
    status: Literal["active", "archived"]
    scope_revision: Revision
    revision: Revision
    scope: PublicResolvedScope | None = None
    source_status: Literal["active", "revoked"] = "active"
    created_at: AwareDatetime
    updated_at: AwareDatetime


class StudySpaceList(Contract):
    items: list[StudySpaceView]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class StudyGoalCreate(Contract):
    title: LearningTitle
    scope_revision: Revision | None = None
    deadline: date | None = None
    daily_minutes: int = Field(default=30, ge=5, le=240)
    status: PlanStatus = "planned"


class StudyGoalUpdate(Contract):
    expected_revision: Revision
    title: LearningTitle | None = None
    deadline: date | None = None
    daily_minutes: int | None = Field(default=None, ge=5, le=240)
    status: PlanStatus | None = None


class StudyGoalView(StudyGoalCreate):
    goal_id: LearningId
    space_id: LearningId
    scope_revision: Revision
    revision: Revision
    source_status: Literal["active", "revoked"] = "active"
    created_at: AwareDatetime
    updated_at: AwareDatetime


class StudyGoalList(Contract):
    items: list[StudyGoalView]


class StudyUnitCreate(Contract):
    title: LearningTitle
    scope_revision: Revision
    scope: RequestedScope
    position: int = Field(ge=0)
    status: PlanStatus = "planned"


class StudyUnitUpdate(Contract):
    expected_revision: Revision
    title: LearningTitle | None = None
    status: PlanStatus | None = None


class StudyUnitReorder(Contract):
    expected_revision: Revision
    unit_ids: list[LearningId] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_units(self):
        if len(self.unit_ids) != len(set(self.unit_ids)):
            raise ValueError("Unit IDs must be unique")
        return self


class StudyUnitView(StudyUnitCreate):
    unit_id: LearningId
    goal_id: LearningId
    space_id: LearningId
    scope: RequestedScope | None
    revision: Revision
    source_status: Literal["active", "revoked"] = "active"
    created_at: AwareDatetime
    updated_at: AwareDatetime


class StudyUnitList(Contract):
    items: list[StudyUnitView]
    goal_revision: Revision


class StudyConceptCreate(Contract):
    title: LearningTitle
    scope_revision: Revision | None = None


class StudyConceptUpdate(Contract):
    expected_revision: Revision
    title: LearningTitle
    scope_revision: Revision | None = None


class StudyConceptView(StudyConceptCreate):
    concept_id: LearningId
    space_id: LearningId
    scope_revision: Revision
    revision: Revision
    source_status: Literal["active", "revoked"] = "active"
    created_at: AwareDatetime


class StudyConceptList(Contract):
    items: list[StudyConceptView]


class StudyQaPracticeContextView(Contract):
    answer_id: LearningId
    session_id: LearningId
    scope_revision: Revision
    answer_status: Literal["answered", "partial"]
    scope: PublicResolvedScope
    retrieval_query: str = Field(min_length=1, max_length=2000)
    fact_blocks: list[AnswerBlock] = Field(min_length=1, max_length=12)


class StudyQuizFromQaBody(Contract):
    answer_id: LearningId
    block_ids: list[Identity] = Field(min_length=1, max_length=12)
    space_id: LearningId
    scope_revision: Revision
    objectives: Objectives
    question_count: int = Field(default=5, ge=3, le=10)
    difficulty: Literal["easy", "medium", "hard", "mixed"] = "mixed"

    @model_validator(mode="after")
    def distinct_blocks(self):
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("Selected fact block IDs must be unique")
        return self


class ReviewQuizBody(Contract):
    review_task_ids: list[LearningId] = Field(min_length=1, max_length=3)
    expected_revisions: dict[LearningId, Revision]
    question_count: int = Field(default=5, ge=3, le=10)
    difficulty: Literal["easy", "medium", "hard", "mixed"] = "mixed"

    @model_validator(mode="after")
    def exact_occurrence_revisions(self):
        if len(self.review_task_ids) != len(set(self.review_task_ids)):
            raise ValueError("Review task IDs must be unique")
        if set(self.expected_revisions) != set(self.review_task_ids):
            raise ValueError(
                "Each selected review requires exactly one expected revision"
            )
        return self


class ReviewUpdateBody(Contract):
    expected_revision: Revision
    action: Literal["pause", "resume", "reschedule"]
    due_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def reschedule_has_a_time(self):
        if (self.action == "reschedule") != (self.due_at is not None):
            raise ValueError("Only reschedule requires a timezone-aware due_at")
        return self


StudyProjectionStatus = Literal[
    "not_ready", "pending", "pending_assessments", "current", "failed"
]


class StudyConceptSummary(Contract):
    concept_id: LearningId
    title: str


class StudyReviewView(Contract):
    review_task_id: LearningId
    space_id: LearningId
    scope_revision: Revision
    concept_id: LearningId
    space_title: str
    concept_title: str
    timezone: IanaTimezone
    schedule_seq: Revision
    revision: Revision
    status: Literal[
        "scheduled", "claimed", "running", "completed", "failed", "cancelled"
    ]
    paused: bool
    is_current: bool
    rule_version: str
    rule_due_at: AwareDatetime | None
    due_at: AwareDatetime
    override_due_at: AwareDatetime | None
    task_id: LearningId | None
    origin_kind: Literal["quiz", "practice"] | None
    origin_id: LearningId | None
    last_error_code: str | None
    claimed_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    source_status: Literal["active", "revoked"]


class StudyReviewList(Contract):
    items: list[StudyReviewView]
    next_cursor: str | None


class StudyWrongQuestionView(Contract):
    item_id: str
    attempt_id: LearningId | None
    origin_kind: Literal["quiz", "practice"]
    origin_id: LearningId
    question_id: str
    question_version: str | None
    question_type: Literal[
        "single", "multiple", "judge", "cloze", "numeric", "short_answer"
    ]
    space_id: LearningId | None
    scope_revision: Revision | None
    occurred_at: AwareDatetime
    help_usage: Literal["none", "hints", "unknown"]
    association_status: Literal["linked", "unlinked"]
    concepts: list[StudyConceptSummary]
    question: QuestionView | PublicPracticeQuestion | None
    answer: JsonValue = None
    correct_answers: list[str]
    feedback: str = ""
    current_assessment: PracticeAssessmentView | None
    result_status: Literal["wrong", "partial"]
    projection_status: StudyProjectionStatus
    next_reviews: list[StudyReviewView]
    source_status: Literal["active", "revoked"]


class StudyWrongQuestionList(Contract):
    items: list[StudyWrongQuestionView]
    next_cursor: str | None


class StudyHistoryView(Contract):
    history_id: str
    origin_kind: Literal["quiz", "practice"]
    origin_id: LearningId
    space_id: LearningId | None
    scope_revision: Revision | None
    title: str
    status: str
    occurred_at: AwareDatetime
    completed_at: AwareDatetime | None
    completion_id: LearningId | None
    question_count: int = Field(ge=0)
    attempted_count: int = Field(ge=0)
    confirmed_count: int = Field(ge=0)
    correct_count: int = Field(ge=0)
    wrong_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    current_assessments: list[PracticeAssessmentView]
    assessment_set_hash: str | None
    projection_status: StudyProjectionStatus
    projection_revision: Revision | None
    concepts: list[StudyConceptSummary]
    next_reviews: list[StudyReviewView]
    scope: PublicResolvedScope | None
    source_status: Literal["active", "revoked"]


class StudyHistoryList(Contract):
    items: list[StudyHistoryView]
    next_cursor: str | None


class StudyConceptStateView(Contract):
    scope_revision: Revision
    rule_version: str
    evidence_count: int = Field(ge=0)
    stage: int = Field(ge=0, le=4)
    revision: int = Field(ge=0)
    last_activity_local_date: date | None
    last_success_local_date: date | None
    rule_due_at: AwareDatetime | None
    due_at: AwareDatetime | None
    override_due_at: AwareDatetime | None
    paused: bool
    assessment_set_hash: str | None
    last_completion_id: LearningId | None


class StudyConceptProgressView(Contract):
    concept_id: LearningId
    space_id: LearningId
    title: str
    source_status: Literal["active", "revoked"]
    states: list[StudyConceptStateView]
    next_reviews: list[StudyReviewView]
    recent_history: list[StudyHistoryView]
    history_next_cursor: str | None
