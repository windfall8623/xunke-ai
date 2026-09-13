"""Public projection is explicit and does not mutate persisted artifacts."""

import copy
from unittest.mock import AsyncMock

import pytest

from app.teaching.contracts import LessonBlock, LessonCheck, TeachUnit


def test_application_criterion_projects_its_explanation_without_private_rubric():
    from app.services.course_application_service import _public_application_criterion

    stored = {
        "criterion_id": "r1", "credit": "full", "rationale": "回答说明了此项步骤。",
        "answer_quotes": ["先校验参数，再返回计算结果。"], "evidence_refs": [],
        "rubric": {"private": True}, "reference_answer": "未公开的标准答案",
    }
    before = copy.deepcopy(stored)
    assert _public_application_criterion(stored) == {
        "criterion_id": "r1", "credit": "full", "feedback": "回答说明了此项步骤。",
        "answer_quotes": ["先校验参数，再返回计算结果。"], "evidence_refs": [],
    }
    assert _public_application_criterion({**stored, "feedback": "已有公开反馈。"})["feedback"] == "已有公开反馈。"
    assert stored == before


def test_v2_projection_remains_readable_by_existing_public_types(valid_v2_course, valid_v2_lesson):
    from app.teaching.protocol import public_lesson_payload, public_unit

    before = copy.deepcopy(valid_v2_lesson)
    unit = public_unit(valid_v2_course["payload"]["units"][0], schema_version="xunke-teach.v2")
    payload = public_lesson_payload(valid_v2_lesson, schema_version="xunke-teach.v2")
    TeachUnit.model_validate(unit)
    for block in payload["blocks"]:
        LessonBlock.model_validate(block)
    for check in payload["checks"]:
        LessonCheck.model_validate(check)
    assert "course_criterion_refs" not in unit
    assert set(payload) == {"blocks", "checks", "next_step"}
    assert "block_ref" not in payload["blocks"][0]
    assert "course_criterion_refs" not in payload["checks"][0]
    assert valid_v2_lesson == before


def test_draft_hash_is_canonical_and_sensitive_to_content(valid_v2_lesson):
    from app.teaching.protocol import draft_hash

    reversed_keys = dict(reversed(list(valid_v2_lesson.items())))
    assert draft_hash(valid_v2_lesson) == draft_hash(reversed_keys)
    changed = copy.deepcopy(valid_v2_lesson)
    changed["payload"]["blocks"][0]["text"] = "不同内容"
    assert draft_hash(valid_v2_lesson) != draft_hash(changed)


@pytest.mark.parametrize("source_policy", ["topic", "strict_docs"])
def test_historical_v1_alias_preserves_identity_and_source_validation(
    valid_v2_course, valid_v1_lesson, strict_material, source_policy,
):
    from pydantic import ValidationError

    from app.teaching.contracts import CourseDraft, LessonDraft
    from app.teaching.protocol import (
        HISTORICAL_V1, draft_hash, parse_course_draft, parse_lesson_draft,
        public_lesson_payload, public_unit,
    )

    course, lesson = copy.deepcopy(valid_v2_course), copy.deepcopy(valid_v1_lesson)
    course["schema_version"] = "xunke-teach.v1"
    course["payload"].pop("course_criteria")
    for unit in course["payload"]["units"]:
        unit.pop("course_criterion_refs")
    if source_policy == "strict_docs":
        sources = [source.model_dump(mode="json") for source in strict_material.sources]
        for draft in (course, lesson):
            draft.update(source_policy=source_policy, sources=sources)
        for unit in course["payload"]["units"]:
            unit["source_refs"] = ["s1"]
        for block in lesson["payload"]["blocks"]:
            block["source_refs"] = ["s1"]
    # Published v1 artifacts already include their canonical defaults. Only
    # substitute the exact historical marker present in deployed old courses.
    course = CourseDraft.model_validate(course).model_dump(mode="json")
    lesson = LessonDraft.model_validate(lesson).model_dump(mode="json")
    for draft in (course, lesson):
        draft["schema_version"] = HISTORICAL_V1
    before = copy.deepcopy((course, lesson))
    parsed_course, parsed_lesson = parse_course_draft(course), parse_lesson_draft(lesson)
    assert parsed_course.model_dump(mode="json") == course
    assert parsed_lesson.model_dump(mode="json") == lesson
    assert draft_hash(parsed_course) == draft_hash(course)
    assert draft_hash(parsed_lesson) == draft_hash(lesson)
    assert public_unit(course["payload"]["units"][0], schema_version=HISTORICAL_V1)["title"]
    payload = public_lesson_payload(lesson, schema_version=HISTORICAL_V1)
    assert payload["blocks"][0]["source_refs"] == lesson["payload"]["blocks"][0]["source_refs"]
    assert (course, lesson) == before
    invalid = copy.deepcopy(lesson)
    invalid["payload"]["blocks"][0]["source_refs"] = ["outside_current_sources"]
    with pytest.raises(ValidationError):
        parse_lesson_draft(invalid)
    with pytest.raises(ValueError, match="unsupported_teach_schema_version"):
        parse_lesson_draft({**lesson, "schema_version": "zhixue-teach.v2"})


