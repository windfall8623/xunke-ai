import httpx
import openai
import pytest

from app.llm.provider_errors import user_provider_failure


@pytest.mark.parametrize("status,message", [(401, "Invalid API key"), (402, "Insufficient Balance"), (429, "Quota exceeded"), (503, "Model unavailable")])
def test_user_failure_preserves_provider_message(status, message):
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.org/v1/chat"), json={"error": {"message": message}})
    error = openai.APIStatusError(message, response=response, body=response.json())
    failure = user_provider_failure(error, api_key="secret-key")
    assert failure.code == "user_llm_failed"
    assert message in failure.message
    assert "检查" in failure.message


def test_user_failure_never_echoes_key_headers_or_entire_body():
    response = httpx.Response(401, request=httpx.Request("POST", "https://example.org"), json={"error": {"message": "Invalid secret-key; Authorization: Bearer another-secret"}, "prompt": "private prompt"})
    failure = user_provider_failure(httpx.HTTPStatusError("bad", request=response.request, response=response), api_key="secret-key")
    assert "secret-key" not in failure.message
    assert "another-secret" not in failure.message
    assert "private prompt" not in failure.message


def test_non_json_response_and_unknown_exception_do_not_echo_raw_text():
    response = httpx.Response(502, request=httpx.Request("POST", "https://example.org"), text="<html>private proxy details</html>")
    failure = user_provider_failure(httpx.HTTPStatusError("bad", request=response.request, response=response), api_key="key")
    assert "502" in failure.message
    assert "private proxy" not in failure.message
    assert user_provider_failure(ValueError("private prompt"), api_key="key") is None


def test_provider_message_is_bounded_and_control_characters_removed():
    response = httpx.Response(400, request=httpx.Request("POST", "https://example.org"), json={"message": "bad\x00\x1b[31m " + "a" * 5000})
    failure = user_provider_failure(httpx.HTTPStatusError("bad", request=response.request, response=response), api_key="key")
    assert len(failure.message) <= 900
    assert "\x00" not in failure.message
    assert "\x1b" not in failure.message


def test_control_character_removal_cannot_reconstruct_a_credential():
    key = "private-credential-1234"
    encoded = key[:8] + "\u200b" + key[8:]
    response = httpx.Response(401, request=httpx.Request("POST", "https://example.org"),
                              json={"error": {"message": f"Invalid {encoded}"}})
    failure = user_provider_failure(
        httpx.HTTPStatusError("bad", request=response.request, response=response), api_key=key
    )
    assert key not in failure.message and "\u200b" not in failure.message
