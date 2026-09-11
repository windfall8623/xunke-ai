"""JSON-only QA contracts. History explains intent; it is never source evidence."""

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.rag.contracts import Contract, DocumentEvidence, Identity, Usage

AnswerStatus = Literal[
    "answered",
    "partial",
    "needs_clarification",
    "insufficient_evidence",
    "conflicting_sources",
]


class ChatHistoryTurn(Contract):
    question: str = Field(min_length=1, max_length=2000)
    # Accept every valid answer (24,000 text bytes plus block separators) before
    # select_history applies the smaller, whole-turn context budget.
    answer: str = Field(min_length=1, max_length=24022)
    scope_fingerprint: str = Field(min_length=1, max_length=256)


def select_history(
    turns: list[ChatHistoryTurn], scope_fingerprint: str
) -> list[ChatHistoryTurn]:
    selected, size = [], 0
    for raw in reversed(turns):
        turn = ChatHistoryTurn.model_validate(raw)
        if turn.scope_fingerprint != scope_fingerprint:
            continue
        # Include JSON framing slack in addition to the complete text pairs.
        cost = (
            len(turn.question.encode("utf-8")) + len(turn.answer.encode("utf-8")) + 64
        )
        if len(selected) == 6 or size + cost > 8000:
            break
        selected.append(turn)
        size += cost
    return list(reversed(selected))


class AnswerBlock(Contract):
    block_id: Identity
    kind: Literal["fact", "notice"] = "fact"
    text: str = Field(min_length=1, max_length=6000)
    citation_refs: list[Identity] = Field(default_factory=list, max_length=20)

    @field_validator("text")
    @classmethod
    def meaningful_text(cls, value):
        if not value.strip():
            raise ValueError("Answer text cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def fact_needs_citation(self):
        if self.kind == "fact" and not self.citation_refs:
            raise ValueError("A factual block needs source citations")
        if len(self.citation_refs) != len(set(self.citation_refs)):
            raise ValueError("Duplicate citation references")
        return self


class ChatAnswerPayload(Contract):
    answer_status: AnswerStatus
    blocks: list[AnswerBlock] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def status_matches_blocks(self):
        if len({b.block_id for b in self.blocks}) != len(self.blocks):
            raise ValueError("Answer block identities must be unique")
        facts = [block for block in self.blocks if block.kind == "fact"]
        if (
            self.answer_status in {"answered", "partial", "conflicting_sources"}
            and not facts
        ):
            raise ValueError("Substantive answers require cited factual blocks")
        if (
            self.answer_status in {"needs_clarification", "insufficient_evidence"}
            and facts
        ):
            raise ValueError("Abstention cannot publish factual claims")
        if sum(len(b.text.encode("utf-8")) for b in self.blocks) > 24000:
            raise ValueError("Answer exceeds its text budget")
        return self


class ChatAnswerArtifact(ChatAnswerPayload):
    schema_version: Literal["1"] = "1"
    case_type: Literal["qa"] = "qa"
    run_id: Identity
    evidence: list[DocumentEvidence] = Field(default_factory=list, max_length=40)
    retrieval_query: str = Field(min_length=1, max_length=2000)
    scope_fingerprint: str
    pipeline_config_hash: str
    model_fingerprint: str = "unconfigured"
    prompt_version: str = "qa-v1"
    usage: Usage = Field(default_factory=Usage)
    effective_config: dict[str, Any] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def citations_exist(self):
        ids = {item.evidence_id for item in self.evidence}
        if len(ids) != len(self.evidence):
            raise ValueError("Duplicate evidence identities")
        cited = {ref for block in self.blocks for ref in block.citation_refs}
        if not cited <= ids:
            raise ValueError("Answer cites evidence outside its evidence pack")
        if self.answer_status == "conflicting_sources" and len(cited) < 2:
            raise ValueError("Conflicting sources require separate source references")
        return self
