"""Course generation and publication share the owner's durable task lease."""

from app.core.config import get_settings
from app.core.db import execute, transaction
from app.core.errors import AppError, conflict
from app.core.values import dump, load, now, uid
from app.models.course import CourseCreate
from app.rag.budget import BudgetLedger
from app.rag.contracts import ResolvedScope
from app.rag.errors import BudgetExceeded
from app.rag.graph_trace import SummarySink, emit_summary
from app.services import (
    content_event_service, course_outcome_service, course_read, course_teaching, job_service,
    teaching_quality_service,
)
from app.services.evaluation_service import pipeline_config
from app.teaching.context import lesson_material, outline_material
from app.teaching.contracts_v2 import CourseCriterionDraft
from app.teaching.generator import CourseGenerator
from app.teaching.agents import PlannerAgent, ReviewerAgent, TeacherAgent
from app.teaching.graph import run_teaching_graph
from app.teaching.policy import policy_from_job
from app.teaching.protocol import V2, draft_hash, parse_course_draft, parse_lesson_draft, parse_teach_unit
from app.teaching.review_contracts import TeachingAgentInput, TeachingAgentPorts


async def _authorized(job, *, conn=None, lock=False):
    request = job["request"]
    course = await course_read.owned_course(job["user_id"], request["course_id"], conn=conn, lock=lock)
    scope = await course_read.authorize_course(course, conn=conn)
    if job["mode"] != "production" or scope != ResolvedScope.model_validate(job["scope"]) or request["scope_fingerprint"] != scope.fingerprint:
        raise conflict("course_scope_changed", "课程来源与生成任务不匹配")
    if "criteria_revision" in request and course.get("criteria_revision", 1) != request["criteria_revision"]:
        raise conflict("course_criteria_changed", "课程目标已更新")
    lesson = None
    if job["kind"] == "course_outline":
        if course["active_task_id"] != job["task_id"] or course["outline_json"]:
            raise conflict("course_task_replaced", "课程生成任务已更新")
    else:
        lesson = await course_read.owned_lesson(job["user_id"], course["course_id"], request["lesson_id"], conn=conn, lock=lock)
        revision_mode = bool(request.get("revision_id"))
        if lesson["active_task_id"] != job["task_id"] or course["revision"] != request["expected_course_revision"]:
            raise conflict("course_task_replaced", "课时生成任务已更新")
        if lesson["content_json"] and not revision_mode:
            raise conflict("course_task_replaced", "课时生成任务已更新")
        if request.get("plan_hash") is not None and draft_hash(await course_read.load_course_plan(course, conn=conn)) != request["plan_hash"]:
            raise conflict("course_criteria_changed", "课程规划已更新")
    return course, lesson, scope


async def _preload_first_lesson(conn, job, course, scope, units, lesson_ids, expected_revision):
    """纲要发布后立即排队第一个可生成课时，缩短首次可学习内容的等待。

    与 generate_lesson 走同一任务契约：认领时 _authorized 校验
    active_task_id、expected_course_revision 与空内容；失败由 reconcile
    落为 failed，用户可手动重试。
    """
    target = next(
        (
            lesson_id
            for lesson_id, unit in zip(lesson_ids, units)
            if unit["availability"] != "material_gap"
        ),
        None,
    )
    if target is None:
        return
    saved = await course_read.owned_course(job["user_id"], course["course_id"], conn=conn)
    spec = CourseCreate.model_validate(load(saved["spec_json"]))
    request = dict(course_id=course["course_id"], lesson_id=target,
                   expected_course_revision=expected_revision,
                   scope_fingerprint=scope.fingerprint, pipeline_id=get_settings().rag_pipeline_id,
                   criteria_revision=saved.get("criteria_revision", 1),
                   plan_hash=draft_hash(await course_read.load_course_plan(saved, conn=conn)),
                   **await course_teaching.frozen_request_fields(
                       "lesson", spec, owner_id=job["user_id"], request_quality_review=False,
                       inherited=job.get("request"), conn=conn,
                   ))
    lesson_task = await job_service.enqueue_job(
        job["user_id"], "course_lesson", request,
        f"course-preload:{course['course_id']}:{target}",
        scope=scope.model_dump(mode="json"), conn=conn,
    )
    await execute(
        "UPDATE learning_course_lessons SET generation_task_id=%s,active_task_id=%s,status='generating',"
        "revision=revision+1,updated_at=%s WHERE lesson_id=%s AND owner_id=%s",
        (lesson_task["task_id"], lesson_task["task_id"], now(), target, job["user_id"]), conn=conn,
    )


