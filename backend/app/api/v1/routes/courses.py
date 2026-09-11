from fastapi import APIRouter, Depends, Header, Query

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.course import (
    CourseCreate, CourseEvidenceView, CourseLessonGenerate, CourseLessonView, CourseList,
    CourseOutlineUpdate, CourseProgressView, CourseQuizCreate, CourseQuizLinkView,
    CourseReadUpdate, CourseTaskView, CourseView,
)
from app.services import course_progress, course_quiz_service, course_read, course_service

router = APIRouter(prefix="/courses", tags=["courses"])


@router.post("", status_code=202, response_model=ApiResponse[CourseTaskView])
async def create(body: CourseCreate, actor=Depends(get_current_actor), idempotency_key: str = Header(..., min_length=1, max_length=128)):
    return ApiResponse.success(await course_service.create_course(actor, body, idempotency_key))


@router.get("", response_model=ApiResponse[CourseList])
async def list_courses(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_read.list_courses(actor.owner_id, page, page_size))


@router.get("/tasks/{task_id}", response_model=ApiResponse[CourseTaskView])
async def task(task_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_read.get_task(actor.owner_id, task_id))


@router.post("/tasks/{task_id}/cancel", response_model=ApiResponse[CourseTaskView])
async def cancel(task_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_service.cancel_task(actor.owner_id, task_id))


@router.get("/{course_id}", response_model=ApiResponse[CourseView])
async def course(course_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_read.get_course(actor.owner_id, course_id))


@router.patch("/{course_id}/outline", response_model=ApiResponse[CourseView])
async def edit(course_id: str, body: CourseOutlineUpdate, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_service.update_outline(actor.owner_id, course_id, body))


@router.post("/{course_id}/outline-jobs", status_code=202, response_model=ApiResponse[CourseTaskView])
async def retry(course_id: str, actor=Depends(get_current_actor), idempotency_key: str = Header(..., min_length=1, max_length=128)):
    return ApiResponse.success(await course_service.retry_outline(actor, course_id, idempotency_key))


@router.post("/{course_id}/lessons/{lesson_id}/generation-jobs", status_code=202, response_model=ApiResponse[CourseTaskView])
async def generate(course_id: str, lesson_id: str, body: CourseLessonGenerate, actor=Depends(get_current_actor), idempotency_key: str = Header(..., min_length=1, max_length=128)):
    return ApiResponse.success(await course_service.generate_lesson(actor, course_id, lesson_id, body, idempotency_key))


@router.get("/{course_id}/lessons/{lesson_id}", response_model=ApiResponse[CourseLessonView])
async def lesson(course_id: str, lesson_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_read.get_lesson(actor.owner_id, course_id, lesson_id, opened=True))


@router.patch("/{course_id}/lessons/{lesson_id}/progress", response_model=ApiResponse[CourseLessonView])
async def read(course_id: str, lesson_id: str, body: CourseReadUpdate, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_service.update_read(actor.owner_id, course_id, lesson_id, body))


@router.post("/{course_id}/lessons/{lesson_id}/quiz-jobs", status_code=202, response_model=ApiResponse[CourseQuizLinkView])
async def practice(course_id: str, lesson_id: str, body: CourseQuizCreate, actor=Depends(get_current_actor), idempotency_key: str = Header(..., min_length=1, max_length=128)):
    return ApiResponse.success(await course_quiz_service.create_quiz(actor, course_id, lesson_id, body, idempotency_key))


@router.get("/{course_id}/progress", response_model=ApiResponse[CourseProgressView])
async def progress(course_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_progress.get_progress(actor.owner_id, course_id))


@router.get("/{course_id}/evidence/{source_ref}", response_model=ApiResponse[CourseEvidenceView])
async def outline_evidence(course_id: str, source_ref: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_read.read_evidence(actor.owner_id, course_id, source_ref))


@router.get("/{course_id}/lessons/{lesson_id}/evidence/{source_ref}", response_model=ApiResponse[CourseEvidenceView])
async def lesson_evidence(course_id: str, lesson_id: str, source_ref: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_read.read_evidence(actor.owner_id, course_id, source_ref, lesson_id))
