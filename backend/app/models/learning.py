from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.quiz import QuestionOption
from app.rag.contracts import RequestedScope


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_input: str | None = Field(default=None, min_length=1, max_length=2000)
    review_of_quiz_id: str | None = None
    question_count: int = Field(default=5, ge=3, le=10)
    difficulty: Literal["easy", "medium", "hard", "mixed"] = "mixed"
    source_policy: Literal["topic", "strict_docs", "doc_plus_web"] | None = None
    scope: RequestedScope | None = None
    doc_id: str | None = None
    generate_images: bool = False

    @model_validator(mode="after")
    def mode_is_unambiguous(self):
        if bool(self.user_input) == bool(self.review_of_quiz_id):
            raise ValueError("Provide user_input or review_of_quiz_id, exclusively")
        if self.review_of_quiz_id and any(
            v is not None for v in (self.scope, self.doc_id, self.source_policy)
        ):
            raise ValueError("Review inherits its source policy and scope")
        return self


class AnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_answers: list[str] = Field(min_length=1, max_length=10)
    duration_ms: int = Field(ge=0, le=86400000)


class CompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)


class QuestionView(BaseModel):
    id: str
    type: Literal["single", "multiple", "judge"]
    stem: str
    options: list[QuestionOption]
    knowledge_point: str = ""
    difficulty: str = "medium"
    citation_refs: list[str] = Field(default_factory=list)
    image_url: str | None = None
    image_status: str = "not_requested"


class AnswerView(BaseModel):
    question_id: str
    selected_answers: list[str]
    is_correct: bool
    duration_ms: int
    correct_answers: list[str]
    explanation: str
    citation_refs: list[str] = Field(default_factory=list)


class AnswerReceipt(BaseModel):
    answer_record: AnswerView
    revision: int
    answered_count: int
    correct_count: int


class CompletionReceipt(BaseModel):
    quiz_id: str
    revision: int
    xp_awarded: int
    correct_count: int
    total_questions: int
    total: int
    accuracy: float
    report_status: str


class CourseReturnContext(BaseModel):
    course_id: str
    lesson_id: str
    link_id: str
    kind: Literal["initial", "review", "scheduled_review"]
    content_version: int


class QuizView(BaseModel):
    quiz_id: str
    title: str
    summary: str
    user_input: str | None = None
    questions: list[QuestionView]
    answer_records: list[AnswerView]
    revision: int
    status: str
    source_policy: str
    source_status: str
    source_scope: dict | None = None
    images_status: str
    report_status: str
    created_at: str
    course_context: CourseReturnContext | None = None


class TaskView(BaseModel):
    task_id: str
    quiz_id: str | None = None
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    stage: str = "queued"
    error_code: str | None = None
    error_message: str | None = None
    result: QuizView | None = None


class ReportText(BaseModel):
    mastered_points: list[str] = Field(default_factory=list)
    weak_points: list[str] = Field(default_factory=list)
    three_line_summary: list[str] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
    share_quote: str = ""


class ReportView(BaseModel):
    quiz_id: str
    total_questions: int
    correct_count: int
    accuracy: float
    xp_awarded: int
    report_status: str
    report: ReportText | None = None
    error_code: str | None = None
    weak_question_ids: list[str] = Field(default_factory=list)


class ReportRetryView(BaseModel):
    quiz_id: str
    report_status: str
