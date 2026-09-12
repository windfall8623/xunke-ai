"""Course generation and publication share the owner's durable task lease."""

from app.core.config import get_settings
from app.core.db import execute
from app.core.errors import AppError, conflict
from app.core.values import dump, load, now, uid
from app.models.course import CourseCreate
from app.rag.budget import BudgetLedger
from app.rag.contracts import BudgetLimits, ResolvedScope
from app.services import course_read, job_service
from app.services.evaluation_service import pipeline_config
from app.teaching.context import lesson_material, outline_material
from app.teaching.contracts import TeachUnit


async def _authorized(job, *, conn=None, lock=False):
    request = job["request"]
    course = await course_read.owned_course(job["user_id"], request["course_id"], conn=conn, lock=lock)
    scope = await course_read.authorize_course(course, conn=conn)
    if job["mode"] != "production" or scope != ResolvedScope.model_validate(job["scope"]) or request["scope_fingerprint"] != scope.fingerprint:
        raise conflict("course_scope_changed", "课程来源与生成任务不匹配")
    lesson = None
    if job["kind"] == "course_outline":
        if course["active_task_id"] != job["task_id"] or course["outline_json"]:
            raise conflict("course_task_replaced", "课程生成任务已更新")
    else:
        lesson = await course_read.owned_lesson(job["user_id"], course["course_id"], request["lesson_id"], conn=conn, lock=lock)
        if lesson["active_task_id"] != job["task_id"] or course["revision"] != request["expected_course_revision"] or lesson["content_json"]:
            raise conflict("course_task_replaced", "课时生成任务已更新")
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
    request = dict(course_id=course["course_id"], lesson_id=target,
                   expected_course_revision=expected_revision,
                   scope_fingerprint=scope.fingerprint, pipeline_id=get_settings().rag_pipeline_id)
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


async def run_course(job, engine, generator, *, usage_loader):
    settings = get_settings()
    if not settings.course_enabled:
        raise AppError(409, "course_disabled", "课程生成功能未启用")
    if generator is None:
        raise AppError(503, "course_provider_unavailable", "课程模型暂未配置")
    course, lesson, scope = await _authorized(job)
    spec = CourseCreate.model_validate(load(course["spec_json"]))
    budget = BudgetLedger(BudgetLimits(max_llm_calls=3, max_reranker_calls=1, max_search_calls=0, max_fetch_calls=0,
                                       deadline_seconds=max(.001, min(1800, (job["deadline_at"] - now()).total_seconds()))))
    await job_service.heartbeat(job, "preparing_course_sources")
    if lesson is None:
        material = await outline_material(engine, scope, spec.topic + "\n" + spec.goal)
        await job_service.heartbeat(job, "generating_outline")
        generated = await generator.outline(spec, material, budget=budget)
    else:
        unit = TeachUnit.model_validate(load(lesson["unit_json"]))
        config = pipeline_config(job["request"]["pipeline_id"])
        material = await lesson_material(engine, scope, unit, config, budget=budget)
        await job_service.heartbeat(job, "generating_lesson")
        generated = await generator.lesson(spec, unit, material, budget=budget)
    draft = generated["draft"]
    result = dict(course_id=course["course_id"], lesson_id=lesson["lesson_id"] if lesson else None,
                  skill_version=generated["skill_version"], skill_hash=generated["skill_hash"],
                  effective_config=generated["effective_config"],
                  usage=await usage_loader(job, budget.snapshot().model_dump(mode="json")))

    async def publish(current, public, conn):
        saved_course, saved_lesson, saved_scope = await _authorized(current, conn=conn, lock=True)
        if saved_scope != scope:
            raise conflict("course_scope_changed", "课程来源发生变更")
        for item in material.evidence.values():
            engine.verify_evidence(item, saved_scope)
        stamp = now()
        if saved_lesson is None:
            units = draft["payload"]["units"]
            metadata = {**draft, "payload": {k: v for k, v in draft["payload"].items() if k != "units"}}
            lesson_ids = []
            for position, unit in enumerate(units):
                lesson_id = uid("lesson")
                lesson_ids.append(lesson_id)
                await execute(
                    "INSERT INTO learning_course_lessons(lesson_id,course_id,owner_id,unit_ref,position,unit_json,status) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (lesson_id, course["course_id"], job["user_id"], unit["unit_ref"], position, dump(unit),
                     "material_gap" if unit["availability"] == "material_gap" else "not_generated"), conn=conn,
                )
            status = "partial" if draft["status"] == "insufficient_evidence" or any(u["availability"] == "material_gap" for u in units) else "ready"
            await execute(
                "UPDATE learning_courses SET outline_json=%s,evidence_json=%s,status=%s,skill_version=%s,skill_hash=%s,"
                "active_task_id=NULL,revision=revision+1,updated_at=%s WHERE course_id=%s AND owner_id=%s",
                (dump(metadata), dump(generated["evidence"]), status, generated["skill_version"], generated["skill_hash"],
                 stamp, course["course_id"], job["user_id"]), conn=conn,
            )
            if spec.preload_first_lesson:
                await _preload_first_lesson(conn, job, course, scope, units, lesson_ids,
                                            course["revision"] + 1)
        else:
            await execute(
                "UPDATE learning_course_lessons SET content_json=%s,evidence_json=%s,status='ready',active_task_id=NULL,"
                "content_version=content_version+1,revision=revision+1,updated_at=%s WHERE lesson_id=%s AND owner_id=%s",
                (dump(draft), dump(generated["evidence"]), stamp, lesson["lesson_id"], job["user_id"]), conn=conn,
            )
            await execute("UPDATE learning_courses SET updated_at=%s WHERE course_id=%s AND owner_id=%s",
                          (stamp, course["course_id"], job["user_id"]), conn=conn)
    await job_service.heartbeat(job, "saving_course")
    await job_service.complete_job(job, result, publisher=publish)


async def reconcile_course(job, conn):
    if job["kind"] not in {"course_outline", "course_lesson"} or job["status"] not in {"failed", "cancelled"}:
        return
    request = job.get("request") or {}
    if not request.get("course_id"):
        return
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
