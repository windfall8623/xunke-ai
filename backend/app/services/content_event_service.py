"""Durable previews fenced by job leases. Losing preview storage never reruns a model."""

import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, register_after_commit, transaction
from app.core.errors import AppError, conflict
from app.core.values import dump, load
from app.models.content_event import ContentBlock, ContentFrame, ContentPayload
from app.models.task_event import TaskSignal, execution_id
from app.rag.errors import RagError
from app.services import job_service, source_service, task_event_notifier

logger = logging.getLogger(__name__)
KINDS = frozenset({"qa", "course_lesson", "course_tutor"})
MAX_FRAME_BYTES = 8192
MAX_PREVIEW_BYTES = 262144
_preview = ContextVar("private_content_preview", default=None)


def current_preview():
    return _preview.get()


def preview_block_fits(block_id, text, source_refs) -> bool:
    """Skip a block that cannot occupy one frame; never close the channel for size."""
    try:
        payload = ContentPayload(
            validated_blocks=[ContentBlock(block_id=block_id, text=text, source_refs=source_refs)],
            validation="structure_and_references_checked",
        )
    except Exception:
        return False
    encoded = dump(payload.model_dump(mode="json", exclude_none=True))
    return len(encoded.encode("utf-8")) + 512 <= MAX_FRAME_BYTES


async def reset_current_preview(generation_revision: int):
    preview = current_preview()
    if preview is not None:
        await preview.reset(generation_revision)
    return preview


def _notify(conn, row, seq):
    signal = TaskSignal(task_id=row["task_id"], owner_id=row["user_id"],
                        execution_id=execution_id(row["task_id"], row["attempt"]), seq=seq)

    async def send():
        # The local wake also works when Redis is disabled.
        task_event_notifier._dispatch_wake([signal.task_id])
        await task_event_notifier.publish_signals([signal])

    register_after_commit(conn, "content:" + row["task_id"], send)


async def _write(conn, row, head, frame_type, payload):
    seq = int(head["seq"]) + 1
    frame = ContentFrame(
        task_id=row["task_id"], execution_id=execution_id(row["task_id"], row["attempt"]),
        generation_revision=head["generation_revision"], seq=seq, type=frame_type, payload=payload,
    ).model_dump(mode="json", exclude_none=True)
    encoded = dump(frame)
    size = len(encoded.encode("utf-8"))
    if size > MAX_FRAME_BYTES:
        raise ValueError("Content frame exceeds preview limit")
    if frame_type in {"block", "delta"} and head["byte_count"] + size > MAX_PREVIEW_BYTES:
        return await _write(conn, row, head, "unavailable", ContentPayload(reason="preview_limit"))
    if frame_type in {"unavailable", "reset"}:
        await execute("DELETE FROM task_content_frames WHERE task_id=%s", (row["task_id"],), conn=conn)
    closed = frame_type in {"unavailable", "finalized"}
    status = frame_type if closed else "active"
    await execute(
        "INSERT INTO task_content_frames(task_id,owner_id,attempt,generation_revision,seq,payload_json) VALUES(%s,%s,%s,%s,%s,%s)",
        (row["task_id"], row["user_id"], row["attempt"], head["generation_revision"], seq, encoded), conn=conn,
    )
    await execute(
        "UPDATE task_content_heads SET seq=%s,byte_count=byte_count+%s,status=%s,updated_at=UTC_TIMESTAMP(6),"
        "closed_at=IF(%s,UTC_TIMESTAMP(6),NULL) WHERE task_id=%s",
        (seq, size, status, closed, row["task_id"]), conn=conn,
    )
    _notify(conn, row, seq)
    return frame


async def append_content_frame(job, generation_revision: int, frame_type: str, payload: dict) -> dict | None:
    if not get_settings().content_events_enabled or job["kind"] not in KINDS or job["mode"] != "production":
        return None
    if frame_type not in {"block", "delta", "reset", "unavailable"} or generation_revision < 1:
        raise ValueError("Unsupported worker preview frame")
    clean = ContentPayload.model_validate(payload)
    async with transaction() as conn:
        row = await job_service.locked_job(job, conn)
        if row.get("scope"):
            await source_service.reauthorize_scope(row["scope"], conn=conn)
        head = await fetch_one("SELECT * FROM task_content_heads WHERE task_id=%s FOR UPDATE", (job["task_id"],), conn=conn)
        if not head:
            await execute(
                "INSERT INTO task_content_heads(task_id,owner_id,attempt,generation_revision) VALUES(%s,%s,%s,%s)",
                (row["task_id"], row["user_id"], row["attempt"], generation_revision), conn=conn,
            )
            head = dict(seq=0, byte_count=0, attempt=row["attempt"], generation_revision=generation_revision, status="active")
        elif head["attempt"] != row["attempt"] or generation_revision > head["generation_revision"]:
            if head["attempt"] == row["attempt"] and frame_type != "reset":
                raise ValueError("A new draft requires a reset before its blocks")
            await execute("DELETE FROM task_content_frames WHERE task_id=%s", (row["task_id"],), conn=conn)
            await execute(
                "UPDATE task_content_heads SET attempt=%s,generation_revision=%s,seq=0,byte_count=0,status='active',closed_at=NULL WHERE task_id=%s",
                (row["attempt"], generation_revision, row["task_id"]), conn=conn,
            )
            head = dict(seq=0, byte_count=0, attempt=row["attempt"], generation_revision=generation_revision, status="active")
        if generation_revision != head["generation_revision"]:
            raise conflict("preview_revision_changed", "内容草稿已更新")
        if head["status"] != "active":
            return None
        return await _write(conn, row, head, frame_type, clean)


