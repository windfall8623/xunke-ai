"""Real isolated SQL + session/CSRF ownership; provider probe is always mocked."""
import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.db import fetch_one, insert, execute
from app.core.errors import AppError
from app.core.user_llm_crypto import decrypt_api_key, encrypt_api_key
from app.services import user_llm_config_service as service


@pytest.mark.asyncio
async def test_user_config_persistence_owner_isolation_and_current_admin_policy(learner, platform_settings, monkeypatch):
    api, session = learner
    owner = session["user"]["id"]
    platform_settings.user_llm_key_secret = "isolated-user-llm-secret-not-a-real-secret-1234"
    other = await insert("INSERT INTO users(openid,nickname) VALUES(%s,'other')", (f"llm-test-{uuid.uuid4().hex}",))
    other_cipher = encrypt_api_key("sk-other-9999", other, platform_settings)
    await execute("INSERT INTO user_llm_configs(owner_id,provider,model,base_url,api_key_cipher) VALUES(%s,'deepseek','m','https://api.example.com',%s)", (other, other_cipher))
    probe = AsyncMock()
    monkeypatch.setattr(service, "probe_provider", probe)
    body = dict(provider="deepseek", model="m", base_url="https://api.example.com", api_key="sk-owner-private-1234")
    try:
        empty = (await api.get("/api/v1/me/llm")).json()["data"]
        assert empty["source"] is None and not empty["can_use_system"]
        with pytest.raises(AppError) as error:
            await service.resolve_actor_llm_config(owner)
        assert error.value.code == "llm_configuration_required"
        saved = await api.put("/api/v1/me/llm", json=body)
        assert saved.status_code == 200, saved.text
        assert body["api_key"] not in saved.text
        assert saved.json()["data"]["api_key_hint"] == "****1234"
        row = await fetch_one("SELECT * FROM user_llm_configs WHERE owner_id=%s", (owner,))
        assert body["api_key"] not in row["api_key_cipher"]
        assert decrypt_api_key(row["api_key_cipher"], owner, platform_settings) == body["api_key"]
        assert (await service.resolve_actor_llm_config(owner)).source == "user"
        assert (await api.put("/api/v1/me/llm", json={key: value for key, value in body.items() if key != "api_key"})).status_code == 200
        foreign = await api.put("/api/v1/me/llm", json={**body, "owner_id": other})
        assert foreign.status_code == 422
        csrf = api.headers.pop("X-CSRF-Token")
        assert (await api.delete("/api/v1/me/llm")).status_code == 403
        api.headers["X-CSRF-Token"] = csrf
        deleted = await api.delete(f"/api/v1/me/llm?owner_id={other}")
        assert deleted.status_code == 200
        assert deleted.json()["data"] == {
            "configured": False, "provider": None, "model": None, "base_url": None,
            "api_key_hint": None, "can_use_system": False, "source": None,
        }
        assert deleted.headers["cache-control"] == "no-store"
        assert not await fetch_one("SELECT owner_id FROM user_llm_configs WHERE owner_id=%s", (owner,))
        assert (await fetch_one("SELECT api_key_cipher FROM user_llm_configs WHERE owner_id=%s", (other,)))["api_key_cipher"] == other_cipher
        await execute("UPDATE users SET role='admin' WHERE id=%s", (owner,))
        await execute(
            "INSERT INTO user_llm_configs(owner_id,provider,model,base_url,api_key_cipher) "
            "VALUES(%s,'deepseek','legacy-personal','https://api.example.com','unreadable')",
            (owner,),
        )
        assert (await service.resolve_actor_llm_config(owner)).source == "system"
        admin_view = (await api.get("/api/v1/me/llm")).json()["data"]
        assert admin_view["source"] == "system" and admin_view["api_key_hint"] is None
        rejected = await api.put("/api/v1/me/llm", json=body)
        assert rejected.status_code == 403
        assert rejected.json()["error_code"] == "system_llm_managed"
        await execute("DELETE FROM user_llm_configs WHERE owner_id=%s", (owner,))
        await execute("UPDATE users SET role='learner' WHERE id=%s", (owner,))
        with pytest.raises(AppError) as error:
            await service.resolve_actor_llm_config(owner)
        assert error.value.code == "llm_configuration_required"
        assert probe.await_count == 2
    finally:
        await execute("DELETE FROM user_llm_configs WHERE owner_id IN (%s,%s)", (owner, other))
        await execute("UPDATE users SET role='learner' WHERE id=%s", (owner,))
        await execute("DELETE FROM users WHERE id=%s", (other,))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["delete", "rotate", "promote"])
async def test_inflight_probe_cannot_restore_deleted_or_replace_newer_credentials(
    learner, platform_settings, monkeypatch, change
):
    import asyncio
    from app.models.user_llm_config import LLMConfigRequest

    _, session = learner
    owner = session["user"]["id"]
    platform_settings.user_llm_key_secret = "isolated-user-llm-secret-not-a-real-secret-1234"
    body = LLMConfigRequest(provider="deepseek", model="old-model", base_url="https://api.example.com", api_key="sk-old-1234")
    monkeypatch.setattr(service, "probe_provider", AsyncMock())
    await service.save_my_llm_config(owner, body)
    entered, release = asyncio.Event(), asyncio.Event()
    async def probe(config):
        if config.model == "stale-model":
            entered.set()
            await release.wait()
    monkeypatch.setattr(service, "probe_provider", probe)
    pending = asyncio.create_task(service.save_my_llm_config(owner, body.model_copy(update={"model": "stale-model"})))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == "delete":
            await service.delete_my_llm_config(owner)
        elif change == "rotate":
            await service.save_my_llm_config(owner, body.model_copy(update={"model": "new-model", "api_key": "sk-new-5678"}))
        else:
            await execute("UPDATE users SET role='admin' WHERE id=%s", (owner,))
        release.set()
        with pytest.raises(AppError) as error:
            await pending
        assert error.value.code == ("system_llm_managed" if change == "promote" else "llm_configuration_changed")
        current = await service.get_user_llm_config(owner)
        if change == "delete":
            assert current is None
        else:
            assert current["model"] == ("new-model" if change == "rotate" else "old-model")
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
