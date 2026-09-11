"""Pure validation and private sealing against the complete, fixed source pack."""

from __future__ import annotations

from pydantic import Field, StrictBool, TypeAdapter, ValidationError

from app.practice.contracts import (
    PracticeArtifact,
    PracticePayload,
    PracticeQuestion,
    PracticeSpec,
    PracticeUsage,
)
from app.practice.identity import (
    canonical_question_version as canonical_question_version,
)
from app.rag.contracts import (
    ActorContext,
    Contract,
    DocumentEvidence,
    EvidencePack,
    ExecutionContext,
    PipelineConfig,
    stable_hash,
)
from app.rag.errors import GenerationValidationFailed
from app.rag.scope import evidence_in_scope, require_execution_scope

_QUESTION = TypeAdapter(PracticeQuestion)


class PracticeSupportCheck(Contract):
    question_id: str = Field(min_length=1, max_length=64)
    supported: StrictBool


class PracticeSemanticReply(Contract):
    """Generation support only; never a learner assessment or confirmation."""

    checks: list[PracticeSupportCheck] = Field(max_length=10)
    errors: list[str] = Field(max_length=30)


def validate_practice_semantics(raw, payload: PracticePayload) -> list[str]:
    try:
        reply = PracticeSemanticReply.model_validate(
            raw.model_dump(mode="json")
            if isinstance(raw, PracticeSemanticReply)
            else raw
        )
    except ValidationError:
        return ["generation_semantics_failed"]
    expected = {question.id for question in payload.questions}
    ids = [check.question_id for check in reply.checks]
    if (
        len(ids) != len(expected)
        or set(ids) != expected
        or not all(check.supported for check in reply.checks)
        or reply.errors
    ):
        return ["generation_semantics_failed"]
    return []


def checked_evidence_pack(pack: EvidencePack) -> EvidencePack:
    """Revalidate mutable nested values; actual source reads remain an injected port."""
    try:
        checked = EvidencePack.model_validate(pack.model_dump(mode="json"))
        ids = [item.evidence_id for item in checked.evidence]
        provided = checked.provided_evidence_ids
        if (
            not checked.resolved_scope.documents
            or checked.policy != "strict_docs"
            or checked.status != "ready"
            or not ids
            or len(ids) != len(set(ids))
            or not provided
            or len(provided) != len(set(provided))
            or not set(provided) <= set(ids)
            or any(
                not isinstance(item, DocumentEvidence)
                or not evidence_in_scope(item, checked.resolved_scope)
                for item in checked.evidence
            )
        ):
            raise ValueError("Invalid fixed document evidence")
        return checked
    except (ValidationError, ValueError, TypeError, AttributeError) as exc:
        raise GenerationValidationFailed(
            "Practice requires intact fixed document evidence",
            details={"validation_errors": ["source_changed"]},
        ) from exc


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_practice_payload(
    payload: PracticePayload | dict, spec: PracticeSpec, pack: EvidencePack
) -> list[str]:
    """Return stable private error codes without echoing model or source text."""
    checked = checked_evidence_pack(pack)
    raw = (
        payload.model_dump(mode="json")
        if isinstance(payload, PracticePayload)
        else payload
    )
    if not isinstance(raw, dict) or not isinstance(raw.get("questions"), list):
        return ["question_count_mismatch", "invalid_practice_payload"]
    questions = raw["questions"]
    errors = []
    if len(questions) != spec.question_count:
        errors.append("question_count_mismatch")
    ids = [q.get("id") for q in questions if isinstance(q, dict)]
    if all(isinstance(identity, str) for identity in ids) and len(ids) != len(set(ids)):
        errors.append("duplicate_question_id")
    types = [q.get("type") for q in questions if isinstance(q, dict)]
    if not all(isinstance(kind, str) for kind in types) or set(types) != set(
        spec.question_types
    ):
        errors.append("question_type_mismatch")
    requested = set(spec.concept_ids)
    covered = set()
    evidence = {
        item.evidence_id: item
        for item in checked.evidence
        if item.evidence_id in checked.provided_evidence_ids
    }
    for question in questions:
        if not isinstance(question, dict):
            errors.append("invalid_practice_payload")
            continue
        concepts = question.get("concept_ids")
        if (
            not _strings(concepts)
            or not 1 <= len(concepts) <= 3
            or len(concepts) != len(set(concepts))
            or not set(concepts) <= requested
        ):
            errors.append("concept_outside_request")
        if _strings(concepts):
            covered.update(concepts)
    if requested - covered:
        errors.append("missing_requested_concept")
    for question in questions:
        if not isinstance(question, dict):
            continue
        refs = question.get("citation_refs")
        if (
            not _strings(refs)
            or not refs
            or len(refs) != len(set(refs))
            or not set(refs) <= set(evidence)
        ):
            errors.append("invalid_practice_citation")
        excerpts = (
            [evidence[ref].excerpt for ref in refs if ref in evidence]
            if _strings(refs)
            else []
        )
        quotes = question.get("support_quotes")
        if (
            not _strings(quotes)
            or not quotes
            or any(
                not quote.strip() or not any(quote in text for text in excerpts)
                for quote in quotes
            )
        ):
            errors.append("unsupported_support_quote")
        try:
            _QUESTION.validate_python(question)
        except ValidationError as exc:
            for error in exc.errors(include_input=False, include_context=False):
                location = error["loc"]
                if "rubric" in location or (
                    error["type"] == "value_error" and len(location) == 1
                ):
                    errors.append("invalid_rubric")
                else:
                    errors.append("invalid_practice_payload")
    try:
        PracticePayload.model_validate(raw)
    except ValidationError:
        if not errors:
            errors.append("invalid_practice_payload")
    return list(dict.fromkeys(errors))


def seal_practice_artifact(
    payload: PracticePayload | dict,
    spec: PracticeSpec,
    actor: ActorContext,
    context: ExecutionContext,
    pack: EvidencePack,
    *,
    config: PipelineConfig,
    usage: PracticeUsage | None = None,
    model_fingerprint: str | None = None,
) -> PracticeArtifact:
    """Seal validated private content; authorization/publication remain caller work."""
    from app.prompts.practice_prompt import PROMPT_HASH, PROMPT_VERSION

    pack = checked_evidence_pack(pack)
    require_execution_scope(actor, context, pack.resolved_scope)
    errors = validate_practice_payload(payload, spec, pack)
    if errors:
        raise GenerationValidationFailed(
            "Practice payload failed validation", details={"validation_errors": errors}
        )
    payload = PracticePayload.model_validate(
        payload.model_dump(mode="json")
        if isinstance(payload, PracticePayload)
        else payload
    )
    body = {
        **payload.model_dump(mode="json"),
        "run_id": context.run_id,
        "owner_id": actor.owner_id,
        "mode": context.mode,
        "space_id": spec.space_id,
        "scope_revision": spec.scope_revision,
        "scope_fingerprint": pack.resolved_scope.fingerprint,
        "question_versions": {
            q.id: canonical_question_version(q, pack) for q in payload.questions
        },
        "rubric_hashes": {
            q.id: stable_hash(q.rubric.model_dump(mode="json"))
            for q in payload.questions
        },
        "evidence_pack": pack.model_dump(mode="json"),
        "pipeline_config_hash": config.pipeline_config_hash,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": PROMPT_HASH,
        "model_fingerprint": model_fingerprint
        or stable_hash({"model": config.generator_model}),
        "usage": (usage or PracticeUsage()).model_dump(mode="json"),
    }
    return PracticeArtifact(artifact_id="practice-" + stable_hash(body), **body)
