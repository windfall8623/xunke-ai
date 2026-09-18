from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.core.auth import get_admin, get_current_actor, get_evaluator
from app.models.common import ApiResponse
from app.models.sources import (
    DocumentDeletionView,
    DocumentList,
    DocumentView,
    ReindexBody,
    SourceExcerptView,
)
from app.services import source_service as service

router = APIRouter(prefix="/knowledge/documents", tags=["knowledge"])
eval_router = APIRouter(prefix="/eval/documents", tags=["evaluation sources"])


@router.post("", status_code=202, response_model=ApiResponse[DocumentView])
async def upload(file: UploadFile = File(...), actor=Depends(get_current_actor)):
    return ApiResponse.success(await service.upload_document(actor, file))


@router.get("", response_model=ApiResponse[DocumentList])
async def listing(actor=Depends(get_current_actor)):
    return ApiResponse.success(await service.list_documents(actor.owner_id))


@router.get("/{doc_id}", response_model=ApiResponse[DocumentView])
async def get_document(doc_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await service.document_view(
            await service.owned_document(actor.owner_id, doc_id)
        )
    )


@router.delete(
    "/{doc_id}", status_code=202, response_model=ApiResponse[DocumentDeletionView]
)
async def delete(doc_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await service.revoke_document(actor, doc_id))


@router.post(
    "/{doc_id}/versions", status_code=202, response_model=ApiResponse[DocumentView]
)
async def version(
    doc_id: str, file: UploadFile = File(...), actor=Depends(get_current_actor)
):
    return ApiResponse.success(
        await service.upload_document(actor, file, doc_id=doc_id)
    )


@router.post(
    "/{doc_id}/reindex", status_code=202, response_model=ApiResponse[DocumentView]
)
async def reindex(doc_id: str, body: ReindexBody, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await service.reindex_document(actor, doc_id, body.index_profile_id)
    )


@router.get("/{doc_id}/source", response_model=ApiResponse[SourceExcerptView])
async def source(
    doc_id: str,
    version_id: str,
    parse_artifact_id: str,
    block_id: str | None = None,
    start_char: int | None = Query(default=None, ge=0),
    end_char: int | None = Query(default=None, gt=0),
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await service.read_source(
            actor.owner_id,
            doc_id,
            version_id,
            parse_artifact_id,
            block_id,
            start_char=start_char,
            end_char=end_char,
        )
    )


@eval_router.post("", status_code=202, response_model=ApiResponse[DocumentView])
async def eval_upload(file: UploadFile = File(...), actor=Depends(get_admin)):
    return ApiResponse.success(
        await service.upload_document(actor, file, purpose="evaluation")
    )


@eval_router.get("", response_model=ApiResponse[DocumentList])
async def eval_list(actor=Depends(get_evaluator)):
    return ApiResponse.success(
        await service.list_documents(actor.owner_id, purpose="evaluation")
    )


@eval_router.get("/{doc_id}", response_model=ApiResponse[DocumentView])
async def eval_document(doc_id: str, actor=Depends(get_evaluator)):
    return ApiResponse.success(
        await service.document_view(
            await service.owned_document(actor.owner_id, doc_id, purpose="evaluation")
        )
    )


@eval_router.delete(
    "/{doc_id}", status_code=202, response_model=ApiResponse[DocumentDeletionView]
)
async def eval_delete(doc_id: str, actor=Depends(get_evaluator)):
    return ApiResponse.success(
        await service.revoke_document(actor, doc_id, purpose="evaluation")
    )


@eval_router.post(
    "/{doc_id}/reindex", status_code=202, response_model=ApiResponse[DocumentView]
)
async def eval_reindex(doc_id: str, body: ReindexBody, actor=Depends(get_admin)):
    return ApiResponse.success(
        await service.reindex_document(
            actor, doc_id, body.index_profile_id, purpose="evaluation"
        )
    )


@eval_router.get("/{doc_id}/source", response_model=ApiResponse[SourceExcerptView])
async def eval_source(
    doc_id: str,
    version_id: str,
    parse_artifact_id: str,
    block_id: str | None = None,
    start_char: int | None = None,
    end_char: int | None = None,
    actor=Depends(get_evaluator),
):
    return ApiResponse.success(
        await service.read_source(
            actor.owner_id,
            doc_id,
            version_id,
            parse_artifact_id,
            block_id,
            start_char=start_char,
            end_char=end_char,
            purpose="evaluation",
        )
    )
