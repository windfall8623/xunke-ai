"""Evaluation-only adapters for the production pure practice and grading paths.

No learning entity is looked up or persisted here. The caller owns source
authorization, durable quotas and publication; only explicit ports can do I/O.
"""

from __future__ import annotations

import inspect
import time

from pydantic import ValidationError

from app.models.eval_contracts import AnswerGradingSample, PracticeGenerationSample
from app.practice.contracts import GradeArtifact, PracticeSpec, PracticeUsage
from app.practice.grade_contracts import GradeInputSnapshot
from app.practice.grading import grade_rules
from app.practice.identity import canonical_question_version
from app.practice.pipeline import PracticePorts, generate_practice_artifact
from app.practice.short_answer import GradingPorts, grade_short_answer
from app.practice.validation import checked_evidence_pack
from app.prompts.practice_grade_prompt import (
    GRADER_VERSION,
    PROMPT_HASH,
    PROMPT_VERSION,
)
from app.rag.contracts import (
    DocumentEvidence,
    EvidencePack,
    ExecutionContext,
    ResolvedScope,
    stable_hash,
)
from app.rag.errors import (
    GenerationValidationFailed,
    InvalidScope,
    ScopeRevoked,
    SourceUnavailable,
)
from app.rag.evaluation_artifacts import (
    AnswerGradingEvalArtifact,
    LearningEvaluationUsage,
    PracticeGenerationEvalArtifact,
)
from app.rag.pipeline import reauthorize_scope
from app.rag.scope import evidence_in_scope


def _identity(kind: str, context: ExecutionContext, sample_id: str, part="") -> str:
    return "eval_" + kind + "_" + stable_hash([context.run_id, sample_id, part])[:40]


def evaluation_practice_spec(
    raw_spec: PracticeSpec | dict, context: ExecutionContext, sample_id: str
) -> PracticeSpec:
    """Keep the frozen request, replacing study IDs with evaluation-only IDs."""
    if context.mode != "evaluation":
        raise ScopeRevoked("Synthetic practice identities require evaluation mode")
    spec = PracticeSpec.model_validate(
        raw_spec.model_dump(mode="json")
        if isinstance(raw_spec, PracticeSpec)
        else raw_spec
    )
    return spec.model_copy(
        update={
            "space_id": _identity("space", context, sample_id),
            "scope_revision": 1,
            "concept_ids": [
                _identity("concept", context, sample_id, index)
                for index in range(len(spec.concept_ids))
            ],
        }
    )


def _fixed_sources(sample, scope):
    # Shared with the original evaluation cases; no aliasing of parse identities.
    from app.rag.evaluation import _validate_sources

    _validate_sources(sample.model_dump(mode="json"), scope)
    if {ref.get("doc_id") for ref in sample.source_refs} != {
        source.doc_id for source in scope.documents
    }:
        raise ScopeRevoked("Practice evaluation source scope differs from the sample")
    if not scope.documents or not (
        scope.namespace == "evaluation" or scope.namespace.startswith("evaluation:")
    ):
        raise ScopeRevoked("Practice evaluation requires isolated document sources")


def grading_evidence_pack(
    sample: AnswerGradingSample, scope: ResolvedScope, store
) -> EvidencePack:
    """Read cited immutable build nodes after the caller authorizes the scope.

    This helper is also used by scoring and human review. Imported excerpts,
    paths, artifact packs, reference grades and claimed span aliases are ignored.
    All three input checksums are verified against this source-bound pack.
    """
    sample = AnswerGradingSample.model_validate(sample.model_dump(mode="json"))
    scope = ResolvedScope.model_validate(scope.model_dump(mode="json"))
    _fixed_sources(sample, scope)
    requested = set(sample.question.citation_refs)
    found = {}
    for source in scope.documents:
        for node in store.read_build(source).nodes:
            item = node.evidence
            if item.evidence_id not in requested:
                continue
            if (
                not isinstance(item, DocumentEvidence)
                or not evidence_in_scope(item, scope)
                or item.evidence_id in found
            ):
                raise SourceUnavailable(
                    "Grading evidence is outside scope or ambiguous"
                )
            found[item.evidence_id] = item.model_copy(deep=True)
    if set(found) != requested:
        raise SourceUnavailable("Grading question cites unavailable source evidence")
    pack = checked_evidence_pack(
        EvidencePack(
            trace_id="eval_evidence_"
            + stable_hash([scope.fingerprint, sample.sample_id])[:40],
            policy="strict_docs",
            resolved_scope=scope,
            evidence=[found[ref] for ref in sample.question.citation_refs],
            provided_evidence_ids=list(sample.question.citation_refs),
            status="ready",
        )
    )
    if (
        sample.question_version != canonical_question_version(sample.question, pack)
        or sample.rubric_hash
        != stable_hash(sample.question.rubric.model_dump(mode="json"))
        or sample.response_hash != stable_hash(sample.answer.model_dump(mode="json"))
        or any(
            not any(quote in item.excerpt for item in pack.evidence)
            for quote in sample.question.support_quotes
        )
    ):
        raise GenerationValidationFailed(
            "Frozen grading inputs failed source identity validation"
        )
    return pack


