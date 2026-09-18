"""Small public teaching metadata, separate from student grades and outcomes."""

from typing import Literal

from pydantic import Field

from app.rag.contracts import Contract

TeachingMode = Literal["guided", "fast"]


class CourseCapabilities(Contract):
    teaching_modes: list[TeachingMode]
    unavailable_reason: str | None = None


class TeachingQualitySummary(Contract):
    level: Literal["outline", "lesson"]
    status: Literal["reviewed", "needs_revision", "unreviewed"]
    draft_hash: str | None = None
    artifact_hash: str | None = None
    reason_code: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=6)
