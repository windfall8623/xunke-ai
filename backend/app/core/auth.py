"""JWT 鉴权模块"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt
import structlog
from fastapi import Depends, Request

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError

logger = structlog.get_logger()

ALGORITHM = "HS256"


def create_token(user_id: int, openid: str) -> str:
    """生成 JWT token。"""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "user_id": user_id,
        "openid": openid,
        "exp": expire,
    }
    if settings.wechat_app_id:
        payload["app_scope"] = settings.wechat_app_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """解析 JWT token，失败时抛出 AuthenticationError。"""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise AuthenticationError("无效的登录凭证")


def _extract_token(request: Request) -> str | None:
    """从请求 Header 中提取 Bearer token。"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


async def get_current_user(request: Request) -> int:
    """必选鉴权依赖，返回 user_id。未登录时抛出 AuthenticationError。"""
    return (await get_current_actor(request)).owner_id


async def get_optional_user(request: Request) -> int | None:
    """可选鉴权依赖，返回 user_id 或 None。不抛异常。"""
    if not request.headers.get("Authorization") and not request.cookies.get(
        get_settings().session_cookie_name
    ):
        return None
    return await get_current_user(request)


def verify_origin(request: Request):
    from app.core.errors import AppError

    if request.headers.get("origin") not in get_settings().web_origins:
        raise AppError(403, "origin_rejected", "请求来源不受信任")


async def get_current_actor(request: Request):
    from app.core.db import fetch_one
    from app.core.errors import AppError
    from app.core.values import digest
    from app.rag.contracts import ActorContext

    authorization = request.headers.get("Authorization")
    if authorization:
        token = _extract_token(request)
        if not token:
            raise AuthenticationError("无效的登录凭证")
        payload = decode_token(token)
        user_id = payload.get("user_id")
        if not isinstance(user_id, int) or user_id <= 0:
            raise AuthenticationError("无效的登录凭证")
        user = await fetch_one(
            "SELECT id,role,openid FROM users WHERE id=%s", (user_id,)
        )
        app_scope = payload.get("app_scope")
        if app_scope:
            identity = await fetch_one(
                "SELECT identity_id FROM auth_identities WHERE user_id=%s AND provider='wechat' AND app_scope=%s AND subject=%s",
                (user_id, app_scope, payload.get("openid")),
            )
            identity_valid = (
                app_scope == get_settings().wechat_app_id and identity is not None
            )
        else:
            identity_valid = (
                user and user["openid"] and user["openid"] == payload.get("openid")
            )
        if not user or not identity_valid:
            raise AuthenticationError("无效的登录凭证")
        request.state.auth_type = "bearer"
    else:
        token = request.cookies.get(get_settings().session_cookie_name)
        if not token:
            raise AuthenticationError()
        user = await fetch_one(
            "SELECT u.id,u.role,s.csrf_token FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>UTC_TIMESTAMP(6)",
            (digest(token),),
        )
        if not user:
            raise AuthenticationError("登录已过期，请重新登录")
        request.state.auth_type = "cookie"
        request.state.csrf_token = user["csrf_token"]
        request.state.session_hash = digest(token)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            verify_origin(request)
            if not secrets.compare_digest(
                request.headers.get("X-CSRF-Token", ""), user["csrf_token"]
            ):
                raise AppError(403, "csrf_rejected", "请求验证失败，请刷新页面")
    return ActorContext(owner_id=user["id"], roles=[user["role"]])


async def get_evaluator(actor=Depends(get_current_actor)):
    from app.core.errors import AppError

    if not {"evaluator", "admin"}.intersection(actor.roles):
        raise AppError(403, "evaluator_required", "需要评测维护权限")
    return actor


async def require_system_model_admin(owner_id, *, conn=None):
    """Recheck this owner's current role, without granting access to other owners.

    Transactional callers hold a shared user-row lock through scheduling or
    publication so a concurrent demotion cannot race the authorization check.
    """
    from app.core.db import fetch_one
    from app.core.errors import AppError

    user = await fetch_one(
        "SELECT role FROM users WHERE id=%s"
        + (" FOR SHARE" if conn is not None else ""),
        (owner_id,),
        conn=conn,
    )
    if not user or user.get("role") != "admin":
        raise AppError(
            403, "system_model_admin_required", "仅管理员可使用系统模型执行评测"
        )


async def get_admin(actor=Depends(get_current_actor)):
    await require_system_model_admin(actor.owner_id)
    return actor
