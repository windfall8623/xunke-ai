"""Teach v2 local targets and reciprocal lesson alignment; v1 types stay unchanged."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.rag.contracts import Contract
from app.teaching.contracts import CoursePayload, LessonBlock, LessonCheck, LessonPayload, TeachEnvelope, TeachUnit
from app.teaching.quality import require_course_criteria, require_lesson_alignment, require_ordered_prerequisites, require_v2_block_sources

EvidenceType = Literal["recognition", "recall", "application", "explanation", "creation"]
CourseCriterionRef = Annotated[str, Field(pattern=r"^cc[1-9][0-9]*$", max_length=16)]
BlockRef = Annotated[str, Field(pattern=r"^b[1-9][0-9]*$", max_length=16)]


class CourseCriterionDraft(Contract):
    course_criterion_ref: CourseCriterionRef
    description: str = Field(min_length=1, max_length=300)
    evidence_type: EvidenceType
    expectation: str = Field(min_length=1, max_length=500)


class TeachUnitV2(TeachUnit):
    course_criterion_refs: list[CourseCriterionRef] = Field(min_length=1, max_length=3)


class LessonBlockV2(LessonBlock):
    block_ref: BlockRef
    course_criterion_refs: list[CourseCriterionRef] = Field(min_length=1, max_length=3)


class LessonCheckV2(LessonCheck):
    course_criterion_refs: list[CourseCriterionRef] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def options_match_question_type(self):
        if self.question_type in {"single", "multiple", "judge"}:
            keys = [option.key for option in self.options]
            if len(keys) < 2 or len(keys) != len(set(keys)) or any(not key.strip() for key in keys):
                raise ValueError("check_options_mismatch")
            if self.question_type == "judge" and len(keys) != 2:
                raise ValueError("check_options_mismatch")
        elif self.options:
            raise ValueError("check_options_mismatch")
        return self


class CriterionAlignment(Contract):
    course_criterion_ref: CourseCriterionRef
    explanation_block_refs: list[BlockRef] = Field(min_length=1, max_length=20)
    example_block_refs: list[BlockRef] = Field(min_length=1, max_length=20)
    check_refs: list[str] = Field(min_length=1, max_length=5)


class CoursePayloadV2(CoursePayload):
    course_criteria: list[CourseCriterionDraft] = Field(min_length=1, max_length=10)
    units: list[TeachUnitV2] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def targets_and_prerequisites(self):
        require_course_criteria(self)
        require_ordered_prerequisites(self.units)
        return self


class LessonPayloadV2(LessonPayload):
    blocks: list[LessonBlockV2] = Field(min_length=3, max_length=20)
    checks: list[LessonCheckV2] = Field(min_length=1, max_length=5)
    alignments: list[CriterionAlignment] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def targets_align(self):
        require_lesson_alignment(self)
        if not {"explanation", "example", "recap"} <= {block.type for block in self.blocks}:
            raise ValueError("lesson_needs_explanation_example_recap")
        return self


class TeachEnvelopeV2(TeachEnvelope):
    schema_version: Literal["xunke-teach.v2"] = "xunke-teach.v2"


class CourseDraftV2(TeachEnvelopeV2):
    kind: Literal["course_draft"] = "course_draft"
    payload: CoursePayloadV2 | None = None

    @model_validator(mode="after")
    def check_sources(self):
        self.check_references([
            (unit.source_refs, unit.availability == "ready") for unit in self.payload.units
        ] if self.payload else [])
        if self.status == "draft" and self.payload is None:
            raise ValueError("missing_generated_content")
        return self


class LessonDraftV2(TeachEnvelopeV2):
    kind: Literal["lesson_draft"] = "lesson_draft"
    payload: LessonPayloadV2 | None = None

    @model_validator(mode="after")
    def check_sources(self):
        require_v2_block_sources(self)
        self.check_references([(block.source_refs, True) for block in self.payload.blocks] if self.payload else [])
        if self.status == "draft" and self.payload is None:
            raise ValueError("missing_generated_content")
        return self
