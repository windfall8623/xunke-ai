"""Explicit injected chats; no model selection, credentials, SQL or hidden retry."""

from __future__ import annotations

import json
import math
import re

from pydantic import ValidationError

from app.llm.responses import response_text
from app.practice.contracts import PracticePayload
from app.practice.validation import PracticeSemanticReply
from app.prompts.practice_prompt import (
    PROMPT_HASH,
    PROMPT_VERSION,
    measure_practice_messages,
    practice_messages,
)
from app.rag.budget import count_tokens
from app.rag.contracts import GenerationResult, Usage, stable_hash
from app.rag.errors import BudgetExceeded, GenerationValidationFailed


class PracticeResponseInvalid(GenerationValidationFailed):
    """A completed structured-text failure, retaining its output accounting."""

    def __init__(self, stage: str, usage: Usage):
        super().__init__("Practice provider returned invalid structured text")
        self.stage = stage
        self.usage = usage


class PracticeResponseBudgetExceeded(BudgetExceeded):
    """A completed over-limit response must still be counted by the caller."""

    def __init__(self, usage: Usage):
        super().__init__("Practice response exceeds its admitted token budget")
        self.usage = usage


def _distinct_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError("Nonfinite JSON number")


def _reported_tokens(response):
    """Prefer raw provider counters; absent/raw-null counters are not SDK zeroes."""
    metadata = getattr(response, "response_metadata", None)
    normalized = getattr(response, "usage_metadata", None)
    if isinstance(metadata, dict) and (
        "usage" in metadata or "token_usage" in metadata
    ):
        native = "usage" in metadata
        raw = metadata.get("usage" if native else "token_usage")
        if not isinstance(raw, dict):
            return None
        inputs = raw.get("input_tokens" if native else "prompt_tokens")
        outputs = raw.get("output_tokens" if native else "completion_tokens")
        if native:
            parts = [inputs] + [
                raw[key] if raw.get(key) is not None else 0
                for key in ("cache_read_input_tokens", "cache_creation_input_tokens")
            ]
            inputs = (
                sum(parts)
                if all(type(value) is int and value >= 0 for value in parts)
                else None
            )
        total = raw.get("total_tokens")
    elif isinstance(normalized, dict):
        inputs, outputs = (
            normalized.get("input_tokens"),
            normalized.get("output_tokens"),
        )
        total = normalized.get("total_tokens")
    else:
        return None
    if type(inputs) is not int or inputs < 0 or type(outputs) is not int or outputs < 0:
        return None
    if total is not None and (type(total) is not int or total != inputs + outputs):
        return None
    return inputs, outputs


def _limited_chat(client, limit):
    if client is None or not callable(getattr(client, "ainvoke", None)):
        raise ValueError("An explicit practice chat provider is required")
    current, seen, actual_limit = client, set(), None
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "max_retries", 0) != 0:
            raise ValueError("Practice chats must disable hidden retries")
        kwargs = getattr(current, "kwargs", {})
        if isinstance(kwargs, dict):
            if any(
                kwargs.get(key) for key in ("tools", "functions", "response_format")
            ):
                raise ValueError(
                    "Practice messages cannot carry unmeasured tools or schemas"
                )
            actual_limit = actual_limit or kwargs.get("max_tokens")
        actual_limit = actual_limit or getattr(current, "max_tokens", None)
        if getattr(current, "output_upper", limit) != limit:
            raise ValueError("The injected meter must reserve the same output limit")
        current = getattr(current, "bound", None) or getattr(current, "llm", None)
    if callable(getattr(client, "bind", None)):
        return client.bind(max_tokens=limit)
    # The owner runtime may inject an already-bounded MeteredChat without bind().
    if actual_limit != limit:
        raise ValueError("The injected chat must bind the configured max_tokens")
    return client


