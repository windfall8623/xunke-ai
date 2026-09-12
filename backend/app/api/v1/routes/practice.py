"""Owned fixed-source practice generation, immutable answers and completion."""

from fastapi import APIRouter, Depends, Header, Request, Response

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.practice import (
    PracticeAnswerBody,
    PracticeAttemptView,
    PracticeCompleteBody,
    PracticeCompletionReceipt,
    PracticeHelpView,
    PracticeSubmissionReceipt,
    PracticeTaskView,
    PracticeView,
    ReviewPracticeBody,
)
from app.practice.contracts import PracticeSpec
from app.services import practice_answer_service, practice_service, task_event_stream

router = APIRouter(prefix="/practice", tags=["practice"])


@router.post(
    "/generate/async", status_code=202, response_model=ApiResponse[PracticeTaskView]
)
async def generate(
    body: PracticeSpec,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await practice_service.create_practice_job(actor, body, idempotency_key)
    )


@router.get("/tasks/{task_id}", response_model=ApiResponse[PracticeTaskView])
async def task(task_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await practice_service.get_practice_task(actor.owner_id, task_id)
    )


@router.get("/tasks/{task_id}/events")
async def task_events(
    task_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    actor=Depends(get_current_actor),
):
    return await task_event_stream.task_events_endpoint(
        request, actor=actor, kind="practice", task_id=task_id,
        last_event_id=last_event_id,
    )


@router.post(
    "/review-jobs", status_code=202, response_model=ApiResponse[PracticeTaskView]
)
async def review_job(
    body: ReviewPracticeBody,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await practice_service.create_review_practice_job(actor, body, idempotency_key)
    )


@router.post("/tasks/{task_id}/cancel", response_model=ApiResponse[PracticeTaskView])
async def cancel(task_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await practice_service.cancel_practice_task(actor.owner_id, task_id)
    )


@router.post(
    "/{practice_id}/questions/{question_id}/attempts",
    status_code=201,
    response_model=ApiResponse[PracticeSubmissionReceipt],
    responses={202: {"model": ApiResponse[PracticeSubmissionReceipt]}},
)
async def submit_answer(
    practice_id: str,
    question_id: str,
    body: PracticeAnswerBody,
    response: Response,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    receipt = await practice_answer_service.submit_practice_answer(
        actor, practice_id, question_id, body, idempotency_key
    )
    response.status_code = 202 if receipt.task_id else 201
    return ApiResponse.success(receipt)


@router.get("/attempts/{attempt_id}", response_model=ApiResponse[PracticeAttemptView])
async def attempt(attempt_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await practice_answer_service.get_practice_attempt(actor.owner_id, attempt_id)
    )


@router.post(
    "/{practice_id}/questions/{question_id}/help",
    response_model=ApiResponse[PracticeHelpView],
)
async def help_used(
    practice_id: str, question_id: str, actor=Depends(get_current_actor)
):
    return ApiResponse.success(
        await practice_answer_service.acknowledge_practice_help(
            actor.owner_id, practice_id, question_id
        )
    )


@router.post(
    "/{practice_id}/complete", response_model=ApiResponse[PracticeCompletionReceipt]
)
async def complete(
    practice_id: str, body: PracticeCompleteBody, actor=Depends(get_current_actor)
):
    return ApiResponse.success(
        await practice_answer_service.complete_practice(
            actor.owner_id, practice_id, body.expected_revision
        )
    )


@router.get("/{practice_id}", response_model=ApiResponse[PracticeView])
async def practice(practice_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await practice_service.get_practice(actor.owner_id, practice_id)
    )
