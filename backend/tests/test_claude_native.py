"""Exercise the configured chat factory through real SDKs and loopback HTTP."""

from contextlib import asynccontextmanager

import anthropic
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.core.config import Settings
from app.llm.langchain_factory import ChatModelCloser, create_chat_model
from tests.helpers.provider_http import (
    ProviderHTTPServer,
    ProviderReply,
    anthropic_message,
)


@pytest.fixture(autouse=True)
def bypass_proxy_for_loopback_provider(monkeypatch):
    """Keep a developer's HTTP proxy out of the real local SDK boundary."""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def _settings(base_url: str, **overrides) -> Settings:
    """Keep every service credential explicit and never load a developer .env."""
    values = {
        "app_env": "test",
        "llm_provider": "anthropic",
        "anthropic_api_key": "test-native-key",
        "anthropic_base_url": base_url,
        "anthropic_model": "claude-local-test",
        "llm_api_key": "",
        "llm_base_url": "",
        "llm_model": "",
        "deepseek_api_key": "",
        "deepseek_base_url": "",
        "deepseek_model": "",
        "tavily_api_key": "",
        "enable_web_search": False,
        "dashscope_api_key": "",
        "dashscope_image_api_key": "",
        "reranker_api_key": "",
        "cos_secret_id": "",
        "cos_secret_key": "",
        "wechat_app_id": "",
        "wechat_app_secret": "",
        "eval_worker_token": "",
        "mysql_password": "",
        "mysql_database": "claude_protocol_test",
        "provider_timeout_seconds": 3,
    }
    return Settings(_env_file=None, **(values | overrides))


@asynccontextmanager
async def _chat_model(settings: Settings):
    model = create_chat_model(settings, temperature=0.25)
    try:
        yield model
    finally:
        await ChatModelCloser(model).aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("invoke_mode", ["sync", "async"])
@pytest.mark.parametrize("base_suffix", ["", "/", "/v1", "/v1/"])
async def test_native_messages_protocol_and_api_root_normalization(
    invoke_mode, base_suffix
):
    with ProviderHTTPServer(
        lambda _request: ProviderReply(anthropic_message("Native Claude response."))
    ) as server:
        messages = [
            SystemMessage(content="Use only the supplied evidence."),
            HumanMessage(content="Explain RAG."),
        ]
        async with _chat_model(_settings(server.base_url + base_suffix)) as model:
            if invoke_mode == "sync":
                response = model.invoke(messages)
            else:
                response = await model.ainvoke(messages)

        assert response.content == "Native Claude response."
        assert response.response_metadata["stop_reason"] == "end_turn"
        assert response.usage_metadata["input_tokens"] == 31
        assert response.usage_metadata["output_tokens"] == 17
        assert response.usage_metadata["total_tokens"] == 48
        assert len(server.requests) == 1
        request = server.requests[0]
        assert request.path == "/v1/messages"
        assert request.headers["x-api-key"] == "test-native-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in request.headers
        assert request.body["model"] == "claude-local-test"
        assert request.body["max_tokens"] == 4096
        assert request.body["temperature"] == 0.25
        assert request.body["system"] == "Use only the supplied evidence."
        assert request.body["messages"] == [{"role": "user", "content": "Explain RAG."}]


@pytest.mark.asyncio
async def test_native_usage_includes_cache_read_creation_and_ttl_details():
    reply = anthropic_message(
        "A cached answer.",
        input_tokens=31,
        output_tokens=17,
        usage_details={
            "cache_read_input_tokens": 7,
            "cache_creation_input_tokens": 13,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 8,
                "ephemeral_1h_input_tokens": 5,
            },
        },
    )
    with ProviderHTTPServer(lambda _request: ProviderReply(reply)) as server:
        async with _chat_model(_settings(server.base_url)) as model:
            response = await model.ainvoke([HumanMessage(content="Reuse evidence.")])

        assert len(server.requests) == 1
        assert response.usage_metadata == {
            "input_tokens": 51,
            "output_tokens": 17,
            "total_tokens": 68,
            "input_token_details": {
                "cache_read": 7,
                "cache_creation": 13,
                "ephemeral_5m_input_tokens": 8,
                "ephemeral_1h_input_tokens": 5,
            },
        }
        usage = response.response_metadata["usage"]
        assert usage["input_tokens"] == 31
        assert usage["cache_read_input_tokens"] == 7
        assert usage["cache_creation_input_tokens"] == 13


