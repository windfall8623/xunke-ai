"""Immutable text submissions; feedback is a separate, recoverable operation."""

import logging

from pymysql import MySQLError

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.security import check_content
from app.core.values import digest, dump, iso, load, now, uid
from app.models.course_assessment import (
    CourseApplicationAttemptView, CourseApplicationFeedbackView,
    CourseApplicationJobView, CourseApplicationTaskView,
)
from app.rag.contracts import ResolvedScope, stable_hash
from app.services import course_assessment_service as assessments
from app.services import job_service
from app.teaching.application import CourseApplicationQuestion

logger = logging.getLogger(__name__)
KINDS = {"course_application_generate", "course_application_feedback"}


class _ReuseCurrent(Exception):
    """Roll back a racing job reservation before reusing the committed group."""


def application_criterion_ids(snapshot):
    items = [item for item in snapshot["criteria"]
             if item["course_criterion_id"] in snapshot["selected_criterion_ids"] and item["available"]]
    # Text application covers the abilities that an objective check cannot.
    items.sort(key=lambda item: item["evidence_type"] == "recognition")
    return [item["course_criterion_id"] for item in items[:3]]


async def owned_application(owner, course_id, assessment_id, application_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM learning_course_application_tasks WHERE application_task_id=%s AND course_assessment_id=%s "
        "AND course_id=%s AND owner_id=%s" + (" FOR UPDATE" if lock else ""),
        (application_id, assessment_id, course_id, owner), conn=conn,
    )
    if row is None:
        raise not_found()
    if row["revoked_at"] is not None or row["draft_json"] is None:
        raise AppError(404, "source_revoked", "应用任务关联资料已失效")
    return row


async def owned_attempt(owner, course_id, assessment_id, attempt_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM learning_course_application_attempts WHERE attempt_id=%s AND course_assessment_id=%s "
        "AND course_id=%s AND owner_id=%s" + (" FOR UPDATE" if lock else ""),
        (attempt_id, assessment_id, course_id, owner), conn=conn,
    )
    if row is None:
        raise not_found()
    if row["revoked_at"] is not None or row["answer_text"] is None:
        raise AppError(404, "source_revoked", "回答关联资料已失效")
    return row


def question_from_row(row):
    question = CourseApplicationQuestion.model_validate(load(row["draft_json"]))
    if stable_hash(question.model_dump(mode="json")) != row["question_version"]:
        raise conflict("course_application_question_changed", "应用任务内容已变化")
    return question


async def application_views(owner, assessment_id, *, conn=None):
    rows = await fetch_all(
        "SELECT t.*,(SELECT p.attempt_id FROM learning_course_application_attempts p "
        "WHERE p.application_task_id=t.application_task_id AND p.owner_id=t.owner_id AND p.revoked_at IS NULL "
        "ORDER BY p.saved_at DESC,p.attempt_id DESC LIMIT 1) AS latest_attempt_id "
        "FROM learning_course_application_tasks t JOIN quiz_tasks j ON j.task_id=t.generation_task_id "
        "AND j.user_id=t.owner_id AND j.status='completed' WHERE t.owner_id=%s AND t.course_assessment_id=%s "
        "AND t.revoked_at IS NULL ORDER BY t.position,t.application_task_id", (owner, assessment_id), conn=conn,
    )
    result = []
    for row in rows:
        question = question_from_row(row)
        result.append(CourseApplicationTaskView(
            application_task_id=row["application_task_id"], revision=row["revision"],
            prompt=question.prompt, public_expectations=question.public_expectations,
            source_policy=question.source_policy, source_refs=question.source_refs,
            support_quotes=question.support_quotes,
            course_criterion_ids=load(row["course_criterion_ids_json"], []), latest_attempt_id=row["latest_attempt_id"],
        ).model_dump(mode="json"))
    return result


