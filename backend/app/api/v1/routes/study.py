from typing import Literal
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Path, Query

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.learning import TaskView
from app.models.study import (
    StudyConceptCreate,
    StudyConceptList,
    StudyConceptUpdate,
    StudyConceptView,
    StudyGoalCreate,
    StudyGoalList,
    StudyGoalUpdate,
    StudyGoalView,
    StudyQaPracticeContextView,
    StudyQuizFromQaBody,
    StudyScopeUpdate,
    StudyScopeView,
    StudySpaceCreate,
    StudySpaceList,
    StudySpaceUpdate,
    StudySpaceView,
    StudyUnitCreate,
    StudyUnitList,
    StudyUnitReorder,
    StudyUnitUpdate,
    StudyUnitView,
    ReviewQuizBody,
    ReviewUpdateBody,
    StudyReviewView,
    StudyReviewList,
    StudyWrongQuestionList,
    StudyHistoryList,
    StudyConceptProgressView,
)
from app.services import learning_concept_service as concepts
from app.services import learning_space_service as spaces
from app.services import learning_quiz_service, qa_practice_source
from app.services import review_service, wrongbook_service

router = APIRouter(prefix="/study", tags=["study"])


@router.get("/wrong-questions", response_model=ApiResponse[StudyWrongQuestionList])
async def wrong_questions(
    space_id: str | None = None,
    concept_id: str | None = None,
    question_type: Literal[
        "single", "multiple", "judge", "cloze", "numeric", "short_answer"
    ]
    | None = None,
    status: Literal["wrong", "partial"] | None = None,
    association_status: Literal["linked", "unlinked"] | None = None,
    origin_kind: Literal["quiz", "practice"] | None = None,
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=20, ge=1, le=100),
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await wrongbook_service.list_wrong_questions(
            actor,
            {
                "space_id": space_id,
                "concept_id": concept_id,
                "question_type": question_type,
                "status": status,
                "association_status": association_status,
                "origin_kind": origin_kind,
            },
            cursor,
            limit,
        )
    )


@router.get("/history", response_model=ApiResponse[StudyHistoryList])
async def learning_history(
    space_id: str | None = None,
    concept_id: str | None = None,
    scope_revision: int | None = Query(default=None, ge=1),
    status: str | None = None,
    origin_kind: Literal["quiz", "practice"] | None = None,
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=20, ge=1, le=100),
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await wrongbook_service.list_learning_history(
            actor,
            {
                "space_id": space_id,
                "concept_id": concept_id,
                "scope_revision": scope_revision,
                "status": status,
                "origin_kind": origin_kind,
            },
            cursor,
            limit,
        )
    )


@router.get("/reviews", response_model=ApiResponse[StudyReviewList])
async def due_reviews(
    space_id: str | None = None,
    concept_id: str | None = None,
    due_before: datetime | None = None,
    status: Literal["scheduled", "claimed", "running", "failed", "cancelled"]
    | None = None,
    paused: bool = False,
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=20, ge=1, le=100),
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await review_service.list_due_reviews(
            actor,
            {
                "space_id": space_id,
                "concept_id": concept_id,
                "due_before": due_before,
                "status": status,
                "paused": paused,
            },
            cursor,
            limit,
        )
    )


@router.post("/review-quiz-jobs", status_code=202, response_model=ApiResponse[TaskView])
async def start_review_quiz(
    body: ReviewQuizBody,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await review_service.start_review_quiz(actor, body, idempotency_key)
    )


@router.patch("/reviews/{review_id}", response_model=ApiResponse[StudyReviewView])
async def update_review(
    review_id: str, body: ReviewUpdateBody, actor=Depends(get_current_actor)
):
    return ApiResponse.success(
        await review_service.update_review(actor, review_id, body)
    )


@router.get(
    "/concepts/{concept_id}/progress",
    response_model=ApiResponse[StudyConceptProgressView],
)
async def concept_progress(concept_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await wrongbook_service.get_concept_progress(actor, concept_id)
    )


