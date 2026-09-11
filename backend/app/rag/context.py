"""Pack whole immutable source excerpts into an explicit context token budget."""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

from app.rag.budget import count_tokens
from app.rag.contracts import DocumentEvidence, Evidence, EvidencePack
from app.rag.errors import GenerationValidationFailed, ScopeRevoked
from app.rag.scope import evidence_in_scope

_EVIDENCE_ADAPTER = TypeAdapter(Evidence)


def format_evidence(evidence) -> str:
    return f'<evidence id="{evidence.evidence_id}" source="{evidence.source_type}">\n{evidence.excerpt}\n</evidence>'


def assemble_evidence(
    evidence, scope, policy, token_budget: int, trace_id: str, *, coverage=None
) -> EvidencePack:
    accepted, seen, used = [], set(), 0
    for original in evidence:
        try:
            item = _EVIDENCE_ADAPTER.validate_python(
                original.model_dump(mode="json")
                if hasattr(original, "model_dump")
                else original
            )
        except ValidationError as exc:
            raise GenerationValidationFailed(
                "Evidence identity, quote, or locator is corrupt"
            ) from exc
        if not evidence_in_scope(item, scope):
            raise ScopeRevoked("Retrieved source is outside the authorized scope")
        if policy == "strict_docs" and not isinstance(item, DocumentEvidence):
            raise ScopeRevoked(
                "Web evidence is not allowed by the strict document policy"
            )
        if item.evidence_id in seen:
            continue
        # Retain only one copy of an identical source span, regardless of rank channel.
        anchor = (
            item.source_type,
            getattr(item, "parse_artifact_id", getattr(item, "snapshot_id", "")),
            getattr(item, "doc_id", ""),
            item.locator.start_char,
            item.locator.end_char,
            item.text_hash,
        )
        if anchor in seen:
            continue
        tokens = count_tokens(format_evidence(item))
        if used + tokens > token_budget:
            continue
        accepted.append(item)
        seen.add(item.evidence_id)
        seen.add(anchor)
        used += tokens
    status = (
        "ready" if accepted else ("model_only" if policy == "topic" else "insufficient")
    )
    return EvidencePack(
        trace_id=trace_id,
        policy=policy,
        resolved_scope=scope,
        evidence=accepted,
        coverage=coverage,
        status=status,
        provided_evidence_ids=[e.evidence_id for e in accepted],
        context_tokens=used,
    )
