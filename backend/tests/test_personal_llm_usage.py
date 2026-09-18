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
