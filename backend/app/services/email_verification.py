"""Registration-only email challenges and durable, atomic send budgets."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import secrets
from collections.abc import Callable
from datetime import timedelta

from app.core.config import Settings, get_settings
from app.core.db import execute, fetch_one, transaction
from app.core.errors import AppError
from app.core.values import digest, now
from app.models.auth import normalize_email
from app.services import mail_transport

logger = logging.getLogger(__name__)
PURPOSE = "register"
CODE_LIFETIME_SECONDS = 600
MAX_VERIFICATION_ATTEMPTS = 5
SEND_MESSAGE = "如该邮箱可用于注册，验证码将发送至邮箱，请检查收件箱和垃圾邮件"


def is_available(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return (
        settings.email_registration_enabled
        and len(settings.email_code_secret.strip()) >= 32
        and mail_transport.is_ready(settings)
    )


def require_available() -> Settings:
    settings = get_settings()
    if not is_available(settings):
        raise AppError(503, "email_registration_unavailable", "邮箱注册暂未开放")
    return settings


def registration_unavailable() -> AppError:
    return AppError(
        400, "registration_unavailable", "邮箱或验证码不可用，请检查输入或稍后重试"
    )


def rate_limited() -> AppError:
    return AppError(429, "rate_limited", "请求过于频繁，请稍后再试")


def _code_hash(email: str, generation: str, code: str, settings: Settings) -> str:
    # NUL separators make all components unambiguous; low-entropy codes need HMAC.
    value = "\0".join((email, PURPOSE, generation, code))
    return hmac.new(
        settings.email_code_secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _quota_specs(email: str, ip: str, at, settings: Settings):
    day = at.replace(hour=0, minute=0, second=0, microsecond=0)
    hour = at.replace(minute=0, second=0, microsecond=0)
    specs = [
        (
            "global_day",
            "global",
            day,
            timedelta(days=1),
            settings.email_send_daily_limit,
        ),
        (
            "email_day",
            email,
            day,
            timedelta(days=1),
            settings.email_send_max_per_email_per_day,
        ),
        (
            "ip_hour",
            ip,
            hour,
            timedelta(hours=1),
            settings.email_send_max_per_ip_per_hour,
        ),
    ]
    return sorted(
        [
            {
                "bucket_hash": digest(f"email-code:{scope}:{subject}"),
                "scope": scope,
                "window_start": start,
                "expires_at": start + duration,
                "limit": limit,
            }
            for scope, subject, start, duration, limit in specs
        ],
        key=lambda spec: spec["bucket_hash"],
    )


async def _reserve_quotas(email: str, ip: str, settings: Settings, *, conn):
    """All senders lock the same buckets in the same order, then reserve together."""
    buckets = {}
    for spec in _quota_specs(email, ip, now(), settings):
        await execute(
            "INSERT INTO auth_email_send_quotas"
            "(bucket_hash,scope,window_start,expires_at,attempts) VALUES(%s,%s,%s,%s,0) "
            "ON DUPLICATE KEY UPDATE bucket_hash=bucket_hash",
            (
                spec["bucket_hash"],
                spec["scope"],
                spec["window_start"],
                spec["expires_at"],
            ),
            conn=conn,
        )
        buckets[spec["bucket_hash"]] = await fetch_one(
            "SELECT * FROM auth_email_send_quotas WHERE bucket_hash=%s FOR UPDATE",
            (spec["bucket_hash"],),
            conn=conn,
        )

    # Locks may span a UTC boundary. Use one current timestamp after acquiring them.
    specs = _quota_specs(email, ip, now(), settings)
    for spec in specs:
        bucket = buckets[spec["bucket_hash"]]
        if bucket["window_start"] != spec["window_start"]:
            await execute(
                "UPDATE auth_email_send_quotas SET window_start=%s,expires_at=%s,"
                "attempts=0,warning_emitted_at=NULL WHERE bucket_hash=%s",
                (spec["window_start"], spec["expires_at"], spec["bucket_hash"]),
                conn=conn,
            )
            bucket["attempts"] = 0
            bucket["warning_emitted_at"] = None

    global_spec = next(spec for spec in specs if spec["scope"] == "global_day")
    global_bucket = buckets[global_spec["bucket_hash"]]
    if global_bucket["attempts"] >= global_spec["limit"]:
        warn = global_bucket["warning_emitted_at"] is None
        if warn:
            await execute(
                "UPDATE auth_email_send_quotas SET warning_emitted_at=%s "
                "WHERE bucket_hash=%s AND warning_emitted_at IS NULL",
                (now(), global_spec["bucket_hash"]),
                conn=conn,
            )
        return False, warn
    if any(buckets[spec["bucket_hash"]]["attempts"] >= spec["limit"] for spec in specs):
        return False, False
    for spec in specs:
        await execute(
            "UPDATE auth_email_send_quotas SET attempts=attempts+1 WHERE bucket_hash=%s",
            (spec["bucket_hash"],),
            conn=conn,
        )
    return True, False


async def _reserve_send(email, ip, generation, code_hash, settings):
    email_hash = digest(email)
    rejection = None
    warn = False
    expires_at = requested_at = None
    async with transaction() as conn:
        # The expired placeholder makes concurrent first sends lock the same row.
        await execute(
            "INSERT INTO auth_email_challenges"
            "(email_hash,purpose,generation,code_hash,status,attempts,expires_at) "
            "VALUES(%s,%s,'','','failed',0,%s) "
            "ON DUPLICATE KEY UPDATE email_hash=email_hash",
            (email_hash, PURPOSE, now()),
            conn=conn,
        )
        challenge = await fetch_one(
            "SELECT * FROM auth_email_challenges WHERE email_hash=%s AND purpose=%s FOR UPDATE",
            (email_hash, PURPOSE),
            conn=conn,
        )
        at = now()
        if (
            challenge["expires_at"] > at
            and challenge["attempts"] >= MAX_VERIFICATION_ATTEMPTS
        ):
            rejection = rate_limited()
        elif (
            challenge["last_requested_at"] is not None
            and challenge["last_requested_at"]
            + timedelta(seconds=settings.email_send_cooldown_seconds)
            > at
        ):
            rejection = rate_limited()
        else:
            reserved, warn = await _reserve_quotas(email, ip, settings, conn=conn)
            if not reserved:
                rejection = rate_limited()
            else:
                requested_at = now()
                active = challenge["expires_at"] > requested_at
                expires_at = (
                    challenge["expires_at"]
                    if active
                    else requested_at + timedelta(seconds=CODE_LIFETIME_SECONDS)
                )
                attempts = challenge["attempts"] if active else 0
                await execute(
                    "UPDATE auth_email_challenges SET generation=%s,code_hash=%s,"
                    "status='pending',attempts=%s,expires_at=%s,last_requested_at=%s,"
                    "consumed_at=NULL WHERE email_hash=%s AND purpose=%s",
                    (
                        generation,
                        code_hash,
                        attempts,
                        expires_at,
                        requested_at,
                        email_hash,
                        PURPOSE,
                    ),
                    conn=conn,
                )
    # These effects happen only after commit: quota warnings and rejections must
    # not roll back the database's once-per-day warning claim.
    if warn:
        logger.warning(
            "email_send_daily_limit_reached",
            extra={"event": "email_send_daily_limit_reached"},
        )
    if rejection is not None:
        raise rejection
    return expires_at, requested_at


async def _finish_delivery(email_hash: str, generation: str, status: str):
    return await execute(
        "UPDATE auth_email_challenges SET status=%s "
        "WHERE email_hash=%s AND purpose=%s AND generation=%s AND status='pending'",
        (status, email_hash, PURPOSE, generation),
    )


async def send_code(
    email: str, ip: str, *, transport: Callable[..., None] | None = None
) -> dict:
    settings = require_available()
    try:
        email = normalize_email(email)
    except ValueError:
        raise AppError(400, "invalid_email", "请输入有效的邮箱地址") from None
    generation = secrets.token_hex(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at, requested_at = await _reserve_send(
        email, ip, generation, _code_hash(email, generation, code, settings), settings
    )
    email_hash = digest(email)
    failed = False
    try:
        await asyncio.to_thread(
            transport or mail_transport.send_registration_email,
            email,
            code,
            max(0, math.ceil((expires_at - now()).total_seconds())),
            settings=settings,
        )
    except Exception as exc:
        failed = True
        if not isinstance(exc, AppError):
            logger.warning(
                "email_delivery_failed",
                extra={
                    "event": "email_delivery_failed",
                    "error_type": type(exc).__name__,
                },
            )
    if failed:
        # Leave the exception handler before writing state, so a DB failure
        # cannot accidentally chain a raw error from an injected transport.
        await _finish_delivery(email_hash, generation, "failed")
        raise mail_transport.delivery_error() from None
    await _finish_delivery(email_hash, generation, "sent")
    at = now()
    return {
        "message": SEND_MESSAGE,
        "retry_after_seconds": max(
            0,
            math.ceil(
                (requested_at - at).total_seconds()
                + settings.email_send_cooldown_seconds
            ),
        ),
        "expires_in_seconds": max(0, math.ceil((expires_at - at).total_seconds())),
    }


async def check_registration_code(email: str, code: str, *, conn):
    """Hold the challenge lock and return errors so failed attempts can commit."""
    settings = require_available()
    email = normalize_email(email)
    challenge = await fetch_one(
        "SELECT * FROM auth_email_challenges WHERE email_hash=%s AND purpose=%s FOR UPDATE",
        (digest(email), PURPOSE),
        conn=conn,
    )
    if not challenge or challenge["expires_at"] <= now():
        return None, registration_unavailable()
    if challenge["attempts"] >= MAX_VERIFICATION_ATTEMPTS:
        return None, rate_limited()
    if challenge["status"] != "sent":
        return None, registration_unavailable()
    if not hmac.compare_digest(
        challenge["code_hash"],
        _code_hash(email, challenge["generation"], code, settings),
    ):
        attempts = challenge["attempts"] + 1
        await execute(
            "UPDATE auth_email_challenges SET attempts=%s WHERE email_hash=%s AND purpose=%s",
            (attempts, challenge["email_hash"], PURPOSE),
            conn=conn,
        )
        error = (
            rate_limited()
            if attempts >= MAX_VERIFICATION_ATTEMPTS
            else registration_unavailable()
        )
        return None, error
    return challenge, None


async def consume_registration_code(challenge, *, conn):
    changed = await execute(
        "UPDATE auth_email_challenges SET status='consumed',consumed_at=%s "
        "WHERE email_hash=%s AND purpose=%s AND generation=%s AND status='sent'",
        (now(), challenge["email_hash"], PURPOSE, challenge["generation"]),
        conn=conn,
    )
    if changed != 1:
        raise registration_unavailable()