async def close_content_in_transaction(conn, job, *, completed: bool):
    """Called after business publication. Preview errors are contained by callers."""
    if job["kind"] not in KINDS:
        return
    head = await fetch_one("SELECT * FROM task_content_heads WHERE task_id=%s FOR UPDATE", (job["task_id"],), conn=conn)
    if head and head["attempt"] == job["attempt"] and head["status"] == "active":
        await _write(conn, job, head, "finalized" if completed else "unavailable", ContentPayload(
            reason="final_result_available" if completed else "generation_failed",
        ))


async def close_content(job, *, completed):
    if not get_settings().content_events_enabled or job["kind"] not in KINDS:
        return
    try:
        async with transaction() as conn:
            row = await fetch_one("SELECT * FROM quiz_tasks WHERE task_id=%s FOR UPDATE", (job["task_id"],), conn=conn)
            if row and row["user_id"] == job["user_id"] and row["attempt"] == job["attempt"]:
                await close_content_in_transaction(conn, job_service.decode(row), completed=completed)
    except Exception as exc:
        logger.warning("content_preview_close_degraded", extra={"reason": type(exc).__name__})


async def read_content(owner, task_id, attempt, revision, after_seq=0, *, limit=100):
    rows = await fetch_all(
        "SELECT f.payload_json FROM task_content_frames f JOIN task_content_heads h ON h.task_id=f.task_id "
        "WHERE f.task_id=%s AND f.owner_id=%s AND f.attempt=%s "
        "AND f.generation_revision=%s AND f.seq>%s "
        "AND (h.closed_at IS NULL OR h.closed_at>UTC_TIMESTAMP(6)-INTERVAL 1 HOUR) ORDER BY f.seq LIMIT %s",
        (task_id, owner, attempt, revision, after_seq, limit),
    )
    return [ContentFrame.model_validate(load(row["payload_json"])).model_dump(mode="json", exclude_none=True) for row in rows]


async def purge_content(*, owner_id=None, task_id=None, dry_run=False):
    # Expired or revoked previews only; official business content is untouched.
    if not dry_run and not task_id:
        await execute(
            "UPDATE task_content_heads h JOIN quiz_tasks q ON q.task_id=h.task_id "
            "SET h.closed_at=UTC_TIMESTAMP(6),h.status='unavailable' WHERE h.closed_at IS NULL "
            "AND (q.status IN ('completed','failed','cancelled') OR q.attempt<>h.attempt)"
            + (" AND h.owner_id=%s" if owner_id is not None else ""),
            (owner_id,) if owner_id is not None else (),
        )
    where, args = "closed_at < UTC_TIMESTAMP(6)-INTERVAL 1 HOUR", []
    if task_id:
        where, args = "task_id=%s", [task_id]
    if owner_id is not None:
        where += " AND owner_id=%s"
        args.append(owner_id)
    if dry_run:
        return (await fetch_one("SELECT COUNT(*) AS n FROM task_content_heads WHERE " + where, args))["n"]
    return await execute("DELETE FROM task_content_heads WHERE " + where, args)


class ContentPreview:
    def __init__(self, job):
        self.job, self.revision, self.disabled = job, 1, False
        self.pending = ""
        self.last_flush = time.monotonic()

    async def _send(self, kind, payload):
        if self.disabled:
            return
        try:
            frame = await append_content_frame(self.job, self.revision, kind, payload)
            if frame and frame["type"] == "unavailable":
                self.disabled = True
        except (AppError, RagError):
            raise
        except ValueError:
            try:
                await append_content_frame(self.job, self.revision, "unavailable", {"reason": "preview_limit"})
            except Exception:
                pass
            self.disabled = True
        except Exception as exc:
            self.disabled = True
            logger.warning("content_preview_storage_unavailable", extra={"reason": type(exc).__name__})

    async def reset(self, generation_revision):
        if generation_revision > self.revision:
            self.revision, self.pending = generation_revision, ""
            await self._send("reset", {"reason": "new_draft"})

    async def text(self, text):
        self.pending += text
        if len(self.pending.encode("utf-8")) >= 1024 or time.monotonic() - self.last_flush >= .25:
            await self.flush()

    async def flush(self):
        while self.pending and not self.disabled:
            # 1,000 codepoints is <=4 KiB of UTF-8 plus the bounded frame header.
            text, self.pending = self.pending[:1000], self.pending[1000:]
            await self._send("delta", {"text": text, "validation": "preview"})
        self.last_flush = time.monotonic()

    async def block(self, block_id, text, source_refs):
        await self._send("block", {"validated_blocks": [{"block_id": block_id, "text": text, "source_refs": source_refs}],
                                  "validation": "structure_and_references_checked"})

    async def invalidate(self):
        self.pending = ""
        await self._send("unavailable", {"reason": "generation_failed"})


@asynccontextmanager
async def content_preview(job):
    preview = ContentPreview(job) if get_settings().content_events_enabled and job["kind"] in KINDS else None
    token = _preview.set(preview)
    try:
        yield preview
        if preview:
            await preview.flush()
    except BaseException:
        if preview:
            try:
                await preview.invalidate()
            except Exception:
                pass
        raise
    finally:
        _preview.reset(token)
