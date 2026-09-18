"""Actual SQL meters for personal calls, failures, mixed infrastructure and caps."""

import asyncio
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.core.db import fetch_all, fetch_one
from app.core.errors import AppError
from app.core.values import load
from app.services import job_service, provider_meter
from app.workers.practice_job import load_practice_usage


async def personal_job(learner):
    from app.core.config import get_settings

    get_settings().practice_enabled = True
    _, session = learner
    owner = session["user"]["id"]
    logical_id = "practice-" + uuid.uuid4().hex
    job = await job_service.enqueue_job(
        owner, "practice_generate",
        {"practice_id": logical_id, "generation_request_id": logical_id,
         "spec": {"question_types": ["cloze"]}},
        uuid.uuid4().hex,
    )
    job = await job_service.claim_job("personal-meter-test", task_id=job["task_id"])
    return job, owner, logical_id


async def successful_provider():
    return SimpleNamespace(usage_metadata={"input_tokens": 12, "output_tokens": 5})


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "401", "429", "timeout", "cancelled"])
async def test_personal_meter_never_prices_or_reserves_money(
    learner, platform_settings, monkeypatch, outcome
):
    job, owner, logical_id = await personal_job(learner)
    estimator = Mock(side_effect=AssertionError("Personal calls must never be priced"))
    monkeypatch.setattr(provider_meter, "estimate", estimator)
    secret = "sk-synthetic-personal-private-1234"

    async def provider():
        if outcome == "success":
            return await successful_provider()
        if outcome in {"401", "429"}:
            response = httpx.Response(
                int(outcome), request=httpx.Request("POST", "https://example.test/v1/chat"),
                json={"error": {"message": f"Invalid {secret}"}},
            )
            response.raise_for_status()
        if outcome == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        raise asyncio.CancelledError()

    with provider_meter.execution(job):
        if outcome == "success":
            await provider_meter.call_external(
                "llm", provider, config_source="user", api_key=secret,
                purpose="practice_generation", model="personal-test", input_upper=100, output_upper=100,
            )
        else:
            expected = asyncio.CancelledError if outcome == "cancelled" else AppError
            with pytest.raises(expected) as error:
                await provider_meter.call_external(
                    "llm", provider, config_source="user", api_key=secret,
                    purpose="practice_generation", model="personal-test", input_upper=100, output_upper=100,
                )
            if isinstance(error.value, AppError):
                assert error.value.code == "user_llm_failed"
                assert secret not in error.value.message
    estimator.assert_not_called()
    row = await fetch_one(
        "SELECT call_id,usage_json FROM provider_calls WHERE operation_id=%s", (job["task_id"],)
    )
    record = load(row["usage_json"])
    assert record["config_source"] == "user" and record["cost_status"] == "not_applicable"
    assert record["cost_cny"] is record["reserved_cost_cny"] is record["pricing_version"] is None
    assert secret not in row["usage_json"]
    reservations = await fetch_all(
        "SELECT resource_type,status,actual FROM budget_reservations WHERE operation_id=%s",
        (row["call_id"],),
    )
    assert reservations == [{"resource_type": "calls", "status": "settled", "actual": Decimal("1")}]
    usage = await load_practice_usage(owner, "production", logical_id)
    assert usage.ledger_complete and usage.llm_calls == 1
    assert usage.cost_status_cny == "not_applicable"
    assert usage.cost_cny is usage.reserved_cost_cny is None


@pytest.mark.asyncio
async def test_mixed_personal_generation_and_system_retrieval_accounts_only_system_money(
    learner, platform_settings
):
    job, owner, logical_id = await personal_job(learner)
    platform_settings.embedding_cny_per_million = 2
    platform_settings.llm_input_cny_per_million = 100
    platform_settings.llm_output_cny_per_million = 100
    with provider_meter.execution(job):
        await provider_meter.call_external(
            "llm", successful_provider, config_source="user", purpose="practice_generation",
            model="personal-test", input_upper=100, output_upper=100,
        )
        await provider_meter.call_external("embedding", successful_provider, input_upper=100)
    usage = await load_practice_usage(owner, "production", logical_id)
    assert usage.ledger_complete and usage.cost_status_cny == "estimated"
    assert usage.cost_cny == Decimal("0.000024")
    assert usage.reserved_cost_cny == 0
    assert usage.llm_calls == usage.embedding_calls == 1
    assert {call.config_source for call in usage.calls} == {"user", "system"}


@pytest.mark.asyncio
async def test_personal_calls_still_enforce_daily_technical_limits(learner, platform_settings):
    job, _, _ = await personal_job(learner)
    platform_settings.user_daily_llm_calls = 1
    provider = AsyncMock(side_effect=successful_provider)
    with provider_meter.execution(job):
        await provider_meter.call_external(
            "llm", provider, config_source="user", purpose="practice_generation", model="personal-test"
        )
        with pytest.raises(AppError) as error:
            await provider_meter.call_external(
                "llm", provider, config_source="user", purpose="practice_generation", model="personal-test"
            )
    assert error.value.status == 429
    assert provider.await_count == 1
