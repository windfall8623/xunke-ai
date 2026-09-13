"""A finite LangGraph for course roles; durable ports own slots and publication."""

import asyncio
from dataclasses import replace

from app.core.errors import AppError
from app.rag.errors import BudgetExceeded, ProviderRateLimited, ProviderTimeout, ProviderUnavailable
from app.rag.graph_trace import ERROR_CODES, GraphSummaryRecorder, emit_summary, terminal_reason_for
from app.teaching.contracts_v2 import CourseCriterionDraft
from app.teaching.generator import CourseGenerator
from app.teaching.policy import can_repair, can_review
from app.teaching.protocol import draft_hash, parse_course_draft, parse_lesson_draft
from app.teaching.quality import TeachingDraftInvalid, validation_codes
from app.teaching.review_contracts import TeachingAgentState, require_review_binding
from app.teaching.reviewer import TeachingReviewUnavailable, bind_report

HARD_SOURCE_CODES = frozenset({
    "source_not_from_material", "source_policy_or_context_changed", "topic_cannot_claim_sources",
    "unknown_source_ref", "strict_block_without_principle_source", "supported_content_needs_evidence",
})


def route_after_review(state, *, can_repair_and_recheck):
    report = state.get("report")
    if report is None or report.status == "unreviewed":
        return "stop"
    if report.status == "passed":
        return "finish_reviewed"
    if state["repair_used"] or not can_repair_and_recheck:
        return "stop"
    return "repair"


def compile_teaching_graph(nodes):
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(TeachingAgentState)
    for name, node in nodes.items():
        graph.add_node(name, node)
    graph.add_edge(START, "authorize")
    graph.add_conditional_edges("authorize", lambda state: state["next_node"], {
        name: name for name in ("planner", "teacher", "validate", "stop")
    })
    graph.add_edge("planner", "validate")
    graph.add_edge("teacher", "validate")
    graph.add_conditional_edges("validate", lambda state: state["next_node"], {
        name: name for name in ("reviewer", "repair", "stop", "finish_reviewed", "finish_unreviewed")
    })
    graph.add_conditional_edges("reviewer", lambda state: state["next_node"], {
        name: name for name in ("repair", "finish_reviewed", "stop")
    })
    graph.add_edge("repair", "revalidate")
    graph.add_conditional_edges("revalidate", lambda state: state["next_node"], {
        name: name for name in ("recheck", "finish_unreviewed", "stop")
    })
    graph.add_conditional_edges("recheck", lambda state: state["next_node"], {
        name: name for name in ("finish_reviewed", "stop")
    })
    for name in ("finish_reviewed", "finish_unreviewed", "stop"):
        graph.add_edge(name, END)
    return graph.compile()


def _summary_reason(error):
    code = getattr(error, "code", "")
    code = {
        "stale_lease": "lease_lost", "course_material_gap": "material_gap",
        "course_criteria_changed": "criteria_revision_changed",
    }.get(code, code)
    return code if code in ERROR_CODES else terminal_reason_for(error)


