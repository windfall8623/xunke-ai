"""Explicit metered chat adapter for short explanations, without hidden retries."""

import json
import re

from app.llm.responses import response_text
from app.practice.grade_contracts import ShortAnswerProposal
from app.practice.providers import (
    PracticeResponseBudgetExceeded,
    PracticeResponseInvalid,
    _distinct_object,
    _invalid_constant,
    _limited_chat,
    _reported_tokens,
)
from app.prompts.practice_grade_prompt import (
    GRADER_VERSION,
    PROMPT_HASH,
    PROMPT_VERSION,
    grade_messages,
    measure_grade_messages,
)
from app.rag.budget import count_tokens
from app.rag.contracts import GenerationResult, Usage, stable_hash
from app.rag.errors import BudgetExceeded


class LangChainShortAnswerProvider:
    def __init__(
        self,
        llm,
        *,
        output_token_limit=2048,
        model_context_window=32768,
        model_configuration=None,
        input_usd_per_million=None,
        output_usd_per_million=None,
    ):
        if type(output_token_limit) is not int or not 1 <= output_token_limit <= 12000:
            raise ValueError("Grading output limit must be bounded")
        if (
            type(model_context_window) is not int
            or model_context_window <= output_token_limit
        ):
            raise ValueError("Grading context must accommodate the full output reserve")
        self.llm = _limited_chat(llm, output_token_limit)
        self.output_token_limit = output_token_limit
        self.model_context_window = model_context_window
        self.model_configuration = {
            **(model_configuration or {}),
            "model": (model_configuration or {}).get(
                "model", getattr(llm, "model", getattr(llm, "model_name", "configured"))
            ),
            "output_token_limit": output_token_limit,
            "model_context_window": model_context_window,
            "max_retries": 0,
        }
        self.model_fingerprint = stable_hash(self.model_configuration)
        self.prompt_hash, self.prompt_version = PROMPT_HASH, PROMPT_VERSION
        self.grader_version = GRADER_VERSION
        self.input_usd_per_million = input_usd_per_million
        self.output_usd_per_million = output_usd_per_million

    def measure_input_tokens(self, stage, messages):
        return measure_grade_messages(stage, messages)

    def estimate_cost(self, stage, inputs, outputs):
        if self.input_usd_per_million is None or self.output_usd_per_million is None:
            return None
        return (
            inputs * self.input_usd_per_million + outputs * self.output_usd_per_million
        ) / 1_000_000

    async def grade(self, snapshot, *, attempt=1, feedback=None):
        messages = grade_messages(snapshot, attempt=attempt, feedback=feedback)
        inputs = self.measure_input_tokens("grade", messages)
        if inputs + self.output_token_limit > self.model_context_window:
            raise BudgetExceeded("Complete grading prompt exceeds the model context")
        response = await self.llm.ainvoke(messages)
        raw = getattr(response, "content", None)
        serialized = (
            raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
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
        metadata = getattr(response, "response_metadata", {})
        truncated = isinstance(metadata, dict) and (
            metadata.get("stop_reason") == "max_tokens"
            or metadata.get("finish_reason") == "length"
        )
        if (
            usage.input_tokens > inputs
            or usage.output_tokens > self.output_token_limit
            or count_tokens(serialized) > 128000
            or truncated
        ):
            raise PracticeResponseBudgetExceeded(usage)
        try:
            content = response_text(response).strip()
            fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            parsed = ShortAnswerProposal.model_validate(
                json.loads(
                    fenced[1] if fenced else content,
                    object_pairs_hook=_distinct_object,
                    parse_constant=_invalid_constant,
                )
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise PracticeResponseInvalid("grade", usage) from exc
        return GenerationResult(payload=parsed.model_dump(mode="json"), usage=usage)
