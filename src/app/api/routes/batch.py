from __future__ import annotations

from fastapi import APIRouter, Depends

from src.app.core.config import get_settings
from src.app.schemas.common import BaseResponse
from src.app.security.hmac import hmac_auth_readonly

router = APIRouter(dependencies=[Depends(hmac_auth_readonly)])


class BatchInfoResponse(BaseResponse):
    poll_interval_seconds: int
    max_wait_minutes: int
    supported_objects: list[str]
    api_version: str


@router.get("/info")
async def get_batch_info() -> BatchInfoResponse:
    settings = get_settings()
    return BatchInfoResponse(
        poll_interval_seconds=settings.SF_BULK_POLL_INTERVAL_SECONDS,
        max_wait_minutes=settings.SF_BULK_MAX_WAIT_MINUTES,
        supported_objects=list(settings.SF_BULK_SUPPORTED_OBJECTS),
        api_version=settings.SF_API_VERSION,
    )
