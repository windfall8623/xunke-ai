from fastapi import APIRouter, Depends, Query, Response

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.course_export import CourseExportView
from app.services import course_export_service

router = APIRouter(prefix="/courses", tags=["course-export"])


@router.get("/{course_id}/export", response_model=ApiResponse[CourseExportView])
async def export_course(
    course_id: str,
    format: str = Query("markdown", pattern="^markdown$"),
    include_history: bool = Query(False),
    actor=Depends(get_current_actor),
):
    view = await course_export_service.build_course_export(
        actor.owner_id, course_id, include_history=include_history)
    return ApiResponse.success(view.model_dump(mode="json"))
