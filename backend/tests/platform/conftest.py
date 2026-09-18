"""Isolated MySQL integration fixtures; never use deployment credentials."""

import os
import re
import uuid

import httpx
import pytest
import pytest_asyncio


@pytest.fixture
def platform_settings(monkeypatch, tmp_path):
    database_name = os.environ.get("XUNKE_TEST_DATABASE", "yu_ai_learn_test")
    if not re.fullmatch(r"(?:yu_ai_learn_test(?:_[a-z0-9_]+)?|xunke_test_[a-z0-9_]+)", database_name):
        raise ValueError("XUNKE_TEST_DATABASE must name an isolated yu_ai_learn_test or xunke_test_ database")
    values = {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": "13316",
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": "yu-local-test",
        "MYSQL_DATABASE": database_name,
        "MYSQL_AUTO_INIT": "false",
        "APP_ENV": "test",
        "COOKIE_SECURE": "false",
        "AUTH_RATE_LIMIT": "10000",
        "JWT_SECRET": "isolated-local-test-jwt-key-32-characters",
        "WEB_ORIGINS": '["http://testserver"]',
        "DATA_DIR": str(tmp_path),
        "EVAL_WORKER_TOKEN": "test-worker-token-32-characters-long",
        "ENABLE_WEB_SEARCH": "false",
        "LLM_PROVIDER": "deepseek",
        "ANTHROPIC_API_KEY": "",
        "LLM_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "DASHSCOPE_API_KEY": "",
        "DASHSCOPE_IMAGE_API_KEY": "",
        "TAVILY_API_KEY": "",
        "RERANKER_API_KEY": "",
        "EVAL_JUDGE_API_KEY": "",
        "EVAL_JUDGE_CONFIG_PATH": "",
        "EMAIL_CODE_SECRET": "isolated-local-test-email-secret-32ch",
        "SMTP_HOST": "smtp.test.local",
        "SMTP_USERNAME": "no-reply@test.local",
        "SMTP_PASSWORD": "test-smtp-password",
        "SMTP_FROM_EMAIL": "no-reply@test.local",
        "EMAIL_SEND_COOLDOWN_SECONDS": "60",
        "EMAIL_SEND_MAX_PER_EMAIL_PER_DAY": "1000",
        "EMAIL_SEND_MAX_PER_IP_PER_HOUR": "100000",
        "EMAIL_SEND_DAILY_LIMIT": "100000",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    from app.core.config import Settings, get_settings

    # Tests use synthetic providers even when the checkout has a deployment .env.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def database(platform_settings):
    from app.core.db import close_mysql_pool, init_pool
    from app.core.migrations import migrate

    await init_pool()
    try:
        await migrate()
        yield
    finally:
        await close_mysql_pool()


@pytest_asyncio.fixture
async def api(database):
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


async def register_email_account(
    api, *, password="Correct-Horse-927!", nickname="测试学习者", email=None
):
    """Email-era registration: captures the verification code in-process."""
    from app.services import email_verification as ev

    email = email or f"u_{uuid.uuid4().hex[:16]}@example.test"
    captured = {}

    def capture(email, code, expires_in_seconds, settings=None):
        captured["code"] = code

    await ev.send_code(email, "testclient", transport=capture)
    assert captured.get("code"), "验证码未被捕获"

    result = await api.post(
        "/api/v1/auth/register",
        json={
            "account": email,
            "password": password,
            "nickname": nickname,
            "verification_code": captured["code"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert result.status_code == 201, result.text
    return result.json()["data"], email


async def install_personal_model(owner_id, *, model="synthetic-personal-model", base_url="https://provider.example/v1"):
    """Install test-only encrypted credentials without a provider probe or request."""
    from app.core.config import get_settings
    from app.core.db import execute
    from app.core.user_llm_crypto import encrypt_api_key

    settings = get_settings()
    settings.user_llm_key_secret = "isolated-personal-model-crypto-secret-32-characters"
    await execute(
        "INSERT INTO user_llm_configs(owner_id,provider,model,base_url,api_key_cipher) "
        "VALUES(%s,'openai_compatible',%s,%s,%s) ON DUPLICATE KEY UPDATE "
        "provider=VALUES(provider),model=VALUES(model),base_url=VALUES(base_url),api_key_cipher=VALUES(api_key_cipher)",
        (owner_id, model, base_url, encrypt_api_key("synthetic-personal-key-1234", owner_id, settings)),
    )


@pytest_asyncio.fixture
async def personal_learner(learner):
    await install_personal_model(learner[1]["user"]["id"])
    return learner


@pytest_asyncio.fixture
async def learner(api):
    session, _ = await register_email_account(api)
    api.headers.update(
        {"X-CSRF-Token": session["csrf_token"], "Origin": "http://testserver"}
    )
    return api, session
