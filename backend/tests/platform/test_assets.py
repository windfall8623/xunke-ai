import io

import httpx
from tests.platform.conftest import register_email_account
import pytest
from PIL import Image


def png_bytes(size=(64, 64)):
    stream = io.BytesIO()
    Image.new("RGB", size, "blue").save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.asyncio
async def test_avatar_is_reencoded_persisted_and_owner_only(learner):
    api, session = learner
    response = await api.post(
        "/api/v1/user/avatar",
        files={"file": ("portrait.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 201, response.text
    url = response.json()["data"]["avatar_url"]
    assert url.startswith("/api/v1/user/assets/")
    image = await api.get(url)
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(image.content)).size == (64, 64)
    assert (await api.get("/api/v1/auth/session")).json()["data"]["user"][
        "avatar_url"
    ] == url
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as stranger:
        assert (await stranger.get(url)).status_code == 401
        await register_email_account(stranger, nickname="Other")
        assert (await stranger.get(url)).status_code == 404


@pytest.mark.asyncio
async def test_avatar_rejects_disguised_or_oversized_content(learner):
    api, _ = learner
    bad = await api.post(
        "/api/v1/user/avatar",
        files={"file": ("fake.png", b'<svg onload="bad"></svg>', "image/png")},
    )
    assert bad.status_code == 422
    large = await api.post(
        "/api/v1/user/avatar",
        files={"file": ("too-large.jpg", b"x" * (2 * 1024 * 1024 + 1), "image/jpeg")},
    )
    assert large.status_code == 413


@pytest.mark.asyncio
async def test_avatar_commit_ack_loss_keeps_published_file(learner, monkeypatch):
    from contextlib import asynccontextmanager

    from starlette.datastructures import UploadFile

    from app.core.db import fetch_one
    from app.services import asset_service

    api, session = learner
    original_transaction = asset_service.transaction

    @asynccontextmanager
    async def lost_ack():
        async with original_transaction() as conn:
            yield conn
        raise ConnectionResetError("synthetic lost COMMIT acknowledgement")

    monkeypatch.setattr(asset_service, "transaction", lost_ack)
    with pytest.raises(ConnectionResetError):
        await asset_service.save_avatar(
            session["user"]["id"],
            UploadFile(io.BytesIO(png_bytes()), filename="avatar.png"),
        )
    user = await fetch_one(
        "SELECT avatar_url FROM users WHERE id=%s", (session["user"]["id"],)
    )
    assert (await api.get(user["avatar_url"])).status_code == 200
