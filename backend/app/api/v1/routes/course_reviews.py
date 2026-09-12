"""Register this router before courses: /today must precede /{course_id}."""

from fastapi import APIRouter, Depends, Header, Query

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.course import CourseQuizLinkView
from app.models.course_review import CourseReviewStart, CourseReviewView, CourseTodayView
from app.services import course_review_service, course_today_service

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("/today", response_model=ApiResponse[CourseTodayView])
async def today(
    timezone: str = Query("Asia/Shanghai", min_length=1, max_length=64),
    minutes_budget: int = Query(20, ge=5, le=120),
    actor=Depends(get_current_actor),
):
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
