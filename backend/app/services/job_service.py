"""Finite durable job queue. A lease fences every publication, including retries."""

import secrets
from datetime import timedelta

from pymysql import IntegrityError

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, load, now, uid

OPERATIONS = {
    "qa": "qa.answer",
    "quiz": "quiz.generate",
    "report": "report.generate",
    "ingest": "knowledge.ingest",
    "delete": "knowledge.delete",
    "eval_sample": "eval.sample",
    "images": "quiz.images",
    "learning_project": "learning.project",
    "practice_generate": "practice.generate",
    "practice_grade": "practice.grade",
    "course_outline": "course.outline",
    "course_lesson": "course.lesson",
    "course_tutor": "course.tutor",
    "course_application_generate": "course.application.generate",
    "course_application_feedback": "course.application.feedback",
}


def decode(row):
    if row is None:
        return None
    result = dict(row)
    for field, name in [
        ("request_json", "request"),
        ("scope_json", "scope"),
        ("result_json", "result"),
    ]:
        result[name] = load(result.pop(field, None))
    return result


async def existing_job(owner, kind, key, request_hash, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM quiz_tasks WHERE user_id=%s AND operation=%s AND idempotency_key=%s"
        + (" FOR UPDATE" if lock else ""),
        (owner, OPERATIONS[kind], key),
        conn=conn,
    )
    if row and row["request_hash"] != request_hash:
        raise conflict("idempotency_conflict", "相同操作标识已用于不同请求")
    return decode(row)


