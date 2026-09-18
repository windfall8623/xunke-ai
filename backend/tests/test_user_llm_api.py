"""Self-service HTTP contract using mocked persistence, no model or DB calls."""
from contextlib import asynccontextmanager
from unittest.mock import ANY, AsyncMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.models.user_llm_config import LLMConfigRequest
from app.services import user_llm_config_service as service
from tests.test_api import api_request
from tests import test_api

# Register shared authentication fixture without shadowing an imported name.
authenticated_actor = test_api.authenticated_actor


@asynccontextmanager
async def isolated_transaction():
    yield object()


@pytest.fixture(autouse=True)
def mock_transaction(monkeypatch):
    monkeypatch.setattr(service, "transaction", isolated_transaction)


@pytest.fixture
def settings():
    return Settings(_env_file=None, user_llm_key_secret="a-separate-test-secret-with-32-characters")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
async def test_authentication_required(method):
    response = await api_request(method, "/api/v1/me/llm", **({"json": {}} if method == "PUT" else {}))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ordinary_get_does_not_disclose_system_config(authenticated_actor):
    with patch.object(service, "fetch_one", AsyncMock(side_effect=[{"role": "learner"}, None])):
        response = await api_request("GET", "/api/v1/me/llm")
    assert response.status_code == 200
    assert response.json()["data"] == dict(configured=False, provider=None, model=None,
        base_url=None, api_key_hint=None, can_use_system=False, source=None)
    # Global response middleware deliberately applies no-store to every route.
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["learner", "evaluator", "admin"])
async def test_delete_uses_authenticated_owner_and_returns_fresh_metadata(authenticated_actor, role):
    with (
        patch.object(service, "execute", AsyncMock()) as execute,
        patch.object(service, "fetch_one", AsyncMock(side_effect=[{"role": role}, {"role": role}, None])),
    ):
        response = await api_request("DELETE", "/api/v1/me/llm?owner_id=999")
    assert response.status_code == 200
    execute.assert_awaited_once_with("DELETE FROM user_llm_configs WHERE owner_id=%s", (1,), conn=ANY)
    data = response.json()["data"]
    assert data["configured"] is False and data["api_key_hint"] is None
    assert data["source"] == ("system" if role == "admin" else None)
    assert data["can_use_system"] == (role == "admin")
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_save_probes_before_encrypted_write_and_never_returns_key(authenticated_actor, settings):
    from app.core.user_llm_crypto import decrypt_api_key
    key = "sk-private-value-1234"
    with (
        patch.object(service, "get_settings", return_value=settings),
        patch.object(service, "fetch_one", AsyncMock(return_value={"role": "learner"})),
        patch("app.services.auth_service.rate_limit", AsyncMock()) as rate,
        patch("app.services.rate_limit_service.enforce_burst", AsyncMock()),
        patch.object(service, "probe_provider", AsyncMock()) as probe,
        patch.object(service, "execute", AsyncMock()) as execute,
    ):
        response = await api_request("PUT", "/api/v1/me/llm", json=dict(provider="deepseek",
            model="deepseek-chat", base_url="https://api.deepseek.com", api_key=key))
    assert response.status_code == 200, response.text
    assert key not in response.text
    assert response.json()["data"]["api_key_hint"] == "****1234"
    assert rate.await_args.args[:2] == ("user_llm_probe", "1")
    probe.assert_awaited_once()
    values = execute.await_args.args[1]
    assert values[0] == 1 and key not in str(values)
    assert decrypt_api_key(values[-1], 1, settings) == key


