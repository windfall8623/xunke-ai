"""Bounded LangGraph orchestration returning artifacts without learning effects.

All integrations enter through ports. The core cannot write quiz sessions, XP,
answers, image logs, or SQL jobs. SQL publication and leases belong to its caller.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from app.rag.budget import BudgetLedger, count_tokens
from app.rag.context import assemble_evidence
from app.rag.contracts import (
    CoveragePlan,
    GenerationResult,
    PipelineConfig,
    QuizArtifact,
    QuizPayload,
    RerankerConfig,
    ResolvedScope,
    RetrievalResult,
    ValidationResult,
    stable_hash,
)
from app.rag.coverage import bind_coverage, missing_coverage, plan_coverage
from app.rag.errors import (
    BudgetExceeded,
    GenerationValidationFailed,
    InsufficientEvidence,
    RagError,
    RetrievalUnavailable,
    ScopeRevoked,
)
from app.rag.scope import evidence_in_scope, normalize_spec, require_execution_scope
from app.rag.retrieval import rrf_merge
from app.rag.validation import validate_quiz_artifact


logger = logging.getLogger(__name__)


def _validation_categories(errors):
    """Only fixed categories reach logs; model errors may contain private text."""
    allowed = {
        "question_count_mismatch", "duplicate_question_id",
        "provided_evidence_set_mismatch", "evidence_outside_scope",
        "invalid_option_keys", "invalid_answer_set", "single_answer_required",
        "multiple_answers_required", "invalid_judge_options", "difficulty_mismatch",
        "duplicate_question", "unknown_or_duplicate_citation", "missing_citation",
        "unsupported_support_quote", "absence_is_not_false_counterevidence",
        "model_only_cannot_claim_citations", "unknown_coverage_target",
        "coverage_evidence_mismatch", "generator_unavailable",
        "semantic_checks_incomplete", "semantic_validation_failed",
        "answer_valid", "explanation_valid", "not_duplicate", "source_supported",
        "false_requires_counterevidence",
    }
    categories = set()
    for error in errors:
        if not isinstance(error, str):
            categories.add("unclassified")
        elif error.startswith("schema_invalid:"):
            categories.add("schema_invalid")
        elif error.startswith("coverage_quota_mismatch:"):
            categories.add("coverage_quota_mismatch")
        else:
            code = error.rsplit(":", 1)[-1]
            categories.add(code if code in allowed else "unclassified")
    return sorted(categories)


@dataclass(frozen=True)
class PipelinePorts:
    retrieve: Callable
    generate: Callable
    reauthorize: Callable
    web_search: Callable | None = None
    semantic_validator: Callable | None = None
    verify_evidence: Callable | None = None
    record_trace: Callable | None = None
    catalog: Any = None
    estimate_llm_cost: Callable | None = None
    prompt_token_count: Callable | None = None
    rerank_candidates: Callable | None = None


class _State(TypedDict, total=False):
    round: int
    attempt: int
    plan: Any
    candidates: list
    web_evidence: list
    web_attempted: bool
    warnings: list[str]
    retrieval_configs: list[dict]
    pack: Any
    payload: Any
    validation: Any
    generation_error: bool
    artifact: Any


async def _await_if_needed(value):
    return await value if inspect.isawaitable(value) else value


async def reauthorize_scope(callback, scope):
    result = await _await_if_needed(callback(scope))
    if result is False or (
        isinstance(result, ResolvedScope) and result.fingerprint != scope.fingerprint
    ):
        raise ScopeRevoked("Source authorization changed during execution")


def _balanced(evidence, plan):
    by_id = {e.evidence_id: e for e in evidence}
    chosen = []
    bound = bind_coverage(plan, evidence)
    queues = [list(t.evidence_ids) for t in bound.targets]
    while any(queues):
        for queue in queues:
            if queue:
                identity = queue.pop(0)
                if identity in by_id:
                    chosen.append(by_id.pop(identity))
    return chosen + list(by_id.values())


def _fixed_plan(spec, scope, plan, config):
    """Validate a server-selected plan without catalog filtering or truncation."""
    try:
        if not isinstance(plan, CoveragePlan):
            raise ValueError("Fixed coverage requires a CoveragePlan")
        plan = CoveragePlan.model_validate(plan.model_dump(mode="json"), strict=True)
        targets = plan.targets
        by_doc = {source.doc_id: source for source in scope.documents}
        if (
            spec.source_policy != "strict_docs"
            or not by_doc
            or len(targets) > 3
            or len({target.target_id for target in targets}) != len(targets)
            or sum(target.question_quota for target in targets) != spec.question_count
            or len(plan.subqueries) > config.max_subqueries
            or any(not query.strip() for query in plan.subqueries)
        ):
            raise ValueError("Fixed coverage has incompatible targets, quotas or scope")
        for target in targets:
            if (
                not target.target_id.strip()
                or not target.title.strip()
                or not target.doc_ids
                or len(set(target.doc_ids)) != len(target.doc_ids)
                or not set(target.doc_ids) <= set(by_doc)
                or len(set(target.section_ids)) != len(target.section_ids)
                or target.evidence_ids
            ):
                raise ValueError("Fixed coverage contains invalid target identities")
            for section_id in target.section_ids:
                if not any(
                    section_id.startswith(by_doc[doc_id].parse_artifact_id + ":")
                    and (
                        not by_doc[doc_id].section_ids
                        or section_id in by_doc[doc_id].section_ids
                    )
                    for doc_id in target.doc_ids
                ):
                    raise ValueError(
                        "Fixed coverage selects a section outside its scope"
                    )
        return plan
    except (ValueError, TypeError, AttributeError) as exc:
        raise GenerationValidationFailed("Fixed coverage plan is invalid") from exc


async def generate_quiz_artifact(
    spec,
    actor,
    context,
    ports: PipelinePorts,
    *,
    resolved_scope: ResolvedScope | None = None,
    config: PipelineConfig | None = None,
    coverage_plan: CoveragePlan | None = None,
) -> QuizArtifact:
    """Execute at most two retrieval rounds, two generations, five total LLM calls."""
    from langgraph.graph import END, START, StateGraph

    spec = normalize_spec(spec)
    config = config or PipelineConfig()
    scope = resolved_scope or ResolvedScope(
        owner_id=actor.owner_id, namespace=context.storage_namespace
    )
    require_execution_scope(actor, context, scope)
    if spec.source_policy == "topic" and scope.documents:
        raise ScopeRevoked("Topic execution cannot carry a private library scope")
    if spec.source_policy != "topic":
        requested = {d.doc_id for d in spec.scope.documents}
        if requested != {d.doc_id for d in scope.documents}:
            raise ScopeRevoked("Resolved source selection does not match the request")
    fixed = (
        _fixed_plan(spec, scope, coverage_plan, config)
        if coverage_plan is not None
        else None
    )
    limits = context.budget.model_copy(
        update={
            "max_llm_calls": min(context.budget.max_llm_calls, config.max_llm_calls)
        }
    )
    ledger = BudgetLedger(limits)
    trace: list[dict] = []

    async def auth():
        ledger.check()
        await reauthorize_scope(ports.reauthorize, scope)

    def traced(stage, **values):
        # Private excerpt/prompt text is never added to public stage records.
        trace.append({"stage": stage, **values})

    async def prepare(state):
        await auth()
        plan = (
            fixed
            if fixed is not None
            else plan_coverage(
                spec,
                scope,
                ports.catalog,
                max_subqueries=config.max_subqueries,
                strategy=config.coverage_strategy or "catalog-v1",
            )
        )
        traced(
            "plan", target_count=len(plan.targets), subquery_count=len(plan.subqueries)
        )
        return {
            "round": 0,
            "attempt": 0,
            "plan": plan,
            "candidates": [],
            "web_evidence": [],
            "web_attempted": False,
            "warnings": [],
            "retrieval_configs": [],
        }

    async def retrieve(state):
        await auth()
        round_number = state["round"] + 1
        evidence = list(state["candidates"])
        configurations = list(state["retrieval_configs"])
        warnings = list(state["warnings"])
        started = time.monotonic()
        if scope.documents:
            batch_ranking = config.reranker.provider == "llm"
            retrieval_config = (
                config.model_copy(update={"reranker": RerankerConfig()})
                if batch_ranking
                else config
            )
            round_candidates, round_rankings = {}, []
            queries = state["plan"].subqueries
            if round_number > 1:
                missing = missing_coverage(state.get("pack").coverage)
                queries = [target.title for target in missing] or queries
            for query in queries[: config.max_subqueries]:
                await auth()
                try:
                    result = await asyncio.wait_for(
                        ports.retrieve(query, scope, retrieval_config, budget=ledger),
                        timeout=ledger.remaining_seconds,
                    )
                    result = RetrievalResult.model_validate(result)
                    if fixed is not None:
                        for item in [*result.evidence, *result.candidates]:
                            if not evidence_in_scope(item, scope):
                                raise ScopeRevoked(
                                    "Fixed coverage evidence is outside its source scope"
                                )
                except RagError:
                    raise
                except Exception as exc:
                    raise RetrievalUnavailable(
                        "Retrieval infrastructure is unavailable"
                    ) from exc
                await auth()
                if batch_ranking:
                    candidates = result.candidates or result.evidence
                    round_candidates.update({e.evidence_id: e for e in candidates})
                    round_rankings.append([e.evidence_id for e in candidates])
                else:
                    evidence.extend(result.evidence)
                configurations.append(result.effective_config)
                warnings.extend(result.warnings)
                traced(
                    "retrieve",
                    round=round_number,
                    candidate_ids=[e.evidence_id for e in result.candidates],
                    selected_ids=[e.evidence_id for e in result.evidence],
                )
            if batch_ranking and round_candidates:
                if ports.rerank_candidates is None:
                    raise RetrievalUnavailable("LLM ranking port is not configured")
                fused = rrf_merge(round_rankings, config.rrf_k, len(round_candidates))
                merged = [round_candidates[item.id] for item in fused]
                # Keep catalog coverage in the bounded pool even when a broad
                # query otherwise dominates the cross-query rank fusion.
                merged = _balanced(merged, state["plan"])[: config.candidate_limit]
                ranked = RetrievalResult.model_validate(
                    await asyncio.wait_for(
                        ports.rerank_candidates(
                            spec.user_input, merged, scope, config, budget=ledger
                        ),
                        timeout=ledger.remaining_seconds,
                    )
                )
                await auth()
                selected = _balanced(
                    ranked.candidates or ranked.evidence, state["plan"]
                )[: config.final_top_k]
                evidence.extend(selected)
                configurations.append({"reranker": ranked.effective_config})
                warnings.extend(ranked.warnings)
                traced(
                    "rerank",
                    round=round_number,
                    candidate_ids=[e.evidence_id for e in merged],
                    selected_ids=[e.evidence_id for e in selected],
                )
        ledger.usage.stage_ms["retrieval"] = (
            ledger.usage.stage_ms.get("retrieval", 0)
            + (time.monotonic() - started) * 1000
        )
        return {
            "round": round_number,
            "candidates": evidence,
            "retrieval_configs": configurations,
            "warnings": warnings,
        }

    async def assemble(state):
        await auth()
        web_evidence = state["web_evidence"]
        attempted = state["web_attempted"]
        warnings = list(state["warnings"])
        if spec.source_policy in ("topic", "doc_plus_web") and not attempted:
            attempted = True
            if ports.web_search is not None:
                try:
                    web_evidence = await asyncio.wait_for(
                        ports.web_search(
                            spec.user_input, scope, context, budget=ledger
                        ),
                        timeout=ledger.remaining_seconds,
                    )
                except BudgetExceeded:
                    raise
                except Exception as exc:
                    if spec.source_policy == "doc_plus_web" and not state["candidates"]:
                        raise RetrievalUnavailable(
                            "Document and web retrieval are unavailable"
                        ) from exc
                    warnings.append("optional_web_search_unavailable")
        evidence = _balanced([*state["candidates"], *web_evidence], state["plan"])
        pack = assemble_evidence(
            evidence,
            scope,
            spec.source_policy,
            config.context_token_budget,
            context.run_id,
            coverage=state["plan"],
        )
        pack.coverage = bind_coverage(state["plan"], pack.evidence)
        pack.warnings = list(dict.fromkeys(warnings))
        if ports.verify_evidence is not None:
            for item in pack.evidence:
                await _await_if_needed(ports.verify_evidence(item, scope))
        await auth()
        missing = missing_coverage(pack.coverage) if pack.status != "model_only" else []
        if (
            spec.source_policy != "topic"
            and (not pack.evidence or missing)
            and state["round"] >= config.max_retrieval_rounds
        ):
            raise InsufficientEvidence(
                "Selected sources do not provide enough evidence for the requested coverage"
            )
        traced(
            "assemble",
            evidence_ids=pack.provided_evidence_ids,
            context_tokens=pack.context_tokens,
            missing_target_ids=[target.target_id for target in missing],
        )
        return {
            "pack": pack,
            "web_evidence": web_evidence,
            "web_attempted": attempted,
            "warnings": warnings,
        }

    def after_assemble(state):
        pack = state["pack"]
        if spec.source_policy != "topic" and (
            not pack.evidence or missing_coverage(pack.coverage)
        ):
            return "retrieve"
        return "generate"

    def reserve_llm(state, stage):
        # Includes request/coverage and framing; generator validates its actual prompt
        # window too. No excerpt is cropped or generated ID accepted here.
        serialized = json.dumps(
            {
                "spec": spec.model_dump(mode="json"),
                "evidence": [
                    {"id": e.evidence_id, "text": e.excerpt}
                    for e in state["pack"].evidence
                ],
                "coverage": state["pack"].coverage.model_dump(mode="json"),
                "payload": state.get("payload") if stage == "semantic" else None,
            },
            ensure_ascii=False,
        )
        input_tokens = (
            ports.prompt_token_count(
                stage,
                spec,
                state["pack"],
                state["pack"].coverage,
                state.get("payload"),
                state["validation"].errors if state.get("validation") else None,
            )
            if ports.prompt_token_count
            else count_tokens(serialized) + 1500
        )
        if input_tokens + config.output_token_reserve > config.model_context_window:
            raise BudgetExceeded(
                "Evidence and output reserve exceed the configured model context window"
            )
        estimate = (
            ports.estimate_llm_cost(stage, input_tokens, config.output_token_reserve)
            if ports.estimate_llm_cost
            else None
        )
        ledger.reserve("llm", input_tokens=input_tokens, estimated_cost_usd=estimate)

    async def generate(state):
        await auth()
        if config.reranker.provider == "llm" and (
            limits.max_llm_calls - ledger.usage.llm_calls
            < 1 + int(config.require_semantic_validation)
        ):
            raise BudgetExceeded(
                "Remaining calls cannot cover generation and required validation"
            )
        attempt = state["attempt"] + 1
        reserve_llm(state, "generate")
        started = time.monotonic()
        feedback = state["validation"].errors if state.get("validation") else None
        try:
            generated = await asyncio.wait_for(
                ports.generate(
                    spec,
                    state["pack"],
                    state["pack"].coverage,
                    attempt,
                    feedback=feedback,
                ),
                timeout=ledger.remaining_seconds,
            )
            if isinstance(generated, GenerationResult):
                payload = generated.payload
                ledger.record_output(
                    generated.usage.output_tokens
                    or count_tokens(json.dumps(payload, ensure_ascii=False))
                )
            else:
                payload = (
                    generated.model_dump(mode="json")
                    if hasattr(generated, "model_dump")
                    else generated
                )
                ledger.record_output(
                    count_tokens(json.dumps(payload, ensure_ascii=False))
                )
            error = False
        except RagError:
            raise
        except asyncio.TimeoutError as exc:
            raise BudgetExceeded("Generation exceeded the execution deadline") from exc
        except Exception:  # noqa: BLE001 - Bounded validation retry retains the failed call budget.
            payload, error = {}, True
        await auth()
        ledger.usage.stage_ms["generation"] = (
            ledger.usage.stage_ms.get("generation", 0)
            + (time.monotonic() - started) * 1000
        )
        traced(
            "generate",
            attempt=attempt,
            provided_evidence_ids=state["pack"].provided_evidence_ids,
            provider_failed=error,
        )
        return {"attempt": attempt, "payload": payload, "generation_error": error}

    async def validate(state):
        await auth()
        if state["generation_error"]:
            validation = ValidationResult(
                passed=False, errors=["generator_unavailable"]
            )
        else:
            validation = validate_quiz_artifact(state["payload"], spec, state["pack"])
        if validation.passed and config.require_semantic_validation:
            if ports.semantic_validator is None:
                raise GenerationValidationFailed(
                    "A semantic validation provider is required by this pipeline"
                )
            reserve_llm(state, "semantic")
            try:
                semantic = await asyncio.wait_for(
                    ports.semantic_validator(
                        QuizPayload.model_validate(state["payload"]),
                        state["pack"],
                        spec,
                    ),
                    timeout=ledger.remaining_seconds,
                )
                semantic = ValidationResult.model_validate(semantic)
                ledger.record_output(
                    semantic.provider_usage.output_tokens
                    if semantic.provider_usage and semantic.provider_usage.output_tokens
                    else count_tokens(semantic.model_dump_json())
                )
            except RagError:
                raise
            except Exception as exc:
                raise GenerationValidationFailed(
                    "Semantic validator is unavailable"
                ) from exc
            validation = (
                semantic
                if semantic.passed and semantic.semantic_status == "passed"
                else ValidationResult(
                    passed=False,
                    errors=semantic.errors or ["semantic_validation_failed"],
                    semantic_status="failed",
                    semantic_details=semantic.semantic_details,
                )
            )
        await auth()
        traced(
            "validate",
            attempt=state["attempt"],
            passed=validation.passed,
            semantic_status=validation.semantic_status,
            errors=validation.errors,
        )
        if not validation.passed:
            logger.warning(
                "Quiz validation rejected attempt=%s semantic=%s categories=%s",
                state["attempt"], validation.semantic_status,
                ",".join(_validation_categories(validation.errors)),
            )
        return {"validation": validation}

    def after_validate(state):
        if state["validation"].passed:
            return "finish"
        if state["attempt"] >= config.max_generation_attempts:
            raise GenerationValidationFailed(
                "Generated quiz failed validation after the bounded attempts",
                details={"validation_errors": state["validation"].errors},
            )
        return "generate"

    async def finish(state):
        await auth()
        pack = state["pack"].model_copy(update={"usage": ledger.snapshot()})
        artifact = QuizArtifact(
            **state["payload"],
            artifact_id="artifact_"
            + stable_hash([context.run_id, config.pipeline_config_hash])[:32],
            run_id=context.run_id,
            owner_id=actor.owner_id,
            mode=context.mode,
            source_status="model_only" if pack.status == "model_only" else "grounded",
            evidence_pack=pack,
            pipeline_version=config.pipeline_version,
            pipeline_config_hash=config.pipeline_config_hash,
            usage=ledger.snapshot(),
            validation=state["validation"],
            effective_config={
                "pipeline": config.model_dump(mode="json"),
                "retrieval": state["retrieval_configs"],
            },
            trace=trace,
        )
        if ports.record_trace:
            await _await_if_needed(
                ports.record_trace(
                    {
                        "run_id": context.run_id,
                        "stages": trace,
                        "usage": ledger.snapshot().model_dump(mode="json"),
                    }
                )
            )
        return {"artifact": artifact}

    graph = StateGraph(_State)
    for name, function in [
        ("prepare", prepare),
        ("retrieve", retrieve),
        ("assemble", assemble),
        ("generate", generate),
        ("validate", validate),
        ("finish", finish),
    ]:
        graph.add_node(name, function)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "retrieve")
    graph.add_edge("retrieve", "assemble")
    graph.add_conditional_edges(
        "assemble", after_assemble, {"retrieve": "retrieve", "generate": "generate"}
    )
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges(
        "validate", after_validate, {"generate": "generate", "finish": "finish"}
    )
    graph.add_edge("finish", END)
    try:
        result = await asyncio.wait_for(
            graph.compile().ainvoke({}, config={"recursion_limit": 24}),
            timeout=ledger.remaining_seconds,
        )
        return result["artifact"]
    except RagError as exc:
        exc.details.update(
            usage=ledger.snapshot().model_dump(mode="json"), stage_trace=trace
        )
        raise
    except asyncio.TimeoutError as exc:
        raise BudgetExceeded(
            "Pipeline deadline exceeded",
            details={"usage": ledger.snapshot().model_dump(mode="json")},
        ) from exc