def _trace_usage(private_usage, stage, started):
    usage = LearningEvaluationUsage.model_validate(
        private_usage.model_dump(mode="json")
    )
    usage.stage_ms[stage] = (time.perf_counter() - started) * 1000
    return usage


async def run_practice_evaluation(
    sample,
    actor,
    context,
    engine,
    scope,
    config,
    *,
    practice_ports: PracticePorts | None = None,
    grading_ports: GradingPorts | None = None,
    grading_request_id: str | None = None,
):
    """Supply only validated task inputs to pure functions, never reference labels."""
    kind = sample.get("case_type")
    model = (
        PracticeGenerationSample
        if kind == "practice_generation"
        else AnswerGradingSample
    )
    try:
        sample = model.model_validate(sample)
    except ValidationError as exc:
        raise InvalidScope("Practice evaluation sample is invalid") from exc
    _fixed_sources(sample, scope)
    if config.pipeline_version == "legacy-summary-b0":
        raise InvalidScope("The frozen legacy quiz baseline does not support practice")
    started = time.perf_counter()
    if kind == "practice_generation":
        if practice_ports is None:
            raise GenerationValidationFailed(
                "Evaluation practice provider is unavailable"
            )
        practice = await generate_practice_artifact(
            evaluation_practice_spec(sample.spec, context, sample.sample_id),
            actor,
            context,
            scope,
            practice_ports,
            config=config,
        )
        return PracticeGenerationEvalArtifact(
            run_id=context.run_id,
            sample_id=sample.sample_id,
            status="completed",
            practice=practice,
            usage=_trace_usage(practice.usage, "generation", started),
        )

    reauthorize = grading_ports.reauthorize if grading_ports else engine.reauthorize
    verify = grading_ports.verify_evidence if grading_ports else engine.verify_evidence
    await reauthorize_scope(reauthorize, scope)
    pack = grading_evidence_pack(sample, scope, engine.store)
    for item in pack.evidence:
        checked = verify(item, scope)
        if (await checked if inspect.isawaitable(checked) else checked) is False:
            raise SourceUnavailable("Grading evidence verification failed")
    logical_id = grading_request_id or _identity("grade", context, sample.sample_id)
    if not isinstance(logical_id, str) or not 1 <= len(logical_id) <= 64:
        raise InvalidScope("Evaluation grading identity is invalid")
    attempt_id = _identity("attempt", context, sample.sample_id, logical_id)
    if sample.question_type == "short_answer":
        if grading_ports is None:
            raise GenerationValidationFailed(
                "Evaluation grading provider is unavailable"
            )
        adapter = getattr(grading_ports.grade, "__self__", grading_ports.grade)
        fingerprint = getattr(adapter, "model_fingerprint", None)
        if not isinstance(fingerprint, str) or not fingerprint:
            raise GenerationValidationFailed(
                "Evaluation grader identity is unavailable"
            )
        question = sample.question.model_copy(
            update={
                "concept_ids": [
                    _identity("concept", context, sample.sample_id, index)
                    for index in range(len(sample.question.concept_ids))
                ],
            }
        )
        snapshot = GradeInputSnapshot(
            owner_id=actor.owner_id,
            mode="evaluation",
            run_id=context.run_id,
            attempt_id=attempt_id,
            grading_request_id=logical_id,
            space_id=_identity("space", context, sample.sample_id),
            scope_revision=1,
            scope_fingerprint=scope.fingerprint,
            question=question,
            answer=sample.answer,
            question_version=sample.question_version,
            rubric_version=question.rubric.version,
            rubric_hash=sample.rubric_hash,
            response_hash=sample.response_hash,
            evidence=pack.evidence,
            help_usage="unknown",
            model_fingerprint=fingerprint,
            prompt_hash=PROMPT_HASH,
            prompt_version=PROMPT_VERSION,
            grader_version=GRADER_VERSION,
        )
        grade = await grade_short_answer(
            snapshot, actor, context, scope, grading_ports, profile=None
        )
    else:
        try:
            assessment = grade_rules(sample.question, sample.answer)
        except ValueError as exc:
            raise GenerationValidationFailed("Rule grading input is invalid") from exc
        grade = GradeArtifact(
            artifact_id=stable_hash(
                [
                    logical_id,
                    sample.question_version,
                    sample.response_hash,
                    assessment.model_dump(mode="json"),
                ]
            ),
            run_id=context.run_id,
            owner_id=actor.owner_id,
            mode="evaluation",
            attempt_id=attempt_id,
            grading_request_id=logical_id,
            question_version=sample.question_version,
            rubric_version=assessment.rubric_version,
            rubric_hash=sample.rubric_hash,
            response_hash=sample.response_hash,
            scope_fingerprint=scope.fingerprint,
            grader_version=assessment.grader_version,
            model_fingerprint="deterministic-rules-v1",
            prompt_version="rules-no-prompt-v1",
            prompt_hash=stable_hash({"grader": "rules-v1", "prompt": None}),
            assessment=assessment,
            usage=PracticeUsage(),
        )
    await reauthorize_scope(reauthorize, scope)
    return AnswerGradingEvalArtifact(
        run_id=context.run_id,
        sample_id=sample.sample_id,
        status="completed",
        grade=grade,
        usage=_trace_usage(grade.usage, "grading", started),
    )
