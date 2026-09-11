"""用户路由"""

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.auth import get_current_user
from app.models.common import ApiResponse
from app.models.learning import QuizView
from app.models.user import (
    AvatarUploadResponse,
    LoginRequest,
    LoginResponse,
    QuizHistoryList,
    UpdateProfileRequest,
    UserProfile,
)
from app.services import learning_service, user_service

router = APIRouter(prefix="/user", tags=["user"])


@router.post(
    "/avatar", status_code=201, response_model=ApiResponse[AvatarUploadResponse]
)
async def upload_avatar(
    file: UploadFile = File(...), user_id: int = Depends(get_current_user)
):
    from app.services.asset_service import save_avatar

    return ApiResponse.success(await save_avatar(user_id, file))


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str, user_id: int = Depends(get_current_user)):
    from app.services.asset_service import read_asset

    path, content_type = await read_asset(user_id, asset_id)
    return FileResponse(
        path, media_type=content_type, headers={"Cache-Control": "private, no-store"}
    )


@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(req: LoginRequest, request: Request):
    from app.services.auth_service import rate_limit

    await rate_limit(
        "wechat_login", req.code, request.client.host if request.client else "unknown"
    )
    result = await user_service.handle_login(req.code)
    return ApiResponse.success(data=result.model_dump())


@router.get("/profile", response_model=ApiResponse[UserProfile])
async def get_profile(user_id: int = Depends(get_current_user)):
    result = await user_service.get_profile(user_id)
    return ApiResponse.success(data=result.model_dump())


@router.put("/profile", response_model=ApiResponse[None])
async def update_profile(
    req: UpdateProfileRequest,
    user_id: int = Depends(get_current_user),
):
    if req.avatar_url:
        from app.core.db import fetch_one
        from app.core.errors import AppError

        prefix = "/api/v1/user/assets/"
        owned = (
            await fetch_one(
                "SELECT asset_id FROM user_assets WHERE asset_id=%s AND owner_id=%s",
                (req.avatar_url.removeprefix(prefix), user_id),
            )
            if req.avatar_url.startswith(prefix)
            else None
        )
        if not owned:
            raise AppError(422, "invalid_avatar", "请先上传本人头像")
    await user_service.update_profile(user_id, req.nickname, req.avatar_url)
    return ApiResponse.success()


@router.get("/quizzes", response_model=ApiResponse[QuizHistoryList])
async def get_quiz_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    user_id: int = Depends(get_current_user),
):
    return ApiResponse.success(await learning_service.history(user_id, page, page_size))


@router.get("/quizzes/{quiz_id}", response_model=ApiResponse[QuizView])
async def get_quiz_detail(
    quiz_id: str,
    user_id: int = Depends(get_current_user),
):
    return ApiResponse.success(await learning_service.get_detail(user_id, quiz_id))
