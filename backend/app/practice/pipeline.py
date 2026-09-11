"""Pure fixed-scope practice generation; durable jobs and publication are external."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.practice.contracts import (
    PracticeArtifact,
    PracticePayload,
    PracticeSpec,
    PracticeUsage,
)
from app.practice.providers import (
    PracticeResponseBudgetExceeded,
    PracticeResponseInvalid,
)
from app.practice.validation import (
    checked_evidence_pack,
    seal_practice_artifact,
    validate_practice_payload,
    validate_practice_semantics,
)
from app.prompts.practice_prompt import measure_practice_messages, practice_messages
from app.rag.budget import BudgetLedger, count_tokens
from app.rag.context import assemble_evidence
from app.rag.contracts import (
    ActorContext,
    ExecutionContext,
    GenerationResult,
    PipelineConfig,
    ResolvedScope,
    RetrievalResult,
    Usage,
    stable_hash,
)
from app.rag.errors import (
    BudgetExceeded,
    GenerationValidationFailed,
    InsufficientEvidence,
    RagError,
    RetrievalUnavailable,
    ScopeRevoked,
    SourceUnavailable,
)
from app.rag.pipeline import reauthorize_scope
from app.rag.scope import require_execution_scope


@dataclass(frozen=True)
class PracticePorts:
    retrieve: Callable
    generate: Callable
    validate_semantics: Callable
    reauthorize: Callable
    verify_evidence: Callable
    measure_input_tokens: Callable


async def await_if_needed(value):
    return await value if inspect.isawaitable(value) else value


def _adapter(callback):
    return getattr(callback, "__self__", callback)


async def generate_practice_artifact(
    spec: PracticeSpec,
    actor: ActorContext,
    context: ExecutionContext,
    scope: ResolvedScope,
    ports: PracticePorts,
    *,
    config: PipelineConfig,
) -> PracticeArtifact:
    """Retrieve once; at most one paid rerank, two generations and two checks.

    This execution ledger is deliberately not a durable billing ledger. The owner
    worker must separately enforce logical-request quotas and fenced publication.
    """
    require_execution_scope(actor, context, scope)
    try:
        scope = ResolvedScope.model_validate(scope.model_dump(mode="json"))
    except ValidationError as exc:
        raise ScopeRevoked("Practice source scope is invalid") from exc
    if not scope.documents:
        raise InsufficientEvidence("Practice requires a complete fixed document scope")
    spec = PracticeSpec.model_validate(spec.model_dump(mode="json"))
    config = PipelineConfig.model_validate(config.model_dump(mode="json"))
    if not config.require_semantic_validation:
        raise GenerationValidationFailed(
            "Practice always requires semantic support validation"
        )
    if config.reranker.provider == "llm" and config.max_retrieval_rounds != 1:
        raise BudgetExceeded("Practice permits only one paid LLM reranking round")
    if not all(
        callable(getattr(ports, name)) for name in PracticePorts.__dataclass_fields__
    ):
        raise GenerationValidationFailed(
            "Practice requires all explicit pipeline ports"
        )
    limits = context.budget.model_copy(
        update={
            "max_llm_calls": min(context.budget.max_llm_calls, config.max_llm_calls, 5),
            "max_reranker_calls": min(context.budget.max_reranker_calls, 1),
        }
    )
    ledger = BudgetLedger(limits)
    scope_fingerprint = scope.fingerprint
    spec_hash = stable_hash(spec.model_dump(mode="json"))
    pack = None
    pack_hash = None
    methods = []
    observations = []

    def unchanged():
        if scope.fingerprint != scope_fingerprint or (
            pack is not None and stable_hash(pack.model_dump(mode="json")) != pack_hash
        ):
            raise SourceUnavailable(
                "Practice evidence changed during generation",
                details={"validation_errors": ["source_changed"]},
            )
        if stable_hash(spec.model_dump(mode="json")) != spec_hash:
            raise GenerationValidationFailed(
                "Practice request changed during generation"
            )

    async def bounded(operation, stage):
        ledger.check()
        try:
            value = await asyncio.wait_for(
                await_if_needed(operation()), timeout=ledger.remaining_seconds
            )
        except TimeoutError as exc:
            raise BudgetExceeded(
                f"Practice {stage} exceeded the execution deadline"
            ) from exc
        # A completed model response must reach record_output, which checks the
        # deadline after retaining its usage. Every next I/O and sealing check it.
        return value

    async def auth():
        unchanged()
        await bounded(
            lambda: reauthorize_scope(ports.reauthorize, scope), "authorization"
        )
        unchanged()

    def require_calls(count):
        if ledger.usage.llm_calls + count > limits.max_llm_calls:
            raise BudgetExceeded(
                "Remaining calls cannot cover required practice stages"
            )

    async def verify():
        unchanged()
        checked_evidence_pack(pack)
        for item in pack.evidence:
            valid = await bounded(
                lambda: ports.verify_evidence(item, scope), "evidence verification"
            )
            if valid is False:
                raise SourceUnavailable("Practice evidence could not be verified")
            unchanged()

    await auth()
    if config.reranker.provider == "llm":
        require_calls(3)
    try:
        retrieved = await bounded(
            lambda: ports.retrieve(
                "；".join(spec.objectives), scope, config, budget=ledger
            ),
            "retrieval",
        )
        retrieved = RetrievalResult.model_validate(retrieved)
    except RagError:
        raise
    except Exception as exc:
        raise RetrievalUnavailable("Practice retrieval is unavailable") from exc
    await auth()
    pack = assemble_evidence(
        retrieved.evidence,
        scope,
        "strict_docs",
        config.context_token_budget,
        context.run_id,
    )
    if not pack.evidence:
        raise InsufficientEvidence("No complete evidence for this practice scope")
    identities = {}
    for evidence in retrieved.evidence:
        raw = evidence.model_dump(mode="json", exclude={"score", "retrieval_scores"})
        identity = evidence.evidence_id
        if identity in identities and identities[identity] != raw:
            raise GenerationValidationFailed(
                "Conflicting retrieved evidence identities"
            )
        identities[identity] = raw
    pack_hash = stable_hash(pack.model_dump(mode="json"))
    await verify()

    def record(usage, inputs, output_limit):
        usage = Usage.model_validate(usage.model_dump(mode="json"))
        ledger.record_output(usage.output_tokens)
        methods.append(usage.token_count_method)
        if usage.input_tokens > inputs or usage.output_tokens > output_limit:
            raise BudgetExceeded("Practice provider exceeded its admitted token limits")
        observations.append((inputs, usage.input_tokens))

    async def invoke(
        stage, callback, operation, *, payload=None, attempt=1, feedback=None
    ):
        await auth()
        messages = practice_messages(
            stage, spec, pack, payload=payload, attempt=attempt, feedback=feedback
        )
        measured = ports.measure_input_tokens(stage, messages)
        if type(measured) is not int or measured < 0:
            raise BudgetExceeded("Practice input measurement is invalid")
        inputs = max(measured, measure_practice_messages(stage, messages))
        adapter = _adapter(callback)
        output_limit = getattr(
            adapter, "output_token_limit", config.output_token_reserve
        )
        if output_limit != config.output_token_reserve:
            raise BudgetExceeded(
                "Practice model max_tokens must match the admitted output reserve"
            )
        model_window = min(
            config.model_context_window,
            getattr(adapter, "model_context_window", config.model_context_window),
        )
        if inputs + output_limit > model_window:
            raise BudgetExceeded(
                "Complete practice prompt and output exceed the context window"
            )
        if ledger.usage.output_tokens + output_limit > limits.max_output_tokens:
            raise BudgetExceeded(
                "Remaining output budget cannot cover the practice model limit"
            )
        estimate = getattr(adapter, "estimate_cost", None)
        ledger.reserve(
            "llm",
            input_tokens=inputs,
            estimated_cost_usd=estimate(stage, inputs, output_limit)
            if callable(estimate)
            else None,
        )
        try:
            result = await bounded(operation, stage)
        except (PracticeResponseInvalid, PracticeResponseBudgetExceeded) as exc:
            record(exc.usage, inputs, output_limit)
            await auth()
            raise
        if isinstance(result, GenerationResult):
            record(result.usage, inputs, output_limit)
            result = result.payload
        else:
            # Bare injected ports are synthetic/legacy adapters, not provider billing.
            if hasattr(result, "model_dump"):
                result = result.model_dump(mode="json")
            serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            record(
                Usage(
                    input_tokens=inputs,
                    output_tokens=count_tokens(serialized),
                    token_count_method="synthetic-payload-utf8-upper-bound-v1",
                ),
                inputs,
                output_limit,
            )
        await auth()
        return result

    feedback = None
    for attempt in range(1, config.max_generation_attempts + 1):
        require_calls(2)
        try:
            raw = await invoke(
                "generate",
                ports.generate,
                lambda: ports.generate(spec, pack, attempt=attempt, feedback=feedback),
                attempt=attempt,
                feedback=feedback,
            )
        except PracticeResponseInvalid:
            feedback = ["invalid_practice_payload"]
            continue
        feedback = validate_practice_payload(raw, spec, pack)
        if feedback:
            continue
        payload = PracticePayload.model_validate(raw)
        payload_hash = stable_hash(payload.model_dump(mode="json"))
        try:
            semantic = await invoke(
                "semantic",
                ports.validate_semantics,
                lambda: ports.validate_semantics(payload, pack, spec),
                payload=payload,
            )
        except PracticeResponseInvalid:
            feedback = ["generation_semantics_failed"]
            continue
        if stable_hash(payload.model_dump(mode="json")) != payload_hash:
            raise GenerationValidationFailed(
                "Practice payload changed during semantic validation"
            )
        feedback = validate_practice_semantics(semantic, payload)
        if feedback:
            continue
        await auth()
        await verify()
        ledger.check()
        usage = PracticeUsage(**ledger.snapshot().model_dump(mode="json"))
        usage.input_tokens -= sum(
            admitted - actual for admitted, actual in observations
        )
        if usage.reranker_calls or usage.embedding_calls:
            methods.append("retrieval-provider-or-utf8-upper-bound-v1")
        if methods:
            usage.token_count_method = "+".join(sorted(set(methods)))
        return seal_practice_artifact(
            payload,
            spec,
            actor,
            context,
            pack,
            config=config,
            usage=usage,
            model_fingerprint=getattr(
                _adapter(ports.generate), "model_fingerprint", None
            ),
        )
    raise GenerationValidationFailed(
        "Practice failed validation after the bounded attempts",
        details={"validation_errors": feedback or ["invalid_practice_payload"]},
    )
