"""Public DNS pinning and bounded probe tests, all transport I/O mocked."""
import json
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.core.errors import AppError
from app.llm import user_endpoint as endpoint
from app.llm.configuration import LLMConfig
from app.services.user_llm_config_service import probe_provider


@pytest.mark.parametrize("url", [
    "http://127.0.0.1", "http://[::1]", "http://10.0.0.1", "http://169.254.169.254",
    "http://localhost", "http://service.internal", "ftp://api.example.com",
    "http://user:pass@api.example.com", "http://api.example.com?key=secret",
    "http://[fd00::1]", "http://0.0.0.0", "http://[::ffff:127.0.0.1]",
    "http://api.example.com\\@127.0.0.1", "http://[64:ff9b::7f00:1]",
])
def test_reject_unsafe_urls_without_dns(url):
    with pytest.raises(AppError):
        endpoint.normalize_user_llm_endpoint(url)


@pytest.mark.asyncio
async def test_mixed_public_private_dns_rejected():
    with patch.object(endpoint.socket, "getaddrinfo", return_value=[
        (2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("10.0.0.1", 443))]):
        with pytest.raises(AppError):
            await endpoint.validate_user_llm_endpoint("https://api.example.com")


@pytest.mark.asyncio
async def test_async_transport_pins_ip_preserves_host_sni_and_rechecks_dns():
    transport = endpoint.PublicAsyncHTTPTransport()
    transport._transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    capture = transport._transport.handle_async_request
    transport._transport.handle_async_request = AsyncMock(side_effect=capture)
    with patch.object(endpoint, "_resolve_public", side_effect=["93.184.216.34", AppError(422, "invalid_llm_endpoint", "safe")]):
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("https://api.example.com/v1")
            pinned = transport._transport.handle_async_request.await_args.args[0]
            assert pinned.url.host == "93.184.216.34"
            assert pinned.headers["host"] == "api.example.com"
            assert pinned.extensions["sni_hostname"] == "api.example.com"
            with pytest.raises(AppError):
                await client.get("https://api.example.com/v1")
    transport._transport.handle_async_request.assert_awaited_once()


def test_sync_transport_blocks_redirect_even_if_caller_enables_following():
    transport = endpoint.PublicHTTPTransport()
    respond = Mock(return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1"}))
    transport._transport = httpx.MockTransport(respond)
    with patch.object(endpoint, "_resolve_public", return_value="93.184.216.34"):
        with httpx.Client(transport=transport, follow_redirects=True) as client:
            with pytest.raises(AppError):
                client.get("https://api.example.com/v1")
    respond.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,path", [("deepseek", "/chat/completions"), ("openai_compatible", "/chat/completions"), ("anthropic", "/v1/messages")])
async def test_probe_is_small_bounded_and_uses_provider_protocol(provider, path):
    def respond(request):
        body = json.loads(request.content)
        assert body["max_tokens"] == 8 and body["stream"] is False
        assert request.url.path == path
        assert request.headers.get("x-api-key" if provider == "anthropic" else "authorization")
        return httpx.Response(200, json={"content": [{"text": "OK"}]} if provider == "anthropic" else {"choices": [{"message": {"content": "OK"}}]})
    with patch("app.services.user_llm_config_service.create_user_llm_async_http_client", return_value=httpx.AsyncClient(transport=httpx.MockTransport(respond))):
        await probe_provider(LLMConfig(provider, "m", "https://api.example.com", "sk-private-1234", source="user"))


@pytest.mark.asyncio
async def test_probe_error_is_typed_and_key_redacted():
    key = "sk-private-1234"
    with patch("app.services.user_llm_config_service.create_user_llm_async_http_client", return_value=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": {"message": f"Invalid key {key}"}})))):
        with pytest.raises(AppError) as error:
            await probe_provider(LLMConfig("deepseek", "m", "https://api.example.com", key, source="user"))
    assert error.value.code == "user_llm_failed" and key not in str(error.value)


@pytest.mark.asyncio
async def test_probe_rejects_oversized_success_response():
    with patch("app.services.user_llm_config_service.create_user_llm_async_http_client", return_value=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 65537)))):
        with pytest.raises(AppError, match="过大"):
            await probe_provider(LLMConfig("deepseek", "m", "https://api.example.com", "sk-private-1234", source="user"))
