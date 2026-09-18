"""Reject broken learning relationships, while preserving historical v1 reads."""

import copy

import pytest
from pydantic import ValidationError


def test_course_mission_and_local_targets_cannot_disagree(valid_v2_course):
    from app.teaching.contracts_v2 import CourseDraftV2

    assert CourseDraftV2.model_validate(valid_v2_course).payload.course_criteria[0].course_criterion_ref == "cc1"
    valid_v2_course["payload"]["mission"]["success_criteria"] = ["另一目标"]
    with pytest.raises(ValidationError, match="success_criteria_display_mismatch"):
        CourseDraftV2.model_validate(valid_v2_course)


@pytest.mark.parametrize("broken", ["no_check", "wrong_type", "unknown", "reverse_missing", "duplicate"])
def test_lesson_rejects_broken_alignment(valid_v2_lesson, broken):
    from app.teaching.contracts_v2 import LessonDraftV2

    payload = valid_v2_lesson["payload"]
    if broken == "no_check":
        payload["alignments"][0]["check_refs"] = []
    elif broken == "wrong_type":
        payload["alignments"][0]["example_block_refs"] = ["b3"]
    elif broken == "unknown":
        payload["checks"][0]["course_criterion_refs"] = ["cc2"]
    elif broken == "reverse_missing":
        payload["blocks"].append({**payload["blocks"][0], "block_ref": "b4"})
    else:
        payload["blocks"][1]["block_ref"] = "b1"
    with pytest.raises(ValidationError):
        LessonDraftV2.model_validate(valid_v2_lesson)


def test_one_check_can_cover_two_targets(valid_v2_lesson):
    from app.teaching.contracts_v2 import LessonDraftV2

    payload = valid_v2_lesson["payload"]
    for item in [*payload["blocks"], *payload["checks"]]:
        item["course_criterion_refs"].append("cc2")
    payload["alignments"].append({**payload["alignments"][0], "course_criterion_ref": "cc2"})
    result = LessonDraftV2.model_validate(valid_v2_lesson)
    assert result.payload.checks[0].course_criterion_refs == ["cc1", "cc2"]


@pytest.mark.parametrize("invalid", ["forward", "material_gap", "uncovered", "duplicate"])
def test_course_rejects_unreachable_targets_and_prerequisites(valid_v2_course, invalid):
    from app.teaching.contracts_v2 import CourseDraftV2

    payload = valid_v2_course["payload"]
    first = payload["units"][0]
    second = copy.deepcopy(first)
    second["unit_ref"] = "u2"
    second["prerequisite_unit_refs"] = ["u1"]
    payload["units"].append(second)
    if invalid == "forward":
        second["prerequisite_unit_refs"] = []
        first["prerequisite_unit_refs"] = ["u2"]
    elif invalid == "material_gap":
        first["availability"] = "material_gap"
    elif invalid == "uncovered":
        criterion = {**payload["course_criteria"][0], "course_criterion_ref": "cc2", "description": "设计函数"}
        payload["course_criteria"].append(criterion)
        payload["mission"]["success_criteria"].append("设计函数")
    else:
        first["course_criterion_refs"] = ["cc1", "cc1"]
    with pytest.raises(ValidationError):
        CourseDraftV2.model_validate(valid_v2_course)


def test_strict_constructed_example_still_needs_a_real_source(valid_v2_lesson, strict_material):
    from app.teaching.contracts_v2 import LessonDraftV2

    valid_v2_lesson["source_policy"] = "strict_docs"
    valid_v2_lesson["sources"] = [source.model_dump(mode="json") for source in strict_material.sources]
    for block in valid_v2_lesson["payload"]["blocks"]:
        block["source_refs"] = ["s1"]
    LessonDraftV2.model_validate(valid_v2_lesson)
    valid_v2_lesson["payload"]["blocks"][1]["source_refs"] = []
    with pytest.raises(ValidationError, match="strict_block_without_principle_source"):
        LessonDraftV2.model_validate(valid_v2_lesson)


@pytest.mark.parametrize("invalid", ["topic_source", "synthetic_explanation", "answer", "rubric", "score"])
def test_new_drafts_reject_source_loopholes_and_private_answers(valid_v2_lesson, invalid):
    from app.teaching.contracts_v2 import LessonDraftV2

    if invalid == "topic_source":
        valid_v2_lesson["payload"]["blocks"][0]["source_refs"] = ["s1"]
    elif invalid == "synthetic_explanation":
        valid_v2_lesson["payload"]["blocks"][0]["synthetic"] = True
    else:
        valid_v2_lesson["payload"]["checks"][0][invalid] = "private"
    with pytest.raises(ValidationError):
        LessonDraftV2.model_validate(valid_v2_lesson)


def test_historical_v1_does_not_acquire_target_alignment(valid_v1_lesson):
    from app.teaching.protocol import parse_lesson_draft

    before = copy.deepcopy(valid_v1_lesson)
    result = parse_lesson_draft(valid_v1_lesson)
    assert result.schema_version == "xunke-teach.v1"
    assert "alignments" not in result.payload.model_dump()
    assert valid_v1_lesson == before


def test_unknown_versions_are_not_inferred_from_fields(valid_v2_lesson):
    from app.teaching.protocol import parse_lesson_draft

    valid_v2_lesson["schema_version"] = "xunke-teach.v3"
    with pytest.raises(ValueError, match="unsupported_teach_schema_version"):
        parse_lesson_draft(valid_v2_lesson)
