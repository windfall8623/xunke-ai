"""Finite durable job queue. A lease fences every publication, including retries."""

import secrets
from datetime import timedelta

from pymysql import IntegrityError

from app.core.config import get_settings
from app.core.db import execute, fetch_one, transaction
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
    return decode(
        await fetch_one(
            "SELECT * FROM quiz_tasks WHERE task_id=%s", (task_id,), conn=conn
        )
    )


async def claim_job(worker_id, *, task_id=None, kinds=None):
    s = get_settings()
    async with transaction() as conn:
        await execute(
            "UPDATE quiz_tasks SET status='cancelled',stage='cancelled',lease_token=NULL WHERE cancel_requested=TRUE AND status IN ('pending','running')",
            conn=conn,
        )
        await execute(
            """UPDATE quiz_tasks SET status='failed',stage='failed',error_code='deadline_exceeded',lease_token=NULL
                         WHERE (status='pending' AND queued_expires_at<=UTC_TIMESTAMP(6)) OR
                         (status IN ('pending','running') AND deadline_at<=UTC_TIMESTAMP(6)) OR
                         (status='running' AND lease_expires_at<=UTC_TIMESTAMP(6) AND attempt>=max_attempts)""",
            conn=conn,
        )
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
        return decode(
            await fetch_one(
                "SELECT * FROM quiz_tasks WHERE task_id=%s",
                (row["task_id"],),
                conn=conn,
            )
        )


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
        await execute(
            "UPDATE quiz_tasks SET lease_expires_at=%s,stage=%s WHERE task_id=%s",
            (
                min(
                    row["deadline_at"],
                    now() + timedelta(seconds=get_settings().job_lease_seconds),
                ),
                stage or row["stage"],
                job["task_id"],
            ),
            conn=conn,
        )


async def complete_job(job, result, *, publisher=None):
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


async def cancel_job(owner, task_id, *, conn=None):
    if conn is None:
        async with transaction() as tx:
            return await cancel_job(owner, task_id, conn=tx)
    row = await fetch_one(
        "SELECT status FROM quiz_tasks WHERE task_id=%s AND user_id=%s FOR UPDATE",
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


async def get_task(owner, task_id):
    row = await fetch_one(
        "SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s AND kind='quiz' AND mode='production'",
        (task_id, owner),
    )
    if not row:
        raise not_found()
    result = decode(row)
    return {
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