@pytest.mark.asyncio
async def test_probe_failure_preserves_old_configuration(settings):
    with (
        patch.object(service, "fetch_one", AsyncMock(return_value={"role": "learner"})),
        patch.object(service, "probe_provider", AsyncMock(side_effect=AppError(422, "user_llm_failed", "safe"))),
        patch.object(service, "execute", AsyncMock()) as execute,
    ):
        with pytest.raises(AppError):
            await service.save_my_llm_config(17, LLMConfigRequest(provider="deepseek", model="m",
                base_url="https://api.example.com", api_key="sk-synthetic-1234"), settings)
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_key_omission_only_for_identical_stored_configuration(settings):
    from app.core.user_llm_crypto import encrypt_api_key
    row = dict(provider="deepseek", model="m", base_url="https://api.example.com",
               api_key_cipher=encrypt_api_key("sk-original-1234", 17, settings))
    for model, succeeds in [("m", True), ("changed", False)]:
        with (
            patch.object(service, "fetch_one", AsyncMock(side_effect=[{"role": "learner"}, row, {"role": "learner"}, row])),
            patch.object(service, "probe_provider", AsyncMock()) as probe,
            patch.object(service, "execute", AsyncMock()),
        ):
            body = LLMConfigRequest(provider="deepseek", model=model, base_url=row["base_url"])
            if succeeds:
                assert (await service.save_my_llm_config(17, body, settings)).api_key_hint == "****1234"
            else:
                with pytest.raises(AppError) as error:
                    await service.save_my_llm_config(17, body, settings)
                assert error.value.code == "api_key_required"
                probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_save_is_rejected_without_probe_or_write(authenticated_actor, settings):
    with (
        patch.object(service, "get_settings", return_value=settings),
        patch.object(service, "get_actor_role", AsyncMock(return_value="admin")),
        patch("app.services.auth_service.rate_limit", AsyncMock()),
        patch("app.services.rate_limit_service.enforce_burst", AsyncMock()),
        patch.object(service, "probe_provider", AsyncMock()) as probe,
        patch.object(service, "execute", AsyncMock()) as execute,
    ):
        response = await api_request("PUT", "/api/v1/me/llm", json=dict(
            provider="deepseek", model="m", base_url="https://api.example.com", api_key="synthetic-credential"))
    assert response.status_code == 403
    assert response.json()["error_code"] == "system_llm_managed"
    probe.assert_not_awaited()
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_rate_limit_prevents_probe(authenticated_actor):
    with (
        patch("app.services.rate_limit_service.enforce_burst", AsyncMock()),
        patch("app.services.auth_service.rate_limit", AsyncMock(side_effect=AppError(429, "rate_limited", "safe"))),
        patch.object(service, "save_my_llm_config", AsyncMock()) as save,
    ):
        response = await api_request("PUT", "/api/v1/me/llm", json=dict(provider="deepseek", model="m",
            base_url="https://api.example.com", api_key="sk-private-1234"))
    assert response.status_code == 429
    save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["delete", "rotate", "promote"])
async def test_probe_cannot_overwrite_a_concurrent_configuration_change(settings, change):
    from app.core.user_llm_crypto import encrypt_api_key

    row = dict(provider="deepseek", model="m", base_url="https://api.example.com",
               api_key_cipher=encrypt_api_key("sk-original-1234", 17, settings))
    current = None if change == "delete" else {**row, "model": "newer-model"}
    role = "admin" if change == "promote" else "learner"
    with (
        patch.object(service, "get_actor_role", AsyncMock(side_effect=["learner", role])) as roles,
        patch.object(service, "get_user_llm_config", AsyncMock(side_effect=[row, current])),
        patch.object(service, "probe_provider", AsyncMock()) as probe,
        patch.object(service, "execute", AsyncMock()) as execute,
    ):
        with pytest.raises(AppError) as error:
            await service.save_my_llm_config(17, LLMConfigRequest(
                provider="deepseek", model="m", base_url=row["base_url"], api_key="sk-new-5678"
            ), settings)
    assert error.value.code == ("system_llm_managed" if change == "promote" else "llm_configuration_changed")
    assert roles.await_args.kwargs["lock"] is True
    probe.assert_awaited_once()
    execute.assert_not_awaited()
