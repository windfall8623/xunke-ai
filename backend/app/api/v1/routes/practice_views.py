from fastapi import APIRouter, Depends

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.practice_views import (
    PracticeCostPreview,
    PracticeReviewContext,
    PublicPracticeEvidence,
)
from app.practice.contracts import PracticeSpec
from app.services import practice_view_service

router = APIRouter(prefix="/practice", tags=["practice"])


@router.get(
    "/attempts/{attempt_id}/review-context",
    response_model=ApiResponse[PracticeReviewContext],
)
async def review_context(attempt_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await practice_view_service.get_practice_review_context(actor, attempt_id)
    )


@router.get(
    "/{practice_id}/questions/{question_id}/evidence/{evidence_id}",
    response_model=ApiResponse[PublicPracticeEvidence],
)
async def evidence(
    practice_id: str,
    question_id: str,
    evidence_id: str,
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await practice_view_service.get_practice_evidence(
            actor.owner_id, practice_id, question_id, evidence_id
        )
    )


@router.post("/cost-preview", response_model=ApiResponse[PracticeCostPreview])
async def cost_preview(body: PracticeSpec, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await practice_view_service.preview_practice_cost(actor, body)
    )