async def run_teaching_graph(request, policy, ports, *, budget, run_id, initial_state=None):
    recorder = GraphSummaryRecorder("course_teaching", run_id)
    initial = TeachingAgentState(
        request=request, candidate=None, deterministic_codes=(), report=None,
        generation_revision=1, repair_used=False, review_calls_started=0,
        known_blocking=False, terminal_reason=None, reason_code=None, completed_slot=None, trace=[],
    )
    if initial_state:
        initial.update(initial_state)
        initial["request"] = request

    async def checkpoint(state):
        await ports.checkpoint(state)
        return state

    def stop_with(state, code, reason):
        state.update(next_node="stop", terminal_reason=code, reason_code=reason)
        return state

    async def authorize(state):
        await ports.authorize()
        budget.check()
        state = dict(state)
        state["next_node"] = (
            "validate" if state.get("candidate") or state.get("deterministic_codes")
            else "planner" if request.kind == "outline" else "teacher"
        )
        return state

    async def generate(state, *, repair=False):
        state = dict(state)
        await ports.authorize()
        if repair and (state["repair_used"] or not can_repair(policy, budget)):
            return stop_with(state, "course_quality_blocked" if state["known_blocking"] else "course_generation_invalid", "repair_unavailable")
        slot = "repair" if repair else "initial"
        await ports.claim_stage(slot, candidate_hash=state["candidate"]["draft_hash"] if state.get("candidate") else None)
        if repair:
            state["repair_used"] = True  # Only after a successful durable claim.
            state["generation_revision"] = 2
            # The earlier draft's checks never carry over, so its preview cannot either.
            from app.services.content_event_service import reset_current_preview

            await reset_current_preview(state["generation_revision"])
        await ports.heartbeat("revising" if repair else "planning" if request.kind == "outline" else "teaching")
        candidate, report = state.get("candidate"), state.get("report")
        criteria = request.course_criteria
        if repair and request.kind == "outline" and candidate is not None:
            criteria = tuple(CourseCriterionDraft.model_validate(item) for item in candidate["draft"]["payload"]["course_criteria"])
        findings = tuple(report.proposal.findings) if repair and report is not None and report.proposal else ()
        agent_input = replace(
            request, generation_revision=state["generation_revision"], course_criteria=criteria,
            feedback_codes=state.get("deterministic_codes", ()) or tuple(finding.code for finding in findings),
            findings=findings,
        )
        state.update(candidate=None, report=None, deterministic_codes=(), completed_slot=slot)
        try:
            agent = ports.planner if request.kind == "outline" else ports.teacher
            state["candidate"] = await agent(agent_input, budget=budget)
        except TeachingDraftInvalid as exc:
            state["deterministic_codes"] = exc.codes
        return await checkpoint(state)

    async def validate(state, *, repaired=False):
        state = dict(state)
        if state.get("terminal_reason") not in {None, "completed"}:
            state["next_node"] = "stop"
            return await checkpoint(state)
        candidate = state.get("candidate")
        if candidate is not None:
            try:
                raw = candidate["draft"]
                if candidate["draft_hash"] != draft_hash(raw):
                    raise ValueError("schema_invalid")
                parsed = parse_course_draft(raw) if request.kind == "outline" else parse_lesson_draft(raw)
                CourseGenerator._validate(parsed, request.kind, request.spec, request.unit, request.material)
            except (ValueError, TypeError) as exc:
                state.update(candidate=None, deterministic_codes=validation_codes(exc))
        if state.get("candidate") is None:
            if not state["repair_used"] and not HARD_SOURCE_CODES.intersection(state.get("deterministic_codes", ())) and can_repair(policy, budget):
                state["next_node"] = "repair"
            else:
                stop_with(state, "course_quality_blocked" if state["known_blocking"] else "course_generation_invalid", "deterministic_validation_failed")
        elif not policy.review_enabled:
            state["next_node"] = "finish_unreviewed"
        elif repaired:
            state["next_node"] = "recheck"
        elif state.get("report") is not None:
            try:
                require_review_binding(state["report"], state["candidate"], request, skill_hash=state["candidate"]["skill_hash"], policy_hash=policy.policy_hash)
                state["next_node"] = route_after_review(state, can_repair_and_recheck=can_repair(policy, budget))
            except ValueError:
                stop_with(state, "course_quality_unavailable", "review_binding_mismatch")
            if state["next_node"] == "stop" and not state.get("terminal_reason"):
                stop_with(state, "course_quality_blocked" if state["known_blocking"] else "course_quality_unavailable", "review_incomplete")
        else:
            state["next_node"] = "reviewer"
        return await checkpoint(state)

    async def review(state, *, recheck=False):
        state = dict(state)
        candidate = state["candidate"]
        await ports.authorize()
        if not can_review(policy, budget) or state["review_calls_started"] >= policy.max_review_calls:
            state["report"] = bind_report(request, candidate, policy_hash=policy.policy_hash, reason_code="review_budget_or_deadline")
        else:
            slot = "review_initial" if state["review_calls_started"] == 0 else "review_recheck"
            await ports.claim_stage(slot, candidate_hash=candidate["draft_hash"])
            state["review_calls_started"] += 1
            state["completed_slot"] = slot
            await ports.heartbeat("reviewing")
            try:
                state["report"] = await ports.reviewer(
                    replace(request, generation_revision=state["generation_revision"]), candidate,
                    budget=budget, policy_hash=policy.policy_hash,
                )
                require_review_binding(state["report"], candidate, request, skill_hash=candidate["skill_hash"], policy_hash=policy.policy_hash)
            except TeachingReviewUnavailable as exc:
                state["report"] = bind_report(request, candidate, policy_hash=policy.policy_hash, reason_code=exc.reason_code)
            except (TimeoutError, ProviderTimeout, ProviderRateLimited, ProviderUnavailable, BudgetExceeded) as exc:
                reason = "review_timeout" if isinstance(exc, (TimeoutError, ProviderTimeout)) else "review_budget" if isinstance(exc, BudgetExceeded) else "review_provider_unavailable"
                state["report"] = bind_report(request, candidate, policy_hash=policy.policy_hash, reason_code=reason)
            except ValueError:
                state["report"] = bind_report(request, candidate, policy_hash=policy.policy_hash, reason_code="review_binding_mismatch")
        if state["report"].status == "needs_revision":
            state["known_blocking"] = True
        state["next_node"] = route_after_review(state, can_repair_and_recheck=not recheck and can_repair(policy, budget))
        if state["next_node"] == "stop":
            stop_with(state, "course_quality_blocked" if state["known_blocking"] else "course_quality_unavailable", state["report"].reason_code or "blocking_findings")
        return await checkpoint(state)

    async def finish(state, *, reviewed):
        state = dict(state)
        await ports.authorize()
        budget.check()
        if state.get("candidate") is None or state.get("deterministic_codes"):
            raise AppError(422, "course_generation_invalid", "课程草案未通过基本检查")
        if reviewed:
            if state.get("report") is None or state["report"].status != "passed":
                raise AppError(422, "course_quality_unavailable", "教学核对未完成")
            require_review_binding(state["report"], state["candidate"], request, skill_hash=state["candidate"]["skill_hash"], policy_hash=policy.policy_hash)
        elif policy.review_enabled:
            raise AppError(422, "course_quality_unavailable", "所请求的教学核对未完成")
        state.update(terminal_reason="completed", reason_code=None if reviewed else "not_requested", completed_slot=None)
        return await checkpoint(state)

    async def stop(state):
        return await checkpoint(dict(state))

    def tracked(name, func):
        async def run(state):
            state = dict(state)
            state["trace"] = [*state.get("trace", []), name]
            summary_stage = {"recheck": "reviewer", "finish_reviewed": "finish", "finish_unreviewed": "finish"}.get(name, name)
            if name == "authorize":
                return await func(state)
            revision = 2 if name == "repair" else state["generation_revision"]
            recorder.begin(summary_stage, budget.snapshot(), generation_revision=revision, generation_attempt=revision)
            try:
                result = await func(state)
            except BaseException as exc:
                recorder.end(summary_stage, budget.snapshot(), status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed", branch="stop", error_code=_summary_reason(exc))
                raise
            route = result.get("next_node")
            branch = "quality_repair" if route == "repair" and result.get("known_blocking") else "retry_generation" if route == "repair" else "stop" if name == "stop" else "next"
            recorder.end(summary_stage, budget.snapshot(), branch=branch)
            return result
        return run

    nodes = {
        "authorize": authorize,
        "planner": generate, "teacher": generate,
        "validate": validate, "reviewer": review,
        "repair": lambda state: generate(state, repair=True),
        "revalidate": lambda state: validate(state, repaired=True),
        "recheck": lambda state: review(state, recheck=True),
        "finish_reviewed": lambda state: finish(state, reviewed=True),
        "finish_unreviewed": lambda state: finish(state, reviewed=False),
        "stop": stop,
    }
    compiled = compile_teaching_graph({name: tracked(name, node) for name, node in nodes.items()})
    try:
        result = await compiled.ainvoke(initial, config={"recursion_limit": 16})
    except BaseException as exc:
        emit_summary(ports.record_summary, recorder.finish(
            status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
            terminal_reason=_summary_reason(exc), usage=budget.snapshot(),
        ))
        raise
    emit_summary(ports.record_summary, recorder.finish(
        status="completed" if result["terminal_reason"] == "completed" else "failed",
        terminal_reason=result["terminal_reason"], usage=budget.snapshot(),
    ))
    return result
