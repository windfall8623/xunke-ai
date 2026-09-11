"""Owned grading retries, evaluator judgments and learner annotations."""

from fastapi import APIRouter, Depends, Header

from app.core.auth import get_current_actor
from app.learning.contracts import AssessmentRef
from app.models.common import ApiResponse
from app.models.practice import PracticeTaskView
from app.models.practice_grading import (
    PracticeReviewBody,
    PracticeSelfReviewBody,
    PracticeSelfReviewReceipt,
)
from app.services import practice_grading_service as grading

router = APIRouter(prefix="/practice", tags=["practice"])


@router.post(
    "/attempts/{attempt_id}/retry-grading",
    status_code=202,
    response_model=ApiResponse[PracticeTaskView],
)
async def retry_grading(
    attempt_id: str,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await grading.retry_practice_grading(actor, attempt_id, idempotency_key)
    )


@router.post("/attempts/{attempt_id}/review", response_model=ApiResponse[AssessmentRef])
async def review(
    attempt_id: str,
    body: PracticeReviewBody,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await grading.review_practice_attempt(actor, attempt_id, body, idempotency_key)
    )


@router.post(
    "/attempts/{attempt_id}/self-review",
    response_model=ApiResponse[PracticeSelfReviewReceipt],
)
async def self_review(
    attempt_id: str,
    body: PracticeSelfReviewBody,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await grading.self_review_practice_attempt(
            actor, attempt_id, body, idempotency_key
        )
    )
