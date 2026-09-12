"""共享突发短窗限流：Redis 快速门槛，原 SQL 硬限制始终执行。

新门槛只统计"进入后续 SQL 检查的请求"。Redis 拒绝的请求不再访问 SQL；
Redis 放行仍须 SQL 放行；disabled/degraded 一律继续原 SQL 检查。
正常返回的限流拒绝不计为基础设施错误，两侧计数互不替代。
"""

from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog
from redis.exceptions import NoScriptError

from app.core.config import Settings, get_settings
from app.core.errors import rate_limited
from app.core.redis_client import RedisUnavailable, execute

logger = structlog.get_logger()

_SCRIPT = (Path(__file__).with_name("lua") / "burst_limit.lua").read_text(encoding="utf-8")
_SCRIPT_SHA1 = hashlib.sha1(_SCRIPT.encode("utf-8")).hexdigest()

# 键派生：先以 JWT_SECRET 对固定用途串派生 HMAC 密钥（仅进程内），再对主体做 HMAC。
# Redis 键中不出现明文邮箱/IP；密钥轮换会重建短窗桶，但不影响 SQL 硬限制。
_KEY_PURPOSE = b"xunke/redis-rate-key/v1"
_derived_key: bytes | None = None


@dataclass(frozen=True)
class BurstPolicy:
    scope: str  # 服务端固定枚举，不接受客户端输入
    window_seconds: int
    max_per_ip: int
    max_per_account: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int
    source: Literal["redis", "disabled", "degraded"]


def auth_burst_policy(settings: Settings) -> BurstPolicy:
    return BurstPolicy(
        scope="auth",
        window_seconds=settings.auth_burst_window_seconds,
        max_per_ip=settings.auth_burst_max_per_ip,
        max_per_account=settings.auth_burst_max_per_account,
    )


def email_burst_policy(settings: Settings) -> BurstPolicy:
    return BurstPolicy(
        scope="email_code",
        window_seconds=settings.email_burst_window_seconds,
        max_per_ip=settings.email_burst_max_per_ip,
        max_per_account=settings.email_burst_max_per_account,
    )


def _subject_mac(subject: str) -> str:
    global _derived_key
    if _derived_key is None:
        secret = get_settings().jwt_secret.encode("utf-8")
        _derived_key = hmac.new(secret, _KEY_PURPOSE, hashlib.sha256).digest()
    return hmac.new(_derived_key, subject.encode("utf-8"), hashlib.sha256).hexdigest()


def burst_key(policy: BurstPolicy, kind: str, subject: str) -> str:
    settings = get_settings()
    return (
        f"{settings.redis_key_prefix}:rl:burst-v1:{policy.scope}:{kind}:"
        f"{_subject_mac(subject)}"
    )


async def check_burst(
    scope: str,
    ip: str,
    account: str | None,
    *,
    policy: BurstPolicy,
) -> RateLimitDecision:
    """一次 Lua 原子检查 IP 与账户两个桶；任一满则拒绝且不消耗另一桶。"""
    settings = get_settings()
    if not (settings.redis_enabled and settings.redis_rate_limit_enabled):
        return RateLimitDecision(True, 0, "disabled")
    buckets = [(burst_key(policy, "ip", ip), policy.max_per_ip)]
    if account:
        buckets.append((burst_key(policy, "account", account), policy.max_per_account))
    buckets.sort()
    keys = [key for key, _ in buckets]
    arguments = [str(limit) for _, limit in buckets] + [
        str(policy.window_seconds * 1000)
    ]

    async def run(client):
        try:
            return await client.evalsha(_SCRIPT_SHA1, len(keys), *keys, *arguments)
        except NoScriptError:
            # 只有确认脚本尚未缓存才装载一次并重试。
            return await client.eval(_SCRIPT, len(keys), *keys, *arguments)

    try:
        result = await execute(run)
    except RedisUnavailable:
        return RateLimitDecision(True, 0, "degraded")
    allowed_flag, retry_after_ms = int(result[0]), int(result[1])
    if allowed_flag == 1:
        return RateLimitDecision(True, 0, "redis")
    return RateLimitDecision(False, max(1, math.ceil(retry_after_ms / 1000)), "redis")


async def enforce_burst(
    account: str | None, ip: str, *, policy: BurstPolicy
) -> None:
    """统一入口：仅 source=redis 且拒绝时抛 429；其余继续原 SQL 硬检查。"""
    decision = await check_burst(policy.scope, ip, account, policy=policy)
    if decision.source == "redis" and not decision.allowed:
        logger.info(
            "burst_limit_rejected",
            scope=policy.scope,
            retry_after_seconds=decision.retry_after_seconds,
        )
        raise rate_limited(decision.retry_after_seconds)


async def enforce_auth_burst(account: str, ip: str) -> None:
    account = account.strip().lower()
    await enforce_burst(account, ip, policy=auth_burst_policy(get_settings()))


async def enforce_email_burst(email: str, ip: str) -> None:
    # 调用方已完成邮箱规范化；此处不再改变主体形式。
    await enforce_burst(email, ip, policy=email_burst_policy(get_settings()))
