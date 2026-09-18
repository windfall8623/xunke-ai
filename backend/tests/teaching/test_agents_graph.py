"""Real LangGraph routes with bounded local providers and a claim journal."""

import copy
from dataclasses import replace

import pytest

from app.core.values import digest
from app.rag.budget import BudgetLedger
from app.teaching.context import TeachingMaterial
from app.teaching.contracts_v2 import CourseDraftV2
from app.teaching.generator import CourseGenerator
from app.teaching.policy import freeze_teaching_policy
from app.teaching.review_contracts import TeachingAgentInput, TeachingAgentPorts
from tests.teaching.conftest import ScriptedChat, reply
from tests.teaching.test_review_policy import passing_proposal


def blocking_proposal():
    result = passing_proposal()
    result["dimensions"][2]["result"] = "fail"
    result["findings"] = [{"code": "wrong_worked_example", "dimension": "example_correctness",
        "severity": "blocking", "course_criterion_refs": ["cc1"], "block_refs": ["b2"],
        "explanation": "示例步骤需要修改", "suggestion": "明确输入、计算过程与返回结果"}]
    return result


def input_for(course, spec):
    payload = CourseDraftV2.model_validate(course).payload
    return TeachingAgentInput(
        kind="lesson", spec=spec, unit=payload.units[0], course_criteria=tuple(payload.course_criteria),
        material=TeachingMaterial(), plan_hash=digest("saved-plan"), criteria_revision=1,
        scope_fingerprint=digest("topic-scope"), frozen_plan=payload.model_dump(mode="json"),
    )


def ports_for(chat, policy):
    from app.teaching.agents import PlannerAgent, ReviewerAgent, TeacherAgent
    from app.teaching.reviewer import TeachingReviewer

    generator = CourseGenerator(chat, chat, reviewer=TeachingReviewer(chat))
    journal, phases, summaries, checkpoints = [], [], [], []

    async def authorize():
        return None

    async def claim(stage, *, candidate_hash):
        assert stage not in journal, "a durable slot cannot be replayed"
        journal.append(stage)

    async def heartbeat(stage):
        phases.append(stage)

    async def checkpoint(state):
        checkpoints.append(dict(state))

    ports = TeachingAgentPorts(
        planner=PlannerAgent(generator, policy), teacher=TeacherAgent(generator, policy),
        reviewer=ReviewerAgent(generator.reviewer, policy), authorize=authorize,
        claim_stage=claim, heartbeat=heartbeat, checkpoint=checkpoint, record_summary=summaries.append,
    )
    return ports, journal, phases, summaries


@pytest.mark.asyncio
async def test_guided_lesson_reuses_plan_and_reviews_the_actual_draft(valid_v2_course, valid_v2_lesson, topic_spec):
    from app.teaching.graph import run_teaching_graph

    request = input_for(valid_v2_course, topic_spec)
    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    budget = BudgetLedger(policy.budget_limits(300))
    chat = ScriptedChat(reply(valid_v2_lesson), reply(passing_proposal()))
    ports, claims, phases, summaries = ports_for(chat, policy)
    result = await run_teaching_graph(request, policy, ports, budget=budget, run_id="fixture")
    assert result["terminal_reason"] == "completed"
    assert claims == ["initial", "review_initial"]
    assert phases == ["teaching", "reviewing"]
    assert result["report"].draft_hash == result["candidate"]["draft_hash"]
    assert budget.snapshot().llm_calls == 2
    assert [stage.stage for stage in summaries[0].stages] == ["teacher", "validate", "reviewer", "finish"]


@pytest.mark.asyncio
async def test_schema_repair_consumes_the_only_content_repair_slot(valid_v2_course, valid_v2_lesson, topic_spec):
    from app.teaching.graph import run_teaching_graph

    request = input_for(valid_v2_course, topic_spec)
    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    budget = BudgetLedger(policy.budget_limits(300))
    chat = ScriptedChat(reply("bad json"), reply(valid_v2_lesson), reply(blocking_proposal()))
    ports, claims, _, _ = ports_for(chat, policy)
    result = await run_teaching_graph(request, policy, ports, budget=budget, run_id="fixture")
    assert claims == ["initial", "repair", "review_initial"]
    assert result["repair_used"] is True
    assert result["terminal_reason"] == "course_quality_blocked"
    assert budget.snapshot().llm_calls == 3