def _restore_usage(budget, previous, policy):
    """Carry durable calls and conservative token reservations across worker leases."""
    calls = previous.get("calls", [])
    if any(call.get("status") in {"unknown", "reserved"} for call in calls):
        raise conflict("teaching_call_outcome_unknown", "上一次模型调用结果尚未确认")
    for field in ("llm_calls", "reranker_calls", "embedding_calls", "search_calls", "fetch_calls"):
        setattr(budget.usage, field, previous.get(field, 0))
        if getattr(budget.usage, field) > getattr(budget.limits, "max_" + field):
            raise BudgetExceeded("Teaching call budget exceeded")
    used_input, used_output = 0, 0
    for call in calls:
        if call.get("stage") != "llm":
            continue
        output_limit = policy.review_output_limit if call.get("purpose") == "course_teaching_review" else policy.generation_output_limit
        bounds = {"input_tokens": policy.generation_input_limit, "output_tokens": output_limit}
        values = {}
        for field, fallback in bounds.items():
            actual, estimate = call.get(field), call.get("estimated_" + field)
            if actual is not None and (type(actual) is not int or actual < 0):
                raise AppError(422, "course_generation_invalid_usage", "模型用量信息无效")
            if type(estimate) is not int or estimate < 0:
                estimate = fallback
            # Input admission uses the UTF-8 upper bound; output uses the
            # provider's measurement when known, otherwise the reserved maximum.
            values[field] = max(actual or 0, estimate) if field == "input_tokens" else actual if actual is not None else estimate
        used_input += values["input_tokens"]
        used_output += values["output_tokens"]
    budget.usage.input_tokens = max(previous.get("input_tokens", 0), used_input)
    budget.usage.output_tokens = max(previous.get("output_tokens", 0), used_output)
    if used_input > policy.max_input_tokens or used_output > policy.max_output_tokens:
        raise BudgetExceeded("Teaching token budget exceeded")
    budget.check()


