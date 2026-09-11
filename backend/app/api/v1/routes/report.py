from fastapi import APIRouter, Depends, Header, Response

from app.core.auth import get_current_actor
from app.core.values import uid
from app.models.common import ApiResponse
from app.models.learning import AnswerBody, ReportRetryView, ReportView
from app.models.report import ReportGenerateRequest
from app.services import learning_service

router = APIRouter(prefix="/report", tags=["reports"])


@router.get("/{quiz_id}", response_model=ApiResponse[ReportView])
async def get_report(quiz_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await learning_service.get_report(actor.owner_id, quiz_id)
    )


@router.post(
    "/{quiz_id}/retry", status_code=202, response_model=ApiResponse[ReportRetryView]
)
async def retry(
    quiz_id: str,
    actor=Depends(get_current_actor),
    idempotency_key: str | None = Header(default=None),
):
    return ApiResponse.success(
        await learning_service.retry_report(
            actor.owner_id, quiz_id, idempotency_key or uid("report_retry")
        )
    )


@router.post("/generate", status_code=202, response_model=ApiResponse[ReportView])
async def legacy_report(
    body: ReportGenerateRequest, response: Response, actor=Depends(get_current_actor)
):
    quiz = await learning_service.owned_quiz(actor.owner_id, body.quiz_id)
    if not quiz["settled_at"]:
        for record in body.answer_records:
            await learning_service.submit_answer(
                actor.owner_id,
                body.quiz_id,
                record.question_id,
                AnswerBody(
                    selected_answers=record.selected_answers,
                    duration_ms=record.duration_ms,
                ),
            )
        detail = await learning_service.get_detail(actor.owner_id, body.quiz_id)
        await learning_service.complete_quiz(
            actor.owner_id, body.quiz_id, detail["revision"]
        )
    result = await learning_service.get_report(actor.owner_id, body.quiz_id)
    if result["report_status"] == "completed":
        response.status_code = 200
    return ApiResponse.success(result)
