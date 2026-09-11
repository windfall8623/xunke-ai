"""Source-bound pure grading. Persistence, leases and durable quotas stay outside."""

import asyncio
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, localcontext

from pydantic import ValidationError

from app.learning.contracts import AssessmentDraft
from app.practice.calibration import calibration_profile_applies
from app.practice.contracts import GradeArtifact, PracticeUsage
from app.practice.grade_contracts import GradeInputSnapshot, ShortAnswerProposal
from app.practice.providers import (
    PracticeResponseBudgetExceeded,
    PracticeResponseInvalid,
)
from app.practice.validation import canonical_question_version, checked_evidence_pack
from app.prompts.practice_grade_prompt import (
    PROMPT_HASH,
    PROMPT_VERSION,
    GRADER_VERSION,
    grade_messages,
    measure_grade_messages,
)
from app.rag.budget import BudgetLedger, count_tokens
from app.rag.contracts import (
    EvidencePack,
    GenerationResult,
    ResolvedScope,
    Usage,
    stable_hash,
)
from app.rag.errors import (
    BudgetExceeded,
    GenerationValidationFailed,
    ScopeRevoked,
    SourceUnavailable,
)
from app.rag.pipeline import reauthorize_scope
from app.rag.scope import require_execution_scope


@dataclass(frozen=True)
class GradingPorts:
    grade: Callable
    reauthorize: Callable
    verify_evidence: Callable
    measure_input_tokens: Callable


async def _await(value):
    return await value if inspect.isawaitable(value) else value


def grading_identity(snapshot):
    return {
        "model_fingerprint": snapshot.model_fingerprint,
        "prompt_hash": snapshot.prompt_hash,
        "grader_version": snapshot.grader_version,
        "rubric_family": snapshot.rubric_family,
        "rubric_version": snapshot.rubric_version,
        "question_type": "short_answer",
        "language": snapshot.language,
    }


def proposal_errors(proposal, snapshot):
    expected = {
        criterion.criterion_id: criterion
        for criterion in snapshot.question.rubric.criteria
    }
    ids = [item.criterion_id for item in proposal.criterion_results]
    errors = []
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        errors.append("criterion_ids_mismatch")
    for item in proposal.criterion_results:
        criterion = expected.get(item.criterion_id)
        if (
            criterion is None
            or len(item.evidence_refs) != len(set(item.evidence_refs))
            or not set(item.evidence_refs) <= set(criterion.evidence_refs)
        ):
            errors.append("criterion_evidence_mismatch")
        if any(
            not quote or quote not in snapshot.answer.text
            for quote in item.answer_quotes
        ):
            errors.append("unsupported_answer_quote")
        if item.credit in {"full", "half"} and not item.answer_quotes:
            errors.append("missing_answer_quote")
    return sorted(set(errors))


def proposal_assessment(proposal, snapshot, *, confirmed=False, source="model"):
    uncertain = (
        proposal.status == "needs_review"
        or bool(proposal.uncertainty_reasons)
        or any(item.credit == "uncertain" for item in proposal.criterion_results)
    )
    weights = {
        item.criterion_id: item.weight for item in snapshot.question.rubric.criteria
    }
    fractions = {"full": Decimal(1), "half": Decimal("0.5"), "none": Decimal(0)}
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        score = (
            None
            if uncertain
            else sum(
                (
                    weights[item.criterion_id] * fractions[item.credit]
                    for item in proposal.criterion_results
                ),
                Decimal(0),
            )
        )
    confirmed = confirmed and not uncertain
    return AssessmentDraft(
        status="needs_review" if uncertain else "graded",
        score=score,
        source=source,
        confirmation="confirmed" if confirmed else "provisional",
        grader_version=snapshot.grader_version,
        rubric_version=snapshot.rubric_version,
        rubric_hash=snapshot.rubric_hash,
        feedback=proposal.feedback,
        evidence_refs=sorted(
            {ref for item in proposal.criterion_results for ref in item.evidence_refs}
        ),
        criterion_results=[
            item.model_dump(mode="json") for item in proposal.criterion_results
        ],
        independent_eligible=confirmed and snapshot.help_usage == "none",
    )


