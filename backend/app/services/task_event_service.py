"""任务公开事件：与任务状态同事务追加，提交后经 notifier 唤醒 SSE。

约束：
- 只有已接入授权任务页的白名单 kind 且 mode=production 的任务产生公开事件；
  覆盖问答、课程、测验和练习生成/评分，其余任务走原状态路径。
- seq 在同一 task 内严格递增、跨 attempt 不归零；事件行带 attempt，
  游标 {execution_id}:{seq} 的补读同时过滤 owner/task/attempt/seq 区间。
- phase 事件只映射白名单公开阶段；相同阶段的纯续租不写事件。
- 事件 owner/attempt 取自调用方已锁定的任务行，不信任外部传入。
"""

from __future__ import annotations

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.values import dump, iso, load, now
from app.models.task_event import (
    EVENT_KINDS,
    PERSISTENT_TYPES,
    PUBLIC_STAGES,
    STAGE_ALIASES,
    TaskEvent,
    TaskSignal,
    business_settled_from,
    build_event,
)
from app.services import task_event_notifier

_SIGNALS_KEY = "__task_event_signals__"
_FLUSH_KEY = "__task_event_flush__"


def _identity_fields(job) -> dict:
    """按任务种类提取 payload 白名单内的身份字段；不含正文或结果。"""
    request = job.get("request") or {}
    kind = job["kind"]
    fields: dict = {}
    if kind == "qa":
        if request.get("session_id"):
            fields["session_id"] = request["session_id"]
        if request.get("assistant_message_id"):
            fields["message_id"] = request["assistant_message_id"]
    else:
        if request.get("course_id"):
            fields["course_id"] = request["course_id"]
        if request.get("lesson_id"):
            fields["lesson_id"] = request["lesson_id"]
        if request.get("content_version"):
            fields["content_version"] = int(request["content_version"])
    return fields


def _slot(conn) -> dict:
    registry = getattr(conn, "_xunke_after_commit", None)
    if registry is None:
        raise ValueError("task events require an active transaction connection")
    return registry.setdefault(_SIGNALS_KEY, {})


def _register_flush(conn) -> None:
    if _FLUSH_KEY not in getattr(conn, "_xunke_after_commit", {}):
        # Capture this transaction's signals before the connection is released.
        # A returned pool connection may already belong to another transaction.
        pending = _slot(conn)

        async def flush():
            signals = list(pending.values())
            pending.clear()
            await task_event_notifier.publish_signals(signals)

        from app.core.db import register_after_commit

        register_after_commit(conn, _FLUSH_KEY, flush)


async def append_task_event(conn, job, event_type: str, payload: dict) -> TaskSignal | None:
    """在持有任务行锁的当前事务里追加一条公开事件。

    返回 TaskSignal（已注册为提交后通知）；任务不在白名单或阶段不可公开时
    返回 None，调用方无需区分。
    """
    if event_type not in PERSISTENT_TYPES:
        raise ValueError(f"unsupported public event type: {event_type}")
    if job["mode"] != "production" or job["kind"] not in EVENT_KINDS:
        return None
    if not job.get("user_id"):
        # 无属主任务没有可授权的读取方，也不产生事件。
        return None
    clean = dict(payload)
    if event_type == "phase":
        internal_stage = clean.get("stage")
        # 内部阶段映射为固定公开枚举；未命中的真实阶段不伪造。
        public_stage = STAGE_ALIASES.get(internal_stage or "") or (
            internal_stage if internal_stage in PUBLIC_STAGES else None
        )
        if public_stage is None:
            return None
        clean["stage"] = public_stage
    task_id = job["task_id"]
    attempt = int(job["attempt"])
    owner = int(job["user_id"])
    await execute(
        "UPDATE quiz_tasks SET public_event_seq=LAST_INSERT_ID(public_event_seq+1) WHERE task_id=%s",
        (task_id,),
        conn=conn,
    )
    row = await fetch_one("SELECT LAST_INSERT_ID() AS seq", conn=conn)
    seq = int(row["seq"])
    event = build_event(task_id, attempt, seq, event_type, clean, iso(now()))
    await execute(
        "INSERT INTO task_public_events(task_id,owner_id,seq,attempt,event_type,payload_json) "
        "VALUES(%s,%s,%s,%s,%s,%s)",
        (task_id, owner, seq, attempt, event_type, dump(event.model_dump(mode="json"))),
        conn=conn,
    )
    signal = TaskSignal(
        task_id=task_id, owner_id=owner, execution_id=event.execution_id, seq=seq
    )
    slot = _slot(conn)
    previous = slot.get(task_id)
    if previous is None or signal.seq > previous.seq:
        slot[task_id] = signal
    _register_flush(conn)
    return signal


def event_payload(
    job, *, status: str, stage: str | None = None, error_code: str | None = None, settled: bool = False
) -> dict:
    payload = _identity_fields(job)
    payload["status"] = status
    payload["stage"] = stage or status
    payload["business_settled"] = (
        True if settled else business_settled_from(status, stage or status)
    )
    if error_code:
        payload["error_code"] = error_code
    return payload


async def append_settled_event(conn, job) -> TaskSignal | None:
    """调和收尾事件：只更新 business_settled 布尔值，不制造第二次失败。"""
    return await append_task_event(
        conn,
        job,
        "settled",
        event_payload(job, status=job["status"], settled=True),
    )


async def read_task_events(
    owner_id: int,
    task_id: str,
    *,
    attempt: int,
    after_seq: int = 0,
    through_seq: int | None = None,
    limit: int = 100,
) -> list[TaskEvent]:
    sql = (
        "SELECT payload_json FROM task_public_events WHERE task_id=%s AND owner_id=%s "
        "AND attempt=%s AND seq>%s"
    )
    params: list = [task_id, owner_id, attempt, after_seq]
    if through_seq is not None:
        sql += " AND seq<=%s"
        params.append(through_seq)
    sql += " ORDER BY seq LIMIT %s"
    params.append(limit)
    rows = await fetch_all(sql, tuple(params))
    return [TaskEvent.model_validate(load(row["payload_json"])) for row in rows]


async def purge_expired_events(retention_hours: int = 24, limit: int = 500) -> int:
    """只清理已终态任务的到期事件；不删除任务或学习记录。"""
    rows = await fetch_all(
        "SELECT e.task_id, e.seq FROM task_public_events e JOIN quiz_tasks t ON t.task_id=e.task_id "
        "WHERE e.created_at < UTC_TIMESTAMP(6) - INTERVAL %s HOUR "
        "AND t.status IN ('completed','failed','cancelled') "
        "ORDER BY e.created_at, e.task_id, e.seq LIMIT %s",
        (retention_hours, limit),
    )
    if not rows:
        return 0
    removed = 0
    async with transaction() as conn:
        for row in rows:
            removed += await execute(
                "DELETE FROM task_public_events WHERE task_id=%s AND seq=%s",
                (row["task_id"], row["seq"]),
                conn=conn,
            )
    return removed
