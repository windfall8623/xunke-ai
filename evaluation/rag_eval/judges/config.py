"""Non-secret, frozen external-judge configuration; safe to import in the API."""

from __future__ import annotations

import copy
import ipaddress
import math
import re
from datetime import date, datetime
from urllib.parse import urlsplit

ALLOWED_FIELDS = {
    "enabled",
    "provider",
    "model",
    "base_url",
    "api_key_env",
    "ragas_version",
    "prompt_version",
    "prompt_hash",
    "max_llm_calls",
    "max_cost_cny",
    "call_cost_ceiling_cny",
    "max_input_tokens",
    "max_output_tokens",
    "timeout_seconds",
    "total_timeout_seconds",
    "price_table",
    "calibrated",
    "calibration_record",
}


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_price_table(price):
    required = {"effective_date", "input_cny_per_million", "output_cny_per_million"}
    optional = {"cache_read_cny_per_million", "cache_write_cny_per_million"}
    if (
        not isinstance(price, dict)
        or not required <= set(price)
        or set(price) - required - optional
    ):
        raise ValueError("judge needs a dated CNY input/output price table")
    try:
        date.fromisoformat(price["effective_date"])
    except (TypeError, ValueError):
        raise ValueError("judge pricing date must be YYYY-MM-DD") from None
    for name in required - {"effective_date"} | (optional & set(price)):
        if name in optional and price[name] is None:
            continue
        if (
            type(price[name]) not in (int, float)
            or not math.isfinite(price[name])
            or price[name] < 0
        ):
            raise ValueError(
                "judge prices must be finite nonnegative CNY per million tokens"
            )
    return price


def minimum_call_reservation(max_input, max_output, price):
    input_rate = max(
        price["input_cny_per_million"],
        price.get("cache_read_cny_per_million") or 0,
        price.get("cache_write_cny_per_million") or 0,
    )
    return (
        max_input * input_rate + max_output * price["output_cny_per_million"]
    ) / 1_000_000


def validate_judge_config(raw: dict) -> dict:
    if not isinstance(raw, dict) or set(raw) - ALLOWED_FIELDS:
        raise ValueError(
            "judge config has unknown fields; credentials must stay in the worker environment"
        )
    config = copy.deepcopy(raw)
    provider = config.get("provider", "openai_compatible")
    if provider not in {"openai_compatible", "anthropic"}:
        raise ValueError("judge provider must be openai_compatible or anthropic")
    if config.get("enabled") is not True or config.get("ragas_version") != "0.4.3":
        raise ValueError(
            "judge must be enabled and use the supported pinned Ragas version"
        )
    if any(
        not isinstance(config.get(field), str) or not config[field].strip()
        for field in ("model", "prompt_version")
    ) or not _hash(config.get("prompt_hash")):
        raise ValueError(
            "judge model, prompt version and actual prompt hash must be fixed"
        )
    parsed = urlsplit(config.get("base_url", ""))
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "judge base_url must be explicit and contain no credentials or query"
        )
    if parsed.scheme == "http":
        try:
            local = (
                parsed.hostname == "localhost"
                or ipaddress.ip_address(parsed.hostname).is_loopback
            )
        except ValueError:
            local = False
        if not local:
            raise ValueError("remote judge endpoint must use HTTPS")
    if provider == "anthropic":
        endpoint = config["base_url"].strip().rstrip("/")
        path = parsed.path.rstrip("/")
        if path.endswith("/messages"):
            raise ValueError("native judge base_url must be an API root, not /messages")
        if path.endswith("/v1"):
            endpoint = endpoint[:-3]
        config["base_url"] = endpoint
    env_name = config.setdefault("api_key_env", "EVAL_JUDGE_API_KEY")
    if not isinstance(env_name, str) or not re.fullmatch(
        r"EVAL_JUDGE_(?:[A-Z0-9_]+_)?API_KEY", env_name
    ):
        raise ValueError(
            "judge credentials require a dedicated EVAL_JUDGE_*API_KEY variable"
        )
    limits = {
        "max_llm_calls": 100,
        "max_input_tokens": 200000,
        "max_output_tokens": 16000,
        "timeout_seconds": 60,
        "total_timeout_seconds": 600,
        "max_cost_cny": 1000,
        "call_cost_ceiling_cny": 1000,
    }
    for name, maximum in limits.items():
        value = config.get(name)
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 < value <= maximum
        ):
            raise ValueError(f"judge config needs bounded {name}")
        if (
            name in ("max_llm_calls", "max_input_tokens", "max_output_tokens")
            and type(value) is not int
        ):
            raise ValueError(f"judge config requires an integer {name}")
    price = validate_price_table(config.get("price_table"))
    ceiling = minimum_call_reservation(
        config["max_input_tokens"], config["max_output_tokens"], price
    )
    if config["call_cost_ceiling_cny"] < ceiling:
        raise ValueError(
            "judge per-call reservation must cover both configured token limits"
        )
    if type(config.get("calibrated", False)) is not bool:
        raise ValueError("judge calibration status must be boolean")
    config.setdefault("calibrated", False)
    if config["calibrated"]:
        record = config.get("calibration_record", {})
        if (
            not isinstance(record, dict)
            or record.get("decision") != "approved"
            or not record.get("reviewer_id")
            or record.get("model") != config["model"]
            or record.get("prompt_hash") != config["prompt_hash"]
            or not all(
                _hash(record.get(field)) for field in ("dataset_hash", "report_hash")
            )
        ):
            raise ValueError(
                "calibrated judge requires a matching human-approved calibration record"
            )
        try:
            stamp = datetime.fromisoformat(record.get("reviewed_at", ""))
            if stamp.tzinfo is None:
                raise ValueError()
        except (AttributeError, ValueError):
            raise ValueError(
                "calibration approval requires a timestamp with timezone"
            ) from None
    return config
