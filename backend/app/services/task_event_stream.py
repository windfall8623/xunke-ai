"""业务授权的任务阶段 SSE 流：快照 + 游标补读 + 控制帧。

边界：
- 不提供绕过业务范围的通用任务 reader；每种任务注入自己的授权 reader。
- 先鉴权，再解释游标；历史可读性取决于当前授权。
- 快照的状态与 public_event_seq 来自同一行一致读取；不拼接两个 attempt。
- Redis 通知只是唤醒；每 task_event_sync_seconds 兜底复核授权并补读。
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable

import structlog
from starlette.responses import StreamingResponse

from app.core.auth import get_current_actor
from app.core.config import get_settings
from app.core.db import fetch_one
from app.core.errors import AppError, not_found
from app.core.exceptions import AuthenticationError
from app.core.values import iso, now
from app.models.task_event import (
    PUBLIC_STAGES,
    SOURCE_REVOKED_REASONS,
    STAGE_ALIASES,
    SnapshotEvent,
    business_settled_from,
    execution_id,
)
from app.services import task_event_notifier, task_event_service

logger = structlog.get_logger()

MAX_CONNECTIONS_PER_PROCESS = 200
MAX_CONNECTIONS_PER_OWNER = 5
MAX_BATCH = 100
MAX_EVENT_JSON_BYTES = 4096
TERMINAL_SYNC_WAIT_SECONDS = 60
TERMINAL = {"completed", "failed", "cancelled"}


def _public_stage(status: str, stage: str | None) -> str:
    mapped = STAGE_ALIASES.get(stage or "", stage)
    if mapped in PUBLIC_STAGES:
        return mapped
    return status


def _sse(frame: dict, *, event: str, frame_id: str | None = None) -> str:
    data = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
    lines = []
    if frame_id:
        lines.append(f"id: {frame_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"


@dataclass
class TaskReader:
    """每种任务注入自己的授权与身份提取；不开放裸通用任务流。"""

    kinds: frozenset
    authorize: Callable[[int, str], Awaitable[dict]]
    identity: Callable[[dict], dict]


def _qa_identity(view: dict) -> dict:
    fields = {}
    if view.get("session_id"):
        fields["session_id"] = view["session_id"]
    if view.get("message_id"):
        fields["message_id"] = view["message_id"]
    return fields


def _course_identity(view: dict) -> dict:
    fields = {}
    if view.get("course_id"):
        fields["course_id"] = view["course_id"]
    if view.get("lesson_id"):
        fields["lesson_id"] = view["lesson_id"]
    return fields


def _qa_reader() -> TaskReader:
    from app.services import qa_read

    return TaskReader(kinds=frozenset({"qa"}), authorize=qa_read.get_task, identity=_qa_identity)


def _course_reader() -> TaskReader:
    from app.services import course_read

    return TaskReader(
        kinds=frozenset({"course_outline", "course_lesson", "course_tutor"}),
        authorize=course_read.get_task,
        identity=_course_identity,
    )


def _quiz_reader() -> TaskReader:
    from app.services import job_service

    return TaskReader(
        kinds=frozenset({"quiz"}),
        authorize=job_service.get_task,
        identity=lambda view: {},
    )


def _practice_reader() -> TaskReader:
    from app.services import practice_service

    async def authorize(owner: int, task_id: str) -> dict:
        # The business reader checks generation/grading ownership and sources.
        # Its result can contain questions or grades; none belong in the stream.
        await practice_service.get_practice_task(owner, task_id)
        return {}

    return TaskReader(
        kinds=frozenset({"practice_generate", "practice_grade"}),
        authorize=authorize,
        identity=lambda view: {},
    )


_READERS = {
    "qa": _qa_reader(),
    "course": _course_reader(),
    "quiz": _quiz_reader(),
    "practice": _practice_reader(),
}


def _reader_for(kind: str) -> TaskReader:
    reader = _READERS.get(kind)
    if reader is None:
        raise not_found()
    return reader


class _ConnectionGate:
    def __init__(self) -> None:
        self._total = 0
        self._by_owner: defaultdict[int, int] = defaultdict(int)

    def register(self, owner_id: int) -> None:
        if self._total >= MAX_CONNECTIONS_PER_PROCESS or self._by_owner[owner_id] >= MAX_CONNECTIONS_PER_OWNER:
            raise AppError(
                429,
                "rate_limited",
                "订阅连接数已达上限，请稍后重试",
                retry_after_seconds=5,
            )
        self._total += 1
        self._by_owner[owner_id] += 1

    def release(self, owner_id: int) -> None:
        self._total = max(0, self._total - 1)
        self._by_owner[owner_id] = max(0, self._by_owner[owner_id] - 1)
        if self._by_owner[owner_id] == 0:
            self._by_owner.pop(owner_id, None)


_gate = _ConnectionGate()


def _parse_cursor(task_id: str, raw: str | None) -> tuple[int, int] | None:
    """游标 {execution_id}:{seq}；格式错误或与任务不符返回 None（视为无效）。"""
    if not raw:
        return None
    exec_part, sep, seq_part = raw.rpartition(":")
    prefix = task_id + ".a"
    if sep != ":" or not exec_part.startswith(prefix):
        return None
    attempt_digits = exec_part[len(prefix):]
    if not attempt_digits.isdigit() or not seq_part.isdigit():
        return None
    return int(attempt_digits), int(seq_part)


async def _snapshot_row(owner: int, task_id: str, kinds: frozenset):
    row = await fetch_one(
        "SELECT status,stage,error_code,attempt,public_event_seq,kind FROM quiz_tasks "
        "WHERE task_id=%s AND user_id=%s AND mode='production'",
        (task_id, owner),
    )
    if not row or row["kind"] not in kinds:
        raise not_found()
    return row


def _build_snapshot(task_id: str, identity: dict, row: dict) -> dict:
    attempt = int(row["attempt"])
    payload = dict(identity)
    payload["status"] = row["status"]
    payload["stage"] = _public_stage(row["status"], row["stage"])
    payload["business_settled"] = business_settled_from(row["status"], row["stage"])
    if row["status"] in {"failed", "cancelled"} and row["error_code"]:
        payload["error_code"] = row["error_code"]
    return SnapshotEvent(
        task_id=task_id,
        execution_id=execution_id(task_id, attempt),
        seq=int(row["public_event_seq"]),
        attempt=attempt,
        payload=payload,
        occurred_at=iso(now()),
    ).model_dump(mode="json")


def _reset_frame(task_id: str, reason: str, new_execution_id: str) -> dict:
    return {
        "schema_version": 1,
        "task_id": task_id,
        "type": "reset",
        "reason": reason,
        "execution_id": new_execution_id,
    }


def _source_revoked_frame(task_id: str, reason: str) -> dict:
    return {
        "schema_version": 1,
        "task_id": task_id,
        "type": "source_revoked",
        "reason": reason,
    }


async def task_events_endpoint(
    request,
    *,
    actor,
    kind: str,
    task_id: str,
    last_event_id: str | None,
) -> StreamingResponse:
    """SSE 端点入口：鉴权先行，快照一致读取后交给流生成器。"""
    settings = get_settings()
    if not settings.task_events_enabled:
        raise AppError(503, "task_events_disabled", "任务阶段推送未启用")
    reader = _reader_for(kind)
    owner = actor.owner_id

    # 先鉴权（会话已由依赖校验；这里做业务授权与来源版本校验），再解释游标。
    view = await reader.authorize(owner, task_id)
    row = await _snapshot_row(owner, task_id, reader.kinds)

    cursor = _parse_cursor(task_id, last_event_id)
    current_attempt, high = int(row["attempt"]), int(row["public_event_seq"])
    if cursor is not None:
        cursor_attempt, cursor_seq = cursor
        if cursor_attempt > current_attempt or (
            cursor_attempt == current_attempt and cursor_seq > high
        ):
            raise AppError(422, "invalid_cursor", "事件游标无效")
        if cursor_seq < 0:
            raise AppError(422, "invalid_cursor", "事件游标无效")

    _gate.register(owner)
    try:
        return StreamingResponse(
            _stream(
                request,
                owner=owner,
                task_id=task_id,
                reader=reader,
                identity=reader.identity(view),
                row=row,
                cursor=cursor,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
    except BaseException:
        _gate.release(owner)
        raise


async def _stream(
    request,
    *,
    owner: int,
    task_id: str,
    reader: TaskReader,
    identity: dict,
    row: dict,
    cursor: tuple[int, int] | None,
):
    settings = get_settings()
    sync_seconds = settings.task_event_sync_seconds
    max_connection_seconds = settings.task_event_max_connection_seconds
    started = now()
    try:
        cursor_attempt = int(row["attempt"])
        high = int(row["public_event_seq"])

        if cursor is None:
            yield _sse(
                _build_snapshot(task_id, identity, row),
                event="snapshot",
                frame_id=f"{execution_id(task_id, cursor_attempt)}:{high}",
            )
            cursor_seq = high
        else:
            # 带合法游标重连：不发快照，首次补读由循环完成。
            cursor_attempt, cursor_seq = cursor
        if cursor is not None and cursor[0] < int(row["attempt"]):
            # attempt 已切换：禁止拼接旧执行，reset 后重新快照。
            new_attempt = int(row["attempt"])
            yield _sse(
                _reset_frame(task_id, "attempt_changed", execution_id(task_id, new_attempt)),
                event="reset",
            )
            cursor_attempt = new_attempt
            cursor_seq = high
            yield _sse(
                _build_snapshot(task_id, identity, row),
                event="snapshot",
                frame_id=f"{execution_id(task_id, new_attempt)}:{high}",
            )

        unsettled_cycles = 0
        first_cycle = True
        while True:
            if not first_cycle:
                await task_event_notifier.wait_for_wake(task_id, float(sync_seconds))
            first_cycle = False
            if (now() - started).total_seconds() >= max_connection_seconds:
                return  # 轮换连接：前端用游标重连同一任务

            # 每个周期先复核会话与业务授权，再补读。
            try:
                current_actor = await get_current_actor(request)
                if current_actor.owner_id != owner:
                    return
                await reader.authorize(owner, task_id)
            except AuthenticationError:
                return
            except AppError as exc:
                if exc.status == 403 and exc.code in SOURCE_REVOKED_REASONS:
                    yield _sse(
                        _source_revoked_frame(task_id, "source_revoked"),
                        event="source_revoked",
                    )
                return

            row = await _snapshot_row(owner, task_id, reader.kinds)
            current_attempt = int(row["attempt"])
            high = int(row["public_event_seq"])
            sent_any = False

            if current_attempt != cursor_attempt:
                yield _sse(
                    _reset_frame(task_id, "attempt_changed", execution_id(task_id, current_attempt)),
                    event="reset",
                )
                cursor_attempt, cursor_seq, sent_any = current_attempt, high, True
                yield _sse(
                    _build_snapshot(task_id, identity, row),
                    event="snapshot",
                    frame_id=f"{execution_id(task_id, current_attempt)}:{high}",
                )

            if high > cursor_seq:
                events = await task_event_service.read_task_events(
                    owner,
                    task_id,
                    attempt=cursor_attempt,
                    after_seq=cursor_seq,
                    through_seq=high,
                    limit=MAX_BATCH,
                )
                gap = bool(events) and events[0].seq != cursor_seq + 1 and cursor_seq > 0
                gap = gap or (not events and cursor_seq > 0)
                if gap:
                    yield _sse(
                        _reset_frame(task_id, "event_gap", execution_id(task_id, cursor_attempt)),
                        event="reset",
                    )
                    yield _sse(
                        _build_snapshot(task_id, identity, row),
                        event="snapshot",
                        frame_id=f"{execution_id(task_id, cursor_attempt)}:{high}",
                    )
                    cursor_seq = high
                    sent_any = True
                else:
                    for event in events:
                        frame = event.model_dump(mode="json")
                        data = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
                        if len(data.encode("utf-8")) > MAX_EVENT_JSON_BYTES:
                            logger.warning("task_event_frame_oversized", task_id=task_id, seq=event.seq)
                            continue
                        yield _sse(
                            frame,
                            event=event.type,
                            frame_id=f"{event.execution_id}:{event.seq}",
                        )
                        cursor_seq = event.seq
                        sent_any = True

            settled = business_settled_from(row["status"], row["stage"])
            if row["status"] in TERMINAL and settled:
                if not sent_any:
                    yield ": keepalive\n\n"
                return
            if row["status"] in TERMINAL:
                unsettled_cycles += 1
                if unsettled_cycles * sync_seconds >= TERMINAL_SYNC_WAIT_SECONDS:
                    yield _sse(
                        _build_snapshot(task_id, identity, row),
                        event="snapshot",
                        frame_id=f"{execution_id(task_id, cursor_attempt)}:{high}",
                    )
                    return
            if not sent_any:
                yield ": keepalive\n\n"
    finally:
        _gate.release(owner)