async def grade_short_answer(snapshot, actor, context, scope, ports, *, profile=None):
    require_execution_scope(actor, context, scope)
    snapshot = GradeInputSnapshot.model_validate(snapshot.model_dump(mode="json"))
    scope = ResolvedScope.model_validate(scope.model_dump(mode="json"))
    if (
        snapshot.owner_id,
        snapshot.mode,
        snapshot.run_id,
        snapshot.scope_fingerprint,
    ) != (actor.owner_id, context.mode, context.run_id, scope.fingerprint):
        raise ScopeRevoked("Grading input is outside the execution scope")
    if (snapshot.prompt_hash, snapshot.prompt_version, snapshot.grader_version) != (
        PROMPT_HASH,
        PROMPT_VERSION,
        GRADER_VERSION,
    ):
        raise GenerationValidationFailed("Grading protocol identity changed")
    pack = EvidencePack(
        trace_id=context.run_id,
        policy="strict_docs",
        resolved_scope=scope,
        evidence=snapshot.evidence,
        status="ready",
        provided_evidence_ids=[item.evidence_id for item in snapshot.evidence],
    )
    checked_evidence_pack(pack)
    if (
        snapshot.question_version != canonical_question_version(snapshot.question, pack)
        or snapshot.rubric_hash
        != stable_hash(snapshot.question.rubric.model_dump(mode="json"))
        or snapshot.rubric_version != snapshot.question.rubric.version
        or snapshot.response_hash
        != stable_hash(snapshot.answer.model_dump(mode="json"))
    ):
        raise GenerationValidationFailed(
            "Frozen grading inputs failed identity validation"
        )
    if not set(snapshot.question.citation_refs) <= set(pack.provided_evidence_ids):
        raise SourceUnavailable("Grading question cites missing evidence")
    if not all(
        callable(getattr(ports, name)) for name in GradingPorts.__dataclass_fields__
    ):
        raise GenerationValidationFailed("Explicit grading ports are required")
    frozen = stable_hash(snapshot.model_dump(mode="json"))
    fingerprint = scope.fingerprint
    limits = context.budget.model_copy(
        update={"max_llm_calls": min(2, context.budget.max_llm_calls)}
    )
    ledger = BudgetLedger(limits)
    observations = []
    adapter = getattr(ports.grade, "__self__", ports.grade)
    if (
        getattr(adapter, "model_fingerprint", snapshot.model_fingerprint)
        != snapshot.model_fingerprint
    ):
        raise GenerationValidationFailed(
            "Frozen grader model does not match the provider"
        )

    async def bounded(value):
        ledger.check()
        return await asyncio.wait_for(_await(value), timeout=ledger.remaining_seconds)

    async def authorize():
        if (
            scope.fingerprint != fingerprint
            or stable_hash(snapshot.model_dump(mode="json")) != frozen
        ):
            raise SourceUnavailable("Grading inputs changed during execution")
        await bounded(reauthorize_scope(ports.reauthorize, scope))
        for evidence in snapshot.evidence:
            if await bounded(ports.verify_evidence(evidence, scope)) is False:
                raise SourceUnavailable("Grading evidence verification failed")
        if (
            scope.fingerprint != fingerprint
            or stable_hash(snapshot.model_dump(mode="json")) != frozen
        ):
            raise SourceUnavailable("Grading evidence changed during verification")

    def record(usage, inputs, output_limit):
        observations.append(usage)
        ledger.record_output(usage.output_tokens)
        if usage.input_tokens > inputs or usage.output_tokens > output_limit:
            raise BudgetExceeded("Grading response exceeded admitted token bounds")

    await authorize()
    proposal = None
    errors = None
    for attempt in (1, 2):
        await authorize()
        messages = grade_messages(snapshot, attempt=attempt, feedback=errors)
        measured = ports.measure_input_tokens("grade", messages)
        if type(measured) is not int or measured < 0:
            raise BudgetExceeded("Invalid grading token measurement")
        inputs = max(measured, measure_grade_messages("grade", messages))
        output_limit = getattr(adapter, "output_token_limit", 2048)
        if (
            inputs + output_limit > getattr(adapter, "model_context_window", 32768)
            or ledger.usage.output_tokens + output_limit > limits.max_output_tokens
        ):
            raise BudgetExceeded(
                "Complete grading messages exceed remaining token bounds"
            )
        estimate = getattr(adapter, "estimate_cost", None)
        ledger.reserve(
            "llm",
            input_tokens=inputs,
            estimated_cost_usd=estimate("grade", inputs, output_limit)
            if callable(estimate)
            else None,
        )
        try:
            raw = await bounded(ports.grade(snapshot, attempt=attempt, feedback=errors))
        except PracticeResponseInvalid as exc:
            record(exc.usage, inputs, output_limit)
            errors = ["invalid_grading_proposal"]
            continue
        except PracticeResponseBudgetExceeded as exc:
            record(exc.usage, inputs, output_limit)
            raise
        if isinstance(raw, GenerationResult):
            record(raw.usage, inputs, output_limit)
            raw = raw.payload
        else:
            raw = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
            record(
                Usage(
                    input_tokens=inputs,
                    output_tokens=count_tokens(json.dumps(raw, ensure_ascii=False)),
                    token_count_method="synthetic-payload-utf8-upper-bound-v1",
                ),
                inputs,
                output_limit,
            )
        await authorize()
        try:
            candidate = ShortAnswerProposal.model_validate(raw)
            errors = proposal_errors(candidate, snapshot)
        except (ValidationError, ValueError, TypeError):
            errors = ["invalid_grading_proposal"]
        if not errors:
            proposal = candidate
            break
    await authorize()
    applicable = calibration_profile_applies(profile, grading_identity(snapshot))
    if snapshot.calibration_profile_hash is not None and (
        not applicable or snapshot.calibration_profile_hash != profile["profile_hash"]
    ):
        applicable = False
    if proposal is None:
        assessment = AssessmentDraft(
            status="needs_review",
            source="model",
            confirmation="provisional",
            grader_version=snapshot.grader_version,
            rubric_version=snapshot.rubric_version,
            rubric_hash=snapshot.rubric_hash,
            feedback="自动评分未能可靠核对全部要点，需要人工复核。",
        )
    else:
        assessment = proposal_assessment(proposal, snapshot, confirmed=applicable)
    data = ledger.snapshot().model_dump(mode="json")
    data.update(
        input_tokens=sum(item.input_tokens for item in observations),
        output_tokens=sum(item.output_tokens for item in observations),
        token_count_method="provider-reported"
        if observations
        and all(item.token_count_method == "provider-reported" for item in observations)
        else "utf8-upper-bound-v1",
    )
    usage = PracticeUsage.model_validate(data)
    return GradeArtifact(
        artifact_id=stable_hash(
            {"snapshot": frozen, "assessment": assessment.model_dump(mode="json")}
        ),
        run_id=context.run_id,
        owner_id=actor.owner_id,
        mode=context.mode,
        attempt_id=snapshot.attempt_id,
        grading_request_id=snapshot.grading_request_id,
        question_version=snapshot.question_version,
        rubric_version=snapshot.rubric_version,
        rubric_hash=snapshot.rubric_hash,
        response_hash=snapshot.response_hash,
        scope_fingerprint=fingerprint,
        grader_version=snapshot.grader_version,
        model_fingerprint=snapshot.model_fingerprint,
        prompt_version=snapshot.prompt_version,
        prompt_hash=snapshot.prompt_hash,
        calibration_profile_hash=profile["profile_hash"] if applicable else None,
        assessment=assessment,
        usage=usage,
    )