@pytest.mark.asyncio
@pytest.mark.parametrize("invoke_mode", ["sync", "async"])
@pytest.mark.parametrize(
    ("status", "error_type", "exception_type"),
    [
        (401, "authentication_error", anthropic.AuthenticationError),
        (429, "rate_limit_error", anthropic.RateLimitError),
    ],
)
async def test_native_errors_surface_after_exactly_one_http_request(
    invoke_mode, status, error_type, exception_type
):
    reply = ProviderReply(
        status=status,
        headers={"Retry-After": "0", "request-id": "req_local_failure"},
        body={
            "type": "error",
            "error": {"type": error_type, "message": "Synthetic provider failure"},
        },
    )
    with ProviderHTTPServer(lambda _request: reply) as server:
        async with _chat_model(_settings(server.base_url)) as model:
            with pytest.raises(
                exception_type, match="Synthetic provider failure"
            ) as exc:
                if invoke_mode == "sync":
                    model.invoke([HumanMessage(content="One attempt only.")])
                else:
                    await model.ainvoke([HumanMessage(content="One attempt only.")])

        assert exc.value.status_code == status
        assert len(server.requests) == 1
        assert server.requests[0].path == "/v1/messages"


@tool
def lookup_fact(topic: str) -> str:
    """Look up a fact in the local evidence collection."""
    return {"RAG": "RAG retrieves evidence before generation."}[topic]


