"""共享短窗限流（R01）：键派生、Lua 语义、降级与配置校验。

Lua 语义用例需要真实 Redis：默认连接 127.0.0.1:16379（REDIS_TEST_PORT 可覆盖），
不可达时自动跳过；完整 C1/C2 验收由 Docker 栈上的检查脚本承担。
"""

import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from redis import asyncio as aioredis
from redis.exceptions import RedisError

from app.core import redis_client
from app.core.config import Settings
from app.core.errors import AppError
from app.services import rate_limit_service as rls

TEST_REDIS_HOST = "127.0.0.1"
TEST_REDIS_PORT = int(os.environ.get("REDIS_TEST_PORT", "16379"))
TEST_REDIS_PREFIX = "xunke:test:v1"
TEST_REDIS_PASSWORD = "xunke-test-redis-password-0123456789"

pytestmark = pytest.mark.asyncio


def make_settings(**overrides):
    base = dict(
        redis_enabled=True,
        redis_rate_limit_enabled=True,
        redis_key_prefix=TEST_REDIS_PREFIX,
        jwt_secret="test-only-jwt-secret-at-least-32-characters",
        redis_host=TEST_REDIS_HOST,
        redis_port=TEST_REDIS_PORT,
        redis_db=0,
        redis_password="xunke-test-redis-password-0123456789",
        redis_tls=False,
        redis_connect_timeout_ms=100,
        redis_command_timeout_ms=100,
        redis_operation_timeout_ms=200,
        redis_max_connections=16,
        auth_burst_window_seconds=60,
        auth_burst_max_per_ip=20,
        auth_burst_max_per_account=10,
        email_burst_window_seconds=60,
        email_burst_max_per_ip=10,
        email_burst_max_per_account=3,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def settings_factory(monkeypatch):
    def install(**overrides):
        settings = make_settings(**overrides)
        monkeypatch.setattr(rls, "get_settings", lambda: settings)
        monkeypatch.setattr(redis_client, "get_settings", lambda: settings)
        return settings

    return install


@pytest.fixture(autouse=True)
def reset_state():
    rls._derived_key = None
    yield
    rls._derived_key = None


class TestBurstKeyDerivation:
    def test_key_never_contains_plaintext_subject(self, settings_factory):
        settings_factory()
        policy = rls.auth_burst_policy(make_settings())
        key = rls.burst_key(policy, "ip", "192.168.1.44")
        assert "192.168.1.44" not in key
        assert key.startswith(f"{TEST_REDIS_PREFIX}:rl:burst-v1:auth:ip:")
        assert len(key.split(":")[-1]) == 64

    def test_same_subject_is_deterministic_across_resets(self, settings_factory):
        settings_factory()
        policy = rls.auth_burst_policy(make_settings())
        first = rls.burst_key(policy, "account", "user@example.com")
        rls._derived_key = None
        assert rls.burst_key(policy, "account", "user@example.com") == first

    def test_enforce_path_normalizes_account_before_keying(self, settings_factory, monkeypatch):
        settings = settings_factory()
        captured = {}

        class FakeClient:
            async def evalsha(self, sha, numkeys, *args):
                captured["keys"] = tuple(args[:numkeys])
                return [1, 0]

        async def run_on_fake(operation, *, budget_ms=None):
            return await operation(FakeClient())

        monkeypatch.setattr(rls, "execute", run_on_fake)
        policy = rls.auth_burst_policy(settings)
        import asyncio

        asyncio.run(rls.enforce_auth_burst("  User@Example.com ", "1.1.1.1"))
        expected = rls.burst_key(policy, "account", "user@example.com")
        ip_key = rls.burst_key(policy, "ip", "1.1.1.1")
        assert expected in captured["keys"] and ip_key in captured["keys"]
        assert "User@Example.com" not in str(captured["keys"])

    def test_scopes_and_kinds_produce_distinct_keys(self, settings_factory):
        settings_factory()
        auth = rls.auth_burst_policy(make_settings())
        email = rls.email_burst_policy(make_settings())
        assert rls.burst_key(auth, "ip", "a@b.com") != rls.burst_key(email, "ip", "a@b.com")
        assert rls.burst_key(auth, "ip", "a@b.com") != rls.burst_key(auth, "account", "a@b.com")


class TestDisabledAndDegraded:
    async def test_disabled_when_switches_off(self, settings_factory, monkeypatch):
        settings_factory(redis_enabled=False, redis_rate_limit_enabled=True)
        called = False

        async def fail(client):
            nonlocal called
            called = True

        monkeypatch.setattr(rls, "execute", fail)
        decision = await rls.check_burst("auth", "1.1.1.1", "a@b.com", policy=rls.auth_burst_policy(make_settings()))
        assert decision.source == "disabled" and decision.allowed and not called

    async def test_degraded_when_redis_unavailable(self, settings_factory, monkeypatch):
        settings_factory()

        async def unavailable(operation, *, budget_ms=None):
            raise redis_client.RedisUnavailable("redis-network-error")

        monkeypatch.setattr(rls, "execute", unavailable)
        decision = await rls.check_burst(
            "auth", "1.1.1.1", "a@b.com", policy=rls.auth_burst_policy(make_settings())
        )
        assert decision.source == "degraded" and decision.allowed

    async def test_enforce_burst_denied_raises_429_with_retry_after(self, settings_factory, monkeypatch):
        settings_factory()

        async def denied(operation, *, budget_ms=None):
            return [0, 45000]

        monkeypatch.setattr(rls, "execute", denied)
        with pytest.raises(AppError) as exc:
            await rls.enforce_auth_burst("a@b.com", "1.1.1.1")
        assert exc.value.status == 429
        assert exc.value.code == "rate_limited"
        assert exc.value.retry_after_seconds == 45

    async def test_enforce_burst_allowed_and_disabled_do_not_raise(self, settings_factory, monkeypatch):
        settings_factory()

        async def allowed(operation, *, budget_ms=None):
            return [1, 0]

        monkeypatch.setattr(rls, "execute", allowed)
        await rls.enforce_auth_burst("a@b.com", "1.1.1.1")

        settings_factory(redis_enabled=False)
        await rls.enforce_auth_burst("a@b.com", "1.1.1.1")


class TestCircuitBreaker:
    def test_opens_after_three_consecutive_failures(self):
        breaker = redis_client._CircuitBreaker()
        assert breaker.allow() and breaker.state == "closed"
        for _ in range(3):
            assert breaker.allow()
            breaker.record_failure()
        assert not breaker.allow()
        assert breaker.state == "open"

    def test_half_open_admits_single_probe_and_recovers(self):
        breaker = redis_client._CircuitBreaker()
        for _ in range(3):
            breaker.record_failure()
        breaker._open_until = 0.0
        assert breaker.allow() and breaker.state == "half_open"
        assert not breaker.allow()
        breaker.record_success()
        assert breaker.state == "closed"
        assert breaker.allow()

    def test_failed_probe_reopens(self):
        breaker = redis_client._CircuitBreaker()
        for _ in range(3):
            breaker.record_failure()
        breaker._open_until = 0.0
        assert breaker.allow()
        breaker.record_failure()
        assert not breaker.allow()
        assert breaker.state == "open"


class TestConfigValidation:
    def test_enabled_requires_password(self):
        with pytest.raises(ValueError):
            Settings(redis_enabled=True, redis_password="", _env_file=None)

    def test_disabled_without_password_is_valid(self):
        settings = Settings(redis_enabled=False, _env_file=None)
        assert settings.redis_enabled is False


def _live_redis_available() -> bool:
    import asyncio

    async def probe():
        client = aioredis.Redis(
            host=TEST_REDIS_HOST, port=TEST_REDIS_PORT, password=TEST_REDIS_PASSWORD,
            socket_connect_timeout=0.3, socket_timeout=0.5,
        )
        try:
            return bool(await client.ping())
        except Exception:
            return False
        finally:
            await client.aclose()

    try:
        return asyncio.run(probe())
    except Exception:
        return False


live_redis = pytest.mark.skipif(
    not _live_redis_available(), reason="本机 16379 端口没有可用的测试 Redis"
)


@pytest_asyncio.fixture
async def live_runtime(settings_factory):
    settings = settings_factory()
    runtime = redis_client._RedisRuntime()
    await runtime.start()
    assert runtime.status["available"], "测试 Redis PING 失败"
    redis_client._runtime = runtime
    yield runtime, settings
    await runtime.close()
    redis_client._runtime = None


@live_redis
class TestLuaSemanticsAgainstLiveRedis:
    async def test_window_allows_exact_limit_then_denies_with_retry_after(self, live_runtime):
        runtime, settings = live_runtime
        policy = rls.BurstPolicy(scope="auth", window_seconds=60, max_per_ip=3, max_per_account=100)
        unique_ip = f"10.0.0.{id(policy) % 200 + 1}"
        for _ in range(3):
            decision = await rls.check_burst("auth", unique_ip, None, policy=policy)
            assert decision.allowed and decision.source == "redis"
        denied = await rls.check_burst("auth", unique_ip, None, policy=policy)
        assert not denied.allowed and denied.source == "redis"
        assert 1 <= denied.retry_after_seconds <= 60

    async def test_first_write_sets_ttl_and_never_renews(self, live_runtime):
        runtime, settings = live_runtime
        policy = rls.BurstPolicy(scope="auth", window_seconds=60, max_per_ip=100, max_per_account=100)
        unique_ip = f"10.0.1.{id(policy) % 200 + 1}"
        await rls.check_burst("auth", unique_ip, None, policy=policy)
        key = rls.burst_key(policy, "ip", unique_ip)
        client = runtime._client
        first_ttl = await client.pttl(key)
        assert 0 < first_ttl <= 60000
        for _ in range(10):
            await rls.check_burst("auth", unique_ip, None, policy=policy)
        assert await client.pttl(key) <= first_ttl

    async def test_full_bucket_does_not_consume_the_other(self, live_runtime):
        runtime, settings = live_runtime
        policy = rls.BurstPolicy(scope="auth", window_seconds=60, max_per_ip=1, max_per_account=5)
        unique_ip = f"10.0.2.{id(policy) % 200 + 1}"
        account = f"bucket-{id(policy) % 999}@example.com"
        assert (await rls.check_burst("auth", unique_ip, account, policy=policy)).allowed
        second = await rls.check_burst("auth", unique_ip, account, policy=policy)
        assert not second.allowed
        client = runtime._client
        account_key = rls.burst_key(policy, "account", account)
        assert int(await client.get(account_key)) == 1

    async def test_persistent_key_degrades_instead_of_failing(self, live_runtime):
        runtime, settings = live_runtime
        policy = rls.BurstPolicy(scope="auth", window_seconds=60, max_per_ip=5, max_per_account=5)
        unique_ip = f"10.0.3.{id(policy) % 200 + 1}"
        key = rls.burst_key(policy, "ip", unique_ip)
        await runtime._client.set(key, 5)
        decision = await rls.check_burst("auth", unique_ip, None, policy=policy)
        assert decision.allowed and decision.source == "degraded"

    async def test_script_error_counts_toward_circuit(self, live_runtime, monkeypatch):
        runtime, settings = live_runtime

        async def broken(client):
            raise RedisError("OOM command not allowed when used memory > 'maxmemory'")

        with pytest.raises(redis_client.RedisUnavailable):
            await runtime.execute(broken)
        assert runtime.status["circuit"] in ("open", "closed")