@router.get(
    "/qa-answers/{answer_id}/practice-context",
    response_model=ApiResponse[StudyQaPracticeContextView],
)
async def practice_context(answer_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(
        await qa_practice_source.practice_context_view(actor.owner_id, answer_id)
    )


@router.post(
    "/quiz-jobs/from-qa", status_code=202, response_model=ApiResponse[TaskView]
)
async def create_quiz_from_qa(
    body: StudyQuizFromQaBody,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(
        await learning_quiz_service.create_from_qa(actor, body, idempotency_key)
    )


@router.post("/spaces", status_code=201, response_model=ApiResponse[StudySpaceView])
async def create_space(
    body: StudySpaceCreate,
    actor=Depends(get_current_actor),
    idempotency_key: str = Header(..., min_length=1, max_length=128),
):
    return ApiResponse.success(await spaces.create_space(actor, body, idempotency_key))


@router.get("/spaces", response_model=ApiResponse[StudySpaceList])
async def list_spaces(
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(20, ge=1, le=100),
    status: Literal["active", "archived"] | None = None,
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await spaces.list_spaces(actor.owner_id, page, page_size, status)
    )


@router.get("/spaces/{space_id}", response_model=ApiResponse[StudySpaceView])
async def get_space(space_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await spaces.get_space(actor.owner_id, space_id))


@router.patch("/spaces/{space_id}", response_model=ApiResponse[StudySpaceView])
async def update_space(
    space_id: str, body: StudySpaceUpdate, actor=Depends(get_current_actor)
):
    return ApiResponse.success(await spaces.update_space(actor, space_id, body))


@router.patch("/spaces/{space_id}/scope", response_model=ApiResponse[StudySpaceView])
async def change_scope(
    space_id: str, body: StudyScopeUpdate, actor=Depends(get_current_actor)
):
    return ApiResponse.success(await spaces.change_scope(actor, space_id, body))


@router.get(
    "/spaces/{space_id}/scopes/{scope_revision}",
    response_model=ApiResponse[StudyScopeView],
)
async def get_scope(
    space_id: str,
    scope_revision: int = Path(..., ge=1),
    actor=Depends(get_current_actor),
):
    return ApiResponse.success(
        await spaces.get_scope(actor.owner_id, space_id, scope_revision)
    )


@router.post(
    "/spaces/{space_id}/goals",
    status_code=201,
    response_model=ApiResponse[StudyGoalView],
)
async def create_goal(
    space_id: str, body: StudyGoalCreate, actor=Depends(get_current_actor)
):
    return ApiResponse.success(await spaces.create_goal(actor, space_id, body))


@router.get("/spaces/{space_id}/goals", response_model=ApiResponse[StudyGoalList])
async def list_goals(space_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await spaces.list_goals(actor.owner_id, space_id))


@router.patch("/goals/{goal_id}", response_model=ApiResponse[StudyGoalView])
async def update_goal(
    goal_id: str, body: StudyGoalUpdate, actor=Depends(get_current_actor)
):
    return ApiResponse.success(await spaces.update_goal(actor, goal_id, body))


@router.post(
    "/goals/{goal_id}/units", status_code=201, response_model=ApiResponse[StudyUnitView]
)
async def create_unit(
    goal_id: str, body: StudyUnitCreate, actor=Depends(get_current_actor)
):
    return ApiResponse.success(await spaces.create_unit(actor, goal_id, body))


@router.get("/goals/{goal_id}/units", response_model=ApiResponse[StudyUnitList])
async def list_units(goal_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await spaces.list_units(actor.owner_id, goal_id))


@router.patch("/goals/{goal_id}/units/order", response_model=ApiResponse[StudyUnitList])
async def reorder_units(
    goal_id: str, body: StudyUnitReorder, actor=Depends(get_current_actor)
):
    return ApiResponse.success(await spaces.reorder_units(actor, goal_id, body))


@router.patch("/units/{unit_id}", response_model=ApiResponse[StudyUnitView])
async def update_unit(
    unit_id: str, body: StudyUnitUpdate, actor=Depends(get_current_actor)
):
    return ApiResponse.success(await spaces.update_unit(actor, unit_id, body))


@router.post(
    "/spaces/{space_id}/concepts",
    status_code=201,
    response_model=ApiResponse[StudyConceptView],
)
async def create_concept(
    space_id: str, body: StudyConceptCreate, actor=Depends(get_current_actor)
):
    return ApiResponse.success(await concepts.create_concept(actor, space_id, body))


@router.get("/spaces/{space_id}/concepts", response_model=ApiResponse[StudyConceptList])
async def list_concepts(space_id: str, actor=Depends(get_current_actor)):
    return ApiResponse.success(await concepts.list_concepts(actor.owner_id, space_id))


@router.patch("/concepts/{concept_id}", response_model=ApiResponse[StudyConceptView])
async def update_concept(
    concept_id: str, body: StudyConceptUpdate, actor=Depends(get_current_actor)
):
    return ApiResponse.success(await concepts.update_concept(actor, concept_id, body))
