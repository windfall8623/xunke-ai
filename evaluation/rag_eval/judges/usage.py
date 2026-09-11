"""Price observed native/compatible counters without inventing missing usage."""

from __future__ import annotations


def _mapping(value):
    if isinstance(value, dict):
        return value
    if callable(getattr(value, "model_dump", None)):
        return value.model_dump(exclude_unset=True, warnings=False)
    return vars(value) if hasattr(value, "__dict__") else {}


def _counter(value):
    return value if type(value) is int and value >= 0 else None


def _cache_count(sources):
    observed = [_counter(raw[name]) for raw, name in sources if name in raw]
    if not observed:
        return 0, False, True
    valid = all(value is not None and value == observed[0] for value in observed)
    return observed[0] if valid else None, True, valid


def observed_usage(result, provider, price, *, input_limit, output_limit, ceiling):
    raw = _mapping(getattr(result, "usage", None))
    native = provider == "anthropic"
    input_count = _counter(raw.get("input_tokens" if native else "prompt_tokens"))
    output = _counter(raw.get("output_tokens" if native else "completion_tokens"))
    prompt_details = _mapping(raw.get("prompt_tokens_details"))
    input_details = _mapping(raw.get("input_token_details"))
    read_sources = [(raw, "cache_read_input_tokens")]
    write_sources = [(raw, "cache_creation_input_tokens")]
    if not native:
        read_sources.extend(
            [
                (raw, "prompt_cache_hit_tokens"),
                (prompt_details, "cached_tokens"),
                (input_details, "cache_read"),
            ]
        )
        write_sources.append((input_details, "cache_creation"))
    read, has_read, valid_read = _cache_count(read_sources)
    write, has_write, valid_write = _cache_count(write_sources)
    details = {}
    if has_read:
        details["cache_read"] = read
    if has_write:
        details["cache_creation"] = write
    valid = (
        input_count is not None and output is not None and valid_read and valid_write
    )
    for name in ("prompt_tokens_details", "input_token_details", "cache_creation"):
        if raw.get(name) is not None and not isinstance(raw[name], dict):
            valid = False
    creation = _mapping(raw.get("cache_creation"))
    ttl_counts = []
    for name in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"):
        if name in creation:
            value = _counter(creation[name])
            details[name] = value
            if value is None:
                valid = False
            else:
                ttl_counts.append(value)
    if ttl_counts and (write is None or sum(ttl_counts) > write):
        valid = False
    if native:
        total_input = (
            input_count + read + write
            if input_count is not None and valid_read and valid_write
            else None
        )
        uncached = input_count
    else:
        total_input = input_count
        uncached = (
            input_count - read - write
            if input_count is not None and valid_read and valid_write
            else None
        )
        if uncached is None or uncached < 0:
            valid = False
        if "prompt_cache_miss_tokens" in raw:
            valid = valid and _counter(raw["prompt_cache_miss_tokens"]) == uncached
    if "total_tokens" in raw:
        total = _counter(raw["total_tokens"])
        valid = valid and total is not None and total == total_input + output
    if total_input is not None and total_input > input_limit:
        valid = False
    if output is not None and output > output_limit:
        valid = False
    cost = None
    if valid:
        portions = [
            (uncached, price["input_cny_per_million"]),
            (output, price["output_cny_per_million"]),
            (read, price.get("cache_read_cny_per_million")),
            (write, price.get("cache_write_cny_per_million")),
        ]
        if all(amount == 0 or rate is not None for amount, rate in portions):
            calculated = (
                sum(amount * rate for amount, rate in portions if amount) / 1_000_000
            )
            if calculated <= ceiling + 1e-12:
                cost = calculated
    return {
        "input_tokens": total_input,
        "output_tokens": output,
        "input_token_details": details,
        "usage_status": "provider_reported" if valid else "unknown",
        "cost_cny": cost,
        "cost_status": "estimated" if cost is not None else "unknown",
    }
