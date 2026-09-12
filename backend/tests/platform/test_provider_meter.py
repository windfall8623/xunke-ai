import uuid
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_failed_external_call_retains_cost_reservation_and_attempt_count(
    learner, platform_settings
):
    _, session = learner
    from app.core.db import fetch_one
    from app.services import job_service, provider_meter

    job = await job_service.enqueue_job(
        session["user"]["id"],
        "quiz",
        {"user_input": "meter", "question_count": 3},
        uuid.uuid4().hex,
    )
    job = await job_service.claim_job("meter-test", task_id=job["task_id"])
    platform_settings.llm_input_cny_per_million = 1
    platform_settings.llm_output_cny_per_million = 1

    async def failed():
        raise TimeoutError("provider outcome unknown")

    with provider_meter.execution(job):
        with pytest.raises(TimeoutError):
            await provider_meter.call_external(
                "llm", failed, input_upper=100, output_upper=100
            )
    row = await fetch_one(
        "SELECT call_id,status,usage_json FROM provider_calls WHERE operation_id=%s",
        (job["task_id"],),
    )
    assert row["status"] == "unknown"
    row = await fetch_one(
        "SELECT status FROM budget_reservations WHERE operation_id=%s AND resource_type='cny'",
        (row["call_id"],),
    )
    assert row["status"] == "unknown"


@pytest.mark.asyncio
async def test_evaluation_ingest_has_its_own_cost_budget_without_a_run(
    learner, platform_settings
):
    import httpx

    from app.core.db import execute, fetch_one
    from app.services import job_service, provider_meter

    api, session = learner
    await execute(
        "UPDATE users SET role='evaluator' WHERE id=%s", (session["user"]["id"],)
    )
    uploaded = await api.post(
        "/api/v1/eval/documents",
        files={"file": ("sample.txt", b"public synthetic source", "text/plain")},
    )
    assert uploaded.status_code == 202
    job = await job_service.claim_job(
        "test-ingest-meter", task_id=uploaded.json()["data"]["task_id"]
    )
    platform_settings.embedding_cny_per_million = 1

    async def provider():
        return httpx.Response(
            200,
            json={"usage": {"total_tokens": 10}},
            request=httpx.Request("POST", "https://fixture.invalid/embeddings"),
        )

    with provider_meter.execution(job):
        await provider_meter.call_external("embedding", provider, input_upper=100)
    journal = await fetch_one(
        "SELECT status FROM provider_calls WHERE operation_id=%s", (job["task_id"],)
    )
    assert journal["status"] == "completed"
    budget = await fetch_one(
        "SELECT used,reserved FROM budget_accounts WHERE account_key LIKE %s AND resource_type='cny'",
        (f"evaluation_ingest:user:{session['user']['id']}:%",),
    )
    assert float(budget["used"]) == 0.00001 and budget["reserved"] == 0


async def completed_llm_call(
    learner, settings, usage, *, response_metadata=None, prices=None
):
    from app.core.db import fetch_one
    from app.core.values import load
    from app.services import job_service, provider_meter

    _, session = learner
    settings.llm_input_cny_per_million = 2
    settings.llm_output_cny_per_million = 4
    for name, price in (prices or {}).items():
        setattr(settings, name, price)
    job = await job_service.enqueue_job(
        session["user"]["id"],
        "quiz",
        {"user_input": "usage accounting", "question_count": 3},
        uuid.uuid4().hex,
    )
    job = await job_service.claim_job("usage-test", task_id=job["task_id"])
    response = SimpleNamespace(
        usage_metadata=usage, response_metadata=response_metadata
    )

    async def provider():
        return response

    with provider_meter.execution(job):
        assert (
            await provider_meter.call_external(
                "llm", provider, input_upper=100, output_upper=100
            )
            is response
        )
    row = await fetch_one(
        "SELECT call_id,usage_json FROM provider_calls WHERE operation_id=%s",
        (job["task_id"],),
    )
    reservation = await fetch_one(
        "SELECT status,reserved FROM budget_reservations WHERE operation_id=%s AND resource_type='cny'",
        (row["call_id"],),
    )
    return load(row["usage_json"]), reservation


