"""Deterministic teaching checks; these do not assert semantic truth or mastery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

if TYPE_CHECKING:
    from app.teaching.contracts_v2 import CoursePayloadV2, LessonDraftV2, LessonPayloadV2, TeachUnitV2


DRAFT_ERROR_CODES = frozenset({
    "invalid_json", "schema_invalid", "forbidden_field", "unsupported_teach_schema_version",
    "duplicate_course_criterion_ref", "success_criteria_display_mismatch",
    "unknown_or_duplicate_course_criterion_ref", "course_criterion_without_unit",
    "prerequisite_not_before_unit", "ready_unit_depends_on_material_gap", "invalid_prerequisite",
    "duplicate_block_or_check_ref", "incomplete_course_criterion_alignment", "item_outside_lesson_criteria",
    "duplicate_alignment_ref", "alignment_block_type_mismatch", "alignment_not_reciprocal",
    "alignment_check_mismatch", "synthetic_only_for_example", "strict_block_without_principle_source",
    "topic_cannot_claim_sources", "duplicate_source_ref", "unknown_source_ref", "supported_content_needs_evidence",
    "source_not_from_material", "source_policy_or_context_changed", "missing_generated_content",
    "wrong_lesson_count", "lesson_duration_exceeds_study_time", "invented_concept_identity",
    "topic_unit_material_gap", "lesson_outline_mismatch", "lesson_needs_explanation_example_recap",
    "lesson_needs_self_check", "check_options_mismatch", "unavailable_draft_has_content",
    "course_criteria_changed", "goal_mismatch", "unsupported_prerequisite", "wrong_worked_example",
    "misleading_check", "unsupported_core_claim", "contradictory_core_claim", "answer_leaked",
    "terminology_dense", "example_too_abstract",
})

_LEGACY_ERRORS = {
    "Duplicate source_ref": "duplicate_source_ref",
    "Topic generation cannot invent citations": "topic_cannot_claim_sources",
    "Unknown source_ref": "unknown_source_ref",
    "Supported content needs evidence": "supported_content_needs_evidence",
    "Unavailable drafts cannot contain content": "unavailable_draft_has_content",
    "A course draft needs content": "missing_generated_content",
    "A lesson draft needs content": "missing_generated_content",
    "Duplicate unit_ref": "invalid_prerequisite",
    "Unknown or cyclic prerequisite": "invalid_prerequisite",
}


def safe_feedback_codes(codes) -> tuple[str, ...]:
    """Never put model values, field names, or provider text into a repair prompt."""
    return tuple(dict.fromkeys(code if code in DRAFT_ERROR_CODES else "schema_invalid" for code in codes))[:6]


class TeachingDraftInvalid(ValueError):
    def __init__(self, codes: tuple[str, ...]):
        self.codes = safe_feedback_codes(codes) or ("schema_invalid",)
        super().__init__("teaching_draft_invalid")


def validation_codes(error: ValueError | TypeError) -> tuple[str, ...]:
    if isinstance(error, ValidationError):
        codes = []
        for item in error.errors(include_input=False, include_url=False):
            if item["type"] == "extra_forbidden":
                codes.append("forbidden_field")
                continue
            cause = (item.get("ctx") or {}).get("error")
            message = str(cause) if cause is not None else ""
            codes.append(message if message in DRAFT_ERROR_CODES else _LEGACY_ERRORS.get(message, "schema_invalid"))
        return safe_feedback_codes(codes)
    message = str(error)
    return safe_feedback_codes((message if message in DRAFT_ERROR_CODES else _LEGACY_ERRORS.get(message, "schema_invalid"),))


def duplicate(values) -> bool:
    return len(values) != len(set(values))


def criterion_descriptions(criteria) -> list[str]:
    return [criterion.description for criterion in criteria]


def require_course_criteria(payload: CoursePayloadV2) -> None:
    refs = [item.course_criterion_ref for item in payload.course_criteria]
    if duplicate(refs):
        raise ValueError("duplicate_course_criterion_ref")
    if payload.mission.success_criteria != criterion_descriptions(payload.course_criteria):
        raise ValueError("success_criteria_display_mismatch")
    for unit in payload.units:
        if duplicate(unit.course_criterion_refs) or not set(unit.course_criterion_refs) <= set(refs):
            raise ValueError("unknown_or_duplicate_course_criterion_ref")
    used = {ref for unit in payload.units for ref in unit.course_criterion_refs}
    if used != set(refs):
        raise ValueError("course_criterion_without_unit")


def require_ordered_prerequisites(units: list[TeachUnitV2]) -> None:
    position = {unit.unit_ref: index for index, unit in enumerate(units)}
    by_ref = {unit.unit_ref: unit for unit in units}
    for index, unit in enumerate(units):
        for ref in unit.prerequisite_unit_refs or []:
            if ref not in position or position[ref] >= index:
                raise ValueError("prerequisite_not_before_unit")
            if unit.availability == "ready" and by_ref[ref].availability != "ready":
                raise ValueError("ready_unit_depends_on_material_gap")


def require_lesson_alignment(payload: LessonPayloadV2, unit: TeachUnitV2 | None = None) -> None:
    """Check both directions; an external saved unit additionally fixes the target set."""
    blocks = {block.block_ref: block for block in payload.blocks}
    checks = {check.check_ref: check for check in payload.checks}
    if len(blocks) != len(payload.blocks) or len(checks) != len(payload.checks):
        raise ValueError("duplicate_block_or_check_ref")
    aligned = [item.course_criterion_ref for item in payload.alignments]
    expected = set(unit.course_criterion_refs) if unit is not None else set(aligned)
    if duplicate(aligned) or set(aligned) != expected:
        raise ValueError("incomplete_course_criterion_alignment")
    for item in [*payload.blocks, *payload.checks]:
        if duplicate(item.course_criterion_refs) or not set(item.course_criterion_refs) <= expected:
            raise ValueError("item_outside_lesson_criteria")
    for alignment in payload.alignments:
        ref = alignment.course_criterion_ref
        for names, kind in (
            (alignment.explanation_block_refs, "explanation"),
            (alignment.example_block_refs, "example"),
        ):
            if duplicate(names):
                raise ValueError("duplicate_alignment_ref")
            for name in names:
                if name not in blocks or blocks[name].type != kind:
                    raise ValueError("alignment_block_type_mismatch")
                if ref not in blocks[name].course_criterion_refs:
                    raise ValueError("alignment_not_reciprocal")
            declared = {block.block_ref for block in payload.blocks if block.type == kind and ref in block.course_criterion_refs}
            if set(names) != declared:
                raise ValueError("alignment_not_reciprocal")
        if duplicate(alignment.check_refs):
            raise ValueError("duplicate_alignment_ref")
        for name in alignment.check_refs:
            if name not in checks or ref not in checks[name].course_criterion_refs:
                raise ValueError("alignment_check_mismatch")
        declared_checks = {check.check_ref for check in payload.checks if ref in check.course_criterion_refs}
        if set(alignment.check_refs) != declared_checks:
            raise ValueError("alignment_not_reciprocal")


def require_v2_block_sources(draft: LessonDraftV2) -> None:
    if draft.payload is None:
        return
    for block in draft.payload.blocks:
        if block.synthetic and block.type != "example":
            raise ValueError("synthetic_only_for_example")
        if draft.source_policy == "strict_docs" and not block.source_refs:
            raise ValueError("strict_block_without_principle_source")
        if draft.source_policy == "topic" and block.source_refs:
            raise ValueError("topic_cannot_claim_sources")
