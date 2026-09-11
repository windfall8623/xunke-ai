"""Service-token-only scoring control endpoints; browser authentication is unused."""

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.common import ApiResponse
from app.services import evaluation_scoring as service


def require_worker_token(authorization: str | None = Header(default=None)):
    configured = get_settings().eval_worker_token
    expected = f"Bearer {configured}"
    if (
        not configured
        or not authorization
        or not secrets.compare_digest(authorization, expected)
    ):
        raise AppError(401, "worker_authentication_required", "需要有效的评分服务凭据")


router = APIRouter(
    prefix="/internal/eval/scoring",
    tags=["internal evaluation"],
    dependencies=[Depends(require_worker_token)],
)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimBody(Body):
    worker_id: str = Field(min_length=1, max_length=128)
    lease_seconds: int = Field(default=120, ge=5, le=3600)
    run_id: str | None = Field(default=None, max_length=64)


class FenceBody(Body):
    lease_token: str = Field(min_length=1, max_length=64)
    attempt: int = Field(ge=1, le=2)


class HeartbeatBody(FenceBody):
    lease_seconds: int = Field(default=120, ge=5, le=3600)


class CompleteBody(FenceBody):
    metrics: dict[str, dict[str, Any]] = Field(max_length=256)
    judge_calls: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    status: str = "completed"


class FailBody(FenceBody):
    error_code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    error_message: str | None = Field(default=None, max_length=500)
    judge_calls: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class CallBody(FenceBody):
    call: dict[str, Any]


@router.post("/claim")
async def claim(body: ClaimBody):
    result = await service.claim_scoring(
        body.worker_id, body.lease_seconds, body.run_id
    )
    return Response(status_code=204) if result is None else ApiResponse.success(result)


@router.post("/{result_id}/heartbeat")
async def heartbeat(result_id: str, body: HeartbeatBody):
    return ApiResponse.success(
        await service.heartbeat_scoring(
            result_id, body.lease_token, body.attempt, body.lease_seconds
        )
    )


@router.post("/{result_id}/complete")
async def complete(result_id: str, body: CompleteBody):
    if body.status != "completed":
        raise AppError(422, "invalid_scoring_status", "评分完成状态无效")
    return ApiResponse.success(
        await service.complete_scoring(
            result_id, body.lease_token, body.attempt, body.metrics, body.judge_calls
        )
    )


@router.post("/{result_id}/fail")
async def fail(result_id: str, body: FailBody):
    return ApiResponse.success(
        await service.fail_scoring(
            result_id, body.lease_token, body.attempt, body.error_code, body.judge_calls
        )
    )


@router.post("/{result_id}/calls")
async def calls(result_id: str, body: CallBody):
    return ApiResponse.success(
        await service.journal_call(result_id, body.lease_token, body.attempt, body.call)
    )