async def run_course(job, engine, generator, *, usage_loader, record_summary: SummarySink | None = None):
    if generator is None:
        raise AppError(503, "course_provider_unavailable", "课程模型暂未配置")
    try:
        policy = policy_from_job(job)
    except (ValueError, TypeError):
        raise conflict("teaching_policy_changed", "教学任务的冻结配置无效") from None
    course_teaching.require_frozen_runtime(job, generator, policy)
    course, lesson, scope = await _authorized(job)
    spec = CourseCreate.model_validate(load(course["spec_json"]))
    if policy.mode != spec.teaching_mode or policy.source_policy != spec.source_policy:
        raise conflict("teaching_policy_changed", "课程与任务的教学模式不匹配")
    budget = BudgetLedger(policy.budget_limits((job["deadline_at"] - now()).total_seconds()))
    previous_usage = await usage_loader(job, budget.snapshot().model_dump(mode="json"))
    _restore_usage(budget, previous_usage, policy)
    await job_service.heartbeat(job, "preparing_course_sources")
    unit = None
    course_criteria = ()
    plan = None
    material = await teaching_quality_service.load_quality_material(job)
    if lesson is None:
        if material is None:
            material = await outline_material(engine, scope, spec.topic + "\n" + spec.goal)
    else:
        plan = await course_read.load_course_plan(course)
        checked_plan = parse_course_draft(plan)
        unit = parse_teach_unit(load(lesson["unit_json"]), schema_version=checked_plan.schema_version)
        if checked_plan.schema_version == V2:
            criteria = await course_outcome_service.get_course_criteria(job["user_id"], course["course_id"])
            course_criteria = tuple(CourseCriterionDraft.model_validate({
                field: getattr(item, field) for field in ("course_criterion_ref", "description", "evidence_type", "expectation")
            }) for item in criteria)
            if list(course_criteria) != checked_plan.payload.course_criteria:
                raise conflict("course_criteria_changed", "已保存课程目标与规划不匹配")
        elif policy.review_enabled:
            raise conflict("course_quality_unavailable", "旧版课程暂不支持教学核对")
        if material is None:
            config = pipeline_config(job["request"]["pipeline_id"])
            material = await lesson_material(engine, scope, unit, config, budget=budget)
    for item in material.evidence.values():
        engine.verify_evidence(item, scope)
    agent_input = TeachingAgentInput(
        kind="outline" if lesson is None else "lesson", spec=spec, unit=unit,
        course_criteria=course_criteria, material=material,
        plan_hash=draft_hash(plan) if plan is not None else None,
        criteria_revision=course.get("criteria_revision", 1), scope_fingerprint=scope.fingerprint,
        frozen_plan=plan,
    )
    initial = await teaching_quality_service.start_quality_run(job, agent_input, policy)
    # A resumed lease continues the saved draft identity; the preview follows it
    # instead of replaying first-draft blocks under a second revision.
    await content_event_service.reset_current_preview(int(initial.get("generation_revision", 1) or 1))

    async def authorize():
        async with transaction() as conn:
            current = await job_service.locked_job(job, conn)
            if current["request"] != job["request"]:
                raise conflict("teaching_policy_changed", "课程任务配置已变化")
            saved, saved_lesson, _ = await _authorized(current, conn=conn, lock=True)
            if saved.get("criteria_revision", 1) != agent_input.criteria_revision:
                raise conflict("course_criteria_changed", "课程目标已更新")
            if saved_lesson is not None and draft_hash(await course_read.load_course_plan(saved, conn=conn)) != agent_input.plan_hash:
                raise conflict("course_criteria_changed", "课程规划已更新")

    async def claim_stage(slot, *, candidate_hash):
        await authorize()
        role = "reviewer" if slot.startswith("review_") else "planner" if lesson is None else "teacher"
        claim = await teaching_quality_service.claim_agent_stage(job, slot, role, candidate_hash=candidate_hash)
        if not claim["claimed"]:
            raise conflict("teaching_call_outcome_unknown", "教学步骤已被执行或结果尚未确认")

    async def checkpoint(state):
        await teaching_quality_service.save_quality_checkpoint(job, state)

    async def heartbeat(stage):
        await job_service.heartbeat(job, stage)

    summaries = []

    def observe_summary(summary):
        summaries.append(summary)
        # Emit at graph completion, including rejected drafts and exceptions.
        # Diagnostic failure cannot change validation, metering or publication.
        emit_summary(record_summary, summary)

    state = await run_teaching_graph(
        agent_input, policy,
        TeachingAgentPorts(
            planner=PlannerAgent(generator, policy), teacher=TeacherAgent(generator, policy),
            reviewer=ReviewerAgent(generator.reviewer, policy), authorize=authorize,
            claim_stage=claim_stage, checkpoint=checkpoint, heartbeat=heartbeat,
            record_summary=observe_summary,
        ),
        budget=budget, run_id=job["task_id"], initial_state=initial,
    )
    if state["terminal_reason"] != "completed":
        raise AppError(422, state["terminal_reason"], "课程新稿尚未通过所请求的教学检查")
    generated = state["candidate"]
    draft = generated["draft"]
    result = dict(course_id=course["course_id"], lesson_id=lesson["lesson_id"] if lesson else None,
                  skill_version=generated["skill_version"], skill_hash=generated["skill_hash"],
                  effective_config=generated["effective_config"],
                  teaching_policy_hash=policy.policy_hash,
                  graph_summary=summaries[-1].model_dump(mode="json") if summaries else None,
                  usage=await usage_loader(job, budget.snapshot().model_dump(mode="json")))

    async def publish(current, public, conn):
        saved_course, saved_lesson, saved_scope = await _authorized(current, conn=conn, lock=True)
        if saved_scope != scope:
            raise conflict("course_scope_changed", "课程来源发生变更")
        saved_spec = CourseCreate.model_validate(load(saved_course["spec_json"]))
        if saved_spec != spec or saved_course.get("criteria_revision", 1) != agent_input.criteria_revision:
            raise conflict("course_criteria_changed", "课程目标或教学设置已更新")
        saved_unit = None
        if saved_lesson is not None:
            saved_outline = load(saved_course["outline_json"])
            saved_unit = parse_teach_unit(load(saved_lesson["unit_json"]), schema_version=saved_outline.get("schema_version"))
            if saved_unit != unit or draft_hash(await course_read.load_course_plan(saved_course, conn=conn)) != agent_input.plan_hash:
                raise conflict("course_criteria_changed", "课程目标或纲要已更新")
        if generated["draft_hash"] != draft_hash(draft):
            raise conflict("course_draft_changed", "待发布的课程内容已变化")
        checked = parse_course_draft(draft) if saved_lesson is None else parse_lesson_draft(draft)
        CourseGenerator._validate(checked, "outline" if saved_lesson is None else "lesson", saved_spec, saved_unit, material)
        for item in material.evidence.values():
            engine.verify_evidence(item, saved_scope)
        if generated["skill_hash"] != generator.skill["hash"] or generated["evidence"] != {
            ref: item.model_dump(mode="json") for ref, item in material.evidence.items()
            if ref in {source["source_ref"] for source in draft["sources"]}
        }:
            raise conflict("course_draft_changed", "待发布草案与冻结来源不匹配")
        stamp = now()
        if saved_lesson is None:
            units = draft["payload"]["units"]
            metadata = {**draft, "payload": {k: v for k, v in draft["payload"].items() if k != "units"}}
            lesson_ids = []
            for position, unit_data in enumerate(units):
                lesson_id = uid("lesson")
                lesson_ids.append(lesson_id)
                await execute(
                    "INSERT INTO learning_course_lessons(lesson_id,course_id,owner_id,unit_ref,position,unit_json,status) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (lesson_id, course["course_id"], job["user_id"], unit_data["unit_ref"], position, dump(unit_data),
                     "material_gap" if unit_data["availability"] == "material_gap" else "not_generated"), conn=conn,
                )
            status = "partial" if draft["status"] == "insufficient_evidence" or any(u["availability"] == "material_gap" for u in units) else "ready"
            await execute(
                "UPDATE learning_courses SET outline_json=%s,evidence_json=%s,status=%s,skill_version=%s,skill_hash=%s,"
                "active_task_id=NULL,revision=revision+1,updated_at=%s WHERE course_id=%s AND owner_id=%s",
                (dump(metadata), dump(generated["evidence"]), status, generated["skill_version"], generated["skill_hash"],
                 stamp, course["course_id"], job["user_id"]), conn=conn,
            )
            await course_outcome_service.publish_course_criteria(conn, job["user_id"], course["course_id"], draft)
            if spec.preload_first_lesson:
                await _preload_first_lesson(conn, job, course, scope, units, lesson_ids,
                                            course["revision"] + 1)
        elif (current.get("request") or {}).get("revision_id"):
            # 修订候选：写回修订记录，当前课时保持原版本可读。
            from app.services import course_revision_service

            await course_revision_service.mark_revision_candidate(
                course["course_id"], job["user_id"], current["request"]["revision_id"],
                lesson["lesson_id"], draft, conn=conn,
            )
            await execute("UPDATE learning_course_lessons SET generation_task_id=NULL,active_task_id=NULL,"
                          "revision=revision+1,updated_at=%s WHERE lesson_id=%s AND owner_id=%s",
                          (stamp, lesson["lesson_id"], job["user_id"]), conn=conn)
            await execute("UPDATE learning_courses SET updated_at=%s WHERE course_id=%s AND owner_id=%s",
                          (stamp, course["course_id"], job["user_id"]), conn=conn)
        else:
            await execute(
                "UPDATE learning_course_lessons SET content_json=%s,evidence_json=%s,status='ready',active_task_id=NULL,"
                "content_version=content_version+1,revision=revision+1,updated_at=%s WHERE lesson_id=%s AND owner_id=%s",
                (dump(draft), dump(generated["evidence"]), stamp, lesson["lesson_id"], job["user_id"]), conn=conn,
            )
            await execute("UPDATE learning_courses SET updated_at=%s WHERE course_id=%s AND owner_id=%s",
                          (stamp, course["course_id"], job["user_id"]), conn=conn)
        binding = teaching_quality_service.artifact_binding(
            draft=draft, evidence=generated["evidence"], skill_hash=generated["skill_hash"],
            course_id=course["course_id"], lesson_id=lesson["lesson_id"] if lesson else None,
            content_version=(saved_lesson["content_version"] if (current.get("request") or {}).get("revision_id") else saved_lesson["content_version"] + 1) if saved_lesson else None,
            criteria_revision=agent_input.criteria_revision,
        )
        await teaching_quality_service.seal_quality_run(current, state, binding, conn=conn)
    await job_service.heartbeat(job, "saving_course")
    await job_service.complete_job(job, result, publisher=publish)


async def reconcile_course(job, conn):
    if job["kind"] not in {"course_outline", "course_lesson"} or job["status"] not in {"failed", "cancelled"}:
        return
    request = job.get("request") or {}
    if not request.get("course_id"):
        return
    await teaching_quality_service.mark_quality_terminated(job, conn=conn)
    if job["kind"] == "course_outline":
        await execute(
            "UPDATE learning_courses SET status=%s,active_task_id=NULL,updated_at=%s "
            "WHERE course_id=%s AND owner_id=%s AND active_task_id=%s AND outline_json IS NULL",
            (job["status"], now(), request["course_id"], job["user_id"], job["task_id"]), conn=conn,
        )
    else:
        status = "material_gap" if job.get("error_code") == "course_material_gap" else job["status"]
        await execute(
            "UPDATE learning_course_lessons SET status=%s,active_task_id=NULL,revision=revision+1,updated_at=%s "
            "WHERE lesson_id=%s AND course_id=%s AND owner_id=%s AND active_task_id=%s AND content_json IS NULL",
            (status, now(), request.get("lesson_id"), request["course_id"], job["user_id"], job["task_id"]), conn=conn,
        )
