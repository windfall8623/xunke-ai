"""JWT 鉴权模块单元测试"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from starlette.requests import Request

from app.core.auth import (
    create_token,
    decode_token,
    get_admin,
    get_current_actor,
    get_current_user,
    get_evaluator,
    get_optional_user,
    require_system_model_admin,
)
from app.core.errors import AppError
from app.core.exceptions import AuthenticationError
from app.rag.contracts import ActorContext


def http_request(headers=None, method="GET"):
    return Request({"type": "http", "method": method, "path": "/", "headers": [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]})


@pytest.fixture
def session_settings():
    settings = SimpleNamespace(jwt_secret="test-only-jwt-secret-at-least-32-characters",
                               jwt_expire_minutes=60, wechat_app_id="",
                               session_cookie_name="test_session", web_origins=["http://test"])
    with patch("app.core.auth.get_settings", return_value=settings):
        yield settings


class TestCreateToken:
    def test_creates_valid_jwt(self):
        token = create_token(user_id=1, openid="test_openid")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_user_id(self):
        token = create_token(user_id=42, openid="test_openid")
        payload = decode_token(token)
        assert payload["user_id"] == 42
        assert payload["openid"] == "test_openid"

    def test_token_has_expiration(self):
        token = create_token(user_id=1, openid="test_openid")
        payload = decode_token(token)
        assert "exp" in payload


class TestDecodeToken:
    def test_decode_valid_token(self):
        token = create_token(user_id=1, openid="abc")
        payload = decode_token(token)
        assert payload["user_id"] == 1

    def test_decode_expired_token(self):
        from app.core.config import get_settings
        settings = get_settings()
        expired_payload = {
            "user_id": 1,
            "openid": "abc",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        token = jwt.encode(expired_payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(AuthenticationError, match="过期"):
            decode_token(token)

    def test_decode_invalid_token(self):
        with pytest.raises(AuthenticationError, match="无效"):
            decode_token("not.a.valid.token")

    def test_decode_tampered_token(self):
        token = create_token(user_id=1, openid="abc")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(AuthenticationError):
            decode_token(tampered)


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_returns_user_id_with_valid_token(self, session_settings):
        token = create_token(user_id=99, openid="test")
        request = http_request({"Authorization": f"Bearer {token}"})
        with patch("app.core.db.fetch_one", AsyncMock(return_value={"id": 99, "role": "learner", "openid": "test"})) as fetch:
            user_id = await get_current_user(request)
        assert user_id == 99
        assert request.state.auth_type == "bearer"
        assert fetch.await_args.args[1] == (99,)

    @pytest.mark.asyncio
    async def test_raises_without_token(self):
        request = http_request()
        with pytest.raises(AuthenticationError):
            await get_current_user(request)

    @pytest.mark.asyncio
    async def test_raises_with_invalid_token(self):
        request = http_request({"Authorization": "Bearer invalid_token"})
        with pytest.raises(AuthenticationError):
            await get_current_user(request)


class TestGetOptionalUser:
    @pytest.mark.asyncio
    async def test_returns_user_id_with_valid_token(self, session_settings):
        token = create_token(user_id=77, openid="test")
        request = http_request({"Authorization": f"Bearer {token}"})
        with patch("app.core.db.fetch_one", AsyncMock(return_value={"id": 77, "role": "learner", "openid": "test"})):
            user_id = await get_optional_user(request)
        assert user_id == 77

    @pytest.mark.asyncio
    async def test_returns_none_without_token(self):
        request = http_request()
        user_id = await get_optional_user(request)
        assert user_id is None

    @pytest.mark.asyncio
    async def test_invalid_token_is_not_downgraded_to_guest(self):
        request = http_request({"Authorization": "Bearer bad_token"})
        with pytest.raises(AuthenticationError):
            await get_optional_user(request)


@pytest.mark.asyncio
class TestPersistedIdentity:
    @pytest.mark.parametrize("user", [None, {"id": 99, "role": "learner", "openid": "different"}])
    async def test_signed_token_still_requires_existing_matching_identity(self, session_settings, user):
        token = create_token(99, "test")
        with patch("app.core.db.fetch_one", AsyncMock(return_value=user)):
            with pytest.raises(AuthenticationError):
                await get_current_user(http_request({"Authorization": f"Bearer {token}"}))

    async def test_scoped_wechat_token_requires_bound_app_identity(self, session_settings):
        session_settings.wechat_app_id = "test-app"
        token = create_token(77, "scoped-subject")
        with patch("app.core.db.fetch_one", AsyncMock(side_effect=[
            {"id": 77, "role": "learner", "openid": None}, {"identity_id": 3},
        ])) as fetch:
            assert await get_current_user(http_request({"Authorization": f"Bearer {token}"})) == 77
        assert fetch.await_args.args[1] == (77, "test-app", "scoped-subject")

    async def test_token_from_another_app_is_rejected(self, session_settings):
        session_settings.wechat_app_id = "previous-app"
        token = create_token(77, "scoped-subject")
        session_settings.wechat_app_id = "current-app"
        with patch("app.core.db.fetch_one", AsyncMock(side_effect=[
            {"id": 77, "role": "learner", "openid": None}, {"identity_id": 3},
        ])):
            with pytest.raises(AuthenticationError):
                await get_current_user(http_request({"Authorization": f"Bearer {token}"}))

    async def test_cookie_read_uses_persisted_session(self, session_settings):
        request = http_request({"Cookie": "test_session=test-cookie"})
        with patch("app.core.db.fetch_one", AsyncMock(return_value={"id": 7, "role": "evaluator", "csrf_token": "csrf-test"})):
            actor = await get_current_actor(request)
        assert actor.owner_id == 7 and actor.roles == ["evaluator"]
        assert request.state.auth_type == "cookie"

    async def test_role_demotion_is_visible_on_the_next_cookie_request(self, session_settings):
        with patch("app.core.db.fetch_one", AsyncMock(side_effect=[
            {"id": 7, "role": "admin", "csrf_token": "csrf-test"},
            {"id": 7, "role": "evaluator", "csrf_token": "csrf-test"},
        ])):
            before = await get_current_actor(http_request({"Cookie": "test_session=test-cookie"}))
            after = await get_current_actor(http_request({"Cookie": "test_session=test-cookie"}))
        assert before.role == "admin"
        assert after.role == "evaluator"

    @pytest.mark.parametrize("origin,csrf,code", [
        ("https://untrusted.invalid", "csrf-test", "origin_rejected"),
        ("http://test", "wrong", "csrf_rejected"),
    ])
    async def test_cookie_mutation_requires_origin_and_csrf(self, session_settings, origin, csrf, code):
        request = http_request({"Cookie": "test_session=test-cookie", "Origin": origin, "X-CSRF-Token": csrf}, "POST")
        with patch("app.core.db.fetch_one", AsyncMock(return_value={"id": 7, "role": "learner", "csrf_token": "csrf-test"})):
            with pytest.raises(AppError) as error:
                await get_current_user(request)
        assert error.value.status == 403 and error.value.code == code

    async def test_expired_cookie_is_not_downgraded_to_guest(self, session_settings):
        with patch("app.core.db.fetch_one", AsyncMock(return_value=None)):
            with pytest.raises(AuthenticationError):
                await get_optional_user(http_request({"Cookie": "test_session=expired"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["evaluator", "admin"])
async def test_evaluator_dependency_retains_owned_workbench_access(role):
    actor = ActorContext(owner_id=7, role=role)
    assert await get_evaluator(actor) is actor


@pytest.mark.asyncio
async def test_evaluator_dependency_rejects_learner():
    with pytest.raises(AppError) as caught:
        await get_evaluator(ActorContext(owner_id=7))
    assert (caught.value.status, caught.value.code) == (403, "evaluator_required")


@pytest.mark.asyncio
@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("role", ["admin", "evaluator", "learner", "unknown", None])
async def test_system_model_permission_requires_current_database_admin(role, locked):
    conn = object() if locked else None
    row = {"role": role} if role is not None else None
    with patch("app.core.db.fetch_one", AsyncMock(return_value=row)) as fetch:
        if role == "admin":
            await require_system_model_admin(7, conn=conn)
        else:
            with pytest.raises(AppError) as caught:
                await require_system_model_admin(7, conn=conn)
            assert (caught.value.status, caught.value.code) == (
                403, "system_model_admin_required"
            )
    fetch.assert_awaited_once_with(
        "SELECT role FROM users WHERE id=%s" + (" FOR SHARE" if locked else ""),
        (7,),
        conn=conn,
    )


@pytest.mark.asyncio
async def test_admin_dependency_does_not_trust_stale_actor_or_cache_permission():
    actor = ActorContext(owner_id=7, role="admin")
    with patch("app.core.db.fetch_one", AsyncMock(side_effect=[
        {"role": "admin"}, {"role": "evaluator"}
    ])) as fetch:
        assert await get_admin(actor) is actor
        with pytest.raises(AppError) as caught:
            await get_admin(actor)
    assert (caught.value.status, caught.value.code) == (
        403, "system_model_admin_required"
    )
    assert fetch.await_count == 2
