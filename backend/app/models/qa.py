"""Public QA DTOs; task failures are separate from grounded answer outcomes."""

from typing import Any, Literal

from pydantic import Field, field_validator

from app.models.sources import PublicResolvedScope
from app.qa.contracts import AnswerBlock, AnswerStatus
from app.rag.contracts import Contract, DocumentEvidence, RequestedScope

TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class QaSessionCreate(Contract):
    title: str = Field(default="新的资料问答", min_length=1, max_length=80)
    scope: RequestedScope

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        if not value.strip():
            raise ValueError("Title cannot be blank")
        return value.strip()


class QaScopeUpdate(Contract):
    scope: RequestedScope
    expected_revision: int = Field(ge=1)


class QaMessageCreate(Contract):
    content: str = Field(min_length=1, max_length=2000)
    scope_revision: int = Field(ge=1)

    @field_validator("content")
    @classmethod
    def nonblank_content(cls, value):
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip()


class QaSessionView(Contract):
    session_id: str
    title: str
    scope_revision: int
    scope: PublicResolvedScope | None = None
    source_status: Literal["active", "revoked"] = "active"
    active_task_id: str | None = None
    created_at: str
    updated_at: str


class QaSessionList(Contract):
    items: list[QaSessionView]
    total: int
    page: int
    page_size: int


class QaAnswerView(Contract):
    answer_id: str
    session_id: str
    message_id: str
    scope_revision: int
    answer_status: AnswerStatus
    blocks: list[AnswerBlock]
    evidence: list[DocumentEvidence]
    retrieval_query: str
    usage: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class QaTaskView(Contract):
    task_id: str
    session_id: str
    message_id: str
    status: TaskStatus
    stage: str = "queued"
    error_code: str | None = None
    error_message: str | None = None
    # 任务关联业务记录是否同步完成；失败/取消后等待调和收尾才翻真。
    business_settled: bool = False
    answer: QaAnswerView | None = None
    queue_ms: int | None = None
    execution_ms: int | None = None


class QaMessageView(Contract):
    message_id: str
    session_id: str
    sequence: int
    role: Literal["user", "assistant"]
    content: str
    scope_revision: int
    task_id: str
    status: Literal["pending", "running", "completed", "failed", "cancelled", "revoked"]
    answer: QaAnswerView | None = None
    error_code: str | None = None
    created_at: str


class QaMessageList(Contract):
    items: list[QaMessageView]
    has_more: bool
    next_before: int | None = None


class QaFeedbackBody(Contract):
    rating: Literal["helpful", "unhelpful"]
    reason: Literal["incorrect", "unsupported", "incomplete", "other"] | None = None
    comment: str = Field(default="", max_length=2000)
    evaluation_consent: bool = False


class QaFeedbackView(Contract):
    feedback_id: str
