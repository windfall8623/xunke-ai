"""Single-call generation and bounded repair against a scripted transport."""

import json

import pytest

from app.core.errors import AppError
from app.rag.errors import BudgetExceeded, ProviderRateLimited, ScopeRevoked
from app.teaching.context import TeachingMaterial
from app.teaching.contracts import TeachUnit
from app.teaching.generator import CourseGenerator
from tests.teaching.conftest import ScriptedChat, reply


@pytest.mark.asyncio
async def test_single_call_does_not_hide_a_schema_retry(valid_v2_course, topic_spec, teaching_budget):
    from app.teaching.quality import TeachingDraftInvalid

    chat = ScriptedChat(reply("not-json", output_tokens=37), reply(valid_v2_course))
    generator = CourseGenerator(chat, chat)
    with pytest.raises(TeachingDraftInvalid):
        await generator.generate_once("outline", topic_spec, TeachingMaterial(), budget=teaching_budget)
    assert teaching_budget.snapshot().llm_calls == 1
    assert teaching_budget.snapshot().output_tokens == 37


@pytest.mark.asyncio
async def test_repair_preserves_failed_usage_and_never_resends_raw_output(valid_v2_course, topic_spec, teaching_budget):
    chat = ScriptedChat(reply("secret malformed response", output_tokens=37), reply(valid_v2_course, output_tokens=80))
    result = await CourseGenerator(chat, chat).outline(topic_spec, TeachingMaterial(), budget=teaching_budget)
    assert result["draft"]["schema_version"] == "xunke-teach.v2"
    assert result["effective_config"]["generation_attempts"] == 2
    assert teaching_budget.snapshot().llm_calls == 2
    assert teaching_budget.snapshot().output_tokens == 117
    assert len(result["draft_hash"]) == 64
    assert "secret malformed response" not in json.dumps([m.content for m in chat.calls[1]])


@pytest.mark.asyncio
async def test_two_bad_drafts_fail_without_a_third_call(topic_spec, teaching_budget):
    chat = ScriptedChat(reply("bad"), reply("bad"), reply("must not be called"))
    with pytest.raises(AppError) as failure:
        await CourseGenerator(chat, chat).outline(topic_spec, TeachingMaterial(), budget=teaching_budget)
    assert failure.value.code == "course_generation_invalid"
    assert teaching_budget.snapshot().llm_calls == 2
    assert teaching_budget.snapshot().output_tokens == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ProviderRateLimited(), ScopeRevoked(), TimeoutError(), BudgetExceeded()])
async def test_operational_failures_never_trigger_repair(topic_spec, teaching_budget, error):
    chat = ScriptedChat(error, reply("must not be called"))
    with pytest.raises(type(error)):
        await CourseGenerator(chat, chat).outline(topic_spec, TeachingMaterial(), budget=teaching_budget)
    assert teaching_budget.snapshot().llm_calls == 1


@pytest.mark.asyncio
async def test_truncated_response_is_counted_and_fails_without_repair(valid_v2_course, topic_spec, teaching_budget):
    chat = ScriptedChat(reply(valid_v2_course, output_tokens=100, response_metadata={"finish_reason": "length"}))
    with pytest.raises(AppError) as failure:
        await CourseGenerator(chat, chat).outline(topic_spec, TeachingMaterial(), budget=teaching_budget)
    assert failure.value.code == "course_generation_incomplete"
    assert teaching_budget.snapshot().llm_calls == 1
    assert teaching_budget.snapshot().output_tokens == 100


@pytest.mark.asyncio
async def test_output_budget_is_enforced_before_parsing(topic_spec, teaching_budget):
    chat = ScriptedChat(reply("bad json", output_tokens=3001))
    with pytest.raises(BudgetExceeded):
        await CourseGenerator(chat, chat).outline(topic_spec, TeachingMaterial(), budget=teaching_budget)
    assert teaching_budget.snapshot().output_tokens == 3001
    assert teaching_budget.snapshot().llm_calls == 1


