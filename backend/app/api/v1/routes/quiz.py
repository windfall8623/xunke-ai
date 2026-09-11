import asyncio
import time

from fastapi import APIRouter, Depends, Header, Response

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.learning import (
    AnswerBody,
    AnswerReceipt,
    CompleteBody,
    CompletionReceipt,
    GenerateBody,
    QuizView,
    TaskView,
)
from app.models.sources import PublicWebEvidence
from app.rag.contracts import DocumentEvidence
from app.services import job_service, learning_service, quiz_service

router = APIRouter(prefix="/quiz", tags=["learning"])


@router.post("/generate/async", status_code=202, response_model=ApiResponse[TaskView])
async def create(
    body: GenerateBody,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await quiz_service.create_quiz_job(actor, body, idempotency_key)
    )


@router.post("/generate", response_model=ApiResponse[QuizView | TaskView])
async def legacy_generate(
    body: GenerateBody,
    response: Response,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    task = await quiz_service.create_quiz_job(actor, body, idempotency_key)
    until = time.monotonic() + 30
    while task["status"] in ("pending", "running") and time.monotonic() < until:
        await asyncio.sleep(0.5)
        task = await job_service.get_task(actor.owner_id, task["task_id"])
    if task["status"] == "completed":
        return ApiResponse.success(
            await learning_service.get_detail(actor.owner_id, task["quiz_id"])
        )
    response.status_code = 202
    return ApiResponse.success(task)


@router.get("/task/{task_id}", response_model=ApiResponse[TaskView])
async def get_task(task_id: str, actor=Depends(get_current_actor)):
    task = await job_service.get_task(actor.owner_id, task_id)
    if task["status"] == "completed":
        task["result"] = await learning_service.get_detail(
            actor.owner_id, task["quiz_id"]
        )
    return ApiResponse.success(task)


@router.post("/task/{task_id}/cancel", response_model=ApiResponse[TaskView])
async def cancel_task(task_id: str, actor=Depends(get_current_actor)):
    await job_service.get_task(actor.owner_id, task_id)
    await job_service.cancel_job(actor.owner_id, task_id)
    return ApiResponse.success(await job_service.get_task(actor.owner_id, task_id))


@router.put(
    "/{quiz_id}/answers/{question_id}", response_model=ApiResponse[AnswerReceipt]
)
async def answer(
    quiz_id: str, question_id: str, body: AnswerBody, actor=Depends(get_current_actor)
):
    return ApiResponse.success(
        await learning_service.submit_answer(actor.owner_id, quiz_id, question_id, body)
    )


@router.post("/{quiz_id}/complete", response_model=ApiResponse[CompletionReceipt])
async def complete(quiz_id: str, body: CompleteBody, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await learning_service.complete_quiz(
            actor.owner_id, quiz_id, body.expected_revision
        )
    )


@router.get(
    "/{quiz_id}/evidence/{evidence_id}",
    response_model=ApiResponse[DocumentEvidence | PublicWebEvidence],
)
async def evidence(quiz_id: str, evidence_id: str, actor=Depends(get_current_actor)):
    from app.services.source_service import read_evidence

    return ApiResponse.success(
        await read_evidence(actor.owner_id, quiz_id, evidence_id)
    )
