"""Durable course writes. Every generated artifact is published by the owner worker."""

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict
from app.core.security import check_content
from app.core.values import digest, dump, load, now, uid
from app.models.course import CourseCreate
from app.rag.contracts import ResolvedScope
from app.services import course_read, course_teaching, job_service, source_service
from app.teaching.protocol import draft_hash


class _ReuseTask(Exception):
    def __init__(self, task_id):
        self.task_id = task_id


def require_enabled():
    if not get_settings().course_enabled:
        raise AppError(409, "course_disabled", "请先启用课程生成功能")


async def create_course(actor, body, key):
    require_enabled()
    owner = actor.owner_id
    spec = body.model_dump(mode="json")
    frozen = course_teaching.frozen_request_fields("outline", body)
    request_hash = digest(dump({"spec": spec, **frozen}))
    old = await job_service.existing_job(owner, "course_outline", key, request_hash)
    if old:
        return await course_read.get_task(owner, old["task_id"])
    await course_teaching.require_teaching_available(body.teaching_mode, body.request_quality_review)
    if not check_content(body.topic + "\n" + body.goal):
        raise AppError(422, "content_filtered", "请更换课程主题或目标")
    scope = (await source_service.resolve_scope(actor, body.scope)) if body.scope else ResolvedScope(owner_id=owner, namespace="production")
    course_id = uid("course")
    request = dict(course_id=course_id, spec=spec, scope_fingerprint=scope.fingerprint,
                   pipeline_id=get_settings().rag_pipeline_id,
                   criteria_revision=1, **frozen)
    async with transaction() as conn:
        job = await job_service.enqueue_job(owner, "course_outline", request, key,
                                           scope=scope.model_dump(mode="json"), request_hash=request_hash, conn=conn)
        saved_id = job["request"]["course_id"]
        if saved_id == course_id:
            await source_service.reauthorize_scope(scope, conn=conn)
            await execute(
                "INSERT INTO learning_courses(course_id,owner_id,spec_json,source_policy,requested_scope_json,"
                "resolved_scope_json,scope_fingerprint,creation_task_id,outline_task_id,active_task_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (course_id, owner, dump(spec), body.source_policy, dump(body.scope) if body.scope else None,
                 dump(scope), scope.fingerprint, job["task_id"], job["task_id"], job["task_id"]), conn=conn,
            )
        else:
            await course_read.authorize_course(await course_read.owned_course(owner, saved_id, conn=conn), conn=conn)
    return await course_read.get_task(owner, job["task_id"])


async def retry_outline(actor, course_id, key):
    require_enabled()
    owner = actor.owner_id
    row = await course_read.owned_course(owner, course_id)
    scope = await course_read.authorize_course(row)
    spec = CourseCreate.model_validate(load(row["spec_json"]))
    frozen = course_teaching.frozen_request_fields("outline", spec)
    request_hash = digest(dump({"course_id": course_id, "operation": "retry_outline",
                                "teaching_mode": spec.teaching_mode,
                                "request_quality_review": spec.request_quality_review, **frozen}))
    old = await job_service.existing_job(owner, "course_outline", key, request_hash)
    if old:
        return await course_read.get_task(owner, old["task_id"])
    await course_teaching.require_teaching_available(spec.teaching_mode, spec.request_quality_review)
    request = dict(course_id=course_id, spec=spec.model_dump(mode="json"), scope_fingerprint=scope.fingerprint,
                   pipeline_id=get_settings().rag_pipeline_id,
                   criteria_revision=row.get("criteria_revision", 1), **frozen)
    try:
        async with transaction() as conn:
            job = await job_service.enqueue_job(owner, "course_outline", request, key, scope=scope.model_dump(mode="json"),
                                               request_hash=request_hash, conn=conn)
            row = await course_read.owned_course(owner, course_id, conn=conn, lock=True)
            await course_read.authorize_course(row, conn=conn)
            if row["outline_task_id"] == job["task_id"]:
                return await course_read.task_view(owner, job["task_id"], course_id, conn=conn)
            task = await course_read.task_view(owner, row["outline_task_id"], course_id, conn=conn)
            if task["status"] not in {"failed", "cancelled"}:
                raise _ReuseTask(task["task_id"])
            if row["outline_json"]:
                raise conflict("course_outline_locked", "已有纲要，请从课程继续学习")
            await execute(
                "UPDATE learning_courses SET outline_task_id=%s,active_task_id=%s,status='generating',updated_at=%s "
                "WHERE course_id=%s AND owner_id=%s",
                (job["task_id"], job["task_id"], now(), course_id, owner), conn=conn,
            )
    except _ReuseTask as reuse:
        return await course_read.get_task(owner, reuse.task_id)
    return await course_read.get_task(owner, job["task_id"])