@pytest.mark.asyncio
@pytest.mark.parametrize("execution", ["bind_tools", "langgraph"])
async def test_native_tool_use_round_trips_through_tool_message(execution):
    replies = iter(
        [
            anthropic_message(
                [
                    {
                        "type": "tool_use",
                        "id": "toolu_local_lookup",
                        "name": "lookup_fact",
                        "input": {"topic": "RAG"},
                    }
                ],
                stop_reason="tool_use",
            ),
            anthropic_message(
                "RAG retrieves evidence before generation.",
                input_tokens=61,
                output_tokens=19,
            ),
        ]
    )
    with ProviderHTTPServer(lambda _request: ProviderReply(next(replies))) as server:
        async with _chat_model(_settings(server.base_url)) as model:
            bound = model.bind_tools([lookup_fact])
            question = HumanMessage(content="What is RAG?")
            if execution == "bind_tools":
                history = [
                    SystemMessage(content="Consult the local evidence."),
                    question,
                ]
                first = await bound.ainvoke(history)
                tool_result = await lookup_fact.ainvoke(first.tool_calls[0])
                final = await bound.ainvoke([*history, first, tool_result])
                messages = [question, first, tool_result, final]
            else:
                agent = create_react_agent(
                    bound, [lookup_fact], prompt="Consult the local evidence."
                )
                result = await agent.ainvoke(
                    {"messages": [question]}, config={"recursion_limit": 6}
                )
                messages = result["messages"]

        assert len(messages) == 4
        assert isinstance(messages[1], AIMessage)
        assert messages[1].tool_calls == [
            {
                "name": "lookup_fact",
                "args": {"topic": "RAG"},
                "id": "toolu_local_lookup",
                "type": "tool_call",
            }
        ]
        assert messages[1].response_metadata["stop_reason"] == "tool_use"
        assert isinstance(messages[2], ToolMessage)
        assert messages[2].tool_call_id == "toolu_local_lookup"
        assert messages[2].content == "RAG retrieves evidence before generation."
        assert messages[3].content == "RAG retrieves evidence before generation."
        assert messages[3].response_metadata["stop_reason"] == "end_turn"
        assert messages[3].usage_metadata["input_tokens"] == 61
        assert messages[3].usage_metadata["output_tokens"] == 19
        assert len(server.requests) == 2
        for request in server.requests:
            assert request.path == "/v1/messages"
            assert request.body["system"] == "Consult the local evidence."
            assert [entry["name"] for entry in request.body["tools"]] == ["lookup_fact"]
            schema = request.body["tools"][0]["input_schema"]
            assert schema["type"] == "object"
            assert schema["properties"]["topic"]["type"] == "string"
            assert schema["required"] == ["topic"]

        second_messages = server.requests[1].body["messages"]
        assert [message["role"] for message in second_messages] == [
            "user",
            "assistant",
            "user",
        ]
        tool_use = second_messages[1]["content"][0]
        assert tool_use["type"] == "tool_use"
        assert tool_use["id"] == "toolu_local_lookup"
        assert tool_use["name"] == "lookup_fact"
        assert tool_use["input"] == {"topic": "RAG"}
        assert second_messages[2]["content"] == [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_local_lookup",
                "content": "RAG retrieves evidence before generation.",
                "is_error": False,
            }
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_suffix", "expected_path"),
    [("", "/chat/completions"), ("/v1", "/v1/chat/completions")],
)
@pytest.mark.parametrize(
    ("provider", "prefix", "model_name", "api_key"),
    [
        ("openai_compatible", "llm", "gateway-local-test", "test-gateway-key"),
        ("deepseek", "deepseek", "deepseek-local-test", "test-deepseek-key"),
    ],
)
async def test_compatible_providers_preserve_chat_completions_and_bearer_auth(
    base_suffix, expected_path, provider, prefix, model_name, api_key
):
    reply = {
        "id": "chatcmpl_local_test",
        "object": "chat.completion",
        "created": 0,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Compatibility preserved."},
                "finish_reason": "stop",
                "logprobs": None,
            }
        ],
        "usage": {"prompt_tokens": 23, "completion_tokens": 11, "total_tokens": 34},
    }
    with ProviderHTTPServer(lambda _request: ProviderReply(reply)) as server:
        settings = _settings(
            server.base_url,
            llm_provider=provider,
            anthropic_api_key="",
            **{
                f"{prefix}_api_key": api_key,
                f"{prefix}_base_url": server.base_url + base_suffix,
                f"{prefix}_model": model_name,
            },
        )
        async with _chat_model(settings) as model:
            response = await model.ainvoke(
                [
                    SystemMessage(content="Use the compatible API."),
                    HumanMessage(content="Hello."),
                ]
            )

        assert response.content == "Compatibility preserved."
        assert response.usage_metadata["input_tokens"] == 23
        assert response.usage_metadata["output_tokens"] == 11
        assert response.usage_metadata["total_tokens"] == 34
        assert len(server.requests) == 1
        request = server.requests[0]
        assert request.path == expected_path
        assert request.headers["authorization"] == f"Bearer {api_key}"
        assert "x-api-key" not in request.headers
        assert "anthropic-version" not in request.headers
        assert request.body["model"] == model_name
        assert "system" not in request.body
        assert request.body["messages"] == [
            {"role": "system", "content": "Use the compatible API."},
            {"role": "user", "content": "Hello."},
        ]


@pytest.mark.asyncio
async def test_native_model_can_restart_after_its_owner_closes_the_sdk_clients():
    with ProviderHTTPServer(
        lambda _request: ProviderReply(anthropic_message("The model is available."))
    ) as server:
        settings = _settings(server.base_url)
        for _ in range(2):
            async with _chat_model(settings) as model:
                sync_client = model._client
                async_client = model._async_client
                assert not sync_client.is_closed()
                assert not async_client.is_closed()
                sync_response = model.invoke([HumanMessage(content="Are you ready?")])
                async_response = await model.ainvoke(
                    [HumanMessage(content="Are you ready?")]
                )
                assert sync_response.content == "The model is available."
                assert async_response.content == "The model is available."

            assert sync_client.is_closed()
            assert async_client.is_closed()

        assert len(server.requests) == 4
        assert all(request.path == "/v1/messages" for request in server.requests)
