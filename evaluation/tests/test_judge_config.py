import copy

import pytest


def configuration():
    return {
        "enabled": True,
        "model": "fixture-model-v1",
        "base_url": "https://judge.example.test/v1",
        "ragas_version": "0.4.3",
        "prompt_version": "quiz-facts-v1",
        "prompt_hash": "a" * 64,
        "max_llm_calls": 20,
        "max_cost_cny": 1,
        "call_cost_ceiling_cny": 0.1,
        "max_input_tokens": 20000,
        "max_output_tokens": 512,
        "timeout_seconds": 30,
        "total_timeout_seconds": 300,
        "price_table": {
            "effective_date": "2026-09-07",
            "input_cny_per_million": 2,
            "output_cny_per_million": 4,
        },
        "calibrated": False,
    }


def test_external_profile_requires_pinned_endpoint_prompt_and_dated_prices():
    from rag_eval.judges.config import validate_judge_config

    base = configuration()
    assert validate_judge_config(base)["calibrated"] is False
    for field in ("base_url", "prompt_hash", "model"):
        invalid = {key: value for key, value in base.items() if key != field}
        with pytest.raises(ValueError):
            validate_judge_config(invalid)
    invalid = copy.deepcopy(base)
    invalid["price_table"]["effective_date"] = "unknown"
    with pytest.raises(ValueError):
        validate_judge_config(invalid)


@pytest.mark.parametrize(
    "changes",
    [
        {"api_key": "must-not-persist"},
        {"api_key_env": "JWT_SECRET"},
        {"base_url": "https://user:password@judge.example.test/v1"},
        {"base_url": "https://judge.example.test/v1?api_key=secret"},
        {"base_url": "http://judge.example.test/v1"},
        {"max_llm_calls": 2.5},
        {"calibrated": True},
    ],
)
def test_external_profile_rejects_secrets_unbounded_transport_and_unproven_calibration(
    changes,
):
    from rag_eval.judges.config import validate_judge_config

    with pytest.raises(ValueError):
        validate_judge_config({**configuration(), **changes})


@pytest.mark.parametrize("suffix", ["", "/", "/v1", "/v1/"])
def test_native_judge_profile_normalizes_api_root_and_keeps_separate_cache_rates(
    suffix,
):
    from rag_eval.judges.config import validate_judge_config

    raw = configuration()
    raw.update(
        provider="anthropic",
        model="claude-opus-5-max",
        base_url="https://www.sotamodel.net" + suffix,
        max_cost_cny=5,
        call_cost_ceiling_cny=1,
    )
    raw["price_table"].update(
        input_cny_per_million=35,
        output_cny_per_million=175,
        cache_read_cny_per_million=3.5,
        cache_write_cny_per_million=3.5,
    )
    result = validate_judge_config(raw)
    assert result["provider"] == "anthropic"
    assert result["base_url"] == "https://www.sotamodel.net"
    assert result["price_table"]["cache_read_cny_per_million"] == 3.5
    assert result["price_table"]["cache_write_cny_per_million"] == 3.5
    assert result["calibrated"] is False


def test_legacy_judge_profile_keeps_openai_compatible_default():
    from rag_eval.judges.config import validate_judge_config

    result = validate_judge_config(configuration())
    assert result.get("provider", "openai_compatible") == "openai_compatible"
    assert result["base_url"] == "https://judge.example.test/v1"


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "anthorpic"},
        {"provider": "anthropic", "base_url": "https://judge.example.test/v1/messages"},
        {"provider": "anthropic", "base_url": "https://judge.example.test/messages/"},
    ],
)
def test_judge_rejects_unknown_protocol_and_native_method_urls(changes):
    from rag_eval.judges.config import validate_judge_config

    with pytest.raises(ValueError):
        validate_judge_config({**configuration(), **changes})


@pytest.mark.parametrize("value", [-1, True, float("inf"), "3.5"])
def test_judge_rejects_invalid_cache_prices(value):
    from rag_eval.judges.config import validate_judge_config

    raw = configuration()
    raw["price_table"]["cache_read_cny_per_million"] = value
    with pytest.raises(ValueError):
        validate_judge_config(raw)


def test_judge_unknown_cache_prices_are_not_replaced_with_free_rates():
    from rag_eval.judges.config import validate_judge_config

    raw = configuration()
    raw["price_table"].update(
        cache_read_cny_per_million=None, cache_write_cny_per_million=None
    )
    result = validate_judge_config(raw)
    assert result["price_table"]["cache_read_cny_per_million"] is None
    assert result["price_table"]["cache_write_cny_per_million"] is None


def test_judge_reservation_covers_cache_writes_when_they_cost_more_than_normal_input():
    from rag_eval.judges.config import validate_judge_config

    raw = configuration()
    raw["price_table"]["cache_write_cny_per_million"] = 10
    with pytest.raises(ValueError, match="reservation"):
        validate_judge_config(raw)
