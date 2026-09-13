from fastapi import APIRouter, Depends, Header, Query, Request

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.teaching_quality import CourseCapabilities
from app.models.course import (
    CourseCreate, CourseEvidenceView, CourseLessonGenerate, CourseLessonView, CourseList,
    CourseOutlineUpdate, CourseProgressView, CourseQuizCreate, CourseQuizLinkView,
    CourseReadUpdate, CourseRevisionApply, CourseRevisionGenerate, CourseRevisionPreview,
    CourseRevisionView, CourseTaskView, CourseView,
)
from app.services import content_event_stream, course_progress, course_quiz_service, course_read, course_revision_service, course_service, course_teaching, task_event_stream

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


@router.get("/capabilities", response_model=ApiResponse[CourseCapabilities])
async def capabilities(actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_teaching.capabilities())


@router.get("/tasks/{task_id}/content-events")
async def content_events(
    task_id: str, request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    actor=Depends(get_current_actor),
):
    return await content_event_stream.content_events_endpoint(
        request, actor=actor, kind="course", task_id=task_id, last_event_id=last_event_id,
    )


@router.get("/tasks/{task_id}/events")
async def task_events(
    task_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    actor=Depends(get_current_actor),
):
    """课程/课文/助教任务阶段 SSE 流；覆盖三种任务 kind。"""
    return await task_event_stream.task_events_endpoint(
        request,
        actor=actor,
        kind="course",
        task_id=task_id,
        last_event_id=last_event_id,
    )


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


@router.post("/{course_id}/revision-previews", status_code=201, response_model=ApiResponse[CourseRevisionView])
async def create_revision_preview(
    course_id: str, body: CourseRevisionPreview, actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await course_revision_service.create_revision_preview(actor, course_id, body, idempotency_key))


@router.post("/{course_id}/revision-jobs", status_code=202, response_model=ApiResponse[CourseRevisionView])
async def start_revision_jobs(
    course_id: str, body: CourseRevisionGenerate, actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await course_revision_service.start_revision_jobs(actor, course_id, body, idempotency_key))


@router.get("/{course_id}/revisions/{revision_id}", response_model=ApiResponse[CourseRevisionView])
async def get_revision(course_id: str, revision_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await course_revision_service.get_revision(actor.owner_id, course_id, revision_id))


@router.post("/{course_id}/revisions/{revision_id}/apply", response_model=ApiResponse[CourseRevisionView])
async def apply_revision(
    course_id: str, revision_id: str, body: CourseRevisionApply,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await course_revision_service.apply_revision(actor, course_id, revision_id, body, idempotency_key))


@router.get("/{course_id}/lessons/{lesson_id}/versions")
async def lesson_versions(course_id: str, lesson_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await course_revision_service.list_lesson_versions(actor.owner_id, course_id, lesson_id))


@router.get("/{course_id}/lessons/{lesson_id}/versions/{content_version}")
async def lesson_version(
    course_id: str, lesson_id: str, content_version: int, actor=Depends(get_current_actor)
):
    return ApiResponse.success(
        await course_revision_service.get_lesson_version(
            actor.owner_id, course_id, lesson_id, content_version))
