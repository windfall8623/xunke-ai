"""Register this router before courses: /today must precede /{course_id}."""

from fastapi import APIRouter, Depends, Header, Query

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.course import CourseQuizLinkView
from app.models.course_preferences import CourseReviewUpdate
from app.models.course_review import CourseReviewStart, CourseReviewView, CourseTodayView
from app.services import course_review_service, course_today_service

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("/today", response_model=ApiResponse[CourseTodayView])
async def today(
    timezone: str | None = Query(None, min_length=1, max_length=64),
    minutes_budget: int | None = Query(None, ge=5, le=120),
    actor=Depends(get_current_actor),
):
    # 缺省读持久偏好；显式 query 只作为当次覆盖，不写回偏好。
    return ApiResponse.success(await course_today_service.get_today(actor, timezone, minutes_budget))


@router.get("/{course_id}/reviews", response_model=ApiResponse[list[CourseReviewView]])
async def list_reviews(course_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_review_service.list_course_reviews(actor.owner_id, course_id))


@router.post(
    "/{course_id}/lessons/{lesson_id}/review-jobs", status_code=202,
    response_model=ApiResponse[CourseQuizLinkView],
)
async def start_review(
    course_id: str, lesson_id: str, body: CourseReviewStart,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(await course_review_service.start_course_review(
        actor, course_id, lesson_id, body, idempotency_key,
    ))


@router.patch("/{course_id}/reviews/{review_id}", response_model=ApiResponse[CourseReviewView])
async def adjust_review(
    course_id: str,
    review_id: str,
    body: CourseReviewUpdate,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(await course_review_service.update_course_review(
        actor, course_id, review_id, body, idempotency_key,
    ))
