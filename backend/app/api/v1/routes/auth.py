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
    RecoverBody,
    RegisterBody,
    SessionView,
)
from app.models.common import ApiResponse
from app.services import auth_service as service
from app.services import email_verification

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
    await service.rate_limit(
        scope, account, request.client.host if request.client else "unknown"
    )


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
    result = await email_verification.send_code(
        body.email, request.client.host if request.client else "unknown"
    )
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