async def generate_lesson(actor, course_id, lesson_id, body, key):
    require_enabled()
    owner = actor.owner_id
    course = await course_read.owned_course(owner, course_id)
    scope = await course_read.authorize_course(course)
    spec = CourseCreate.model_validate(load(course["spec_json"]))
    frozen = course_teaching.frozen_request_fields("lesson", spec, request_quality_review=body.request_quality_review)
    request_hash = digest(dump({"course_id": course_id, "lesson_id": lesson_id, **body.model_dump(), **frozen}))
    old = await job_service.existing_job(owner, "course_lesson", key, request_hash)
    if old:
        return await course_read.get_task(owner, old["task_id"])
    await course_teaching.require_teaching_available(
        spec.teaching_mode, body.request_quality_review,
        schema_version=load(course["outline_json"], {}).get("schema_version"),
    )
    if body.revision_id:
        from app.core.config import get_settings as _gs
        from app.services import course_revision_service

        if not _gs().enable_course_revisions:
            raise AppError(409, "course_revisions_disabled", "课程修订功能未开启")
        await course_revision_service.ensure_generating(owner, course_id, body.revision_id, lesson_id)
    request = dict(course_id=course_id, lesson_id=lesson_id, expected_course_revision=body.expected_course_revision,
                   scope_fingerprint=scope.fingerprint, pipeline_id=get_settings().rag_pipeline_id,
                   criteria_revision=course.get("criteria_revision", 1),
                   revision_id=body.revision_id,
                   plan_hash=draft_hash(await course_read.load_course_plan(course)), **frozen)
    try:
        async with transaction() as conn:
            job = await job_service.enqueue_job(owner, "course_lesson", request, key, scope=scope.model_dump(mode="json"),
                                               request_hash=request_hash, conn=conn)
            course = await course_read.owned_course(owner, course_id, conn=conn, lock=True)
            lesson = await course_read.owned_lesson(owner, course_id, lesson_id, conn=conn, lock=True)
            await course_read.authorize_course(course, conn=conn)
            if lesson["generation_task_id"] == job["task_id"]:
                return await course_read.task_view(owner, job["task_id"], course_id, lesson_id, conn=conn)
            last = await course_read.task_view(owner, lesson["generation_task_id"], course_id, lesson_id, conn=conn)
            if body.revision_id:
                if last and last["status"] in {"pending", "running"}:
                    raise _ReuseTask(last["task_id"])
            elif last and (lesson["status"] == "ready" or last["status"] in {"pending", "running"}):
                raise _ReuseTask(last["task_id"])
            if course["revision"] != body.expected_course_revision:
                raise conflict()
            if course.get("criteria_revision", 1) != request["criteria_revision"] or draft_hash(await course_read.load_course_plan(course, conn=conn)) != request["plan_hash"]:
                raise conflict("course_criteria_changed", "课程目标或纲要已更新")
            if course["status"] not in {"ready", "partial"}:
                raise conflict("course_not_ready", "请等待课程纲要生成完成")
            if lesson["status"] == "material_gap":
                raise conflict("course_material_gap", "本课缺少资料，请补充资料后重新创建课程")
            if body.revision_id:
                # 修订候选：旧正文保持 ready 可读，仅挂任务身份。
                await execute(
                    "UPDATE learning_course_lessons SET generation_task_id=%s,active_task_id=%s,"
                    "revision=revision+1,updated_at=%s WHERE lesson_id=%s AND owner_id=%s",
                    (job["task_id"], job["task_id"], now(), lesson_id, owner), conn=conn,
                )
            else:
                await execute(
                    "UPDATE learning_course_lessons SET generation_task_id=%s,active_task_id=%s,status='generating',"
                    "revision=revision+1,updated_at=%s WHERE lesson_id=%s AND owner_id=%s",
                    (job["task_id"], job["task_id"], now(), lesson_id, owner), conn=conn,
                )
            await execute("UPDATE learning_courses SET updated_at=%s WHERE course_id=%s AND owner_id=%s",
                          (now(), course_id, owner), conn=conn)
    except _ReuseTask as reuse:
        return await course_read.get_task(owner, reuse.task_id)
    return await course_read.get_task(owner, job["task_id"])


