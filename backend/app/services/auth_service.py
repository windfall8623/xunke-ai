"""Server-side sessions and identity changes. Secrets are never persisted in clear."""

import asyncio
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pymysql import IntegrityError

from app.core.config import get_settings
from app.core.db import execute, fetch_one, insert, transaction
from app.core.errors import AppError, conflict
from app.core.values import digest, now

_passwords = PasswordHasher()
_dummy_hash = _passwords.hash("nonexistent-account-dummy-password")


def invalid_login():
    return AppError(401, "invalid_credentials", "账号或凭证无效")


async def verify_password(encoded, password):
    def check():
        try:
            return _passwords.verify(encoded or _dummy_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(check)


async def rate_limit(scope, subject, ip):
    # Limit both the source address and the account, without logging either.
    keys = sorted(
        [digest(f"{scope}:ip:{ip}"), digest(f"{scope}:account:{subject.lower()}")]
    )
    async with transaction() as conn:
        for key in keys:
            await execute(
                "INSERT INTO auth_rate_limits(bucket_hash,attempts,expires_at) VALUES(%s,0,%s) ON DUPLICATE KEY UPDATE bucket_hash=bucket_hash",
                (key, now() + timedelta(minutes=15)),
                conn=conn,
            )
            bucket = await fetch_one(
                "SELECT * FROM auth_rate_limits WHERE bucket_hash=%s FOR UPDATE",
                (key,),
                conn=conn,
            )
            attempts = bucket["attempts"] if bucket["expires_at"] > now() else 0
            if attempts >= get_settings().auth_rate_limit:
                raise AppError(429, "rate_limited", "请求过于频繁，请稍后再试")
            await execute(
                "UPDATE auth_rate_limits SET attempts=%s,expires_at=%s WHERE bucket_hash=%s",
                (
                    attempts + 1,
                    bucket["expires_at"] if attempts else now() + timedelta(minutes=15),
                    key,
                ),
                conn=conn,
            )


async def issue_session(user_id, *, conn):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    await execute(
        "INSERT INTO auth_sessions(token_hash,user_id,csrf_token,expires_at) VALUES(%s,%s,%s,%s)",
        (
            digest(token),
            user_id,
            csrf,
            now() + timedelta(days=get_settings().session_days),
        ),
        conn=conn,
    )
    user = await fetch_one(
        "SELECT id,nickname,avatar_url,total_xp,role FROM users WHERE id=%s",
        (user_id,),
        conn=conn,
    )
    return {"user": user, "csrf_token": csrf}, token


async def register(body, *, existing_user=None, conn=None):
    if conn is None:
        async with transaction() as tx:
            return await register(body, existing_user=existing_user, conn=tx)
    encoded = await asyncio.to_thread(_passwords.hash, body.password)
    recovery = secrets.token_urlsafe(32)
    try:
        user_id = existing_user or await insert(
            "INSERT INTO users(openid,nickname) VALUES(NULL,%s)",
            (body.nickname,),
            conn=conn,
        )
        await execute(
            "INSERT INTO auth_identities(user_id,provider,app_scope,subject,password_hash,recovery_hash) VALUES(%s,'password','web',%s,%s,%s)",
            (user_id, body.account, encoded, digest(recovery)),
            conn=conn,
        )
    except IntegrityError as exc:
        raise conflict("account_unavailable", "账号不可用，请选择其他账号") from exc
    result, token = await issue_session(user_id, conn=conn)
    result["recovery_code"] = recovery
    return result, token


async def login(body):
    identity = await fetch_one(
        "SELECT * FROM auth_identities WHERE provider='password' AND app_scope='web' AND subject=%s",
        (body.account,),
    )
    valid = await verify_password(
        identity["password_hash"] if identity else None, body.password
    )
    if not identity or not valid:
        raise invalid_login()
    async with transaction() as conn:
        # Prevent an old password verified concurrently with recovery from issuing a new session.
        locked = await fetch_one(
            "SELECT password_hash FROM auth_identities WHERE identity_id=%s FOR UPDATE",
            (identity["identity_id"],),
            conn=conn,
        )
        if locked["password_hash"] != identity["password_hash"]:
            raise invalid_login()
        return await issue_session(identity["user_id"], conn=conn)


async def recover(body):
    encoded = await asyncio.to_thread(_passwords.hash, body.new_password)
    next_code = secrets.token_urlsafe(32)
    async with transaction() as conn:
        identity = await fetch_one(
            "SELECT * FROM auth_identities WHERE provider='password' AND app_scope='web' AND subject=%s FOR UPDATE",
            (body.account.lower(),),
            conn=conn,
        )
        if not identity or not secrets.compare_digest(
            identity["recovery_hash"] or "", digest(body.recovery_code)
        ):
            raise invalid_login()
        await execute(
            "UPDATE auth_identities SET password_hash=%s,recovery_hash=%s WHERE identity_id=%s",
            (encoded, digest(next_code), identity["identity_id"]),
            conn=conn,
        )
        await execute(
            "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE user_id=%s AND revoked_at IS NULL",
            (identity["user_id"],),
            conn=conn,
        )
    return {"recovery_code": next_code}


async def change_password(user_id, body):
    async with transaction() as conn:
        identity = await fetch_one(
            "SELECT * FROM auth_identities WHERE user_id=%s AND provider='password' FOR UPDATE",
            (user_id,),
            conn=conn,
        )
        if not identity or not await verify_password(
            identity["password_hash"], body.current_password
        ):
            raise invalid_login()
        encoded = await asyncio.to_thread(_passwords.hash, body.new_password)
        await execute(
            "UPDATE auth_identities SET password_hash=%s WHERE identity_id=%s",
            (encoded, identity["identity_id"]),
            conn=conn,
        )
        await execute(
            "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE user_id=%s",
            (user_id,),
            conn=conn,
        )


async def link_code(user_id):
    if not get_settings().legacy_link_enabled:
        raise AppError(404, "feature_disabled", "未启用旧账号关联")
    code = secrets.token_urlsafe(32)
    await execute(
        "INSERT INTO auth_link_codes(code_hash,user_id,app_scope,expires_at) VALUES(%s,%s,%s,%s)",
        (
            digest(code),
            user_id,
            get_settings().wechat_app_id,
            now() + timedelta(minutes=5),
        ),
    )
    return {"code": code, "expires_in": 300}


async def bind(body):
    if not get_settings().legacy_link_enabled:
        raise AppError(404, "feature_disabled", "未启用旧账号关联")
    async with transaction() as conn:
        row = await fetch_one(
            "SELECT * FROM auth_link_codes WHERE code_hash=%s FOR UPDATE",
            (digest(body.code),),
            conn=conn,
        )
        if (
            not row
            or row["used_at"]
            or row["expires_at"] <= now()
            or row["app_scope"] != get_settings().wechat_app_id
        ):
            raise invalid_login()
        # A user can hold several valid link codes. Lock their shared owner
        # before the first consistent identity read, not only the redeemed code.
        user = await fetch_one(
            "SELECT id FROM users WHERE id=%s FOR UPDATE",
            (row["user_id"],),
            conn=conn,
        )
        if not user or row["expires_at"] <= now():
            raise invalid_login()
        exists = await fetch_one(
            "SELECT identity_id FROM auth_identities WHERE user_id=%s AND provider='password'",
            (row["user_id"],),
            conn=conn,
        )
        if exists:
            raise conflict("identity_already_bound", "此账号已有关联的网页身份")
        result = await register(body, existing_user=row["user_id"], conn=conn)
        await execute(
            "UPDATE auth_link_codes SET used_at=UTC_TIMESTAMP(6) WHERE code_hash=%s",
            (digest(body.code),),
            conn=conn,
        )
        return result