@pytest.mark.asyncio
async def test_claude_cache_read_and_write_settle_confirmed_cny_prices(
    learner, platform_settings
):
    record, reservation = await completed_llm_call(
        learner,
        platform_settings,
        {"input_tokens": 40, "output_tokens": 5, "total_tokens": 45},
        response_metadata={
            "usage": {
                "input_tokens": 20,
                "output_tokens": 5,
                "cache_read_input_tokens": 8,
                "cache_creation_input_tokens": 12,
            },
            "model": "claude-provider-alias",
        },
        prices={
            "llm_input_cny_per_million": 35,
            "llm_output_cny_per_million": 175,
            "llm_cache_read_cny_per_million": 3.5,
            "llm_cache_write_cny_per_million": 3.5,
        },
    )
    assert record["input_tokens"] == 40
    assert record["input_token_details"] == {"cache_read": 8, "cache_creation": 12}
    assert record["cost_cny"] == pytest.approx(0.001645)
    assert reservation["status"] == "settled"


@pytest.mark.asyncio
async def test_deepseek_raw_cache_usage_cannot_be_lost_by_sdk_normalization(
    learner, platform_settings
):
    record, reservation = await completed_llm_call(
        learner,
        platform_settings,
        {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        response_metadata={
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_cache_hit_tokens": 80,
                "prompt_cache_miss_tokens": 20,
            }
        },
    )
    assert record["input_token_details"]["cache_read"] == 80
    assert record["cost_cny"] is None
    assert reservation["status"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,missing",
    [
        ({"prompt_tokens": 12}, "output_tokens"),
        ({"completion_tokens": 5}, "input_tokens"),
        ({"prompt_tokens": True, "completion_tokens": 5}, "input_tokens"),
    ],
)
async def test_compatible_raw_usage_must_include_real_input_and_output_counts(
    learner, platform_settings, raw, missing
):
    record, reservation = await completed_llm_call(
        learner,
        platform_settings,
        {"input_tokens": 12, "output_tokens": 0},
        response_metadata={"token_usage": raw},
    )
    assert record[missing] is None
    assert record["cost_cny"] is None
    assert reservation["status"] == "unknown"