async def authorize_application_job(owner, job, *, conn=None, require_active=True):
    request = job.get("request") or {}
    if (job.get("kind") not in KINDS or job.get("user_id") != owner or job.get("mode") != "production"
            or job.get("operation") != job_service.OPERATIONS[job["kind"]]
            or not all(request.get(key) for key in ("course_id", "course_assessment_id", "scope_fingerprint"))):
        raise not_found()
    if conn is None:
        async with transaction() as tx:
            return await authorize_application_job(owner, job, conn=tx, require_active=require_active)
    course, row, scope = await assessments.authorized_assessment(
        owner, request["course_id"], request["course_assessment_id"], conn=conn, lock=True, require_active=require_active,
    )
    if (scope != ResolvedScope.model_validate(job["scope"])
            or request["scope_fingerprint"] != scope.fingerprint):
        raise not_found()
    result = dict(course=course, assessment=row, scope=scope, snapshot=load(row["snapshot_json"]))
    if job["kind"] == "course_application_generate":
        expected = application_criterion_ids(result["snapshot"])
        if request.get("course_criterion_ids") != expected:
            raise not_found()
        if require_active and (row["application_generation_task_id"] != job["task_id"] or row["completed_at"] is not None):
            raise conflict("course_application_task_replaced", "应用题生成任务已更新或检查已封存")
    else:
        if not request.get("attempt_id") or not request.get("application_task_id"):
            raise not_found()
        application = await owned_application(owner, row["course_id"], row["course_assessment_id"],
                                               request["application_task_id"], conn=conn, lock=True)
        attempt = await owned_attempt(owner, row["course_id"], row["course_assessment_id"],
                                      request["attempt_id"], conn=conn, lock=True)
        question = question_from_row(application)
        if (attempt["application_task_id"] != application["application_task_id"]
                or attempt["question_version"] != application["question_version"]
                or request.get("question_version") != application["question_version"]):
            raise not_found()
        if require_active and (attempt["active_task_id"] != job["task_id"] or attempt["feedback_task_id"] != job["task_id"]):
            raise conflict("course_application_task_replaced", "反馈任务已更新")
        result.update(application=application, attempt=attempt, question=question)
    return result


async def get_application_task(owner, task_id):
    row = await fetch_one("SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s "
                          "AND mode='production' AND kind IN ('course_application_generate','course_application_feedback')",
                          (task_id, owner))
    if row is None:
        raise not_found()
    job = job_service.decode(row)
    await authorize_application_job(owner, job, require_active=False)
    summary = await assessments.task_summary(owner, task_id)
    return CourseApplicationJobView(**summary, kind=job["kind"], course_id=job["request"]["course_id"],
                                    course_assessment_id=job["request"]["course_assessment_id"],
                                    application_task_id=job["request"].get("application_task_id"),
                                    attempt_id=job["request"].get("attempt_id")).model_dump(mode="json")


async def cancel_application_task(owner, task_id):
    async with transaction() as conn:
        raw = await fetch_one("SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s FOR UPDATE", (task_id, owner), conn=conn)
        if raw is None:
            raise not_found()
        await authorize_application_job(owner, job_service.decode(raw), conn=conn, require_active=False)
        await job_service.cancel_job(owner, task_id, conn=conn)
    return await get_application_task(owner, task_id)


async def create_application_job(actor, course_id, course_assessment_id, key):
    from app.services.course_service import require_enabled

    assessments._key(key)
    owner = actor.owner_id
    _, row, scope = await assessments.authorized_assessment(owner, course_id, course_assessment_id)
    request_hash = digest(dump(dict(operation="course.application.generate", course_id=course_id,
                                   course_assessment_id=course_assessment_id)))
    old = await job_service.existing_job(owner, "course_application_generate", key, request_hash)
    if old:
        return await assessments.get_course_assessment(owner, course_id, course_assessment_id)
    current = await assessments.task_summary(owner, row["application_generation_task_id"])
    if current and current["status"] in {"pending", "running", "completed"}:
        return await assessments.get_course_assessment(owner, course_id, course_assessment_id)
    require_enabled()
    if row["completed_at"] is not None:
        raise conflict("course_assessment_completed", "本次检查已封存，请创建下一组检查")
    goals = application_criterion_ids(load(row["snapshot_json"]))
    if not goals:
        raise conflict("course_application_no_taught_goals", "当前没有已教且可用于应用练习的目标")
    request = dict(course_id=course_id, course_assessment_id=course_assessment_id,
                   scope_fingerprint=scope.fingerprint, course_criterion_ids=goals,
                   pipeline_id=get_settings().rag_pipeline_id)
    try:
        async with transaction() as conn:
            job = await job_service.enqueue_job(owner, "course_application_generate", request, key,
                                                scope=scope.model_dump(mode="json"), request_hash=request_hash, conn=conn)
            _, saved, _ = await assessments.authorized_assessment(owner, course_id, course_assessment_id,
                                                                  conn=conn, lock=True, require_active=True)
            if saved["completed_at"] is not None:
                raise conflict("course_assessment_completed", "本次检查已封存，请创建下一组检查")
            if saved["application_generation_task_id"] == job["task_id"]:
                return await assessments.get_course_assessment(owner, course_id, course_assessment_id, conn=conn)
            current = await assessments.task_summary(owner, saved["application_generation_task_id"], conn=conn)
            if current and current["status"] in {"pending", "running", "completed"}:
                raise _ReuseCurrent()
            await execute("UPDATE learning_course_assessments SET application_generation_task_id=%s,"
                          "revision=revision+1,updated_at=%s WHERE course_assessment_id=%s AND owner_id=%s",
                          (job["task_id"], now(), course_assessment_id, owner), conn=conn)
    except _ReuseCurrent:
        pass
    return await assessments.get_course_assessment(owner, course_id, course_assessment_id)


