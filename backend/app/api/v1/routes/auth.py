from fastapi import APIRouter, Depends, Request, Response

from app.core.auth import get_current_actor, verify_origin
from app.core.config import get_settings
from app.core.db import execute, fetch_one
from app.core.errors import AppError
from app.models.auth import (
    AuthCapabilitiesView,
    BindBody,
    EmailCodeBody,
    EmailCodeView,
    LoginBody,
    PasswordBody,
    PasswordResetBody,
    RecoverBody,
    RegisterBody,
    SessionView,
    normalize_email,
)
from app.models.common import ApiResponse
from app.services import auth_service as service
from app.services import email_verification, rate_limit_service

router = APIRouter(prefix="/auth", tags=["authentication"])


def cookie(response, token):
    s = get_settings()
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=s.session_days * 86400,
        secure=s.cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )


async def preflight(request, scope, account):
    verify_origin(request)
    ip = request.client.host if request.client else "unknown"
    # Redis 快速门槛（可选）：拒绝时不触达 SQL；放行继续执行原 SQL 硬限制。
    await rate_limit_service.enforce_auth_burst(account, ip)
    await service.rate_limit(scope, account, ip)


@router.get("/capabilities", response_model=ApiResponse[AuthCapabilitiesView])
async def capabilities(response: Response):
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    return ApiResponse.success(
        AuthCapabilitiesView(
            legacy_link_enabled=settings.legacy_link_enabled,
            email_registration_enabled=email_verification.is_available(settings),
            email_verification_required=True,
            email_code_cooldown_seconds=settings.email_send_cooldown_seconds,
        )
    )


@router.post("/email-code", response_model=ApiResponse[EmailCodeView])
async def email_code(body: EmailCodeBody, request: Request, response: Response):
    verify_origin(request)
    response.headers["Cache-Control"] = "no-store"
    ip = request.client.host if request.client else "unknown"
    # 顺序固定：Origin 与功能开关/邮箱校验 → Redis 短窗 → SQL 冷却、配额与发送。
    email_verification.require_available()
    try:
        email = normalize_email(body.email)
    except ValueError:
        raise AppError(400, "invalid_email", "请输入有效的邮箱地址") from None
    await rate_limit_service.enforce_email_burst(email, ip)
    if body.purpose == email_verification.PURPOSE_RESET:
        # 重置码只发给已存在的已验证账号；其余地址返回同一成功口径，
        # 不透露邮箱是否已注册（不发送、不占用发信配额）。
        identity = await fetch_one(
            "SELECT email_verified_at FROM auth_identities "
            "WHERE provider='password' AND app_scope='web' AND subject=%s",
            (email,),
        )
        if not identity or not identity["email_verified_at"]:
            return ApiResponse.success(
                {
                    "message": email_verification.RESET_MESSAGE,
                    "retry_after_seconds": get_settings().email_send_cooldown_seconds,
                    "expires_in_seconds": email_verification.CODE_LIFETIME_SECONDS,
                }
            )
    result = await email_verification.send_code(email, ip, purpose=body.purpose)
    return ApiResponse.success(result)


@router.post("/register", status_code=201, response_model=ApiResponse[SessionView])
async def register(body: RegisterBody, request: Request, response: Response):
    await preflight(request, "register", body.account)
    result, token = await service.register(body)
    cookie(response, token)
    return ApiResponse.success(result)


@router.post("/login", response_model=ApiResponse[SessionView])
async def login(body: LoginBody, request: Request, response: Response):
    await preflight(request, "login", body.account)
    result, token = await service.login(body)
    cookie(response, token)
    return ApiResponse.success(result)


@router.get("/session", response_model=ApiResponse[SessionView])
async def session(request: Request, actor=Depends(get_current_actor)):
    user = await fetch_one(
        "SELECT id,nickname,avatar_url,total_xp,role FROM users WHERE id=%s",
        (actor.owner_id,),
    )
    return ApiResponse.success(
        {"user": user, "csrf_token": getattr(request.state, "csrf_token", "")}
    )


@router.post("/logout", response_model=ApiResponse[dict])
async def logout(
    request: Request, response: Response, actor=Depends(get_current_actor)
):
    if getattr(request.state, "session_hash", None):
        await execute(
            "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE token_hash=%s",
            (request.state.session_hash,),
        )
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    return ApiResponse.success({})


@router.post("/recover", response_model=ApiResponse[dict])
async def recover(body: RecoverBody, request: Request):
    await preflight(request, "recover", body.account)
    return ApiResponse.success(await service.recover(body))


@router.post("/password/reset", response_model=ApiResponse[SessionView])
async def password_reset(body: PasswordResetBody, request: Request, response: Response):
    await preflight(request, "password_reset", body.account)
    result, token = await service.reset_password_with_email_code(body)
    cookie(response, token)
    return ApiResponse.success(result)


@router.post("/change-password", response_model=ApiResponse[dict])
async def change_password(
    body: PasswordBody, response: Response, actor=Depends(get_current_actor)
):
    await service.change_password(actor.owner_id, body)
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    return ApiResponse.success({})


@router.post("/link-code", response_model=ApiResponse[dict])
async def link_code(request: Request, actor=Depends(get_current_actor)):
    if request.state.auth_type != "bearer":
        raise AppError(403, "legacy_identity_required", "需要有效旧微信登录凭证")
    return ApiResponse.success(await service.link_code(actor.owner_id))


@router.post("/bind", response_model=ApiResponse[SessionView])
async def bind(body: BindBody, request: Request, response: Response):
    await preflight(request, "bind", body.account)
    result, token = await service.bind(body)
    cookie(response, token)
    return ApiResponse.success(result)