@pytest.mark.asyncio
async def test_conflicting_deepseek_cache_hit_and_miss_is_unknown(
    learner, platform_settings
):
    record, reservation = await completed_llm_call(
        learner,
        platform_settings,
        {"input_tokens": 100, "output_tokens": 20},
        response_metadata={
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_cache_hit_tokens": 80,
                "prompt_cache_miss_tokens": 30,
            }
        },
    )
    assert record["cost_cny"] is None
    assert reservation["status"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("include_details", [False, True])
@pytest.mark.parametrize("native_metadata", [False, True])
async def test_uncached_llm_usage_settles_configured_price(
    learner, platform_settings, include_details, native_metadata
):
    usage = {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17}
    if include_details:
        usage["input_token_details"] = {"cache_read": 0, "cache_creation": 0}
    record, reservation = await completed_llm_call(
        learner,
        platform_settings,
        usage,
        response_metadata={"usage": {"input_tokens": 12, "output_tokens": 5}}
        if native_metadata
        else None,
    )
    assert record["input_tokens"] == 12
    assert record["output_tokens"] == 5
    assert record["cost_cny"] == pytest.approx(0.000044)
    assert record["cost_status"] == "estimated"
    assert reservation["status"] == "settled"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "details",
    [
        {"cache_read": 8, "cache_creation": 0},
        {"cache_read": 0, "cache_creation": 3},
        {"cache_read": 8, "cache_creation": 3},
        {
            "cache_read": 8,
            "cache_creation": 3,
            "ephemeral_5m_input_tokens": 1,
            "ephemeral_1h_input_tokens": 2,
        },
    ],
)
async def test_cached_llm_usage_is_retained_without_inventing_cache_prices(
    learner, platform_settings, details
):
    record, reservation = await completed_llm_call(
        learner,
        platform_settings,
        {
            "input_tokens": 12,
            "output_tokens": 5,
            "total_tokens": 17,
            "input_token_details": details,
        },
    )
    assert record["input_tokens"] == 12  # LangChain already includes cached tokens.
    assert record["input_token_details"] == details
    assert record["cost_cny"] is None
    assert record["cost_status"] == "unknown"
    assert reservation["status"] == "unknown"
    assert float(reservation["reserved"]) == pytest.approx(0.0006)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": -1, "output_tokens": 5},
        {"input_tokens": True, "output_tokens": 5},
        {"input_tokens": 12.5, "output_tokens": 5},
        {"input_tokens": "12", "output_tokens": 5},
        {"input_tokens": 12, "output_tokens": -1},
        {"input_tokens": 12, "output_tokens": None},
        {
            "input_tokens": 12,
            "output_tokens": 5,
            "input_token_details": {"cache_read": -1},
        },
        {
            "input_tokens": 12,
            "output_tokens": 5,
            "input_token_details": {"cache_creation": True},
        },
        {
            "input_tokens": 12,
            "output_tokens": 5,
            "input_token_details": {"cache_creation": 13},
        },
        {
            "input_tokens": 12,
            "output_tokens": 5,
            "input_token_details": ["invalid"],
        },
    ],
)
async def test_invalid_llm_usage_never_settles_a_known_cost(
    learner, platform_settings, usage
):
    record, reservation = await completed_llm_call(learner, platform_settings, usage)
    assert record["cost_cny"] is None
    assert record["cost_status"] == "unknown"
    assert reservation["status"] == "unknown"
    assert float(reservation["reserved"]) == pytest.approx(0.0006)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,normalized,missing",
    [
        (
            {"input_tokens": 12},
            {"input_tokens": 12, "output_tokens": 0},
            "output_tokens",
        ),
        (
            {"output_tokens": 5},
            {"input_tokens": 0, "output_tokens": 5},
            "input_tokens",
        ),
        (
            {"input_tokens": True, "output_tokens": 5},
            {"input_tokens": 1, "output_tokens": 5},
            "input_tokens",
        ),
    ],
)
async def test_incomplete_native_usage_does_not_bill_sdk_default_zero(
    learner, platform_settings, raw, normalized, missing
):
    record, reservation = await completed_llm_call(
        learner,
        platform_settings,
        normalized,
        response_metadata={"usage": raw, "model": "claude-fixture-v1"},
    )
    assert record[missing] is None
    assert record["cost_cny"] is None
    assert record["cost_status"] == "unknown"
    assert reservation["status"] == "unknown"


@pytest.mark.asyncio
async def test_metered_anthropic_tool_messages_keep_identity_and_count_block_content(
    monkeypatch,
):
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from app.services import provider_meter

    response = SimpleNamespace(content="fixture")

    class Chat:
        model = "claude-fixture-v1"

        def bind_tools(self, tools, **kwargs):
            return SimpleNamespace(bound=self, ainvoke=self.ainvoke)

        async def ainvoke(self, messages):
            return response

    upper = {}

    async def measured(stage, call, **bounds):
        upper.update(bounds)
        return await call()

    monkeypatch.setattr(provider_meter, "call_external", measured)
    chat = provider_meter.MeteredChat(Chat()).bind_tools([])
    assert chat.model_name == "claude-fixture-v1"
    messages = [
        HumanMessage(content=[{"type": "text", "text": "资料"}]),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "tool-1", "name": "search", "args": {"query": "x" * 300}}
            ],
        ),
        ToolMessage(content=[{"type": "text", "text": "证据"}], tool_call_id="tool-1"),
    ]
    assert await chat.ainvoke(messages) is response
    assert upper["input_upper"] >= 312
    assert upper["output_upper"] == 4096
