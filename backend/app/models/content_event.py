"""Private content frames; deliberately separate from public task phase events."""

from typing import Literal

from pydantic import Field

from app.rag.contracts import Contract


class ContentBlock(Contract):
    block_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=6000)
    source_refs: list[str] = Field(default_factory=list, max_length=20)


class ContentPayload(Contract):
    block_id: str | None = Field(default=None, max_length=80)
    text: str | None = Field(default=None, max_length=6000)
    validated_blocks: list[ContentBlock] | None = Field(default=None, max_length=30)
    validation: Literal["preview", "structure_and_references_checked"] | None = None
    reason: Literal[
        "new_draft", "attempt_changed", "cursor_expired", "stream_unavailable",
        "preview_limit", "generation_failed", "source_revoked", "session_expired",
        "final_result_available", "preview_expired",
    ] | None = None


class ContentFrame(Contract):
    schema_version: Literal["xunke-content.v1"] = "xunke-content.v1"
    task_id: str
    execution_id: str
    generation_revision: int = Field(ge=1)
    seq: int = Field(ge=0)
    type: Literal["snapshot", "delta", "block", "reset", "finalized", "unavailable", "revoked"]
    payload: ContentPayload = Field(default_factory=ContentPayload)
