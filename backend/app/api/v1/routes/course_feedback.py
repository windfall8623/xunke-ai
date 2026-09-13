from fastapi import APIRouter, Depends, Header, Query, Request

from app.core.auth import get_current_actor, get_evaluator, verify_origin
from app.models.common import ApiResponse
from app.models.course_feedback import (
    CourseApplicationRegrade,
    CourseCorrectionCreate,
    CourseCorrectionReview,
    CourseCorrectionView,
    CourseFeedbackCreate,
    CourseFeedbackList,
    CourseFeedbackUpdate,
    CourseFeedbackView,
)
from app.services import course_feedback_service as service

router = APIRouter(prefix="/courses", tags=["course-feedback"])


@router.post("/{course_id}/feedback", status_code=201, response_model=ApiResponse[CourseFeedbackView])
async def create_feedback(
    course_id: str,
    body: CourseFeedbackCreate,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(await service.create_course_feedback(actor, course_id, body, idempotency_key))


@router.get("/{course_id}/feedback", response_model=ApiResponse[CourseFeedbackList])
async def list_feedback(
    course_id: str,
    actor=Depends(get_current_actor),
    lesson_id: str | None = Query(default=None),
    check_attempt_id: str | None = Query(default=None),
    course_assessment_id: str | None = Query(default=None),
):
    return ApiResponse.success(
        await service.list_course_feedback(
            actor.owner_id,
            course_id,
            lesson_id=lesson_id,
            check_attempt_id=check_attempt_id,
            course_assessment_id=course_assessment_id,
        )
    )


@router.patch("/{course_id}/feedback/{feedback_id}", response_model=ApiResponse[CourseFeedbackView])
async def update_feedback(
    course_id: str,
    feedback_id: str,
    body: CourseFeedbackUpdate,
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(await service.update_course_feedback(actor.owner_id, course_id, feedback_id, body))


@router.post(
    "/{course_id}/feedback/{feedback_id}/corrections",
    status_code=201,
    response_model=ApiResponse[CourseCorrectionView],
)
async def create_correction(
    course_id: str,
    feedback_id: str,
    body: CourseCorrectionCreate,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await service.create_correction(actor.owner_id, course_id, feedback_id, body, idempotency_key)
    )


@router.post(
    "/{course_id}/feedback/{feedback_id}/reviews",
    response_model=ApiResponse[CourseCorrectionView],
)
async def review_correction(
    course_id: str,
    feedback_id: str,
    body: CourseCorrectionReview,
    request: Request,
    evaluator=Depends(get_evaluator),
):
    from app.core.auth import verify_origin

    verify_origin(request)
    return ApiResponse.success(
        await service.review_correction(evaluator, course_id, feedback_id, body)
    )


@router.post(
    "/{course_id}/assessments/{course_assessment_id}/attempts/{attempt_id}/reviews",
    response_model=ApiResponse[dict],
)
async def review_application_attempt(
    course_id: str,
    course_assessment_id: str,
    attempt_id: str,
    body: CourseApplicationRegrade,
    request: Request,
    evaluator=Depends(get_evaluator),
):
    from app.core.auth import verify_origin

    verify_origin(request)
    return ApiResponse.success(
        await service.review_application_attempt(
            evaluator, course_id, course_assessment_id, attempt_id, body
        )
    )