async def update_outline(owner, course_id, body):
    async with transaction() as conn:
        course = await course_read.owned_course(owner, course_id, conn=conn, lock=True)
        lessons = await fetch_all("SELECT * FROM learning_course_lessons WHERE course_id=%s AND owner_id=%s ORDER BY position FOR UPDATE",
                                  (course_id, owner), conn=conn)
        await course_read.authorize_course(course, conn=conn)
        if course["revision"] != body.expected_revision:
            raise conflict()
        if not course["outline_json"] or any(l["generation_task_id"] for l in lessons):
            raise conflict("course_outline_locked", "开始生成课时后，课程纲要不可修改")
        by_id = {l["lesson_id"]: l for l in lessons}
        if len({l.lesson_id for l in body.lesson_titles}) != len(body.lesson_titles) or any(l.lesson_id not in by_id for l in body.lesson_titles):
            raise conflict("course_lesson_mismatch", "课时与课程不匹配")
        outline = load(course["outline_json"])
        if body.title is not None:
            outline["payload"]["title"] = body.title
        for update in body.lesson_titles:
            unit = load(by_id[update.lesson_id]["unit_json"])
            unit["title"] = update.title
            await execute("UPDATE learning_course_lessons SET unit_json=%s,revision=revision+1,updated_at=%s WHERE lesson_id=%s AND owner_id=%s",
                          (dump(unit), now(), update.lesson_id, owner), conn=conn)
        await execute("UPDATE learning_courses SET outline_json=%s,revision=revision+1,updated_at=%s WHERE course_id=%s AND owner_id=%s",
                      (dump(outline), now(), course_id, owner), conn=conn)
    return await course_read.get_course(owner, course_id)


async def update_read(owner, course_id, lesson_id, body):
    async with transaction() as conn:
        course = await course_read.owned_course(owner, course_id, conn=conn, lock=True)
        lesson = await course_read.owned_lesson(owner, course_id, lesson_id, conn=conn, lock=True)
        await course_read.authorize_course(course, conn=conn)
        if lesson["revision"] != body.expected_revision:
            raise conflict()
        if lesson["status"] != "ready" or not lesson["content_json"]:
            raise conflict("course_lesson_not_ready", "请先生成本课内容")
        stamp = now()
        await execute(
            "UPDATE learning_course_lessons SET read_at=%s,last_opened_at=%s,revision=revision+1,updated_at=%s WHERE lesson_id=%s AND owner_id=%s",
            ((lesson["read_at"] or stamp) if body.read else None, stamp, stamp, lesson_id, owner), conn=conn,
        )
        await execute("UPDATE learning_courses SET updated_at=%s WHERE course_id=%s AND owner_id=%s", (stamp, course_id, owner), conn=conn)
    return await course_read.get_lesson(owner, course_id, lesson_id)


async def cancel_task(owner, task_id):
    view = await course_read.get_task(owner, task_id)
    async with transaction() as conn:
        await job_service.cancel_job(owner, task_id, conn=conn)
        task = await fetch_one("SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s", (task_id, owner), conn=conn)
        from app.workers.course_job import reconcile_course
        if task["kind"] == "course_tutor":
            from app.workers.course_tutor_job import reconcile_course_tutor

            await reconcile_course_tutor(job_service.decode(task), conn)
        else:
            await reconcile_course(job_service.decode(task), conn)
    return await course_read.task_view(owner, task_id, view["course_id"], view["lesson_id"])


async def purge_document(owner, doc_id):
    from app.services.course_assessment_service import purge_course_assessments
    from app.services.course_feedback_service import purge_course_feedback
    from app.services.course_review_service import purge_course_reviews
    from app.services.course_tutor_service import purge_course_tutor
    from app.services.teaching_quality_service import purge_quality_content

    rows = await fetch_all("SELECT course_id,resolved_scope_json FROM learning_courses WHERE owner_id=%s AND source_policy='strict_docs'", (owner,))
    for row in rows:
        if not any(s["doc_id"] == doc_id for s in load(row["resolved_scope_json"], {}).get("documents", [])):
            continue
        async with transaction() as conn:
            await execute(
                "UPDATE learning_courses SET status='source_revoked',spec_json=NULL,outline_json=NULL,evidence_json=NULL,"
                "requested_scope_json=NULL,resolved_scope_json=NULL,active_task_id=NULL,revision=revision+1,updated_at=%s "
                "WHERE course_id=%s AND owner_id=%s AND status<>'source_revoked'", (now(), row["course_id"], owner), conn=conn,
            )
            await execute(
                "UPDATE learning_course_lessons SET status='source_revoked',unit_json=NULL,content_json=NULL,evidence_json=NULL,"
                "active_task_id=NULL,revision=revision+1,updated_at=%s WHERE course_id=%s AND owner_id=%s AND status<>'source_revoked'",
                (now(), row["course_id"], owner), conn=conn,
            )
            await purge_course_tutor(conn, owner, row["course_id"])
            await purge_course_reviews(conn, owner, row["course_id"])
            await purge_quality_content(owner, row["course_id"], conn=conn)
            await purge_course_assessments(conn, owner, row["course_id"])
            await purge_course_feedback(conn, owner, row["course_id"])