@pytest.mark.asyncio
async def test_course_and_lesson_services_return_valid_public_v2_views(monkeypatch, valid_v2_course, valid_v2_lesson):
    from app.models.course import CourseLessonView, CourseView
    from app.models.teaching_quality import TeachingQualitySummary
    from app.rag.contracts import ResolvedScope
    from app.services import course_outcome_service, course_quiz_service, course_read, teaching_quality_service

    metadata = copy.deepcopy(valid_v2_course)
    unit = metadata["payload"].pop("units")[0]
    course = {
        "course_id": "course-fixture", "owner_id": 7, "outline_json": metadata,
        "spec_json": {"topic": "函数"}, "outline_task_id": None, "source_policy": "topic",
        "status": "ready", "revision": 2, "created_at": "2026-09-13T00:00:00Z", "updated_at": "2026-09-13T00:00:00Z",
    }
    lesson = {
        "lesson_id": "lesson-fixture", "unit_json": unit, "content_json": valid_v2_lesson,
        "generation_task_id": None, "status": "ready", "revision": 2, "position": 0,
        "content_version": 1, "read_at": None, "last_opened_at": None,
    }
    monkeypatch.setattr(course_read, "authorize_course", AsyncMock(return_value=ResolvedScope(owner_id=7, namespace="production")))
    monkeypatch.setattr(course_read, "owned_course", AsyncMock(return_value=course))
    monkeypatch.setattr(course_read, "owned_lesson", AsyncMock(return_value=lesson))
    monkeypatch.setattr(course_read, "fetch_all", AsyncMock(return_value=[lesson]))
    monkeypatch.setattr(course_quiz_service, "list_quiz_links", AsyncMock(return_value=[]))

    async def quality_summary(_owner, _course_id, lesson_id=None, *, conn=None):
        return TeachingQualitySummary(
            level="lesson" if lesson_id else "outline", status="unreviewed", reason_code="legacy_content",
        ).model_dump(mode="json")

    # Published criteria and quality runs are host-owned reads; this case covers projection only.
    monkeypatch.setattr(teaching_quality_service, "quality_summary_for_course", quality_summary)
    monkeypatch.setattr(
        course_outcome_service, "course_outcome_fields",
        AsyncMock(return_value=dict(criteria_revision=1, course_criteria=[])),
    )
    course_view = CourseView.model_validate(await course_read.course_view(course))
    lesson_view = CourseLessonView.model_validate(await course_read.get_lesson(7, "course-fixture", "lesson-fixture"))
    assert course_view.mission.success_criteria == ["解释函数参数与返回值"]
    assert lesson_view.checks[0].prompt == valid_v2_lesson["payload"]["checks"][0]["prompt"]
    assert "alignments" not in lesson_view.model_dump()
