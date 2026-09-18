"""Source-aware practice money and previews; no providers or database required."""

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.config import Settings
from app.core.values import dump
from app.practice.contracts import PracticeCallUsage, PracticeSpec
from app.rag.contracts import LLMRerankerConfig, PipelineConfig, RerankerConfig
from app.services import practice_view_service as previews
from app.workers import practice_job


@asynccontextmanager
async def transaction():
    yield object()


def ledger_row(*, source="user", stage="llm", status="completed", number=1):
    cost = None if source == "user" else Decimal("0.000020")
    raw = {
        "call_id": f"call-{number}", "attempt": 1, "stage": stage,
        "status": status, "model": "synthetic-model", "purpose": "practice_generation",
        "cost_cny": None if cost is None else str(cost),
        "reserved_cost_cny": None if cost is None else "0.000100",
        "cost_status": "not_applicable" if source == "user" else "estimated",
        "input_tokens": 12, "output_tokens": 5, "latency_ms": 3,
    }
    if source is not None:
        raw["config_source"] = source
    return {
        "call_id": raw["call_id"], "task_id": "task-1", "stage": stage,
        "status": status, "usage_json": dump(raw),
        "call_status": "settled", "call_reserved": Decimal(1), "call_actual": Decimal(1),
        "cny_status": None if cost is None else "settled",
        "cny_reserved": None if cost is None else Decimal("0.000100"),
        "cny_actual": cost,
    }


