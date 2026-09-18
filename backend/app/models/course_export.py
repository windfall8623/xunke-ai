"""Personal learning outcome export contracts (C01)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.course_outcome import CourseOutcomeSummary


class CourseExportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["self_check", "quiz_result", "application_result", "correction"]
    title: str = Field(min_length=1, max_length=200)
    occurred_at: str
    content_version: int | None = Field(default=None, ge=1)
    own_answer: str | None = Field(default=None, max_length=4000)
    feedback_text: str | None = Field(default=None, max_length=4000)
    confirmation: Literal["not_applicable", "provisional", "confirmed"] = "not_applicable"
    help_usage_label: str = "帮助使用情况未记录"
    source_refs: list[str] = Field(default_factory=list, max_length=10)


class CourseExportCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_ref: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    document_version_id: str | None = None
    locator: str | None = None


class CourseExportSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    title: str
    generated_at: str
    criteria_revision: int
    include_history: bool
    outcomes: CourseOutcomeSummary
    personal_summary: list[str] = Field(default_factory=list, max_length=10)
    records: list[CourseExportRecord] = Field(default_factory=list, max_length=200)
    sources: list[CourseExportCitation] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=6)


class CourseExportView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    generated_at: str
    snapshot: CourseExportSnapshot
    markdown: str
