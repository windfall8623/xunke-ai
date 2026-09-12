"""Provider selection and native Claude output contracts, without paid calls."""

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from app.core.config import Settings
from app.llm import langchain_factory


def claude_settings(**overrides):
    values = {
        "llm_provider": "anthropic",
        "anthropic_api_key": "test-anthropic-key",
        "anthropic_model": "claude-sonnet-4-6",
        "anthropic_base_url": "https://api.anthropic.com",
        "deepseek_api_key": "test-unused-deepseek-key",
    }
    return Settings(_env_file=None, **(values | overrides))


def test_cached_factory_selects_native_claude_instead_of_legacy_deepseek(monkeypatch):
    monkeypatch.setattr(langchain_factory, "get_settings", claude_settings)
    langchain_factory.get_chat_model.cache_clear()
    try:
        model = langchain_factory.get_chat_model()
        assert type(model).__name__ == "ChatAnthropic"
        assert model.max_retries == 0
    finally:
        langchain_factory.get_chat_model.cache_clear()


def test_unknown_provider_is_rejected_instead_of_silently_using_deepseek():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider="anthorpic")


def test_selected_provider_does_not_borrow_another_providers_key():
    from app.llm.configuration import resolve_llm_config

    config = resolve_llm_config(claude_settings(anthropic_api_key=""))
    assert not config.configured
    with pytest.raises(ValueError, match="configured"):
        langchain_factory.create_chat_model(claude_settings(anthropic_api_key=""))


@pytest.mark.parametrize("missing", ["llm_api_key", "llm_base_url", "llm_model"])
def test_compatible_gateway_requires_its_own_complete_configuration(missing):
    from app.llm.configuration import resolve_llm_config

    values = dict(
        llm_provider="openai_compatible",
        llm_api_key="test-gateway-key",
        llm_base_url="https://gateway.invalid/v1",
        llm_model="gateway-claude",
    )
    values[missing] = ""
    config = resolve_llm_config(claude_settings(**values))
    assert not config.configured


@pytest.mark.parametrize(
    "endpoint",
    [
        "api.anthropic.com",
        "https://key:secret@api.anthropic.com",
        "https://api.anthropic.com/v1/messages",
    ],
)
def test_native_base_url_rejects_ambiguous_or_credential_bearing_addresses(endpoint):
    from app.llm.configuration import resolve_llm_config

    with pytest.raises(ValueError):
        resolve_llm_config(claude_settings(anthropic_base_url=endpoint))


def test_provider_identity_does_not_expose_credentials_in_repr():
    from app.llm.configuration import resolve_llm_config

    assert "test-anthropic-key" not in repr(resolve_llm_config(claude_settings()))


@pytest.mark.asyncio
async def test_generator_reads_native_text_blocks_without_thinking_content():
    from app.rag.providers.generator import LangChainQuizGenerator

    class Model:
        max_retries = 0

        async def ainvoke(self, messages):
            return AIMessage(
                content=[
                    {"type": "thinking", "thinking": "not part of the JSON"},
                    {"type": "text", "text": '{"questions":'},
                    {"type": "text", "text": "[]}"},
                ],
                usage_metadata={
                    "input_tokens": 101,
                    "output_tokens": 29,
                    "total_tokens": 130,
                },
                response_metadata={"stop_reason": "end_turn"},
            )

    payload, usage = await LangChainQuizGenerator(Model())._invoke(
        [HumanMessage(content="Return JSON")]
    )
    assert payload == {"questions": []}
    assert usage.input_tokens == 101
    assert usage.output_tokens == 29
    assert usage.token_count_method == "provider-reported"


@pytest.mark.asyncio
async def test_report_reads_claude_text_blocks():
    from app.workers.providers import ConfiguredReportGenerator

    payload = {
        "mastered_points": ["向量检索"],
        "weak_points": [],
        "three_line_summary": ["理解问题", "找到证据", "验证答案"],
        "advice": ["继续练习"],
        "share_quote": "学习有据可循。",
    }

    class Model:
        async def ainvoke(self, messages):
            return SimpleNamespace(
                content=[{"type": "text", "text": json.dumps(payload)}],
                response_metadata={"stop_reason": "end_turn"},
            )

    report = await ConfiguredReportGenerator(Model())(
        topic="RAG", questions=[], answer_records=[], score_summary={}
    )
    assert report.three_line_summary == payload["three_line_summary"]
    assert report.share_quote == payload["share_quote"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal", "tool_use"])
async def test_generator_rejects_incomplete_or_nonfinal_claude_responses(stop_reason):
    from app.rag.errors import GenerationValidationFailed
    from app.rag.providers.generator import LangChainQuizGenerator

    class Model:
        max_retries = 0

        async def ainvoke(self, messages):
            return AIMessage(
                content='{"questions": []}',
                response_metadata={"stop_reason": stop_reason},
            )

    with pytest.raises(GenerationValidationFailed):
        await LangChainQuizGenerator(Model())._invoke([HumanMessage(content="quiz")])