async def enqueue_job(
    owner,
    kind,
    request,
    key,
    *,
    scope=None,
    mode="production",
    conn=None,
    request_hash=None,
):
    if kind not in OPERATIONS or mode not in ("production", "evaluation"):
        raise ValueError("Unsupported job kind or mode")
    if not key or len(key) > 128:
        raise AppError(422, "idempotency_required", "需要有效 Idempotency-Key")
    if conn is None:
        async with transaction() as tx:
            return await enqueue_job(
                owner,
                kind,
                request,
                key,
                scope=scope,
                mode=mode,
                conn=tx,
                request_hash=request_hash,
            )
    user = await fetch_one("SELECT id FROM users WHERE id=%s", (owner,), conn=conn)
    if not user:
        raise not_found()
    request_hash = request_hash or digest(dump(request))
    old = await existing_job(owner, kind, key, request_hash, conn=conn)
    if old:
        return old
    s = get_settings()
    task_id, quiz_id = (
        uid("task"),
        uid("quiz") if kind == "quiz" else request.get("quiz_id"),
    )
    summary = (
        request["spec"]
        if kind in {"quiz", "practice_generate"}
        and isinstance(request.get("spec"), dict)
        else request
    )
    try:
        await execute(
            """INSERT INTO quiz_tasks
        (task_id,user_id,user_input,question_count,difficulty,kind,operation,mode,request_json,request_hash,
         idempotency_key,scope_json,quiz_id,queued_expires_at,max_attempts,priority)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                task_id,
                owner,
                summary.get("user_input", ""),
                summary.get("question_count", 5),
                summary.get("difficulty", "mixed"),
                kind,
                OPERATIONS[kind],
                mode,
                dump(request),
                request_hash,
                key,
                dump(scope) if scope else None,
                quiz_id,
                now() + timedelta(seconds=s.job_queue_ttl_seconds),
                s.job_max_attempts,
                30 if mode == "evaluation" else 10,
            ),
            conn=conn,
        )
    except IntegrityError:
        replay = await existing_job(
            owner, kind, key, request_hash, conn=conn, lock=True
        )
        if replay:
            return replay
        raise
    job = decode(
        await fetch_one(
            "SELECT * FROM quiz_tasks WHERE task_id=%s", (task_id,), conn=conn
        )
    )
    # 幂等重放不重复写事件；只有真正新增的任务写 queued。
    from app.services import task_event_service

    await task_event_service.append_task_event(
        conn, job, "phase", task_event_service.event_payload(job, status="queued")
    )
    return job


_TERMINAL_BATCH = 100


async def finalize_terminal_rows(conn, *, task_id=None, limit=_TERMINAL_BATCH):
    """有界终态收敛：逐行锁定已取消/超时的任务，改状态并追加公开事件。

    取代原 claim_job 与 OwnerWorker.reconcile 中的两条批量 UPDATE，
    保证所有终态路径都经过同一份事件写入。返回提交后待通知的信号。
    """
    filters = (
        "status IN ('pending','running') AND (cancel_requested=TRUE "
        "OR (status='pending' AND queued_expires_at<=UTC_TIMESTAMP(6)) "
        "OR deadline_at<=UTC_TIMESTAMP(6) "
        "OR (status='running' AND lease_expires_at<=UTC_TIMESTAMP(6) AND attempt>=max_attempts))"
    )
    params: list = []
    if task_id:
        filters += " AND task_id=%s"
        params.append(task_id)
    rows = await fetch_all(
        "SELECT task_id FROM quiz_tasks WHERE "
        + filters
        + " ORDER BY priority,created_at LIMIT %s FOR UPDATE SKIP LOCKED",
        (*params, limit),
        conn=conn,
    )
    from app.services import task_event_service

    signals = []
    for item in rows:
        locked = await fetch_one(
            "SELECT * FROM quiz_tasks WHERE task_id=%s FOR UPDATE",
            (item["task_id"],),
            conn=conn,
        )
        if not locked or locked["status"] not in ("pending", "running"):
            continue
        if locked["cancel_requested"]:
            status, code = "cancelled", None
        else:
            status, code = "failed", "deadline_exceeded"
        await execute(
            "UPDATE quiz_tasks SET status=%s,stage=%s,error_code=%s,lease_token=NULL,lease_expires_at=NULL "
            "WHERE task_id=%s",
            (status, status, code, locked["task_id"]),
            conn=conn,
        )
        job = decode(locked)
        signal = await task_event_service.append_task_event(
            conn,
            job,
            status,
            task_event_service.event_payload(job, status=status, error_code=code),
        )
        if signal:
            signals.append(signal)
    return signals


async def claim_job(worker_id, *, task_id=None, kinds=None, maintain=True):
    s = get_settings()
    async with transaction() as conn:
        from app.services import vector_projection_service

        if vector_projection_service.enabled():
            await vector_projection_service.assert_not_maintenance(conn=conn)
        if maintain:
            await finalize_terminal_rows(conn, task_id=task_id)
        filters = "status IN ('pending','running') AND cancel_requested=FALSE AND attempt<max_attempts AND (status='pending' OR lease_expires_at<=UTC_TIMESTAMP(6))"
        params = []
        if task_id:
            filters += " AND task_id=%s"
            params.append(task_id)
        if kinds:
            filters += " AND kind IN (" + ",".join(["%s"] * len(kinds)) + ")"
            params.extend(kinds)
        row = await fetch_one(
            "SELECT * FROM quiz_tasks WHERE "
            + filters
            + " ORDER BY priority,created_at LIMIT 1 FOR UPDATE SKIP LOCKED",
            params,
            conn=conn,
        )
        if not row:
            return None
        token = secrets.token_urlsafe(32)
        timeout = (
            600
            if row["kind"] in ("ingest", "delete", "images")
            else s.course_job_deadline_seconds
            if row["kind"] in (
                "course_outline", "course_lesson", "course_tutor",
                "course_application_generate", "course_application_feedback",
            )
            else s.job_deadline_seconds
        )
        deadline = row["deadline_at"] or now() + timedelta(seconds=timeout)
        await execute(
            "UPDATE quiz_tasks SET status='running',stage='starting',attempt=attempt+1,worker_id=%s,lease_token=%s,lease_expires_at=%s,deadline_at=%s WHERE task_id=%s",
            (
                worker_id,
                token,
                min(deadline, now() + timedelta(seconds=s.job_lease_seconds)),
                deadline,
                row["task_id"],
            ),
            conn=conn,
        )
        job = decode(
            await fetch_one(
                "SELECT * FROM quiz_tasks WHERE task_id=%s",
                (row["task_id"],),
                conn=conn,
            )
        )
        from app.services import task_event_service

        await task_event_service.append_task_event(
            conn,
            job,
            "phase",
            task_event_service.event_payload(job, status="running", stage="starting"),
        )
        return job


async def locked_job(job, conn):
    row = await fetch_one(
        "SELECT * FROM quiz_tasks WHERE task_id=%s FOR UPDATE",
        (job["task_id"],),
        conn=conn,
    )
    if (
        not row
        or row["status"] != "running"
        or row["cancel_requested"]
        or row["lease_token"] != job["lease_token"]
        or row["attempt"] != job["attempt"]
        or row["lease_expires_at"] <= now()
        or row["deadline_at"] <= now()
    ):
        raise conflict("stale_lease", "任务执行权已失效")
    return decode(row)


async def heartbeat(job, stage=None):
    async with transaction() as conn:
        row = await locked_job(job, conn)
        next_stage = stage or row["stage"]
        await execute(
            "UPDATE quiz_tasks SET lease_expires_at=%s,stage=%s WHERE task_id=%s",
            (
                min(
                    row["deadline_at"],
                    now() + timedelta(seconds=get_settings().job_lease_seconds),
                ),
                next_stage,
                job["task_id"],
            ),
            conn=conn,
        )
        # 相同阶段的纯续租不新增事件；只有真实阶段变化才写公开 phase。
        if stage and stage != row["stage"]:
            from app.services import task_event_service

            current = dict(job)
            current["attempt"] = row["attempt"]
            await task_event_service.append_task_event(
                conn,
                current,
                "phase",
                task_event_service.event_payload(current, status=row["status"], stage=stage),
            )


async def complete_job(job, result, *, publisher=None):
    from app.services.content_event_service import current_preview, close_content

    preview = current_preview()
    if preview and preview.job["task_id"] == job["task_id"]:
        await preview.flush()
    async with transaction() as conn:
        current = await locked_job(job, conn)
        if publisher:
            await publisher(current, result, conn)
        count = await execute(
            "UPDATE quiz_tasks SET status='completed',stage='completed',result_json=%s,lease_token=NULL,lease_expires_at=NULL,error_code=NULL,error_message=NULL WHERE task_id=%s AND lease_token=%s",
            (dump(result), job["task_id"], job["lease_token"]),
            conn=conn,
        )
        if count != 1:
            raise conflict("stale_lease", "任务执行权已失效")
        from app.services import task_event_service

        final = dict(job)
        final["attempt"] = current["attempt"]
        await task_event_service.append_task_event(
            conn,
            final,
            "completed",
            task_event_service.event_payload(final, status="completed"),
        )
    await close_content(job, completed=True)


async def fail_job(job, code, *, retryable=False):
    async with transaction() as conn:
        row = await locked_job(job, conn)
        status = (
            "pending"
            if retryable
            and row["attempt"] < row["max_attempts"]
            and row["deadline_at"] > now()
            else "failed"
        )
        await execute(
            "UPDATE quiz_tasks SET status=%s,stage=%s,error_code=%s,error_message=%s,lease_token=NULL,lease_expires_at=NULL WHERE task_id=%s",
            (status, status, code, "任务未完成，请查看错误原因后重试", job["task_id"]),
            conn=conn,
        )
        from app.services import task_event_service

        final = dict(job)
        final["attempt"] = row["attempt"]
        if status == "pending":
            # 可重试失败：回到队列，发 pending/queued 阶段事件。
            await task_event_service.append_task_event(
                conn,
                final,
                "phase",
                task_event_service.event_payload(final, status="pending", stage="queued"),
            )
        else:
            await task_event_service.append_task_event(
                conn,
                final,
                "failed",
                task_event_service.event_payload(final, status="failed", error_code=code),
            )
    from app.services.content_event_service import close_content

    await close_content(job, completed=False)


async def cancel_job(owner, task_id, *, conn=None):
    if conn is None:
        async with transaction() as tx:
            return await cancel_job(owner, task_id, conn=tx)
    row = await fetch_one(
        "SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s FOR UPDATE",
        (task_id, owner),
        conn=conn,
    )
    if not row:
        raise not_found()
    if row["status"] in ("pending", "running"):
        await execute(
            "UPDATE quiz_tasks SET cancel_requested=TRUE,status='cancelled',stage='cancelled',lease_token=NULL WHERE task_id=%s",
            (task_id,),
            conn=conn,
        )
        from app.services import task_event_service

        job = decode(row)
        await task_event_service.append_task_event(
            conn,
            job,
            "cancelled",
            task_event_service.event_payload(job, status="cancelled"),
        )


async def get_task(owner, task_id):
    from app.models.task_event import business_settled_from
    from app.services import course_quiz_service

    row = await fetch_one(
        "SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s AND kind='quiz' AND mode='production'",
        (task_id, owner),
    )
    if not row:
        raise not_found()
    result = decode(row)
    await course_quiz_service.authorize_job(owner, result, require_active=False)
    view = {
        key: result.get(key)
        for key in (
            "task_id",
            "quiz_id",
            "status",
            "stage",
            "error_code",
            "error_message",
            "result",
        )
    }
    view["business_settled"] = business_settled_from(result["status"], result["stage"])
    return view
