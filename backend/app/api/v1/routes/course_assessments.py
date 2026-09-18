from fastapi import APIRouter, Depends, Header, Request

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.course_assessment import (
    CourseApplicationAnswer, CourseApplicationAttemptView, CourseApplicationJobView,
    CourseAssessmentComplete, CourseAssessmentCreate, CourseAssessmentView,
)
from app.models.course_outcome import CourseOutcomeSummary
from app.services import course_application_service as applications
from app.services import course_assessment_service as assessments
from app.services import course_outcome_service, task_event_stream

router = APIRouter(prefix="/courses", tags=["course-assessments"])


@router.get("/application-tasks/{task_id}", response_model=ApiResponse[CourseApplicationJobView])
async def application_task(task_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await applications.get_application_task(actor.owner_id, task_id))


@router.post("/application-tasks/{task_id}/cancel", response_model=ApiResponse[CourseApplicationJobView])
async def cancel_application_task(task_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await applications.cancel_application_task(actor.owner_id, task_id))


@router.get("/application-tasks/{task_id}/events")
async def application_task_events(task_id: str, request: Request,
                                  last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
                                  actor=Depends(get_current_actor)):
    return await task_event_stream.task_events_endpoint(request, actor=actor, kind="course_application",
                                                       task_id=task_id, last_event_id=last_event_id)


@router.get("/{course_id}/outcomes", response_model=ApiResponse[CourseOutcomeSummary])
async def outcomes(course_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await course_outcome_service.get_course_outcomes(actor.owner_id, course_id))


@router.post("/{course_id}/assessment-jobs", status_code=202, response_model=ApiResponse[CourseAssessmentView])
async def create_assessment(course_id: str, body: CourseAssessmentCreate, actor=Depends(get_current_actor),
                            idempotency_key: str = Header(..., min_length=1, max_length=128)):
    return ApiResponse.success(await assessments.create_course_assessment(actor, course_id, body, idempotency_key))


@router.get("/{course_id}/assessments", response_model=ApiResponse[list[CourseAssessmentView]])
async def list_assessments(course_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await assessments.list_course_assessments(actor.owner_id, course_id))


@router.get("/{course_id}/assessments/{course_assessment_id}", response_model=ApiResponse[CourseAssessmentView])
async def assessment(course_id: str, course_assessment_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await assessments.get_course_assessment(actor.owner_id, course_id, course_assessment_id))


@router.post("/{course_id}/assessments/{course_assessment_id}/application-jobs", status_code=202,
             response_model=ApiResponse[CourseAssessmentView])
async def create_application(course_id: str, course_assessment_id: str, actor=Depends(get_current_actor),
                             idempotency_key: str = Header(..., min_length=1, max_length=128)):
    return ApiResponse.success(await applications.create_application_job(actor, course_id, course_assessment_id, idempotency_key))


@router.post("/{course_id}/assessments/{course_assessment_id}/applications/{application_task_id}/attempts",
             status_code=201, response_model=ApiResponse[CourseApplicationAttemptView])
async def submit_application(course_id: str, course_assessment_id: str, application_task_id: str,
                             body: CourseApplicationAnswer, actor=Depends(get_current_actor),
                             idempotency_key: str = Header(..., min_length=1, max_length=128)):
    return ApiResponse.success(await applications.submit_application_answer(
        actor, course_id, course_assessment_id, application_task_id, body, idempotency_key))


@router.get("/{course_id}/assessments/{course_assessment_id}/attempts/{attempt_id}",
            response_model=ApiResponse[CourseApplicationAttemptView])
async def application_attempt(course_id: str, course_assessment_id: str, attempt_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await applications.get_application_attempt(actor.owner_id, course_id, course_assessment_id, attempt_id))


@router.post("/{course_id}/assessments/{course_assessment_id}/attempts/{attempt_id}/feedback-jobs", status_code=202,
             response_model=ApiResponse[CourseApplicationAttemptView])
async def application_feedback(course_id: str, course_assessment_id: str, attempt_id: str, actor=Depends(get_current_actor),
                                idempotency_key: str = Header(..., min_length=1, max_length=128)):
    return ApiResponse.success(await applications.create_feedback_job(actor, course_id, course_assessment_id, attempt_id, idempotency_key))


@router.post("/{course_id}/assessments/{course_assessment_id}/complete", response_model=ApiResponse[CourseAssessmentView])
async def complete_assessment(course_id: str, course_assessment_id: str, body: CourseAssessmentComplete,
                              actor=Depends(get_current_actor),
                              idempotency_key: str = Header(..., min_length=1, max_length=128)):
    return ApiResponse.success(await assessments.complete_course_assessment(
        actor.owner_id, course_id, course_assessment_id, body, idempotency_key))
