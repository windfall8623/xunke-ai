"""Course feedback, corrections and authorized regrade contracts (B03).

问题定位采用带 discriminator 的严格 union：一份反馈只能指向一个对象，
不允许同时携带任意 lesson/Quiz/attempt 标识。正式复核与个人纠正分别建模。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

IssueKind = Literal["confusion", "content_error", "grading_review"]
Provenance = Literal["learner_note", "model_proposal", "human_reviewer"]
Confirmation = Literal["provisional", "confirmed"]


class _Target(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LessonIssueTarget(_Target):
    kind: Literal["lesson"]
    lesson_id: str = Field(min_length=1, max_length=64)
    content_version: int = Field(ge=1)
    block_index: int = Field(ge=0)


class SelfCheckIssueTarget(_Target):
    kind: Literal["self_check"]
    lesson_id: str = Field(min_length=1, max_length=64)
    content_version: int = Field(ge=1)
    check_attempt_id: str = Field(min_length=1, max_length=64)


class QuizIssueTarget(_Target):
    kind: Literal["quiz"]
    quiz_id: str = Field(min_length=1, max_length=64)
    question_id: str = Field(min_length=1, max_length=64)


class CourseAssessmentIssueTarget(_Target):
    kind: Literal["course_assessment"]
    course_assessment_id: str = Field(min_length=1, max_length=64)
    attempt_id: str = Field(min_length=1, max_length=64)
    assessment_id: str | None = Field(default=None, min_length=1, max_length=64)


FeedbackTarget = Annotated[
    LessonIssueTarget
    | SelfCheckIssueTarget
    | QuizIssueTarget
    | CourseAssessmentIssueTarget,
    Field(discriminator="kind"),
]


class CourseFeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_kind: IssueKind
    target: FeedbackTarget
    comment: str = Field(min_length=1, max_length=2000)
    allow_evaluation_use: bool = False


class CourseFeedbackUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    status: Literal["open", "resolved"]


class CourseCorrectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=2000)
    source_refs: list[str] = Field(default_factory=list, max_length=10)
    supersedes_correction_id: str | None = Field(
        default=None, min_length=1, max_length=64
    )


class CourseCorrectionView(BaseModel):
    correction_id: str
    feedback_id: str
    supersedes_correction_id: str | None = None
    text: str
    source_refs: list[str] = Field(default_factory=list)
    provenance: Provenance
    confirmation: Confirmation
    created_at: str


class CourseFeedbackView(BaseModel):
    feedback_id: str
    course_id: str
    issue_kind: IssueKind
    target: FeedbackTarget
    comment: str
    status: Literal["open", "resolved", "rejected"]
    revision: int
    tutor_turn_id: str | None = None
    quiz_feedback_id: str | None = None
    corrections: list[CourseCorrectionView] = Field(default_factory=list)
    created_at: str


class CourseFeedbackList(BaseModel):
    items: list[CourseFeedbackView]
    total: int


class CourseCorrectionReview(BaseModel):
    """owner + evaluator 对内容纠正的确认或退回；追加新记录，不改旧记录。"""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    decision: Literal["confirmed", "rejected"]
    note: str = Field(default="", max_length=2000)


class CourseApplicationRegrade(BaseModel):
    """课程文本应用 attempt 的正式复核：追加新判分头并 supersedes 旧头。"""

    model_config = ConfigDict(extra="forbid")

    expected_assessment_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=1)
    score: float | None = Field(default=None, ge=0, le=1)
    comment: str = Field(default="", max_length=2000)
    status: Literal["graded", "needs_review"] = "graded"
