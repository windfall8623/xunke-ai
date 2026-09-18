"""User LLM credentials and actor policy: no live provider requests."""
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.services import user_llm_config_service as service


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["learner", "evaluator"])
async def test_ordinary_actor_never_uses_system_and_reuses_connection(role):
    conn = object()
    settings = Settings(_env_file=None, deepseek_api_key="system-secret")
    with (
        patch.object(service, "fetch_one", AsyncMock(side_effect=[{"role": role}, None])) as read,
        patch.object(service, "resolve_llm_config") as system,
        patch("socket.getaddrinfo", side_effect=AssertionError("No DNS during resolution")),
    ):
        with pytest.raises(AppError) as error:
            await service.resolve_actor_llm_config(17, settings, conn=conn)
    assert error.value.code == "llm_configuration_required"
    assert all(call.kwargs["conn"] is conn for call in read.await_args_list)
    assert all(call.args[1] == (17,) for call in read.await_args_list)
    system.assert_not_called()


@pytest.mark.asyncio
async def test_role_is_read_again_after_admin_demotion():
    settings = Settings(_env_file=None, deepseek_api_key="system-secret")
    with patch.object(service, "fetch_one", AsyncMock(side_effect=[{"role": "admin"}, {"role": "learner"}, None])):
        assert (await service.resolve_actor_llm_config(17, settings)).source == "system"
        with pytest.raises(AppError, match="配置"):
            await service.resolve_actor_llm_config(17, settings)


@pytest.mark.asyncio
async def test_admin_always_uses_system_without_reading_personal_credentials():
    settings = Settings(_env_file=None, deepseek_api_key="system-secret")
    with (
        patch.object(service, "get_actor_role", AsyncMock(return_value="admin")),
        patch.object(service, "get_user_llm_config", AsyncMock()) as personal,
        patch.object(service, "decrypt_api_key") as decrypt,
    ):
        result = await service.resolve_actor_llm_config(17, settings)
    assert result.source == "system" and result.api_key == "system-secret"
    personal.assert_not_awaited()
    decrypt.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["learner", "evaluator"])
async def test_unreadable_personal_key_never_falls_back(role):
    settings = Settings(_env_file=None, user_llm_key_secret="a-separate-test-secret-with-32-characters")
    row = dict(provider="deepseek", model="private-model", base_url="https://api.example.com",
               api_key_cipher="invalid-cipher")
    with (
        patch.object(service, "fetch_one", AsyncMock(side_effect=[{"role": role}, row])),
        patch.object(service, "resolve_llm_config") as system,
    ):
        with pytest.raises(AppError) as error:
            await service.resolve_actor_llm_config(17, settings)
    assert error.value.code == "user_llm_key_unreadable"
    system.assert_not_called()


@pytest.mark.parametrize("secret", ["", "short", "same-as-jwt-secret-must-be-refused-123"])
def test_missing_short_or_reused_secret_fails_closed(secret):
    from app.core.user_llm_crypto import encrypt_api_key
    settings = Settings(_env_file=None, user_llm_key_secret=secret,
                        jwt_secret="same-as-jwt-secret-must-be-refused-123")
    with pytest.raises(AppError):
        encrypt_api_key("sk-private-1234", 17, settings)


def test_encryption_randomized_owner_bound_and_secret_hidden():
    from app.core.user_llm_crypto import decrypt_api_key, encrypt_api_key
    settings = Settings(_env_file=None, user_llm_key_secret="a-separate-test-secret-with-32-characters")
    key = "sk-private-credential-1234"
    one = encrypt_api_key(key, 17, settings)
    two = encrypt_api_key(key, 17, settings)
    assert one != two and key not in one
    assert decrypt_api_key(one, 17, settings) == key
    assert settings.user_llm_key_secret not in repr(settings)
    for ciphertext, owner in [(one, 18), (one[:-3] + "AAA", 17)]:
        with pytest.raises(AppError):
            decrypt_api_key(ciphertext, owner, settings)