async def project(monkeypatch, rows, *, accounts=None):
    if accounts is None:
        stages = {row["stage"] for row in rows}
        accounts = [
            {"account_key": f"job:task-1:{stage}",
             "used": sum(row["stage"] == stage for row in rows), "reserved": 0}
            for stage in stages
        ]
    monkeypatch.setattr(practice_job, "transaction", transaction)
    fetch = AsyncMock(side_effect=[[{"task_id": "task-1"}], rows, accounts])
    monkeypatch.setattr(practice_job, "fetch_all", fetch)
    return await practice_job.load_practice_usage(7, "production", "practice-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "unknown", "reserved"])
async def test_personal_usage_is_not_applicable_but_keeps_technical_counts(monkeypatch, status):
    usage = await project(monkeypatch, [ledger_row(status=status)])
    assert usage.ledger_complete
    assert usage.cost_cny is usage.reserved_cost_cny is None
    assert usage.cost_status_cny == "not_applicable"
    assert usage.known_cost_cny == 0
    assert usage.llm_calls == 1 and usage.input_tokens == 12 and usage.output_tokens == 5
    call = usage.calls[0]
    assert call.config_source == "user" and call.cost_status == "not_applicable"
    assert call.cost_cny is call.reserved_cost_cny is None


@pytest.mark.asyncio
async def test_mixed_usage_prices_only_system_retrieval_and_keeps_original_ceiling(monkeypatch):
    usage = await project(monkeypatch, [
        ledger_row(), ledger_row(source="system", stage="embedding", number=2),
    ])
    assert usage.ledger_complete and usage.cost_status_cny == "estimated"
    assert usage.cost_cny == Decimal("0.000020")
    assert usage.reserved_cost_cny == 0
    assert usage.calls[1].reserved_cost_cny == Decimal("0.000100")
    assert usage.llm_calls == usage.embedding_calls == 1


@pytest.mark.asyncio
async def test_personal_usage_does_not_hide_missing_technical_journal(monkeypatch):
    usage = await project(monkeypatch, [ledger_row()], accounts=[])
    assert not usage.ledger_complete
    assert usage.cost_status_cny == "unknown" and usage.cost_cny is None


@pytest.mark.asyncio
async def test_personal_usage_does_not_hide_accidental_financial_reservation(monkeypatch):
    row = ledger_row()
    row.update(cny_status="reserved", cny_reserved=Decimal("1"))
    usage = await project(monkeypatch, [row])
    assert not usage.ledger_complete and usage.cost_cny is None


@pytest.mark.asyncio
async def test_historic_missing_source_is_never_inferred_from_empty_money(monkeypatch):
    row = ledger_row()
    from app.core.values import load

    raw = load(row["usage_json"])
    raw.pop("config_source")
    raw["cost_status"] = "unknown"
    row["usage_json"] = dump(raw)
    usage = await project(monkeypatch, [row])
    assert usage.ledger_complete and usage.cost_status_cny == "unknown"
    assert usage.calls[0].config_source is None
    assert "config_source" not in usage.calls[0].model_dump(mode="json")


def test_historic_call_serialization_is_unchanged():
    raw = {
        "call_id": "historic", "task_id": "task-1", "attempt": 1,
        "stage": "llm", "status": "completed", "cost_cny": "0.2",
        "reserved_cost_cny": "0.5", "cost_status": "estimated",
    }
    assert PracticeCallUsage.model_validate(raw).model_dump(mode="json") == raw


def spec():
    return PracticeSpec(
        space_id="space-1", scope_revision=1, objectives=["理解集合"],
        concept_ids=["concept-1"], question_types=["short_answer"],
        question_count=3, difficulty="mixed",
    )


@pytest.mark.parametrize("reranker", ["none", "llm", "bge-v2-m3"])
def test_personal_preview_never_estimates_personal_generation_or_grading(monkeypatch, reranker):
    ranking = (
        RerankerConfig(provider="llm", llm=LLMRerankerConfig(
            provider="deepseek", model="system-ranking", endpoint_hash="a" * 64,
        )) if reranker == "llm" else
        RerankerConfig(provider=reranker, model_revision="revision", license="test")
        if reranker != "none" else RerankerConfig()
    )
    config = PipelineConfig(reranker=ranking)
    settings = Settings(_env_file=None, rerank_call_cny=0.2)
    estimator = Mock(return_value=0.1)
    monkeypatch.setattr(previews.provider_meter, "estimate", estimator)
    result = previews.calculate_practice_cost(spec(), config, settings, config_source="user")
    chat_calls = [call for call in estimator.call_args_list if call.args[0] == "llm"]
    assert len(chat_calls) == int(reranker == "llm")
    if chat_calls:
        assert chat_calls[0].args[1:] == (12000, 512)
    assert result.config_source == "user"
    assert result.personal_model_cost_status == "not_applicable"
    assert result.system_cost_status == "estimated"
    assert result.cost_cny_upper == result.system_cost_cny_upper
    assert result.grading_llm_call_upper == 6
    assert result.generation_llm_call_upper == 4 + int(reranker == "llm")


def test_system_preview_keeps_model_and_infrastructure_estimates(monkeypatch):
    estimator = Mock(return_value=0.1)
    monkeypatch.setattr(previews.provider_meter, "estimate", estimator)
    result = previews.calculate_practice_cost(
        spec(), PipelineConfig(), Settings(_env_file=None), config_source="system"
    )
    assert [call.args[0] for call in estimator.call_args_list] == ["llm", "embedding"]
    assert result.config_source == "system" and result.personal_model_cost_status is None
    assert result.cost_cny_upper == Decimal("0.2")


def test_personal_preview_preserves_unknown_system_cost(monkeypatch):
    monkeypatch.setattr(previews.provider_meter, "estimate", Mock(return_value=None))
    result = previews.calculate_practice_cost(
        spec(), PipelineConfig(), Settings(_env_file=None), config_source="user"
    )
    assert result.personal_model_cost_status == "not_applicable"
    assert result.system_cost_status == "unknown"
    assert result.system_cost_cny_upper is result.cost_cny_upper is None


@pytest.fixture
def metered_teaching_call(monkeypatch):
    """Use the real meter/teaching limits with in-memory SQL and budget boundaries."""
    from types import SimpleNamespace

    from app.services import provider_meter

    settings = Settings(_env_file=None, llm_input_cny_per_million=2, llm_output_cny_per_million=4)
    writes, records = [], []
    job = {"task_id": "teaching-task", "user_id": 7, "attempt": 1, "mode": "production",
           "kind": "course_lesson", "request": {"source_policy": "topic"}, "scope": None}

    async def persist(sql, args, **kwargs):
        from app.core.values import load

        writes.append((sql, args))
        if sql.startswith("INSERT INTO provider_calls"):
            records.append(load(args[-1]))
        elif sql.startswith("UPDATE provider_calls"):
            records.append(load(args[0]))

    reserve, settle = AsyncMock(), AsyncMock()
    monkeypatch.setattr(provider_meter, "transaction", transaction)
    monkeypatch.setattr(provider_meter, "get_settings", lambda: settings)
    monkeypatch.setattr(provider_meter.job_service, "locked_job", AsyncMock(side_effect=lambda *_: dict(job)))
    monkeypatch.setattr(provider_meter, "fetch_all", AsyncMock(return_value=[]))
    monkeypatch.setattr(provider_meter, "fetch_one", AsyncMock(return_value=None))
    monkeypatch.setattr(provider_meter, "execute", persist)
    monkeypatch.setattr(provider_meter.budget_service, "reserve_budget", reserve)
    monkeypatch.setattr(provider_meter.budget_service, "settle_budget", settle)
    return SimpleNamespace(job=job, records=records, writes=writes, reserve=reserve, settle=settle,
                           settings=settings, meter=provider_meter)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["qa", "course_lesson"])
