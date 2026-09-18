"""Tutor publication is fenced by the same persistent job lease as course content."""

from app.core.config import get_settings
from app.core.db import execute, fetch_all
from app.core.errors import AppError, conflict, not_found
from app.core.values import dump, load, now
from app.models.course import CourseCreate
from app.models.course_tutor import CourseTutorCreate
from app.rag.budget import BudgetLedger
from app.rag.contracts import BudgetLimits, ResolvedScope
from app.services import course_tutor_service, job_service
from app.services.evaluation_service import pipeline_config
from app.teaching.protocol import parse_teach_unit
from app.teaching.tutor import HISTORY_TURNS, tutor_material


async def _authorized(job, *, conn=None, lock=False):
    request = job.get("request") or {}
    if (job["kind"] != "course_tutor" or job["mode"] != "production"
            or job["operation"] != "course.tutor"
            or not all(request.get(field) for field in ("course_id", "lesson_id", "turn_id", "expected_content_version"))):
        raise not_found()
    course, lesson, scope = await course_tutor_service.authorized_lesson(
        job["user_id"], request["course_id"], request["lesson_id"], request["expected_content_version"],
        conn=conn, lock=lock,
    )
    turn = await course_tutor_service.owned_turn(
        job["user_id"], request["course_id"], request["lesson_id"], request["turn_id"], conn=conn, lock=lock
    )
    if (scope != ResolvedScope.model_validate(job["scope"])
            or request.get("scope_fingerprint") != scope.fingerprint):
        raise conflict("course_scope_changed", "课程来源与助教任务不匹配")
    if (turn["content_version"] != lesson["content_version"]
            or turn["active_task_id"] != job["task_id"] or turn["last_task_id"] != job["task_id"]
            or turn["response_json"] is not None):
        raise conflict("course_tutor_task_replaced", "助教生成任务已更新")
    return course, lesson, turn, scope


async def _history(job, turn, lesson):
    rows = await fetch_all(
        "SELECT t.mode,t.question,t.response_json,t.check_attempt_id FROM learning_course_tutor_turns t "
        "JOIN quiz_tasks q ON q.task_id=t.last_task_id AND q.user_id=t.owner_id "
        "AND q.kind='course_tutor' AND q.mode='production' AND q.status='completed' "
        "WHERE t.owner_id=%s AND t.course_id=%s AND t.lesson_id=%s AND t.content_version=%s "
        "AND t.turn_id<>%s AND t.created_at<=%s AND t.response_json IS NOT NULL AND t.revoked_at IS NULL "
        "ORDER BY t.created_at DESC,t.turn_id DESC LIMIT %s",
        (job["user_id"], turn["course_id"], turn["lesson_id"], turn["content_version"],
         turn["turn_id"], turn["created_at"], HISTORY_TURNS),
    )
    history = []
    for row in reversed(rows):
        context = None
        if row["check_attempt_id"]:
            from app.services.course_self_check_service import check_attempt_context

            context = await check_attempt_context(
                job["user_id"], turn["course_id"], turn["lesson_id"], row["check_attempt_id"], lesson
            )
        history.append(dict(mode=row["mode"], question=row["question"], answer=load(row["response_json"])["answer"],
                            check_context=context))
    return history


async def run_course_tutor(job, actor, engine, *, generator, usage_loader):
    settings = get_settings()
    if not settings.course_enabled:
        raise AppError(409, "course_disabled", "课程生成功能未启用")
    if generator is None:
        raise AppError(503, "course_provider_unavailable", "课程模型暂未配置")
    if actor.owner_id != job["user_id"]:
        raise not_found()
    course, lesson, turn, scope = await _authorized(job)
    body = CourseTutorCreate(
        expected_content_version=turn["content_version"], mode=turn["mode"], block_index=turn["block_index"],
        question=turn["question"], check_attempt_id=turn["check_attempt_id"],
    )
    check_context = await course_tutor_service._validate_turn_input(
        actor.owner_id, course["course_id"], lesson["lesson_id"], lesson, body
    )
    spec = CourseCreate.model_validate(load(course["spec_json"]))
    budget = BudgetLedger(BudgetLimits(
        max_llm_calls=3, max_reranker_calls=1, max_search_calls=0, max_fetch_calls=0,
        deadline_seconds=max(.001, min(1800, (job["deadline_at"] - now()).total_seconds())),
    ))
    await job_service.heartbeat(job, "preparing_tutor_sources")
    unit = parse_teach_unit(load(lesson["unit_json"]), schema_version=load(course["outline_json"]).get("schema_version"))
    material = await tutor_material(
        engine, scope, unit, body.question, pipeline_config(job["request"]["pipeline_id"]),
        budget=budget, check_context=check_context,
    )
    history = await _history(job, turn, lesson)
    await job_service.heartbeat(job, "generating_tutor_answer")
    generated = await generator.generate(
        spec, lesson, turn, material, history=history, check_context=check_context, budget=budget
    )
    result = dict(
        course_id=course["course_id"], lesson_id=lesson["lesson_id"], turn_id=turn["turn_id"],
        content_version=turn["content_version"], skill_version=generated["skill_version"],
        skill_hash=generated["skill_hash"], effective_config=generated["effective_config"],
        usage=await usage_loader(job, budget.snapshot().model_dump(mode="json")),
    )

    async def publish(current, public, conn):
        saved_course, saved_lesson, saved_turn, saved_scope = await _authorized(current, conn=conn, lock=True)
        if saved_scope != scope:
            raise conflict("course_scope_changed", "课程来源发生变更")
        # The attempt is immutable but can be removed during source revocation.
        saved_check = await course_tutor_service._validate_turn_input(
            current["user_id"], saved_course["course_id"], saved_lesson["lesson_id"], saved_lesson, body, conn=conn
        )
        if saved_check != check_context:
            raise conflict("course_check_changed", "自检来源已变化")
        for item in material.evidence.values():
            engine.verify_evidence(item, saved_scope)
        updated = await execute(
            "UPDATE learning_course_tutor_turns SET response_json=%s,evidence_json=%s,skill_version=%s,skill_hash=%s,"
            "active_task_id=NULL,updated_at=%s WHERE turn_id=%s AND owner_id=%s AND last_task_id=%s "
            "AND active_task_id=%s AND response_json IS NULL AND revoked_at IS NULL AND content_version=%s",
            (dump(generated["response"]), dump(generated["evidence"]), generated["skill_version"], generated["skill_hash"],
             now(), saved_turn["turn_id"], current["user_id"], current["task_id"], current["task_id"], saved_lesson["content_version"]),
            conn=conn,
        )
        if updated != 1:
            raise conflict("course_tutor_task_replaced", "助教生成任务已更新")

    await job_service.heartbeat(job, "saving_tutor_answer")
    await job_service.complete_job(job, result, publisher=publish)


async def reconcile_course_tutor(job, conn):
    if job["kind"] != "course_tutor" or job["status"] not in {"failed", "cancelled"}:
        return
    request = job.get("request") or {}
    if not request.get("turn_id"):
        return
    await execute(
        "UPDATE learning_course_tutor_turns SET active_task_id=NULL,updated_at=%s "
        "WHERE turn_id=%s AND owner_id=%s AND course_id=%s AND lesson_id=%s AND active_task_id=%s "
        "AND last_task_id=%s AND response_json IS NULL",
        (now(), request["turn_id"], job["user_id"], request.get("course_id"), request.get("lesson_id"),
         job["task_id"], job["task_id"]), conn=conn,
    )
