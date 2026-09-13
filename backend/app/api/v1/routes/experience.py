from fastapi import APIRouter, Depends

from app.core.auth import get_current_actor
from app.models.common import ApiResponse
from app.models.experience import ExperienceEventInput, ExperienceEventReceipt
from app.services.experience_event_service import record_experience_event

router = APIRouter(prefix="/experience", tags=["experience"])


@router.post("/events", status_code=202, response_model=ApiResponse[ExperienceEventReceipt])
async def record(body: ExperienceEventInput, actor=Depends(get_current_actor)):
    return ApiResponse.success(await record_experience_event(actor, body))
