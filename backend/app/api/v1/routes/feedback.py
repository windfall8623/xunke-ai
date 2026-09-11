from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.auth import get_current_actor, get_evaluator
from app.models.common import ApiResponse
from app.models.feedback import (
    FeedbackCreate,
    FeedbackList,
    FeedbackPromote,
    FeedbackReview,
    FeedbackView,
    PromotionView,
)
from app.rag.contracts import ActorContext
from app.services import feedback_service as service

router = APIRouter(tags=["feedback"])
Learner = Annotated[ActorContext, Depends(get_current_actor)]
Evaluator = Annotated[ActorContext, Depends(get_evaluator)]


@router.post(
    "/quiz/{quiz_id}/feedback",
    status_code=201,
    response_model=ApiResponse[FeedbackView],
)
async def create(quiz_id: str, body: FeedbackCreate, actor: Learner):
    return ApiResponse.success(await service.create_feedback(actor, quiz_id, body))


@router.get("/eval/feedback", response_model=ApiResponse[FeedbackList])
async def list_feedback(
    actor: Evaluator,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
):
    return ApiResponse.success(
        await service.list_feedback(actor.owner_id, page=page, page_size=page_size)
    )


@router.put(
    "/eval/feedback/{feedback_id}/review", response_model=ApiResponse[FeedbackView]
)
async def review(feedback_id: str, body: FeedbackReview, actor: Evaluator):
    return ApiResponse.success(await service.review_feedback(actor, feedback_id, body))


@router.post(
    "/eval/feedback/{feedback_id}/promote",
    status_code=202,
    response_model=ApiResponse[PromotionView],
)
async def promote(feedback_id: str, body: FeedbackPromote, actor: Evaluator):
    return ApiResponse.success(await service.promote_feedback(actor, feedback_id, body))
