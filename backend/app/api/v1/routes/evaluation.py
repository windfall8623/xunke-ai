from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response

from app.core.auth import get_evaluator
from app.models.common import ApiResponse
from app.models.evaluation import (
    DatasetCreate,
    DatasetList,
    DatasetPatch,
    DatasetReview,
    DatasetView,
    FreezeBody,
    JudgeProfileList,
    ResultList,
    ResultReview,
    RunCreate,
    RunCostPreview,
    RunEstimateQuery,
    RunList,
    RunView,
)
from app.rag.contracts import ActorContext
from app.services import eval_dataset_service as datasets
from app.services import evaluation_service as runs
from app.services.evaluation_cost_preview import preview_run_cost

router = APIRouter(prefix="/eval", tags=["evaluation"])
Evaluator = Annotated[ActorContext, Depends(get_evaluator)]


@router.get("/datasets", response_model=ApiResponse[DatasetList])
async def list_datasets(actor: Evaluator):
    return ApiResponse.success(await datasets.list_datasets(actor.owner_id))


@router.post("/datasets", status_code=201, response_model=ApiResponse[DatasetView])
async def create_dataset(body: DatasetCreate, actor: Evaluator):
    return ApiResponse.success(await datasets.create_dataset(actor, body))


@router.get(
    "/datasets/{dataset_id}/versions/{version}", response_model=ApiResponse[DatasetView]
)
async def get_dataset(dataset_id: str, version: int, actor: Evaluator):
    return ApiResponse.success(
        await datasets.get_dataset(actor.owner_id, dataset_id, version)
    )


@router.patch(
    "/datasets/{dataset_id}/versions/{version}", response_model=ApiResponse[DatasetView]
)
async def edit_dataset(
    dataset_id: str, version: int, body: DatasetPatch, actor: Evaluator
):
    return ApiResponse.success(
        await datasets.patch_dataset(actor, dataset_id, version, body)
    )


@router.post(
    "/datasets/{dataset_id}/versions/{version}/freeze",
    response_model=ApiResponse[DatasetView],
)
async def freeze_dataset(
    dataset_id: str, version: int, body: FreezeBody, actor: Evaluator
):
    return ApiResponse.success(
        await datasets.freeze_dataset(
            actor, dataset_id, version, body.expected_revision, body.checklist
        )
    )


@router.delete(
    "/datasets/{dataset_id}/versions/{version}", response_model=ApiResponse[dict]
)
async def revoke_dataset(dataset_id: str, version: int, actor: Evaluator):
    return ApiResponse.success(
        await datasets.revoke_dataset(actor, dataset_id, version)
    )


@router.post(
    "/datasets/{dataset_id}/versions/{version}/samples/{sample_id}/review",
    response_model=ApiResponse[DatasetView],
)
async def review_sample(
    dataset_id: str, version: int, sample_id: str, body: DatasetReview, actor: Evaluator
):
    return ApiResponse.success(
        await datasets.review_sample(actor, dataset_id, version, sample_id, body)
    )


@router.get("/pipelines", response_model=ApiResponse[dict])
async def pipelines(actor: Evaluator):
    return ApiResponse.success(runs.list_pipelines())


@router.get("/judges", response_model=ApiResponse[JudgeProfileList])
async def judges(actor: Evaluator):
    return ApiResponse.success(runs.list_judges())


@router.post("/runs", status_code=202, response_model=ApiResponse[RunView])
async def create_run(
    body: RunCreate,
    actor: Evaluator,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
):
    return ApiResponse.success(await runs.create_run(actor, body, idempotency_key))


@router.get("/runs", response_model=ApiResponse[RunList])
async def list_runs(actor: Evaluator):
    return ApiResponse.success(await runs.list_runs(actor.owner_id))


@router.get("/runs/estimate", response_model=ApiResponse[RunCostPreview])
async def estimate_run(query: Annotated[RunEstimateQuery, Query()], actor: Evaluator):
    return ApiResponse.success(await preview_run_cost(actor, query))


@router.get("/runs/{run_id}", response_model=ApiResponse[RunView])
async def get_run(run_id: str, actor: Evaluator):
    return ApiResponse.success(await runs.get_run(actor.owner_id, run_id))


@router.get("/runs/{run_id}/results", response_model=ApiResponse[ResultList])
async def get_results(run_id: str, actor: Evaluator):
    return ApiResponse.success(await runs.get_results(actor.owner_id, run_id))


@router.post("/runs/{run_id}/cancel", response_model=ApiResponse[RunView])
async def cancel_run(run_id: str, actor: Evaluator):
    return ApiResponse.success(await runs.cancel_run(actor.owner_id, run_id))


@router.post("/runs/{run_id}/resume", response_model=ApiResponse[RunView])
async def resume_run(run_id: str, actor: Evaluator):
    return ApiResponse.success(await runs.resume_run(actor.owner_id, run_id))


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: str, actor: Evaluator, format: str = Query(default="jsonl")
):
    payload, content_type = await runs.export_run(actor.owner_id, run_id, format)
    safe_id = "".join(c for c in run_id if c.isalnum() or c in "_-")
    return Response(
        payload,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_id}.{format}"'},
    )


@router.put(
    "/runs/{run_id}/results/{result_id}/review", response_model=ApiResponse[dict]
)
async def review_result(
    run_id: str, result_id: str, body: ResultReview, actor: Evaluator
):
    return ApiResponse.success(await runs.review_result(actor, run_id, result_id, body))


@router.get("/compare", response_model=ApiResponse[dict])
async def compare(
    baseline_run_id: str,
    candidate_run_id: str,
    actor: Evaluator,
    exploratory: bool = False,
    group: str = "all",
):
    return ApiResponse.success(
        await runs.compare(
            actor.owner_id,
            baseline_run_id,
            candidate_run_id,
            exploratory=exploratory,
            group=group,
        )
    )
