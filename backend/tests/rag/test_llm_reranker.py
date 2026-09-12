"""Chat ranking preserves immutable evidence and shares generation's call quota."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.rag.budget import BudgetLedger, count_tokens
from app.rag.contracts import BudgetLimits, DocumentEvidence, text_hash
from app.rag.errors import BudgetExceeded, RetrievalUnavailable
from tests.rag.test_contracts import document_payload


def configuration(**overrides):
    from app.rag.providers.llm_reranker_config import llm_reranker_config

    return llm_reranker_config(
        Settings(
            _env_file=None,
            llm_provider="anthropic",
            anthropic_api_key="test-only-secret",
            anthropic_model="claude-opus-5-max",
            anthropic_base_url="https://native.example/v1",
            **overrides,
        )
    )


def candidates(count=2, text="光合作用需要光。"):
    result = []
    for index in range(count):
        payload = document_payload()
        payload.update(
            evidence_id=f"ev_{index}",
            chunk_id=f"chunk_{index}",
            excerpt=text,
            text_hash=text_hash(text),
        )
        payload["locator"].update(end_char=len(text), quote_hash=text_hash(text))
        result.append(DocumentEvidence.model_validate(payload))
    return result


class Chat:
    max_retries = 0

    def __init__(self, ranking=None, *, response=None, delay=0):
        self.ranking = [1, 0] if ranking is None else ranking
        self.response = response
        self.delay = delay
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response or SimpleNamespace(
            content=json.dumps({"ranking": self.ranking}),
            usage_metadata={"output_tokens": 12},
        )


def test_llm_configuration_freezes_real_provider_identity_without_credentials():
    from app.rag.registry import get_pipeline_config

    config = configuration()
    assert config.provider == "llm"
    assert config.llm.provider == "anthropic"
    assert config.llm.model == "claude-opus-5-max"
    assert config.llm.endpoint_hash == text_hash("https://native.example")
    assert config.llm.prompt_version == "listwise-ranking-v1"
    assert config.llm.application == "merged-candidates-per-round-v1"
    assert config.model_revision is None and config.license is None
    assert "test-only-secret" not in config.model_dump_json()
    assert "https://native.example" not in config.model_dump_json()
    pipeline = get_pipeline_config("hybrid-llm-rerank-v1", reranker=config)
    assert pipeline.max_subqueries == 3 and pipeline.max_llm_calls == 5
    assert pipeline.require_semantic_validation
    with pytest.raises(ValueError):
        get_pipeline_config("hybrid-llm-rerank-v1")


@pytest.mark.asyncio
async def test_ranking_changes_only_order_and_scores_and_counts_both_limits_once():
    from app.rag.providers.llm_reranker import LLMReranker
    from app.rag.providers.reranker import rerank

    chat, evidence = Chat(), candidates()
    originals = [item.model_dump(mode="json") for item in evidence]
    config = configuration()
    budget = BudgetLedger(BudgetLimits())
    result = await rerank(
        "植物的能量来源",
        evidence,
        config,
        provider=LLMReranker(chat, config),
        budget=budget,
    )
    assert [item.evidence_id for item in result.evidence] == ["ev_1", "ev_0"]
    assert result.evidence[0].score == 1.0
    assert result.evidence[1].score == 0.5
    assert [item.model_dump(mode="json") for item in evidence] == originals
    for item in result.evidence:
        source = next(e for e in evidence if e.evidence_id == item.evidence_id)
        assert item.model_dump(
            exclude={"score", "retrieval_scores"}
        ) == source.model_dump(exclude={"score", "retrieval_scores"})
    assert budget.usage.llm_calls == budget.usage.reranker_calls == 1
    assert budget.usage.input_tokens == 32 + sum(
        count_tokens(message.content) for message in chat.calls[0]
    )
    assert budget.usage.output_tokens == 12
    assert result.effective_config["llm"]["model"] == "claude-opus-5-max"
    assert result.effective_config["score_kind"] == "reciprocal_rank"


@pytest.mark.asyncio
async def test_unicode_and_json_escaping_fit_prompt_ceiling_without_altering_sources():
    from app.rag.providers.llm_reranker import LLMReranker
    from app.rag.providers.reranker import rerank

    evidence = candidates(40, text=('光😀\\"\n' * 1500))
    chat = Chat(list(reversed(range(40))))
    config = configuration()
    await rerank("能量", evidence, config, provider=LLMReranker(chat, config))
    messages = chat.calls[0]
    assert 32 + sum(count_tokens(message.content) for message in messages) <= 12000
    request = json.loads(messages[1].content)
    assert request["query"] == "能量" and len(request["candidates"]) == 40
    for index, item in enumerate(request["candidates"]):
        assert item["index"] == index and item["text"]
        assert evidence[index].excerpt.startswith(item["text"])
        assert len(item["text"]) < len(evidence[index].excerpt)
    assert evidence[0].text_hash == text_hash(evidence[0].excerpt)


@pytest.mark.parametrize(
    "ranking", [[0, 0], [0], [0, 2], [-1, 0], [False, 1], [0.0, 1], ["0", "1"]]
)
@pytest.mark.asyncio
async def test_invalid_permutations_fail_closed_without_retrying(ranking):
    from app.rag.providers.llm_reranker import LLMReranker
    from app.rag.providers.reranker import rerank

    config, chat = configuration(), Chat(ranking)
    budget = BudgetLedger(BudgetLimits())
    with pytest.raises(
        RetrievalUnavailable, match="Configured reranker is unavailable"
    ):
        await rerank(
            "test",
            candidates(),
            config,
            provider=LLMReranker(chat, config),
            budget=budget,
        )
    assert len(chat.calls) == 1
    assert budget.usage.llm_calls == budget.usage.reranker_calls == 1


@pytest.mark.parametrize("limit", ["max_llm_calls", "max_reranker_calls"])
@pytest.mark.asyncio
async def test_shared_limits_reject_before_call_and_cannot_be_hidden_by_fallback(limit):
    from app.rag.providers.llm_reranker import LLMReranker
    from app.rag.providers.reranker import rerank

    config = configuration().model_copy(update={"allow_rrf_fallback": True})
    chat, budget = Chat(), BudgetLedger(BudgetLimits(**{limit: 0}))
    with pytest.raises(BudgetExceeded):
        await rerank(
            "test",
            candidates(),
            config,
            provider=LLMReranker(chat, config),
            budget=budget,
        )
    assert not chat.calls
    assert budget.usage.llm_calls == budget.usage.reranker_calls == 0


@pytest.mark.asyncio
async def test_impossible_prompt_fails_before_admission_instead_of_dropping_query():
    from app.rag.providers.llm_reranker import LLMReranker
    from app.rag.providers.reranker import rerank

    config, chat = configuration(), Chat()
    budget = BudgetLedger(BudgetLimits())
    with pytest.raises(BudgetExceeded):
        await rerank(
            "很长的查询" * 1000,
            candidates(),
            config,
            provider=LLMReranker(chat, config),
            budget=budget,
        )
    assert not chat.calls and budget.usage.llm_calls == 0


@pytest.mark.asyncio
async def test_explicit_fallback_is_recorded_but_failed_call_is_still_counted():
    from app.rag.providers.llm_reranker import LLMReranker
    from app.rag.providers.reranker import rerank

    config = configuration().model_copy(update={"allow_rrf_fallback": True})
    chat, evidence = Chat(response=OSError("private endpoint detail")), candidates()
    budget = BudgetLedger(BudgetLimits())
    result = await rerank(
        "test", evidence, config, provider=LLMReranker(chat, config), budget=budget
    )
    assert result.evidence == evidence
    assert result.effective_config["requested_provider"] == "llm"
    assert result.effective_config["effective_provider"] == "none"
    assert result.warnings == ["reranker_unavailable_rrf_fallback"]
    assert budget.usage.llm_calls == budget.usage.reranker_calls == 1
    assert len(chat.calls) == 1


@pytest.mark.parametrize(
    "code",
    ["budget_exceeded", "stale_lease", "run_stopped", "pricing_required", "not_found"],
)
@pytest.mark.asyncio
async def test_local_control_errors_cannot_be_converted_into_rrf_fallback(code):
    from app.core.errors import AppError
    from app.rag.providers.llm_reranker import LLMReranker
    from app.rag.providers.reranker import rerank

    config = configuration().model_copy(update={"allow_rrf_fallback": True})
    problem = AppError(409, code, "Local admission stopped the operation")
    chat = Chat(response=problem)
    with pytest.raises(AppError) as caught:
        await rerank("test", candidates(), config, provider=LLMReranker(chat, config))
    assert caught.value is problem
    assert len(chat.calls) == 1


def test_ranking_prompt_ceiling_must_fit_the_pipeline_model_window():
    from app.rag.contracts import PipelineConfig

    with pytest.raises(ValueError, match="context window"):
        PipelineConfig(reranker=configuration(), model_context_window=2048)


@pytest.mark.parametrize("problem_type", ["ScopeRevoked", "SourceUnavailable"])
@pytest.mark.asyncio
async def test_source_authorization_or_integrity_failure_never_falls_back(problem_type):
    from app.rag import errors
    from app.rag.providers.llm_reranker import LLMReranker
    from app.rag.providers.reranker import rerank

    config = configuration().model_copy(update={"allow_rrf_fallback": True})
    problem = getattr(errors, problem_type)("Source access changed")
    chat = Chat(response=problem)
    with pytest.raises(type(problem)) as caught:
        await rerank("test", candidates(), config, provider=LLMReranker(chat, config))
    assert caught.value is problem


@pytest.mark.asyncio
async def test_deadline_exhaustion_is_not_successful_fallback():
    from app.rag.providers.llm_reranker import LLMReranker
    from app.rag.providers.reranker import rerank

    config = configuration().model_copy(update={"allow_rrf_fallback": True})
    chat = Chat(delay=1)
    budget = BudgetLedger(BudgetLimits(deadline_seconds=0.03))
    with pytest.raises(BudgetExceeded):
        await rerank(
            "test",
            candidates(),
            config,
            provider=LLMReranker(chat, config),
            budget=budget,
        )
    assert len(chat.calls) == 1


@pytest.mark.asyncio
async def test_three_catalog_queries_share_one_ranking_and_allow_full_generation_retry():
    from app.rag.contracts import RetrievalResult, ValidationResult
    from app.rag.pipeline import PipelinePorts, generate_quiz_artifact
    from app.rag.providers.llm_reranker import LLMReranker
    from app.rag.providers.reranker import rerank
    from app.rag.registry import get_pipeline_config
    from tests.rag.test_artifact_pipeline import (
        context_and_scope,
        quiz_for,
        strict_spec,
    )

    evidence, actor, context, scope = context_and_scope()
    spec = strict_spec().model_copy(
        update={"objective_titles": ["光照", "叶绿体", "有机物"]}
    )
    config = get_pipeline_config("hybrid-llm-rerank-v1", reranker=configuration())
    queries, generated, validations = [], [], []
    chat = Chat([0])

    async def retrieve(query, scope, selected_config, **kwargs):
        queries.append(query)
        assert selected_config.reranker.provider == "none"
        return RetrievalResult(evidence=[evidence], candidates=[evidence])

    async def rank(query, evidence_items, scope, selected_config, *, budget):
        return await rerank(
            query,
            evidence_items,
            selected_config.reranker,
            provider=LLMReranker(chat, selected_config.reranker),
            budget=budget,
        )

    async def generate(spec, pack, coverage, attempt, **kwargs):
        generated.append(attempt)
        quiz = quiz_for(spec, pack, coverage)
        for question, target in zip(quiz["questions"], coverage.targets):
            question["coverage_target_id"] = target.target_id
        return quiz

    async def validate(*args):
        validations.append(True)
        passed = len(validations) == 2
        return ValidationResult(
            passed=passed,
            semantic_status="passed" if passed else "failed",
            errors=[] if passed else ["semantic_support_missing"],
        )

    artifact = await generate_quiz_artifact(
        spec,
        actor,
        context,
        PipelinePorts(
            retrieve=retrieve,
            generate=generate,
            reauthorize=lambda scope: scope,
            semantic_validator=validate,
            rerank_candidates=rank,
        ),
        resolved_scope=scope,
        config=config,
    )
    assert len(queries) == 3 and len(chat.calls) == 1
    assert generated == [1, 2] and len(validations) == 2
    assert artifact.usage.llm_calls == 5 and artifact.usage.reranker_calls == 1
    assert artifact.validation.passed
    assert len(artifact.evidence_pack.coverage.targets) == 3
    assert sum(stage["stage"] == "rerank" for stage in artifact.trace) == 1
