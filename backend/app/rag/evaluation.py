"""Owner-worker evaluation dispatch. Scoring runtimes consume its JSON artifacts.

Gold parse identities are never silently mapped. Dataset import must explicitly
align canonical text, quotes and spans before running a different parse artifact.
"""

from __future__ import annotations

import asyncio
import time

from pydantic import ValidationError

from app.models.eval_contracts import QaSample
from app.qa.contracts import ChatHistoryTurn
from app.rag.budget import BudgetLedger
from app.rag.context import assemble_evidence
from app.rag.contracts import (
    ActorContext,
    ExecutionContext,
    PipelineConfig,
    ResolvedScope,
    RetrievalArtifact,
    RetrievalResult,
)
from app.rag.evaluation_artifacts import EvaluationArtifact
from app.rag.errors import (
    BudgetExceeded,
    InvalidScope,
    RagError,
    RetrievalUnavailable,
    ScopeRevoked,
    SourceUnavailable,
)
from app.rag.policy_harness import run_policy_case, validate_policy_harness
from app.rag.scope import normalize_spec, require_scope


def _validate_sources(sample, scope):
    sources = {source.doc_id: source for source in scope.documents}
    request = sample.get("scope", {}) or {}
    requested = request.get("doc_ids")
    if requested is None and request.get("documents") is not None:
        requested = [d["doc_id"] for d in request["documents"]]
    if requested is not None and set(requested) != set(sources):
        raise ScopeRevoked("Evaluation source scope does not match the sample")
    for reference in sample.get("source_refs", []):
        source = sources.get(reference.get("doc_id"))
        if source is None:
            raise ScopeRevoked("Evaluation sample refers to an unselected source")
        if "section_ids" in reference and set(reference["section_ids"] or []) != set(
            source.section_ids
        ):
            raise ScopeRevoked(
                "Evaluation source chapter restriction does not match the sample"
            )
        if reference.get("owner_id") is not None and str(reference["owner_id"]) != str(
            source.owner_id
        ):
            raise ScopeRevoked("Evaluation source belongs to another owner")
        if (
            reference.get("namespace") is not None
            and reference["namespace"] != source.namespace
        ):
            raise ScopeRevoked("Evaluation source belongs to another namespace")
        for key, aliases in {
            "document_version_id": ("document_version_id", "source_version_id"),
            "parse_artifact_id": ("parse_artifact_id",),
            "source_sha256": ("source_sha256",),
            "canonical_text_hash": ("canonical_text_hash",),
        }.items():
            provided = next(
                (
                    reference[alias]
                    for alias in aliases
                    if reference.get(alias) is not None
                ),
                None,
            )
            if provided is not None and str(provided) != str(getattr(source, key)):
                raise SourceUnavailable(
                    "Evaluation source version or parse mapping is unavailable",
                    details={"mapping_status": "mapping_failed", "field": key},
                )


