from fastapi import APIRouter, Depends, Header, Query, Request

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.qa import (
    QaFeedbackBody,
    QaFeedbackView,
    QaMessageCreate,
    QaMessageList,
    QaScopeUpdate,
    QaSessionCreate,
    QaSessionList,
    QaSessionView,
    QaTaskView,
)
from app.rag.contracts import DocumentEvidence
from app.services import qa_read, qa_service, task_event_stream

router = APIRouter(prefix="/qa", tags=["knowledge-qa"])


@router.get("/tasks/{task_id}/content-events")
async def content_events(task_id: str, request: Request,
                         last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
                         actor=Depends(get_current_actor)):
    from app.services.content_event_stream import content_events_endpoint

    return await content_events_endpoint(request, actor=actor, kind="qa", task_id=task_id, last_event_id=last_event_id)


@router.post("/sessions", status_code=201, response_model=ApiResponse[QaSessionView])
async def create_session(body: QaSessionCreate, actor=Depends(get_current_actor)):
    return ApiResponse.success(await qa_service.create_session(actor, body))


@router.get("/sessions", response_model=ApiResponse[QaSessionList])
async def sessions(
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(20, ge=1, le=50),
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await qa_read.list_sessions(actor.owner_id, page, page_size)
    )


@router.get("/sessions/{session_id}", response_model=ApiResponse[QaSessionView])
async def session(session_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await qa_read.get_session(actor.owner_id, session_id))


@router.patch("/sessions/{session_id}/scope", response_model=ApiResponse[QaSessionView])
async def scope(session_id: str, body: QaScopeUpdate, actor=Depends(get_current_actor)):
    return ApiResponse.success(await qa_service.update_scope(actor, session_id, body))


@router.get(
    "/sessions/{session_id}/messages", response_model=ApiResponse[QaMessageList]
)
async def messages(
    session_id: str,
    before_sequence: int | None = Query(None, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await qa_read.get_messages(
            actor.owner_id, session_id, before_sequence, page_size
        )
    )


@router.post(
    "/sessions/{session_id}/messages",
    status_code=202,
    response_model=ApiResponse[QaTaskView],
)
async def create_message(
    session_id: str,
    body: QaMessageCreate,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await qa_service.create_message(actor, session_id, body, idempotency_key)
    )


@router.get("/tasks/{task_id}", response_model=ApiResponse[QaTaskView])
async def task(task_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await qa_read.get_task(actor.owner_id, task_id))


@router.get("/tasks/{task_id}/events")
async def task_events(
    task_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    actor=Depends(get_current_actor),
):
    """任务阶段 SSE 流；授权与快照一致读取见 task_event_stream。"""
    return await task_event_stream.task_events_endpoint(
        request,
        actor=actor,
        kind="qa",
        task_id=task_id,
        last_event_id=last_event_id,
    )


@router.post("/tasks/{task_id}/cancel", response_model=ApiResponse[QaTaskView])
async def cancel(task_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await qa_service.cancel_task(actor.owner_id, task_id))


@router.get(
    "/answers/{answer_id}/evidence/{evidence_id}",
    response_model=ApiResponse[DocumentEvidence],
)
async def evidence(answer_id: str, evidence_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await qa_read.read_evidence(actor.owner_id, answer_id, evidence_id)
    )


@router.post(
    "/answers/{answer_id}/feedback", response_model=ApiResponse[QaFeedbackView]
)
async def feedback(
    answer_id: str, body: QaFeedbackBody, actor=Depends(get_current_actor)
):
    return ApiResponse.success(
        await qa_service.save_feedback(actor.owner_id, answer_id, body)
    )
