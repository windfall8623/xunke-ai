from fastapi import APIRouter, Depends, Header, Query

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.course import CourseEvidenceView
from app.models.course_tutor import (
    CourseSelfCheckCreate,
    CourseSelfCheckView,
    CourseTutorCreate,
    CourseTutorTurnView,
)
from app.services import course_self_check_service, course_tutor_service

router = APIRouter(
    prefix="/courses/{course_id}/lessons/{lesson_id}", tags=["courses"]
)


@router.post("/tutor-turns", status_code=202, response_model=ApiResponse[CourseTutorTurnView])
async def create_turn(
    course_id: str,
    lesson_id: str,
    body: CourseTutorCreate,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await course_tutor_service.create_turn(
            actor, course_id, lesson_id, body, idempotency_key
        )
    )


@router.get("/tutor-turns", response_model=ApiResponse[list[CourseTutorTurnView]])
async def list_turns(
    course_id: str,
    lesson_id: str,
    content_version: int = Query(..., ge=1),
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await course_tutor_service.list_turns(
            actor.owner_id, course_id, lesson_id, content_version
        )
    )


@router.post(
    "/tutor-turns/{turn_id}/retry",
    status_code=202,
    response_model=ApiResponse[CourseTutorTurnView],
)
async def retry_turn(
    course_id: str,
    lesson_id: str,
    turn_id: str,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await course_tutor_service.retry_turn(
            actor, course_id, lesson_id, turn_id, idempotency_key
        )
    )


@router.get(
    "/tutor-turns/{turn_id}/evidence/{source_ref}",
    response_model=ApiResponse[CourseEvidenceView],
)
async def turn_evidence(
    course_id: str,
    lesson_id: str,
    turn_id: str,
    source_ref: str,
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await course_tutor_service.read_turn_evidence(
            actor.owner_id, course_id, lesson_id, turn_id, source_ref
        )
    )


@router.post(
    "/self-check-attempts", status_code=201,
    response_model=ApiResponse[CourseSelfCheckView],
)
async def save_check_attempt(
    course_id: str,
    lesson_id: str,
    body: CourseSelfCheckCreate,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await course_self_check_service.save_check_attempt(
            actor, course_id, lesson_id, body, idempotency_key
        )
    )


@router.get(
    "/self-check-attempts", response_model=ApiResponse[list[CourseSelfCheckView]]
)
async def list_check_attempts(
    course_id: str,
    lesson_id: str,
    content_version: int = Query(..., ge=1),
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await course_self_check_service.list_check_attempts(
            actor.owner_id, course_id, lesson_id, content_version
        )
    )
