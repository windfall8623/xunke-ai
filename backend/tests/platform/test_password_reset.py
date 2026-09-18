"""邮箱验证码找回密码：恢复码丢失时的兜底路径。"""

import uuid

import pytest
from tests.platform.conftest import register_email_account


async def send_reset_code(email: str) -> str:
    from app.services import email_verification as ev

    captured = {}

    def capture(addr, code, expires_in_seconds, settings=None):
        captured["code"] = code

    await ev.send_code(email, "testclient", purpose=ev.PURPOSE_RESET, transport=capture)
    return captured["code"]


@pytest.mark.asyncio
async def test_email_code_reset_logs_in_revokes_password_and_keeps_recovery(api):
    session, account = await register_email_account(api, password="Original-secure-135!")
    recovery_code = session["recovery_code"]
    code = await send_reset_code(account)

    response = await api.post(
        "/api/v1/auth/password/reset",
        json={
            "account": account,
            "verification_code": code,
            "new_password": "Reset-secure-9271!",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["user"]["nickname"]

    old_login = await api.post(
        "/api/v1/auth/login",
        json={"account": account, "password": "Original-secure-135!"},
        headers={"Origin": "http://testserver"},
    )
    assert old_login.status_code == 401
    new_login = await api.post(
        "/api/v1/auth/login",
        json={"account": account, "password": "Reset-secure-9271!"},
        headers={"Origin": "http://testserver"},
    )
    assert new_login.status_code == 200

    # 邮箱重置不轮换恢复码：它与密码是相互独立的凭证。
    recover = await api.post(
        "/api/v1/auth/recover",
        json={
            "account": account,
            "recovery_code": recovery_code,
            "new_password": "Recovered-secure-318!",
        },
        headers={"Origin": "http://testserver"},
    )
    assert recover.status_code == 200, recover.text


@pytest.mark.asyncio
async def test_reset_send_response_does_not_reveal_registration(api):
    """未知/未验证地址与真实发送返回同一 200 口径，不能用来枚举账号。"""
    from app.services import email_verification as ev

    stranger = f"s_{uuid.uuid4().hex[:12]}@example.test"
    stranger_response = await api.post(
        "/api/v1/auth/email-code",
        json={"email": stranger, "purpose": "password_reset"},
        headers={"Origin": "http://testserver"},
    )
    assert stranger_response.status_code == 200, stranger_response.text
    body = stranger_response.json()["data"]
    assert body["message"] == ev.RESET_MESSAGE
    assert set(body) == {"message", "retry_after_seconds", "expires_in_seconds"}


@pytest.mark.asyncio
async def test_wrong_reset_codes_consume_attempts(api):
    """错误验证码的失败计数必须随事务提交，耗尽后正确码也被拒绝。"""
    from app.services.email_verification import MAX_VERIFICATION_ATTEMPTS

    session, account = await register_email_account(api, password="Original-secure-135!")
    code = await send_reset_code(account)
    for _ in range(MAX_VERIFICATION_ATTEMPTS - 1):
        wrong = await api.post(
            "/api/v1/auth/password/reset",
            json={
                "account": account,
                "verification_code": "000000" if code != "000000" else "111111",
                "new_password": "Wrong-secure-000!",
            },
            headers={"Origin": "http://testserver"},
        )
        assert wrong.status_code == 400, wrong.text
        assert wrong.json()["error_code"] == "registration_unavailable"
    # 第 5 次错误命中尝试上限；此后即使持有正确代码也被拒绝，证明计数已提交。
    last_wrong = await api.post(
        "/api/v1/auth/password/reset",
        json={
            "account": account,
            "verification_code": "000000" if code != "000000" else "111111",
            "new_password": "Wrong-secure-000!",
        },
        headers={"Origin": "http://testserver"},
    )
    assert last_wrong.status_code == 429, last_wrong.text
    exhausted = await api.post(
        "/api/v1/auth/password/reset",
        json={
            "account": account,
            "verification_code": code,
            "new_password": "Reset-secure-9271!",
        },
        headers={"Origin": "http://testserver"},
    )
    assert exhausted.status_code == 429, exhausted.text


@pytest.mark.asyncio
async def test_reset_rejects_register_verification_code(api):
    """注册用途的验证码不能用于重置：challenge 按 purpose 隔离。"""
    from app.services import email_verification as ev

    email = f"u_{uuid.uuid4().hex[:16]}@example.test"
    captured = {}

    def capture(addr, code, expires_in_seconds, settings=None):
        captured["code"] = code

    await ev.send_code(email, "testclient", transport=capture)
    result = await api.post(
        "/api/v1/auth/register",
        json={
            "account": email,
            "password": "Registered-secure-135!",
            "verification_code": captured["code"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert result.status_code == 201, result.text

    response = await api.post(
        "/api/v1/auth/password/reset",
        json={
            "account": email,
            "verification_code": captured["code"],
            "new_password": "Cross-purpose-927!",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_reset_rejects_wrong_code(api):
    _, account = await register_email_account(api)
    code = await send_reset_code(account)
    wrong = "000000" if code != "000000" else "000001"
    response = await api.post(
        "/api/v1/auth/password/reset",
        json={
            "account": account,
            "verification_code": wrong,
            "new_password": "Wrong-code-9271!",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
