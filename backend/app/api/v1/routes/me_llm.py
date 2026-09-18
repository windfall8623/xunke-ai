"""Self-owned LLM credentials; session authentication includes existing CSRF checks."""
from fastapi import APIRouter, Depends, Request, Response

from app.core.auth import get_current_user
from app.models.common import ApiResponse
from app.models.user_llm_config import LLMConfigRequest, LLMConfigView
from app.services import user_llm_config_service as service

router = APIRouter(prefix="/me/llm", tags=["me"])


@router.get("", response_model=ApiResponse[LLMConfigView])
async def get_my_llm(response: Response, user_id: int = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    return ApiResponse.success(await service.get_my_llm_config(user_id))


@router.put("", response_model=ApiResponse[LLMConfigView])
async def put_my_llm(body: LLMConfigRequest, request: Request, response: Response,
                     user_id: int = Depends(get_current_user)):
    from app.services.auth_service import rate_limit
    from app.services.rate_limit_service import BurstPolicy, enforce_burst

    ip = request.client.host if request.client else "unknown"
    await enforce_burst(str(user_id), ip, policy=BurstPolicy("user_llm_probe", 60, 10, 5))
    # SQL hard limit still runs when Redis is disabled/degraded.
    await rate_limit("user_llm_probe", str(user_id), ip)
    response.headers["Cache-Control"] = "private, no-store"
    return ApiResponse.success(await service.save_my_llm_config(user_id, body))


@router.delete("", response_model=ApiResponse[LLMConfigView])
async def delete_my_llm(user_id: int = Depends(get_current_user)):
    await service.delete_my_llm_config(user_id)
    return ApiResponse.success(await service.get_my_llm_config(user_id))
