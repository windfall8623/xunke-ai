import pytest

from app.llm.configuration import LLMConfig
from app.llm.langchain_factory import ChatModelCloser, chat_model_from_config
from app.llm.user_endpoint import PublicAsyncHTTPTransport, PublicHTTPTransport


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["deepseek", "openai_compatible", "anthropic"])
async def test_user_runtime_uses_public_pinned_transports(provider):
    model = chat_model_from_config(LLMConfig(provider, "test-model", "https://models.example.org", "test-key", source="user"))
    values = model.__dict__
    sync_sdk = values.get("_client") or values.get("root_client")
    async_sdk = values.get("_async_client") or values.get("root_async_client")
    try:
        assert isinstance(sync_sdk._client._transport, PublicHTTPTransport)
        assert isinstance(async_sdk._client._transport, PublicAsyncHTTPTransport)
        assert sync_sdk._client.follow_redirects is False
        assert async_sdk._client.follow_redirects is False
        assert sync_sdk._client._trust_env is False
        assert async_sdk._client._trust_env is False
    finally:
        await ChatModelCloser(model).aclose()
