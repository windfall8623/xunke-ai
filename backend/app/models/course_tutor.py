"""Course tutoring and saved self checks are teaching records, never grades."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.models.course import CourseTaskView
from app.rag.contracts import Contract
from app.teaching.contracts import TeachSource

CourseTutorMode = Literal["explain", "example", "hint", "check"]
CheckOptionKey = Annotated[str, Field(min_length=1, max_length=128)]
CourseCheckAnswer = Annotated[str, Field(min_length=1, max_length=2000)] | Annotated[
    list[CheckOptionKey], Field(min_length=1, max_length=10)
]


class CourseTutorCreate(Contract):
    expected_content_version: int = Field(ge=1, strict=True)
    mode: CourseTutorMode = "explain"
    block_index: int | None = Field(default=None, ge=0, strict=True)
    question: str = Field(default="", max_length=1000)
    check_attempt_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def check_identity(self):
        if (self.mode == "check") != (self.check_attempt_id is not None):
            raise ValueError("Check feedback requires a saved self-check attempt")
        if self.mode != "check" and not self.question and self.block_index is None:
            raise ValueError("Choose a lesson block or enter a question")
        return self


class CourseTutorTurnView(Contract):
    turn_id: str
    course_id: str
    lesson_id: str
    content_version: int
    mode: CourseTutorMode
    block_index: int | None = None
    question: str
    check_attempt_id: str | None = None
    task: CourseTaskView
    answer: str | None = None
    sources: list[TeachSource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str


class CourseSelfCheckCreate(Contract):
    expected_content_version: int = Field(ge=1, strict=True)
    check_ref: str = Field(min_length=1, max_length=128)
    answer: CourseCheckAnswer

    @field_validator("answer")
    @classmethod
    def meaningful_answer(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("Enter an answer before saving")
        if isinstance(value, list) and len(set(value)) != len(value):
            raise ValueError("An option can only be selected once")
        return value


class CourseSelfCheckView(Contract):
    attempt_id: str
    course_id: str
    lesson_id: str
    content_version: int
    check_ref: str
    answer: CourseCheckAnswer
    saved_at: str
    latest_tutor_turn: CourseTutorTurnView | None = None