@pytest.mark.parametrize("outcome", ["success", "401", "timeout", "cancelled"])
async def test_personal_stream_keeps_na_usage_redaction_and_single_attempt(
    monkeypatch, metered_teaching_call, kind, outcome, caplog,
):
    import asyncio

    import httpx
    from langchain_core.messages import AIMessageChunk, HumanMessage

    from app.core.errors import AppError

    state = metered_teaching_call
    state.job["kind"] = kind
    estimate = Mock(side_effect=AssertionError("A personal stream has no platform price"))
    monkeypatch.setattr(state.meter, "estimate", estimate)
    secret = "private-stream-credential-1234"

    class Stream:
        model_name = "personal-stream"
        invocations = 0
        ainvoke = AsyncMock(side_effect=AssertionError("No stream-to-system/nonstream fallback"))

        async def astream(self, messages):
            self.invocations += 1
            yield AIMessageChunk(content="partial", usage_metadata={
                "input_tokens": 12, "output_tokens": 2, "total_tokens": 14,
            })
            if outcome == "401":
                response = httpx.Response(401, request=httpx.Request("POST", "https://provider.example/chat"),
                                          json={"error": {"message": "Invalid " + secret}})
                response.raise_for_status()
            if outcome == "timeout":
                raise httpx.ReadTimeout("transport " + secret)
            if outcome == "cancelled":
                raise asyncio.CancelledError()
            yield AIMessageChunk(content=" final", usage_metadata={
                "input_tokens": 12, "output_tokens": 5, "total_tokens": 17,
            })

    client, chunks = Stream(), []
    wrapper = state.meter.MeteredChat(client, purpose="qa_answer" if kind == "qa" else "course_lesson",
                                     output_upper=100, config_source="user", api_key=secret)
    with state.meter.execution(state.job):
        if outcome == "success":
            response = await wrapper.ainvoke_streamed([HumanMessage(content="synthetic")], on_chunk=chunks.append)
            assert response.content == "partial final"
        else:
            expected = asyncio.CancelledError if outcome == "cancelled" else AppError
            with pytest.raises(expected) as error:
                await wrapper.ainvoke_streamed([HumanMessage(content="synthetic")], on_chunk=chunks.append)
            if isinstance(error.value, AppError):
                assert error.value.code == "user_llm_failed"
                assert secret not in error.value.message
                assert error.value.__cause__ is None and error.value.__suppress_context__
    assert client.invocations == 1
    client.ainvoke.assert_not_awaited()
    estimate.assert_not_called()
    assert len(state.records) == 2
    for record in state.records:
        assert record["config_source"] == "user" and record["cost_status"] == "not_applicable"
        assert record["cost_cny"] is record["reserved_cost_cny"] is record["pricing_version"] is None
    final = state.records[-1]
    assert final["status"] == ("completed" if outcome == "success" else "unknown")
    assert final["latency_ms"] >= 0
    if outcome == "success":
        assert final["input_tokens"] == 12 and final["output_tokens"] == 5
        assert len(chunks) == 2  # cumulative counters are not doubled by chunk addition
    assert secret not in dump(state.records) + caplog.text
    assert [call.args[1] for call in state.reserve.await_args_list] == ["calls"]
    assert [call.args[1] for call in state.settle.await_args_list] == ["calls"]
    accounts = state.reserve.await_args.args[3]
    assert any(key.startswith("user_llm:user:7:") for key, _ in accounts)
    assert not any(":global:" in key for key, _ in accounts)


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["course_lesson", "course_teaching_review", "course_teaching_repair"])
async def test_personal_teaching_calls_keep_frozen_role_and_token_limits(metered_teaching_call, monkeypatch, purpose):
    from types import SimpleNamespace

    from app.core.errors import AppError
    from app.teaching.policy import freeze_teaching_policy

    state = metered_teaching_call
    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    state.job["request"].update(teaching_mode="guided", teaching_policy=policy.model_dump(mode="json"),
                                 teaching_policy_hash=policy.policy_hash)
    provider = AsyncMock(return_value=SimpleNamespace(usage_metadata={"input_tokens": 12, "output_tokens": 5}))
    with state.meter.execution(state.job):
        await state.meter.call_external("llm", provider, config_source="user", purpose=purpose,
                                       input_upper=100, output_upper=100)
        counts = dict(state.reserve.await_args.args[3])
        assert counts["job:teaching-task:llm"] == policy.max_llm_calls
        assert counts["job:teaching-task:" + purpose] == (2 if purpose == "course_teaching_review" else 1)
        with pytest.raises(AppError) as oversized:
            await state.meter.call_external("llm", provider, config_source="user", purpose=purpose,
                                           input_upper=16001, output_upper=100)
        assert oversized.value.code == "course_scope_too_large"
        monkeypatch.setattr(state.meter, "fetch_all", AsyncMock(return_value=[
            {"status": "unknown", "stage": "llm", "usage_json": dump(state.records[-1])},
        ]))
        with pytest.raises(AppError) as replay:
            await state.meter.call_external("llm", provider, config_source="user", purpose=purpose)
        assert replay.value.code == "teaching_call_outcome_unknown"
    provider.assert_awaited_once()
    assert state.records[-1]["config_source"] == "user"
    assert state.records[-1]["cost_status"] == "not_applicable"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,purpose,kind", [
    ("llm", "course_teaching_review", "course_lesson"),
    ("llm", "course_application_generate", "course_application_generate"),
    ("llm", "course_application_feedback", "course_application_feedback"),
    ("llm", "reranker", "qa"), ("embedding", None, "qa"),
])
async def test_system_teaching_and_retrieval_keep_money_accounts(
    metered_teaching_call, monkeypatch, stage, purpose, kind,
):
    from types import SimpleNamespace

    from app.services import course_application_service
    from app.teaching.policy import freeze_teaching_policy

    state = metered_teaching_call
    state.job["kind"] = kind
    state.job["request"].update(course_assessment_id="assessment-1", attempt_id="attempt-1")
    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    state.job["request"].update(teaching_mode="guided", teaching_policy=policy.model_dump(mode="json"),
                                 teaching_policy_hash=policy.policy_hash)
    monkeypatch.setattr(course_application_service, "authorize_application_job", AsyncMock())
    state.settings.embedding_cny_per_million = 2
    provider = AsyncMock(return_value=SimpleNamespace(usage_metadata={"input_tokens": 12, "output_tokens": 5}))
    with state.meter.execution(state.job):
        await state.meter.call_external(stage, provider, purpose=purpose, config_source="system",
                                       input_upper=100, output_upper=100)
    final = state.records[-1]
    assert final["config_source"] == "system" and final["cost_status"] == "estimated"
    assert final["cost_cny"] > 0 and final["reserved_cost_cny"] > 0
    assert final["pricing_version"] == state.settings.pricing_version
    assert [call.args[1] for call in state.reserve.await_args_list] == ["calls", "cny"]
    assert [call.args[1] for call in state.settle.await_args_list] == ["calls", "cny"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["course_application_generate", "course_application_feedback"])
async def test_personal_application_meter_authorizes_and_tracks_business_identity(metered_teaching_call, monkeypatch, kind):
    from types import SimpleNamespace

    from app.services import course_application_service

    state = metered_teaching_call
    state.job["kind"] = kind
    state.job["request"].update(course_assessment_id="assessment-1", attempt_id="attempt-1")
    authorize = AsyncMock()
    monkeypatch.setattr(course_application_service, "authorize_application_job", authorize)
    provider = AsyncMock(return_value=SimpleNamespace(usage_metadata={"input_tokens": 12, "output_tokens": 5}))
    with state.meter.execution(state.job):
        await state.meter.call_external("llm", provider, config_source="user", purpose=kind,
                                       input_upper=100, output_upper=100)
    authorize.assert_awaited_once()
    assert authorize.await_args.args == (7, state.job)
    final = state.records[-1]
    assert final["logical_request_id"] == ("attempt-1" if kind.endswith("feedback") else "assessment-1")
    assert final["cost_status"] == "not_applicable" and final["config_source"] == "user"
    assert [call.args[1] for call in state.reserve.await_args_list] == ["calls"]