class LangChainPracticeProvider:
    def __init__(
        self,
        llm,
        *,
        semantic_llm=None,
        model_context_window=32768,
        output_token_limit=4096,
        model_configuration=None,
        input_usd_per_million=None,
        output_usd_per_million=None,
    ):
        if (
            type(model_context_window) is not int
            or model_context_window <= 0
            or type(output_token_limit) is not int
            or not 1 <= output_token_limit <= 12000
        ):
            raise ValueError(
                "Practice context/output limits must be positive and bounded"
            )
        for price in (input_usd_per_million, output_usd_per_million):
            if price is not None and (not math.isfinite(price) or price < 0):
                raise ValueError("Explicit token prices must be finite and nonnegative")
        semantic_llm = semantic_llm if semantic_llm is not None else llm
        self.llm = _limited_chat(llm, output_token_limit)
        self.semantic_llm = _limited_chat(semantic_llm, output_token_limit)
        self.model_context_window, self.output_token_limit = (
            model_context_window,
            output_token_limit,
        )
        self.input_usd_per_million = input_usd_per_million
        self.output_usd_per_million = output_usd_per_million
        supplied = model_configuration or {}
        self.model_configuration = {
            "provider": supplied.get("provider", "explicit-provider"),
            "model": supplied.get(
                "model", getattr(llm, "model_name", getattr(llm, "model", "configured"))
            ),
            "endpoint_hash": supplied.get("endpoint_hash"),
            "temperature": supplied.get("temperature"),
            "model_context_window": model_context_window,
            "output_token_limit": output_token_limit,
            "max_retries": 0,
            "stage_models": {
                name: getattr(
                    client, "model_name", getattr(client, "model", "configured")
                )
                for name, client in (("generate", llm), ("semantic", semantic_llm))
            },
        }
        self.model_fingerprint = stable_hash(self.model_configuration)
        self.prompt_version, self.prompt_hash = PROMPT_VERSION, PROMPT_HASH

    def measure_input_tokens(self, stage, messages) -> int:
        return measure_practice_messages(stage, messages)

    def estimate_cost(self, stage, input_tokens, output_reserve):
        if (
            self.input_usd_per_million is None
            or self.output_usd_per_million is None
            or self.model_configuration["stage_models"][stage]
            != self.model_configuration["stage_models"]["generate"]
        ):
            return None
        return (
            input_tokens * self.input_usd_per_million
            + output_reserve * self.output_usd_per_million
        ) / 1_000_000

    async def _invoke(self, stage, messages):
        inputs = self.measure_input_tokens(stage, messages)
        if inputs + self.output_token_limit > self.model_context_window:
            raise BudgetExceeded(
                "Complete practice prompt exceeds the model context window"
            )
        client = self.llm if stage == "generate" else self.semantic_llm
        response = await client.ainvoke(messages)
        raw_content = getattr(response, "content", None)
        serialized = (
            raw_content
            if isinstance(raw_content, str)
            else json.dumps(raw_content, ensure_ascii=False)
        )
        observed = _reported_tokens(response)
        usage = Usage(
            llm_calls=1,
            input_tokens=observed[0] if observed else inputs,
            output_tokens=observed[1] if observed else count_tokens(serialized),
            token_count_method="provider-reported"
            if observed
            else "utf8-upper-bound-v1",
        )
        metadata = getattr(response, "response_metadata", None)
        output_stopped = isinstance(metadata, dict) and (
            metadata.get("stop_reason") == "max_tokens"
            or metadata.get("finish_reason") == "length"
        )
        if (
            usage.input_tokens > inputs
            or usage.output_tokens > self.output_token_limit
            or count_tokens(serialized) > 128000
            or output_stopped
        ):
            raise PracticeResponseBudgetExceeded(usage)
        try:
            content = response_text(response).strip()
            fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            raw = json.loads(
                fenced[1] if fenced else content,
                object_pairs_hook=_distinct_object,
                parse_constant=_invalid_constant,
            )
            contract = PracticePayload if stage == "generate" else PracticeSemanticReply
            parsed = contract.model_validate(raw)
        except (ValueError, TypeError, AttributeError, ValidationError) as exc:
            raise PracticeResponseInvalid(stage, usage) from exc
        return GenerationResult(payload=parsed.model_dump(mode="json"), usage=usage)

    async def generate(self, spec, pack, *, attempt, feedback) -> GenerationResult:
        return await self._invoke(
            "generate",
            practice_messages(
                "generate", spec, pack, attempt=attempt, feedback=feedback
            ),
        )

    async def validate_semantics(self, payload, pack, spec) -> GenerationResult:
        return await self._invoke(
            "semantic", practice_messages("semantic", spec, pack, payload=payload)
        )