async def run_eval_sample(
    sample,
    actor: ActorContext,
    context: ExecutionContext,
    engine,
    scope: ResolvedScope,
    config: PipelineConfig | None = None,
    *,
    practice_ports=None,
    grading_ports=None,
    grading_request_id: str | None = None,
) -> EvaluationArtifact:
    """Dispatch evaluation artifacts without any learning persistence port."""
    if hasattr(sample, "model_dump"):
        sample = sample.model_dump(mode="json")
    if context.mode != "evaluation" or "admin" not in actor.roles:
        raise ScopeRevoked(
            "System model admin permission and evaluation context are required"
        )
    if scope.namespace != "evaluation" and not scope.namespace.startswith(
        "evaluation:"
    ):
        raise ScopeRevoked(
            "Evaluation cannot run against a production storage namespace"
        )
    require_scope(actor, scope, namespace=context.storage_namespace)
    kind = sample.get("case_type")
    if kind not in (
        "retrieval",
        "quiz",
        "qa",
        "policy",
        "practice_generation",
        "answer_grading",
    ):
        raise InvalidScope("Unknown evaluation case type")
    _validate_sources(sample, scope)
    if kind == "policy":
        validate_policy_harness(sample, scope)
        return run_policy_case(sample, actor, context, scope)
    config = config or PipelineConfig()
    if kind in {"practice_generation", "answer_grading"}:
        from app.rag.practice_evaluation import run_practice_evaluation

        return await run_practice_evaluation(
            sample,
            actor,
            context,
            engine,
            scope,
            config,
            practice_ports=practice_ports,
            grading_ports=grading_ports,
            grading_request_id=grading_request_id,
        )
    if kind == "qa":
        if config.pipeline_version == "legacy-summary-b0":
            raise InvalidScope("The frozen legacy quiz baseline does not support QA")
        try:
            qa = QaSample.model_validate(sample)
        except ValidationError as exc:
            raise InvalidScope(
                "QA evaluation question, history or expectation is invalid"
            ) from exc
        if {ref.get("doc_id") for ref in qa.source_refs} != {
            source.doc_id for source in scope.documents
        }:
            raise ScopeRevoked("QA evaluation source scope differs from the sample")
        history = [
            ChatHistoryTurn(**turn.model_dump(), scope_fingerprint=scope.fingerprint)
            for turn in qa.history
        ]
        artifact = await engine.answer(
            qa.question, history, actor, context, scope, config
        )
        artifact.effective_config["sample_id"] = qa.sample_id
        return artifact
    if kind == "retrieval":
        query = sample.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise InvalidScope("Retrieval sample query is missing or too long")
        ledger = BudgetLedger(context.budget)
        started = time.monotonic()
        try:
            ledger.check()
            result = RetrievalResult.model_validate(
                await asyncio.wait_for(
                    engine.retrieve(query, scope, config, budget=ledger),
                    timeout=ledger.remaining_seconds,
                )
            )
            ledger.check()
        except Exception as exc:
            ledger.usage.stage_ms["retrieval"] = (time.monotonic() - started) * 1000
            details = {
                "usage": ledger.snapshot().model_dump(mode="json"),
                "sample_id": sample.get("sample_id"),
            }
            if isinstance(exc, RagError):
                exc.details.update(details)
                raise
            if isinstance(exc, asyncio.TimeoutError):
                raise BudgetExceeded(
                    "Retrieval evaluation deadline exceeded", details=details
                ) from exc
            raise RetrievalUnavailable(
                "Retrieval evaluation provider is unavailable", details=details
            ) from exc
        ledger.usage.stage_ms["retrieval"] = (time.monotonic() - started) * 1000
        pack = assemble_evidence(
            result.evidence,
            scope,
            "strict_docs" if scope.documents else "topic",
            config.context_token_budget,
            context.run_id,
        )
        return RetrievalArtifact(
            run_id=context.run_id,
            evidence=pack.evidence,
            usage=ledger.snapshot(),
            trace={
                "sample_id": sample.get("sample_id"),
                "candidates": [e.model_dump(mode="json") for e in result.candidates],
                "provided_evidence_ids": pack.provided_evidence_ids,
                "context_tokens": pack.context_tokens,
                "token_count_method": pack.token_count_method,
                "source_status": pack.status,
                "effective_config": result.effective_config,
                "pipeline_config": config.model_dump(mode="json"),
                "pipeline_config_hash": config.pipeline_config_hash,
                "warnings": result.warnings,
            },
        )
    difficulty = sample.get("difficulty", "mixed")
    normalized_difficulty = {
        "basic": "easy",
        "intermediate": "medium",
        "advanced": "hard",
    }.get(difficulty, difficulty)
    spec_payload = {
        "user_input": sample.get("user_input", ""),
        "question_count": sample.get("question_count", 5),
        "difficulty": normalized_difficulty,
        "source_policy": sample.get(
            "source_policy", "strict_docs" if scope.documents else "topic"
        ),
    }
    if scope.documents:
        spec_payload["scope"] = {
            "type": "selected_documents",
            "documents": [
                {
                    "doc_id": source.doc_id,
                    **(
                        {
                            "section_ids": source.section_ids,
                            "section_catalog_revision": source.parse_artifact_id,
                        }
                        if source.section_ids
                        else {}
                    ),
                }
                for source in scope.documents
            ],
        }
    spec = normalize_spec(spec_payload)
    if config.pipeline_version == "legacy-summary-b0":
        baseline = getattr(engine, "legacy_baseline", None)
        if baseline is None:
            raise SourceUnavailable(
                "The frozen legacy baseline adapter is not configured"
            )
        artifact = await baseline.run(spec, actor, context, scope, config=config)
    else:
        artifact = await engine.generate(spec, actor, context, scope, config)
    artifact.effective_config["sample_id"] = sample.get("sample_id")
    if difficulty != normalized_difficulty:
        artifact.effective_config["input_adaptations"] = [
            f"difficulty:{difficulty}->{normalized_difficulty}"
        ]
    return artifact