def _public_application_criterion(item):
    result = {key: item[key] for key in (
        "criterion_id", "credit", "answer_quotes", "evidence_refs"
    ) if key in item}
    # Grading stores the per-criterion explanation as rationale. Keep the
    # existing public feedback field and older published feedback readable.
    feedback = item.get("feedback")
    if not isinstance(feedback, str) or not feedback.strip():
        feedback = item.get("rationale")
    if isinstance(feedback, str):
        result["feedback"] = feedback
    return result


async def get_application_attempt(owner, course_id, course_assessment_id, attempt_id, *, conn=None):
    course, _, _ = await assessments.authorized_assessment(owner, course_id, course_assessment_id, conn=conn)
    row = await owned_attempt(owner, course_id, course_assessment_id, attempt_id, conn=conn)
    app = await owned_application(owner, course_id, course_assessment_id, row["application_task_id"], conn=conn)
    question_from_row(app)
    if row["question_version"] != app["question_version"]:
        raise not_found()
    feedback = None
    if row["latest_assessment_id"]:
        grade = await fetch_one("SELECT * FROM learning_course_application_assessments WHERE assessment_id=%s "
                                "AND attempt_id=%s AND owner_id=%s", (row["latest_assessment_id"], attempt_id, owner), conn=conn)
        if grade:
            public = load(grade["feedback_json"], {})
            feedback = CourseApplicationFeedbackView(
                assessment_id=grade["assessment_id"], supersedes_assessment_id=grade["supersedes_assessment_id"],
                status=grade["status"], confirmation=grade["confirmation"], score=grade["score"],
                feedback=public.get("feedback"),
                criterion_results=[_public_application_criterion(item)
                                   for item in public.get("criterion_results", [])], created_at=iso(grade["created_at"]),
            )
    await assessments.course_read.authorize_course(course, conn=conn)
    return CourseApplicationAttemptView(
        attempt_id=attempt_id, application_task_id=row["application_task_id"], course_assessment_id=course_assessment_id,
        course_id=course_id, revision=row["revision"], question_version=row["question_version"],
        answer=row["answer_text"], help_usage=row["help_usage"], help_usage_source=row["help_usage_source"],
        saved_at=iso(row["saved_at"]), feedback_task_id=row["feedback_task_id"],
        feedback_task=await assessments.task_summary(owner, row["feedback_task_id"], conn=conn), feedback=feedback,
    ).model_dump(mode="json")


