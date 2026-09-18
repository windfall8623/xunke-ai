"""Private SSE replays current bounded content after session and source checks."""

import time

from starlette.responses import StreamingResponse

from app.core.auth import get_current_actor
from app.core.config import get_settings
from app.core.db import fetch_one
from app.core.errors import AppError, not_found
from app.core.exceptions import AuthenticationError
from app.models.content_event import ContentFrame
from app.models.task_event import execution_id
from app.rag.errors import RagError
from app.services import content_event_service as content, task_event_notifier
from app.services.task_event_stream import _gate, _reader_for, _snapshot_row, _sse


def _frame(task_id, attempt, revision, seq, kind, reason=None):
    return ContentFrame(task_id=task_id, execution_id=execution_id(task_id, attempt),
                        generation_revision=revision, seq=seq, type=kind,
                        payload={"reason": reason} if reason else {}).model_dump(mode="json", exclude_none=True)


def _encode(frame):
    cursor = f"{frame['execution_id']}.g{frame['generation_revision']}:{frame['seq']}"
    return _sse(frame, event=frame["type"], frame_id=cursor)


def _cursor(raw, task_id):
    if not raw or len(raw) > 180:
        return None
    import re
    match = re.fullmatch(re.escape(task_id) + r"\.a(\d+)\.g(\d+):(\d+)", raw)
    return tuple(map(int, match.groups())) if match else None


async def content_events_endpoint(request, *, actor, kind, task_id, last_event_id=None):
    if not get_settings().content_events_enabled:
        raise AppError(503, "content_events_disabled", "正文预览未启用，可继续查看任务进度")
    if kind not in {"course", "qa"}:
        raise not_found()
    reader = _reader_for(kind)
    await reader.authorize(actor.owner_id, task_id)
    row = await _snapshot_row(actor.owner_id, task_id, reader.kinds)
    if row["kind"] not in content.KINDS:
        raise not_found()
    _gate.register(actor.owner_id)
    try:
        return StreamingResponse(
            _stream(request, actor.owner_id, task_id, reader, _cursor(last_event_id, task_id)),
            media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
    except BaseException:
        _gate.release(actor.owner_id)
        raise


async def _stream(request, owner, task_id, reader, cursor):
    started, last = time.monotonic(), cursor
    attempt, revision, seq = cursor or (0, 1, 0)
    try:
        while time.monotonic() - started < get_settings().task_event_max_connection_seconds:
            if await request.is_disconnected():
                return
            try:
                actor = await get_current_actor(request)
                if actor.owner_id != owner:
                    raise AuthenticationError()
                await reader.authorize(owner, task_id)
            except (AuthenticationError, AppError, RagError) as exc:
                reason = "session_expired" if isinstance(exc, AuthenticationError) else "source_revoked"
                yield _encode(_frame(task_id, attempt, revision, seq, "revoked", reason))
                return
            row = await _snapshot_row(owner, task_id, reader.kinds)
            head = await fetch_one("SELECT * FROM task_content_heads WHERE task_id=%s AND owner_id=%s", (task_id, owner))
            attempt = row["attempt"]
            if head and head["attempt"] == attempt:
                revision, high = head["generation_revision"], head["seq"]
                if last is None or last[:2] != (attempt, revision) or last[2] > high:
                    yield _encode(_frame(task_id, attempt, revision, 0, "snapshot" if last is None else "reset",
                                         "new_draft" if last else None))
                    last = (attempt, revision, 0)
                frames = await content.read_content(owner, task_id, attempt, revision, last[2])
                # Frame batches are already bounded to 8 KiB each. A snapshot
                # replays the current revision's frames instead of one huge blob.
                for frame in frames:
                    yield _encode(frame)
                    seq = frame["seq"]
                    last = (attempt, revision, seq)
                if frames and last[2] < high:
                    continue
            if row["status"] in {"completed", "failed", "cancelled"}:
                terminal = "finalized" if row["status"] == "completed" else "unavailable"
                yield _encode(_frame(task_id, attempt, revision, (last or (0, 0, 0))[2], terminal,
                                     "final_result_available" if terminal == "finalized" else "generation_failed"))
                return
            yield ": keepalive\n\n"
            await task_event_notifier.wait_for_wake(task_id, min(.5, float(get_settings().task_event_sync_seconds)))
    finally:
        _gate.release(owner)
