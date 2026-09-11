"""Strict document QA, with one bounded attempt per stage and no learning writes."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.errors import AppError
from app.qa.contracts import ChatAnswerArtifact, ChatAnswerPayload, select_history
from app.qa.generator import NOTICE_TEXTS, PROMPT_HASH, PROMPT_VERSION
from app.rag.budget import BudgetLedger
from app.rag.context import assemble_evidence
from app.rag.contracts import (
    GenerationResult,
    PipelineConfig,
    RetrievalResult,
    ValidationResult,
    stable_hash,
)
from app.rag.errors import (
    BudgetExceeded,
    GenerationValidationFailed,
    InvalidScope,
    RagError,
    RetrievalUnavailable,
)
from app.rag.pipeline import reauthorize_scope
from app.rag.scope import require_execution_scope


@dataclass(frozen=True)
class QaPipelinePorts:
    retrieve: Callable
    reauthorize: Callable
    verify_evidence: Callable
    generator: object


async def _await_if_needed(value):
    return await value if inspect.isawaitable(value) else value


def _notice(status):
    return ChatAnswerPayload(
        answer_status=status,
        blocks=[
            {
                "block_id": "notice",
                "kind": "notice",
                "text": NOTICE_TEXTS[status],
                "citation_refs": [],
            }
        ],
    )


def _validate_payload(raw, pack):
    try:
        payload = ChatAnswerPayload.model_validate(raw)
    except ValidationError as exc:
        raise GenerationValidationFailed("QA answer structure is invalid") from exc
    allowed = set(pack.provided_evidence_ids)
    facts, notices = [], []
    for block in payload.blocks:
        if block.kind == "notice":
            notices.append(block)
            if (
                block.text != NOTICE_TEXTS.get(payload.answer_status)
                or block.citation_refs
            ):
                raise GenerationValidationFailed(
                    "QA notices must use the fixed status text"
                )
        else:
            facts.append(block)
            if not set(block.citation_refs) <= allowed:
                raise GenerationValidationFailed(
                    "QA answer references evidence outside this retrieval"
                )
    if len(notices) > 1:
        raise GenerationValidationFailed("QA answer contains duplicate status notices")
    if payload.answer_status == "conflicting_sources":
        sources = [set(block.citation_refs) for block in facts]
        if not any(
            left - right and right - left for left in sources for right in sources
        ):
            raise GenerationValidationFailed(
                "Conflicting statements require separately cited sources"
            )
    return payload


async def generate_answer_artifact(
    question,
    history,
    actor,
    context,
    scope,
    ports: QaPipelinePorts,
    *,
    config=None,
    progress=None,
) -> ChatAnswerArtifact:
    """Rewrite at most once, retrieve once, generate once, validate once.

    The durable meter remains authoritative across worker attempts. This ledger
    limits the current execution; no exception path retries or synthesizes an answer.
    The caller still owns lease fencing and final transactional publication.
    """
    require_execution_scope(actor, context, scope)
    if not scope.documents:
        raise InvalidScope("QA requires an explicit document scope")
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise InvalidScope("QA question must contain between one and 2000 characters")
    question = question.strip()
    config = PipelineConfig.model_validate(config or {})
    config = config.model_copy(
        update={
            "pipeline_version": "qa-v1",
            "prompt_version": PROMPT_VERSION,
            "max_subqueries": 1,
            "max_retrieval_rounds": 1,
            "max_generation_attempts": 1,
            "require_semantic_validation": True,
            "reranker": config.reranker.model_copy(
                update={"allow_rrf_fallback": False}
            ),
        }
    )
    limits = context.budget.model_copy(
        update={
            "max_llm_calls": min(context.budget.max_llm_calls, config.max_llm_calls, 5),
            "max_reranker_calls": min(context.budget.max_reranker_calls, 1),
        }
    )
    ledger = BudgetLedger(limits)
    trace, observations = [], []
    started = time.monotonic()

    async def bounded(operation, message):
        ledger.check()
        try:
            return await asyncio.wait_for(operation(), timeout=ledger.remaining_seconds)
        except asyncio.TimeoutError as exc:
            raise BudgetExceeded(message) from exc

    async def auth():
        await bounded(
            lambda: reauthorize_scope(ports.reauthorize, scope),
            "QA authorization exceeded the execution deadline",
        )

    async def stage(name):
        if progress is not None:
            await bounded(
                lambda: _await_if_needed(progress(name)),
                "QA progress update exceeded the execution deadline",
            )
        await auth()

    def traced(name, **values):
        trace.append({"stage": name, **values})

    def require_calls(count):
        if ledger.usage.llm_calls + count > limits.max_llm_calls:
            raise BudgetExceeded("Remaining calls cannot cover the required QA stages")

    await auth()
    generator = ports.generator
    if generator is None or not all(
        callable(getattr(generator, name, None))
        for name in (
            "rewrite",
            "generate",
            "validate_semantics",
            "measure_input_tokens",
            "estimate_cost",
        )
    ):
        raise GenerationValidationFailed("QA model provider is not configured")
    try:
        selected_history = select_history(history or [], scope.fingerprint)
    except (ValidationError, TypeError, ValueError) as exc:
        raise InvalidScope("QA history contains an invalid complete turn") from exc
    output_reserve = max(config.output_token_reserve, generator.output_token_limit)
    model_window = min(config.model_context_window, generator.model_context_window)
    config = config.model_copy(
        update={
            "output_token_reserve": output_reserve,
            "model_context_window": model_window,
        }
    )

    async def invoke(name, operation, pack=None, **prompt):
        require_calls(1)
        inputs = generator.measure_input_tokens(name, question, pack, **prompt)
        if inputs + output_reserve > model_window:
            raise BudgetExceeded(
                "Complete QA prompt and output exceed the model context window"
            )
        if (
            ledger.usage.output_tokens + generator.output_token_limit
            > limits.max_output_tokens
        ):
            raise BudgetExceeded(
                "Remaining output token budget cannot cover the QA provider limit"
            )
        ledger.reserve(
            "llm",
            input_tokens=inputs,
            estimated_cost_usd=generator.estimate_cost(name, inputs, output_reserve),
        )
        call_started = time.monotonic()
        try:
            result = await bounded(
                operation, "QA model call exceeded the execution deadline"
            )
            if name == "semantic":
                result = ValidationResult.model_validate(result)
                usage = result.provider_usage
            else:
                result = GenerationResult.model_validate(result)
                usage = result.usage
            if usage is None:
                raise GenerationValidationFailed("QA provider omitted usage accounting")
            if usage.input_tokens > inputs:
                raise BudgetExceeded(
                    "Reported QA input exceeds its admitted token budget"
                )
            ledger.record_output(usage.output_tokens)
            observations.append((inputs, usage))
        except (RagError, AppError):
            raise
        except Exception as exc:
            raise GenerationValidationFailed(
                "QA model provider is unavailable"
            ) from exc
        finally:
            ledger.usage.stage_ms[name] = (time.monotonic() - call_started) * 1000
        await auth()
        return result

    retrieval_query = question
    retrieval_config = {}
    pack = assemble_evidence(
        [], scope, "strict_docs", config.context_token_budget, context.run_id
    )
    payload = None
    if selected_history:
        await stage("rewriting")
        rewritten = await invoke(
            "rewrite",
            lambda: generator.rewrite(question, selected_history),
            history=selected_history,
        )
        retrieval_query = rewritten.payload["retrieval_query"]
        traced(
            "rewrite",
            history_turn_count=len(selected_history),
            needs_clarification=rewritten.payload["needs_clarification"],
        )
        if rewritten.payload["needs_clarification"]:
            payload = _notice("needs_clarification")

    if payload is None:
        await stage("retrieving")
        if config.reranker.provider == "llm":
            # Retain room for the answer and mandatory support check before paying for ranking.
            require_calls(3)
        retrieval_started = time.monotonic()
        try:
            retrieved = RetrievalResult.model_validate(
                await bounded(
                    lambda: ports.retrieve(
                        retrieval_query, scope, config, budget=ledger
                    ),
                    "QA retrieval exceeded the execution deadline",
                )
            )
        except (RagError, AppError):
            raise
        except Exception as exc:
            raise RetrievalUnavailable(
                "QA retrieval infrastructure is unavailable"
            ) from exc
        finally:
            ledger.usage.stage_ms["retrieval"] = (
                time.monotonic() - retrieval_started
            ) * 1000
        await auth()
        retrieval_config = retrieved.effective_config
        pack = assemble_evidence(
            retrieved.evidence,
            scope,
            "strict_docs",
            config.context_token_budget,
            context.run_id,
        )
        if retrieved.evidence and not pack.evidence:
            raise BudgetExceeded(
                "No complete source excerpt fits the QA evidence budget"
            )
        for item in pack.evidence:
            await _await_if_needed(ports.verify_evidence(item, scope))
        await auth()
        traced(
            "retrieve",
            evidence_ids=pack.provided_evidence_ids,
            context_tokens=pack.context_tokens,
            reranker_calls=ledger.usage.reranker_calls,
        )
        if not pack.evidence:
            payload = _notice("insufficient_evidence")

    if payload is None:
        require_calls(2)
        await stage("generating")
        generated = await invoke(
            "generate",
            lambda: generator.generate(question, pack, retrieval_query=retrieval_query),
            pack,
            retrieval_query=retrieval_query,
        )
        payload = _validate_payload(generated.payload, pack)
        traced(
            "generate",
            block_count=len(payload.blocks),
            answer_status=payload.answer_status,
        )
        await stage("validating")
        validated = await invoke(
            "semantic",
            lambda: generator.validate_semantics(
                payload,
                pack,
                question,
                retrieval_query=retrieval_query,
            ),
            pack,
            payload=payload,
            retrieval_query=retrieval_query,
        )
        traced(
            "validate",
            passed=validated.passed,
            semantic_status=validated.semantic_status,
            errors=validated.errors,
        )
        if not validated.passed or validated.semantic_status != "passed":
            raise GenerationValidationFailed(
                "QA answer is not fully supported by its cited evidence",
                details={"validation_errors": validated.errors},
            )

    await auth()
    for item in pack.evidence:
        await _await_if_needed(ports.verify_evidence(item, scope))
    await auth()
    usage = ledger.snapshot()
    usage.input_tokens += sum(
        actual.input_tokens - admitted for admitted, actual in observations
    )
    if observations:
        usage.token_count_method = (
            "provider-reported"
            if usage.embedding_calls == 0
            and usage.reranker_calls == 0
            and all(
                actual.token_count_method == "provider-reported"
                for _, actual in observations
            )
            else "provider-reported-or-utf8-upper-bound-v1"
        )
    usage.stage_ms["total"] = (time.monotonic() - started) * 1000
    execution_config = {
        "pipeline": config.model_dump(mode="json"),
        "model": generator.model_configuration,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": PROMPT_HASH,
        "history_policy": "same-scope-complete-pairs-6-8000-v1",
    }
    ledger.check()
    return ChatAnswerArtifact(
        **payload.model_dump(mode="json"),
        run_id=context.run_id,
        evidence=pack.evidence,
        retrieval_query=retrieval_query,
        scope_fingerprint=scope.fingerprint,
        pipeline_config_hash=stable_hash(execution_config),
        model_fingerprint=generator.model_fingerprint,
        prompt_version=PROMPT_VERSION,
        usage=usage,
        effective_config={
            **execution_config,
            "retrieval": retrieval_config,
            "history_turn_count": len(selected_history),
        },
        trace=trace,
    )