async def submit_application_answer(actor, course_id, course_assessment_id, application_task_id, body, key):
    assessments._key(key)
    owner = actor.owner_id
    request_hash = digest(dump(dict(operation="course.application.answer", course_id=course_id,
                                   course_assessment_id=course_assessment_id, application_task_id=application_task_id,
                                   **body.model_dump(mode="json"))))
    old = await fetch_one("SELECT attempt_id,request_hash FROM learning_course_application_attempts "
                          "WHERE owner_id=%s AND idempotency_key=%s", (owner, key))
    if old:
        if old["request_hash"] != request_hash:
            raise conflict("idempotency_conflict", "相同操作标识已用于不同回答")
        return await get_application_attempt(owner, course_id, course_assessment_id, old["attempt_id"])
    if not check_content(body.answer):
        raise AppError(422, "content_filtered", "请调整回答后重试")
    async with transaction() as conn:
        _, session, _ = await assessments.authorized_assessment(owner, course_id, course_assessment_id,
                                                               conn=conn, lock=True, require_active=True)
        application = await owned_application(owner, course_id, course_assessment_id, application_task_id, conn=conn, lock=True)
        old = await fetch_one("SELECT attempt_id,request_hash FROM learning_course_application_attempts "
                              "WHERE owner_id=%s AND idempotency_key=%s FOR UPDATE", (owner, key), conn=conn)
        if old:
            if old["request_hash"] != request_hash:
                raise conflict("idempotency_conflict", "相同操作标识已用于不同回答")
            return await get_application_attempt(owner, course_id, course_assessment_id, old["attempt_id"], conn=conn)
        if session["completed_at"] is not None:
            raise conflict("course_assessment_completed", "本次检查已封存，请创建下一组检查")
        if application["revision"] != body.expected_revision:
            raise conflict("revision_conflict", "应用任务已更新，请刷新后重试")
        question_from_row(application)
        attempt_id = uid("application_attempt")
        await execute(
            "INSERT INTO learning_course_application_attempts(attempt_id,application_task_id,course_assessment_id,course_id,"
            "owner_id,question_version,answer_text,help_usage,help_usage_source,idempotency_key,request_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (attempt_id, application_task_id, course_assessment_id, course_id, owner, application["question_version"],
             body.answer, body.help_usage, "unknown" if body.help_usage == "unknown" else "learner_declaration", key, request_hash), conn=conn,
        )
        await execute("UPDATE learning_course_assessments SET status=IF(status='ready','in_progress',status),"
                      "revision=revision+1,updated_at=%s WHERE course_assessment_id=%s AND owner_id=%s",
                      (now(), course_assessment_id, owner), conn=conn)
    # The answer and its receipt are committed before any queue/provider work.
    # A replay never requeues invisibly: the explicit feedback endpoint recovers it.
    try:
        return await create_feedback_job(actor, course_id, course_assessment_id, attempt_id, f"initial-feedback:{attempt_id}")
    except (AppError, MySQLError, OSError, TimeoutError):
        logger.info("Course application answer saved; feedback queue unavailable")
        return await get_application_attempt(owner, course_id, course_assessment_id, attempt_id)


async def create_feedback_job(actor, course_id, course_assessment_id, attempt_id, key):
    from app.services.course_service import require_enabled
    from app.workers.course_application_job import reconcile_course_application

    assessments._key(key)
    owner = actor.owner_id
    _, _, scope = await assessments.authorized_assessment(owner, course_id, course_assessment_id)
    row = await owned_attempt(owner, course_id, course_assessment_id, attempt_id)
    request_hash = digest(dump(dict(operation="course.application.feedback", course_id=course_id,
                                   course_assessment_id=course_assessment_id, attempt_id=attempt_id)))
    old = await job_service.existing_job(owner, "course_application_feedback", key, request_hash)
    if old:
        return await get_application_attempt(owner, course_id, course_assessment_id, attempt_id)
    current = await assessments.task_summary(owner, row["feedback_task_id"])
    if current and current["status"] in {"pending", "running", "completed"}:
        return await get_application_attempt(owner, course_id, course_assessment_id, attempt_id)
    require_enabled()
    request = dict(course_id=course_id, course_assessment_id=course_assessment_id,
                   application_task_id=row["application_task_id"], attempt_id=attempt_id,
                   question_version=row["question_version"], scope_fingerprint=scope.fingerprint)
    try:
        async with transaction() as conn:
            job = await job_service.enqueue_job(owner, "course_application_feedback", request, key,
                                                scope=scope.model_dump(mode="json"), request_hash=request_hash, conn=conn)
            await assessments.authorized_assessment(owner, course_id, course_assessment_id,
                                                    conn=conn, lock=True, require_active=True)
            saved = await owned_attempt(owner, course_id, course_assessment_id, attempt_id, conn=conn, lock=True)
            app = await owned_application(owner, course_id, course_assessment_id, saved["application_task_id"], conn=conn, lock=True)
            question_from_row(app)
            if saved["question_version"] != app["question_version"]:
                raise conflict("revision_conflict", "应用任务已更新")
            if saved["feedback_task_id"] != job["task_id"]:
                current_raw = await fetch_one("SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s",
                                              (saved["feedback_task_id"], owner), conn=conn) if saved["feedback_task_id"] else None
                if current_raw and current_raw["status"] in {"pending", "running", "completed"}:
                    raise _ReuseCurrent()
                if current_raw:
                    await reconcile_course_application(job_service.decode(current_raw), conn)
                await execute("UPDATE learning_course_application_attempts SET feedback_task_id=%s,active_task_id=%s,"
                              "revision=revision+1 WHERE attempt_id=%s AND owner_id=%s",
                              (job["task_id"], job["task_id"], attempt_id, owner), conn=conn)
    except _ReuseCurrent:
        pass
    return await get_application_attempt(owner, course_id, course_assessment_id, attempt_id)
