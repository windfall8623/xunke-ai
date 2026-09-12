"""可选 Redis 运行时：共享命令池、熔断与降级状态。

Redis 只承担短窗限流与提交后通知的加速职责。初始化失败或运行期故障都
按"不可用"降级，由调用方退回原 SQL 路径；只有启用开关但缺少密码这类
配置错误才在启动时明确报错。状态输出不包含地址、密码或完整连接串。
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Awaitable, Callable

import structlog
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import NoScriptError
from redis.exceptions import TimeoutError as RedisTimeoutError
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = structlog.get_logger()


class RedisUnavailable(Exception):
    """Redis 不可用（未启用、熔断或操作失败）：调用方按降级处理。"""


# 连续 3 次基础设施错误后熔断约 30 秒（含少量抖动）；半开状态只允许一个探测。
_FAILURE_THRESHOLD = 3
_OPEN_SECONDS = 30.0
_OPEN_JITTER = 0.2


class _CircuitBreaker:
    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._open_until = 0.0
        self._probe_in_flight = False

    @property
    def state(self) -> str:
        if self._probe_in_flight:
            return "half_open"
        if time.monotonic() < self._open_until:
            return "open"
        if self._consecutive_failures >= _FAILURE_THRESHOLD:
            return "half_open"
        return "closed"

    def allow(self) -> bool:
        now = time.monotonic()
        if now < self._open_until:
            return False
        if self._consecutive_failures >= _FAILURE_THRESHOLD:
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._open_until = 0.0
        self._probe_in_flight = False

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        self._probe_in_flight = False
        if self._consecutive_failures >= _FAILURE_THRESHOLD:
            delay = _OPEN_SECONDS * (1 + random.uniform(0, _OPEN_JITTER))
            self._open_until = time.monotonic() + delay

    def cancel_probe(self) -> None:
        # 探测请求被取消（如进程关闭）时释放半开名额，避免熔断永久卡在半开。
        self._probe_in_flight = False


class _RedisRuntime:
    def __init__(self) -> None:
        self._client: Redis | None = None
        self._breaker = _CircuitBreaker()
        self._available = False

    async def start(self) -> None:
        if self._client is not None:
            return
        settings = get_settings()
        if not settings.redis_enabled:
            return
        if not settings.redis_password:
            # 配置错误必须显式失败；这与网络失败降级是两类问题。
            raise RuntimeError("REDIS_ENABLED is set but REDIS_PASSWORD is empty")
        self._breaker = _CircuitBreaker()
        self._client = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password,
            ssl=settings.redis_tls,
            max_connections=settings.redis_max_connections,
            socket_connect_timeout=settings.redis_connect_timeout_ms / 1000,
            socket_timeout=settings.redis_command_timeout_ms / 1000,
            retry=Retry(NoBackoff(), 0),
        )
        try:
            await self.execute(lambda client: client.ping())
        except RedisUnavailable:
            # 连接池本身可重连；保留同一池，让后续操作按熔断规则恢复。
            # 启动探测也计入连续故障，不能因一次启动失败永久停用 Redis。
            logger.warning("redis_init_degraded")
            return
        except BaseException:
            # 启动取消/异常时 runtime 尚未交给 lifespan，仍需释放已创建的池。
            await self.close()
            raise
        logger.info("redis_initialized")

    async def execute(
        self, operation: Callable[[Redis], Awaitable[Any]], *, budget_ms: int | None = None
    ) -> Any:
        """在熔断与总预算约束下执行一个 Redis 操作。

        成功返回操作结果；基础设施失败抛 RedisUnavailable 并计入熔断。
        NOSCRIPT 属于可恢复状态：不计熔断，由调用方装载脚本后重试一次。
        """
        client = self._client
        if client is None:
            raise RedisUnavailable("redis-not-available")
        if not self._breaker.allow():
            raise RedisUnavailable("circuit-open")
        settings = get_settings()
        budget = (
            settings.redis_operation_timeout_ms if budget_ms is None else budget_ms
        ) / 1000
        try:
            result = await asyncio.wait_for(operation(client), timeout=budget)
        except NoScriptError:
            self._breaker.record_success()
            self._available = True
            raise
        except asyncio.CancelledError:
            self._breaker.cancel_probe()
            raise
        except (RedisConnectionError, RedisTimeoutError, asyncio.TimeoutError, OSError) as exc:
            self._breaker.record_failure()
            self._available = False
            logger.warning(
                "redis_operation_degraded", reason="network", error_type=type(exc).__name__
            )
            raise RedisUnavailable("redis-network-error") from None
        except RedisError as exc:
            # OOM、脚本契约错误等：同样按操作不可用降级，不让 Redis 带垮 SQL 路径。
            self._breaker.record_failure()
            self._available = False
            logger.warning(
                "redis_operation_degraded", reason="server", error_type=type(exc).__name__
            )
            raise RedisUnavailable("redis-server-error") from None
        except Exception:
            self._breaker.cancel_probe()
            raise
        self._breaker.record_success()
        self._available = True
        return result

    async def close(self) -> None:
        client, self._client = self._client, None
        self._available = False
        if client is not None:
            await _aclose_quietly(client)

    @property
    def status(self) -> dict[str, str | bool]:
        settings = get_settings()
        circuit = self._breaker.state
        return {
            "enabled": settings.redis_enabled,
            "available": self._client is not None and self._available and circuit != "open",
            "circuit": circuit,
        }


async def _aclose_quietly(client: Redis) -> None:
    try:
        await client.aclose()
    except Exception:  # noqa: BLE001 - 关闭路径不再抛出
        pass


_runtime: _RedisRuntime | None = None


async def init_redis() -> None:
    """FastAPI lifespan 与 worker 启动时调用；网络失败记录为降级。"""
    global _runtime
    if _runtime is not None:
        return
    runtime = _RedisRuntime()
    await runtime.start()
    _runtime = runtime


async def close_redis() -> None:
    global _runtime
    if _runtime is not None:
        await _runtime.close()
        _runtime = None


def redis_status() -> dict[str, str | bool]:
    if _runtime is None:
        return {
            "enabled": get_settings().redis_enabled,
            "available": False,
            "circuit": "closed",
        }
    return _runtime.status


async def execute(
    operation: Callable[[Redis], Awaitable[Any]], *, budget_ms: int | None = None
) -> Any:
    if _runtime is None:
        raise RedisUnavailable("redis-not-initialized")
    return await _runtime.execute(operation, budget_ms=budget_ms)
