import uuid

import pytest
import pytest_asyncio
from tests.platform.conftest import register_email_account


@pytest.mark.asyncio
async def test_registration_cookie_csrf_logout_and_password_hash(api):
    from app.core.db import fetch_one

    from app.services import email_verification as ev

    account = "reg_" + uuid.uuid4().hex[:12] + "@example.test"
    captured = {}

    def capture(addr, code, expires_in_seconds, settings=None):
        captured["code"] = code

    await ev.send_code(account, "testclient", transport=capture)
    response = await api.post(
        "/api/v1/auth/register",
        json={
            "account": account,
            "password": "Secret-random-135!",
            "verification_code": captured["code"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert len(data["recovery_code"]) >= 20
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    identity = await fetch_one(
        "SELECT password_hash,recovery_hash FROM auth_identities WHERE user_id=%s",
        (data["user"]["id"],),
    )
    assert identity["password_hash"].startswith("$argon2id$")
    assert data["recovery_code"] != identity["recovery_hash"]
    assert (await api.get("/api/v1/auth/session")).status_code == 200
    assert (await api.post("/api/v1/auth/logout")).status_code == 403
    headers = {"Origin": "http://testserver", "X-CSRF-Token": data["csrf_token"]}
    assert (await api.post("/api/v1/auth/logout", headers=headers)).status_code == 200
    assert (await api.get("/api/v1/auth/session")).status_code == 401


@pytest.mark.asyncio
async def test_legacy_login_records_app_scoped_identity_and_preserves_user(
    api, platform_settings, monkeypatch
):
    from app.core.auth import decode_token
    from app.core.db import fetch_one, insert
    from app.services import user_service

    openid = "legacy_" + uuid.uuid4().hex
    user_id = await insert(
        "INSERT INTO users(openid,nickname,total_xp) VALUES(%s,%s,73)",
        (openid, "旧学习者"),
    )
    platform_settings.wechat_app_id = "fixture-wechat-app"

    async def verified_code(code):
        return openid

    monkeypatch.setattr(user_service, "wx_code_to_openid", verified_code)
    response = await api.post("/api/v1/user/login", json={"code": "fixture-code"})
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["user"]["id"] == user_id and result["user"]["total_xp"] == 73
    identity = await fetch_one(
        "SELECT * FROM auth_identities WHERE provider='wechat' AND app_scope=%s AND subject=%s",
        ("fixture-wechat-app", openid),
    )
    assert identity and identity["user_id"] == user_id
    assert decode_token(result["token"])["app_scope"] == "fixture-wechat-app"
    api.headers["Authorization"] = "Bearer " + result["token"]
    assert (await api.get("/api/v1/user/profile")).status_code == 200
    platform_settings.wechat_app_id = "a-different-app"
    assert (await api.get("/api/v1/user/profile")).status_code == 401


@pytest.mark.asyncio
async def test_invalid_credentials_never_become_anonymous(api):
    response = await api.post(
        "/api/v1/quiz/generate/async",
        headers={"Authorization": "Bearer invalid"},
        json={"user_input": "光合作用", "question_count": 3},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_cross_site_writes_and_foreign_profile_assets_rejected(learner):
    api, data = learner
    response = await api.put(
        "/api/v1/user/profile",
        headers={"Origin": "https://evil.example"},
        json={"nickname": "Changed"},
    )
    assert response.status_code == 403
    response = await api.put(
        "/api/v1/user/profile",
        json={"avatar_url": "https://external.example/arbitrary.png"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_recovery_revokes_old_sessions_and_is_single_use(api):
    original, account = await register_email_account(
        api, password="Original-secure-135!"
    )
    cookie = api.cookies.get("xunke_session")
    payload = {
        "account": account,
        "recovery_code": original["recovery_code"],
        "new_password": "New-secure-9127!",
    }
    response = await api.post(
        "/api/v1/auth/recover", json=payload, headers={"Origin": "http://testserver"}
    )
    assert response.status_code == 200
    assert (
        await api.post(
            "/api/v1/auth/recover",
            json=payload,
            headers={"Origin": "http://testserver"},
        )
    ).status_code == 401
    api.cookies.clear()
    api.cookies.set("xunke_session", cookie)
    assert (await api.get("/api/v1/auth/session")).status_code == 401


@pytest_asyncio.fixture
async def legacy_identity_owner(database):
    from app.core.db import execute, insert

    owner = await insert(
        "INSERT INTO users(openid,nickname,total_xp) VALUES(%s,'旧用户',73)",
        ("bind_" + uuid.uuid4().hex,),
    )
    try:
        yield owner
    finally:
        # A failed concurrency regression must not leave duplicate identities
        # that would prevent the next test from applying the new constraint.
        for table in ("auth_sessions", "auth_link_codes", "auth_identities"):
            await execute(f"DELETE FROM {table} WHERE user_id=%s", (owner,))
        await execute("DELETE FROM users WHERE id=%s", (owner,))


@pytest.mark.asyncio
async def test_two_link_codes_cannot_create_two_password_identities(
    legacy_identity_owner, platform_settings, monkeypatch
):
    import asyncio

    from app.core.db import fetch_all
    from app.core.errors import AppError
    from app.models.auth import BindBody, LoginBody, PasswordBody
    from app.services import auth_service

    platform_settings.legacy_link_enabled = True
    platform_settings.wechat_app_id = "fixture-binding-app"
    owner = legacy_identity_owner
    from app.services import email_verification as ev

    codes = [await auth_service.link_code(owner) for _ in range(2)]
    requests = []
    for index, code in enumerate(codes):
        email = f"bind_{uuid.uuid4().hex[:16]}@example.test"
        captured = {}

        def capture(addr, code_, expires_in_seconds, settings=None, bag=captured):
            bag["code"] = code_

        await ev.send_code(email, "testclient", transport=capture)
        requests.append(
            BindBody(
                account=email,
                password=f"Bind-password-{index}-927!",
                code=code["code"],
                verification_code=captured["code"],
            )
        )
    original_fetch = auth_service.fetch_one
    both_codes_locked = asyncio.Barrier(2)

    async def synchronized_fetch(sql, args=(), *, conn=None):
        result = await original_fetch(sql, args, conn=conn)
        if sql.startswith("SELECT * FROM auth_link_codes"):
            # Distinct code rows may be locked concurrently. The owning user
            # must serialize the subsequent identity check and creation.
            await both_codes_locked.wait()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(auth_service, "fetch_one", synchronized_fetch)
        results = await asyncio.wait_for(
            asyncio.gather(
                *(auth_service.bind(body) for body in requests),
                return_exceptions=True,
            ),
            timeout=20,
        )
    successes = [
        index for index, result in enumerate(results) if isinstance(result, tuple)
    ]
    failures = [result for result in results if isinstance(result, BaseException)]
    outcomes = [type(result).__name__ for result in results]
    assert len(successes) == 1, outcomes
    assert len(failures) == 1 and isinstance(failures[0], AppError), outcomes
    assert failures[0].code == "registration_unavailable"
    winner, loser = requests[successes[0]], requests[1 - successes[0]]
    identities = await fetch_all(
        "SELECT subject FROM auth_identities WHERE user_id=%s AND provider='password'",
        (owner,),
    )
    assert identities == [{"subject": winner.account}]
    with pytest.raises(AppError) as rejected:
        await auth_service.login(
            LoginBody(account=loser.account, password=loser.password)
        )
    assert rejected.value.code == "invalid_credentials"
    await auth_service.change_password(
        owner,
        PasswordBody(
            current_password=winner.password, new_password="Changed-bind-password-729!"
        ),
    )
    with pytest.raises(AppError) as old_password:
        await auth_service.login(
            LoginBody(account=winner.account, password=winner.password)
        )
    assert old_password.value.code == "invalid_credentials"
    session, _ = await auth_service.login(
        LoginBody(account=winner.account, password="Changed-bind-password-729!")
    )
    assert session["user"]["id"] == owner and session["user"]["total_xp"] == 73


@pytest.mark.asyncio
async def test_password_identity_unique_constraint_preserves_wechat_app_scopes(
    legacy_identity_owner,
):
    from pymysql import IntegrityError

    from app.core.db import execute, fetch_all

    owner = legacy_identity_owner
    subject = "identity_" + uuid.uuid4().hex
    await execute(
        "INSERT INTO auth_identities(user_id,provider,app_scope,subject) VALUES(%s,'password','web',%s)",
        (owner, subject),
    )
    for scope in ("web", "another-web"):
        with pytest.raises(IntegrityError) as duplicate:
            await execute(
                "INSERT INTO auth_identities(user_id,provider,app_scope,subject) VALUES(%s,'password',%s,%s)",
                (owner, scope, subject + "_other"),
            )
        assert duplicate.value.args[0] == 1062
    for scope in ("wechat-app-one", "wechat-app-two"):
        await execute(
            "INSERT INTO auth_identities(user_id,provider,app_scope,subject) VALUES(%s,'wechat',%s,%s)",
            (owner, scope, subject),
        )
    rows = await fetch_all(
        "SELECT provider,app_scope FROM auth_identities WHERE user_id=%s ORDER BY provider,app_scope",
        (owner,),
    )
    assert rows == [
        {"provider": "password", "app_scope": "web"},
        {"provider": "wechat", "app_scope": "wechat-app-one"},
        {"provider": "wechat", "app_scope": "wechat-app-two"},
    ]
