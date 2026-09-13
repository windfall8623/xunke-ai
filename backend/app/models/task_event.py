"""Public task event DTOs. Events carry whitelisted fields only — never
answers, prompts, user questions, raw results, scopes, leases, tokens or
provider errors."""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import Field, RootModel

from app.rag.contracts import Contract

TaskEventType = Literal["phase", "completed", "failed", "cancelled", "settled"]

# 传输层帧类型：snapshot 是授权快照，reset / source_revoked 是连接控制帧，
# 三者都不写入事件表。
STREAM_TYPES = frozenset({"snapshot", "reset", "source_revoked"})

# 持久化白名单：只有真实发生的回调才写入；控制帧（snapshot/reset/source_revoked）
# 是传输层概念，不落库。
PERSISTENT_TYPES = frozenset({"phase", "completed", "failed", "cancelled", "settled"})

# 只为已接入授权任务页的生产任务追加公开事件。
EVENT_KINDS = frozenset({
    "qa", "course_outline", "course_lesson", "course_tutor",
    "quiz", "practice_generate", "practice_grade",
    "course_application_generate", "course_application_feedback",
})

# 公开阶段枚举：每个值都映射自现有真实回调阶段，不虚构拆分、百分比或预计完成时间。
PUBLIC_STAGES = frozenset({
    "queued",
    "starting",
    "rewriting",
    "retrieving",
    "preparing",
    "generating",
    "validating",
    "saving",
    "grading",
    "planning",
    "teaching",
    "reviewing",
    "revising",
})

# 内部阶段 → 公开阶段；未命中的内部阶段不写事件（不伪造）。
STAGE_ALIASES = {
    "rewriting": "rewriting",
    "retrieving": "retrieving",
    "generating": "generating",
    "validating": "validating",
    "grading": "grading",
    "publishing": "saving",
    "preparing_course_sources": "preparing",
    "preparing_tutor_sources": "preparing",
    "generating_outline": "generating",
    "generating_lesson": "generating",
    "generating_tutor_answer": "generating",
    "saving_course": "saving",
    "saving_tutor_answer": "saving",
    "preparing_application_sources": "preparing",
    "generating_application": "generating",
    "grading_application": "grading",
    "saving_application": "saving",
}

RESET_REASONS = frozenset({"attempt_changed", "cursor_expired", "event_gap"})
SOURCE_REVOKED_REASONS = frozenset({"source_revoked", "revision_conflict"})


def execution_id(task_id: str, attempt: int) -> str:
    """执行身份只由 task_id 与 attempt 组成，绝不使用 lease_token。"""
    return f"{task_id}.a{int(attempt)}"


def business_settled_from(status: str, stage: str | None) -> bool:
    """任务关联业务记录是否已同步完成：完成即真；失败/取消须等到调和收尾。"""
    if status == "completed":
        return True
    return status in {"failed", "cancelled"} and bool(stage) and stage.endswith("_reconciled")


class TaskEventPayload(Contract):
    status: str
    stage: str | None = None
    error_code: str | None = None
    business_settled: bool = False

    # 必要身份字段（按任务种类取用），不包含任何正文或结果。
    session_id: str | None = None
    message_id: str | None = None
    course_id: str | None = None
    lesson_id: str | None = None
    content_version: int | None = Field(default=None, ge=1)

    model_config = Contract.model_config | {"extra": "forbid"}


class TaskEvent(Contract):
    schema_version: int = 1
    task_id: str
    execution_id: str
    seq: int = Field(ge=0)
    attempt: int = Field(ge=0)
    type: TaskEventType
    payload: TaskEventPayload
    occurred_at: str


class TaskSignal(Contract):
    """提交后的内部通知数据；只用于唤醒，不代表任务结果。"""

    task_id: str
    owner_id: int
    execution_id: str
    seq: int


def build_event(
    task_id: str,
    attempt: int,
    seq: int,
    event_type: TaskEventType,
    payload: dict[str, Any],
    occurred_at: str,
) -> TaskEvent:
    return TaskEvent(
        task_id=task_id,
        execution_id=execution_id(task_id, attempt),
        seq=seq,
        attempt=attempt,
        type=event_type,
        payload=TaskEventPayload.model_validate(payload),
        occurred_at=occurred_at,
    )


class SnapshotEvent(Contract):
    """首连或 reset 后的授权快照；seq 为本快照高水位，可为 0。"""

    schema_version: int = 1
    task_id: str
    execution_id: str
    seq: int = Field(ge=0)
    attempt: int = Field(ge=0)
    type: Literal["snapshot"] = "snapshot"
    payload: TaskEventPayload
    occurred_at: str


class ResetFrame(Contract):
    """控制帧：不带 seq 与 SSE id，前端清空旧预览并等待新快照。"""

    schema_version: int = 1
    task_id: str
    type: Literal["reset"] = "reset"
    reason: Literal["attempt_changed", "cursor_expired", "event_gap"]
    execution_id: str


class SourceRevokedFrame(Contract):
    """控制帧：隐藏来源内容并停止订阅。"""

    schema_version: int = 1
    task_id: str
    type: Literal["source_revoked"] = "source_revoked"
    reason: Literal["source_revoked", "revision_conflict"]


class TaskStreamFrame(RootModel):
    """SSE data 帧的公开联合类型：持久事件 / 快照 / 控制帧。"""

    root: Union[TaskEvent, SnapshotEvent, ResetFrame, SourceRevokedFrame]