@pytest.mark.asyncio
async def test_unknown_usage_is_conservative_and_labeled(valid_v2_course, topic_spec, teaching_budget):
    chat = ScriptedChat(reply(valid_v2_course, output_tokens=None))
    result = await CourseGenerator(chat, chat).outline(topic_spec, TeachingMaterial(), budget=teaching_budget)
    assert teaching_budget.snapshot().output_tokens > 0
    assert result["effective_config"]["output_token_count_method"] == "utf8-upper-bound-v1"


@pytest.mark.asyncio
async def test_legacy_outline_can_generate_a_v1_lesson(valid_v2_course, valid_v1_lesson, topic_spec, teaching_budget):
    raw_unit = dict(valid_v2_course["payload"]["units"][0])
    raw_unit.pop("course_criterion_refs")
    unit = TeachUnit.model_validate(raw_unit)
    chat = ScriptedChat(reply(valid_v1_lesson))
    result = await CourseGenerator(chat, chat).lesson(topic_spec, unit, TeachingMaterial(), budget=teaching_budget)
    assert result["draft"]["schema_version"] == "xunke-teach.v1"
    assert "alignments" not in result["draft"]["payload"]


@pytest.mark.asyncio
async def test_new_lesson_cannot_replace_saved_targets(valid_v2_course, valid_v2_lesson, topic_spec, teaching_budget):
    from app.teaching.contracts_v2 import CourseDraftV2
    from app.teaching.quality import TeachingDraftInvalid

    course = CourseDraftV2.model_validate(valid_v2_course).payload
    for item in [*valid_v2_lesson["payload"]["blocks"], *valid_v2_lesson["payload"]["checks"]]:
        item["course_criterion_refs"] = ["cc2"]
    valid_v2_lesson["payload"]["alignments"][0]["course_criterion_ref"] = "cc2"
    chat = ScriptedChat(reply(valid_v2_lesson))
    with pytest.raises(TeachingDraftInvalid) as failure:
        await CourseGenerator(chat, chat).generate_once(
            "lesson", topic_spec, TeachingMaterial(), unit=course.units[0],
            course_criteria=course.course_criteria, budget=teaching_budget,
        )
    assert "incomplete_course_criterion_alignment" in failure.value.codes


@pytest.mark.asyncio
async def test_source_identity_must_match_the_actual_material(valid_v2_course, strict_material, teaching_budget):
    from app.models.course import CourseCreate
    from app.teaching.quality import TeachingDraftInvalid

    spec = CourseCreate(topic="函数", lesson_count=1, source_policy="strict_docs", scope={"documents": [{"doc_id": "fixture-doc"}]})
    valid_v2_course["source_policy"] = "strict_docs"
    valid_v2_course["sources"] = [source.model_dump(mode="json") for source in strict_material.sources]
    valid_v2_course["payload"]["units"][0]["source_refs"] = ["s1"]
    valid_v2_course["sources"][0]["evidence_id"] = "invented-evidence"
    chat = ScriptedChat(reply(valid_v2_course))
    with pytest.raises(TeachingDraftInvalid) as failure:
        await CourseGenerator(chat, chat).generate_once("outline", spec, strict_material, budget=teaching_budget)
    assert failure.value.codes == ("source_not_from_material",)


@pytest.mark.asyncio
async def test_material_gap_is_terminal_and_does_not_use_schema_repair(topic_spec, teaching_budget):
    spec = topic_spec.model_copy(update={"source_policy": "strict_docs"})
    draft = {"schema_version": "xunke-teach.v2", "kind": "course_draft", "source_policy": "strict_docs",
             "status": "insufficient_evidence", "payload": None}
    chat = ScriptedChat(reply(draft))
    with pytest.raises(AppError) as failure:
        await CourseGenerator(chat, chat).outline(spec, TeachingMaterial(), budget=teaching_budget)
    assert failure.value.code == "course_material_gap"
    assert teaching_budget.snapshot().llm_calls == 1
    assert teaching_budget.snapshot().output_tokens == 100
