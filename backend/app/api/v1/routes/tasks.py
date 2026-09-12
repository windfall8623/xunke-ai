from fastapi import APIRouter, Depends

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.task_overview import TaskOverviewView
from app.services import task_overview_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/active", response_model=ApiResponse[TaskOverviewView])
async def active(actor=Depends(get_current_actor)):
    """进行中任务、最近终态任务与处理中资料；跨页面通知的轮询数据源。"""
    return ApiResponse.success(await task_overview_service.get_overview(actor.owner_id))