@pytest.mark.asyncio
async def test_blocking_review_repairs_once_and_rechecks_new_hash(valid_v2_course, valid_v2_lesson, topic_spec):
    from app.teaching.graph import run_teaching_graph

    revised = copy.deepcopy(valid_v2_lesson)
    revised["payload"]["blocks"][1]["text"] += "返回值由调用处接收。"
    request = input_for(valid_v2_course, topic_spec)
    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    budget = BudgetLedger(policy.budget_limits(300))
    chat = ScriptedChat(reply(valid_v2_lesson), reply(blocking_proposal()), reply(revised), reply(passing_proposal()))
    ports, claims, phases, _ = ports_for(chat, policy)
    result = await run_teaching_graph(request, policy, ports, budget=budget, run_id="fixture")
    assert claims == ["initial", "review_initial", "repair", "review_recheck"]
    assert phases == ["teaching", "reviewing", "revising", "reviewing"]
    assert result["generation_revision"] == 2 and result["report"].status == "passed"
    assert result["candidate"]["draft"]["payload"]["blocks"][1]["text"] == revised["payload"]["blocks"][1]["text"]
    assert budget.snapshot().llm_calls == 4


@pytest.mark.asyncio
async def test_insufficient_recheck_window_stops_before_repair(valid_v2_course, valid_v2_lesson, topic_spec):
    from app.teaching.graph import run_teaching_graph

    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    budget = BudgetLedger(policy.budget_limits(124), clock=lambda: 0)
    ports, claims, _, _ = ports_for(ScriptedChat(reply(valid_v2_lesson), reply(blocking_proposal())), policy)
    result = await run_teaching_graph(input_for(valid_v2_course, topic_spec), policy, ports, budget=budget, run_id="fixture")
    assert result["terminal_reason"] == "course_quality_blocked"
    assert claims == ["initial", "review_initial"]


@pytest.mark.asyncio
async def test_incomplete_review_cannot_publish_or_start_a_reviewer_retry(valid_v2_course, valid_v2_lesson, topic_spec):
    from app.teaching.graph import run_teaching_graph

    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    budget = BudgetLedger(policy.budget_limits(300))
    ports, claims, _, _ = ports_for(ScriptedChat(reply(valid_v2_lesson), reply({"dimensions": [], "findings": []})), policy)
    result = await run_teaching_graph(input_for(valid_v2_course, topic_spec), policy, ports, budget=budget, run_id="fixture")
    assert result["terminal_reason"] == "course_quality_unavailable"
    assert result["report"].status == "unreviewed"
    assert claims == ["initial", "review_initial"]


@pytest.mark.asyncio
async def test_fast_and_observer_failure_do_not_add_review_calls(valid_v2_course, valid_v2_lesson, topic_spec):
    from app.teaching.graph import run_teaching_graph

    policy = freeze_teaching_policy("lesson", "fast", False, "topic")
    budget = BudgetLedger(policy.budget_limits(300))
    ports, claims, _, _ = ports_for(ScriptedChat(reply(valid_v2_lesson)), policy)

    def broken_observer(_summary):
        raise RuntimeError("observer unavailable")

    result = await run_teaching_graph(
        input_for(valid_v2_course, topic_spec), policy, replace(ports, record_summary=broken_observer),
        budget=budget, run_id="fixture",
    )
    assert result["terminal_reason"] == "completed"
    assert result["report"] is None
    assert claims == ["initial"] and budget.snapshot().llm_calls == 1


@pytest.mark.asyncio
async def test_unknown_stage_outcome_emits_its_reason_without_a_model_retry(valid_v2_course, topic_spec):
    from app.core.errors import AppError, conflict
    from app.teaching.graph import run_teaching_graph

    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    budget = BudgetLedger(policy.budget_limits(300))
    chat = ScriptedChat()
    ports, _, _, summaries = ports_for(chat, policy)

    async def unknown_claim(stage, *, candidate_hash):
        raise conflict("teaching_call_outcome_unknown", "前次调用结果尚未确认")

    with pytest.raises(AppError) as stopped:
        await run_teaching_graph(
            input_for(valid_v2_course, topic_spec), policy, replace(ports, claim_stage=unknown_claim),
            budget=budget, run_id="fixture",
        )
    assert stopped.value.code == "teaching_call_outcome_unknown"
    assert budget.snapshot().llm_calls == 0
    assert summaries[0].terminal_reason == "teaching_call_outcome_unknown"
    assert summaries[0].status == "failed"
    assert summaries[0].stages[-1].error_code == "teaching_call_outcome_unknown"
