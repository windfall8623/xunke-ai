from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_anonymous_auth_capabilities_expose_only_the_configured_flag(
    monkeypatch, enabled
):
    from app.api.v1.routes import auth

    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(
            legacy_link_enabled=enabled,
            wechat_app_secret="must-not-be-returned",
            jwt_secret="must-not-be-returned-either",
            email_registration_enabled=False,
            email_code_secret="",
            email_send_cooldown_seconds=60,
            email_send_max_per_email_per_day=5,
            email_send_max_per_ip_per_hour=10,
            email_send_daily_limit=100,
            smtp_security="ssl",
            smtp_host="",
            smtp_username="",
            smtp_password="",
            smtp_from_email="",
            smtp_from_name="循课",
        ),
    )
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/auth/capabilities")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "legacy_link_enabled": enabled,
        "email_registration_enabled": False,
        "email_verification_required": True,
        "email_code_cooldown_seconds": 60,
    }
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert "must-not-be-returned" not in response.text
