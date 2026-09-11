"""用户服务"""

from __future__ import annotations

import httpx
import structlog

from app.core.auth import create_token
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.models.user import LoginResponse, UserBrief, UserProfile
from app.repositories import quiz_repository, user_repository

logger = structlog.get_logger()

WX_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


async def wx_code_to_openid(code: str) -> str:
    """调用微信 jscode2session 获取 openid。"""
    settings = get_settings()
    if not settings.wechat_app_id or not settings.wechat_app_secret:
        raise AuthenticationError("微信登录未配置")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                WX_CODE2SESSION_URL,
                params={
                    "appid": settings.wechat_app_id,
                    "secret": settings.wechat_app_secret,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.error("wx_login_request_failed", error_type=type(exc).__name__)
        raise AuthenticationError("微信登录服务暂时不可用，请稍后重试") from exc
    except ValueError as exc:  # resp.json() 解析失败
        logger.error("wx_login_invalid_response", error_type=type(exc).__name__)
        raise AuthenticationError("微信登录失败，请重试") from exc

    if "openid" not in data:
        logger.error(
            "wx_login_failed",
            errcode=data.get("errcode"),
            errmsg=data.get("errmsg"),
            appid=settings.wechat_app_id,
        )
        raise AuthenticationError("微信登录失败，请重试")

    return data["openid"]


async def handle_login(code: str) -> LoginResponse:
    """微信登录：code -> openid -> 查/建用户 -> JWT。"""
    openid = await wx_code_to_openid(code)
    from pymysql import IntegrityError

    from app.core.db import execute, fetch_one, insert, transaction

    app_scope = get_settings().wechat_app_id
    if not app_scope:
        raise AuthenticationError("微信登录未配置")
    try:
        async with transaction() as conn:
            identity = await fetch_one(
                "SELECT user_id FROM auth_identities WHERE provider='wechat' AND app_scope=%s AND subject=%s FOR UPDATE",
                (app_scope, openid),
                conn=conn,
            )
            if identity:
                user_id = identity["user_id"]
            else:
                legacy = await fetch_one(
                    "SELECT id FROM users WHERE openid=%s FOR UPDATE",
                    (openid,),
                    conn=conn,
                )
                claimed = (
                    await fetch_one(
                        "SELECT identity_id FROM auth_identities WHERE provider='wechat' AND user_id=%s",
                        (legacy["id"],),
                        conn=conn,
                    )
                    if legacy
                    else None
                )
                user_id = (
                    legacy["id"]
                    if legacy and not claimed
                    else await insert(
                        "INSERT INTO users(openid) VALUES(NULL)", conn=conn
                    )
                )
                await execute(
                    "INSERT INTO auth_identities(user_id,provider,app_scope,subject) VALUES(%s,'wechat',%s,%s)",
                    (user_id, app_scope, openid),
                    conn=conn,
                )
            user = await fetch_one(
                "SELECT id,nickname,avatar_url,total_xp FROM users WHERE id=%s",
                (user_id,),
                conn=conn,
            )
    except IntegrityError:
        identity = await fetch_one(
            "SELECT user_id FROM auth_identities WHERE provider='wechat' AND app_scope=%s AND subject=%s",
            (app_scope, openid),
        )
        if not identity:
            raise
        user = await fetch_one(
            "SELECT id,nickname,avatar_url,total_xp FROM users WHERE id=%s",
            (identity["user_id"],),
        )

    token = create_token(user_id=user["id"], openid=openid)

    return LoginResponse(
        token=token,
        user=UserBrief(
            id=user["id"],
            nickname=user["nickname"],
            avatar_url=user["avatar_url"],
            total_xp=user["total_xp"],
        ),
    )


async def get_profile(user_id: int) -> UserProfile:
    """获取用户档案，含统计聚合。"""
    user = await user_repository.get_user_by_id(user_id)
    if user is None:
        raise AuthenticationError("用户不存在")

    quiz_count = await quiz_repository.get_user_quiz_count(user_id)
    answer_stats = await quiz_repository.get_user_answer_stats(user_id)

    return UserProfile(
        id=user["id"],
        nickname=user["nickname"],
        avatar_url=user["avatar_url"],
        total_xp=user["total_xp"],
        quiz_count=quiz_count,
        correct_count=answer_stats["correct_count"],
        average_accuracy=answer_stats["average_accuracy"],
    )


async def update_profile(
    user_id: int, nickname: str | None, avatar_url: str | None
) -> None:
    """更新用户档案。"""
    await user_repository.update_user_profile(user_id, nickname, avatar_url)
