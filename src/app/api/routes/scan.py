from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.app.core.utils import build_pagination_info
from src.app.db.session import get_db
from src.app.schemas.common import (
    PaginationInfo,
    ScanListResponse,
    ScanStartRequest,
    ScanStatisticsResponse,
    ScanStatusResponse,
)
from src.app.security.hmac import hmac_auth_required
from src.app.services.extraction_service import ExtractionService
from src.app.services.job_service import JobService

router = APIRouter(dependencies=[Depends(hmac_auth_required)])


def _extraction_service(db: Session = Depends(get_db)) -> ExtractionService:
    return ExtractionService(db, JobService(db))


@router.post("/start", status_code=202)
async def start_scan(
    request: ScanStartRequest,
    svc: ExtractionService = Depends(_extraction_service),
) -> Dict[str, Any]:
    raise HTTPException(status_code=501, detail="start_scan implemented in Phase 2")


@router.get("/{scan_id}/status")
async def get_scan_status(
    scan_id: str,
    svc: ExtractionService = Depends(_extraction_service),
) -> ScanStatusResponse:
    status = svc.get_scan_status(scan_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"scan {scan_id} not found")
    return ScanStatusResponse(**status)


@router.post("/{scan_id}/cancel")
async def cancel_scan(
    scan_id: str,
    svc: ExtractionService = Depends(_extraction_service),
) -> Dict[str, Any]:
    raise HTTPException(status_code=501, detail="cancel_scan implemented in Phase 2")


@router.post("/{scan_id}/resume")
async def resume_scan(
    scan_id: str,
    svc: ExtractionService = Depends(_extraction_service),
) -> Dict[str, Any]:
    raise HTTPException(status_code=501, detail="resume_scan implemented in Phase 2")


@router.get("/list")
async def list_scans(
    organization_id: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ScanListResponse:
    return ScanListResponse(
        items=[],
        pagination=PaginationInfo(**build_pagination_info(page, page_size, 0)),
    )


@router.get("/statistics")
async def get_scan_statistics(
    svc: ExtractionService = Depends(_extraction_service),
) -> ScanStatisticsResponse:
    return ScanStatisticsResponse(counts_by_status=svc.get_scan_statistics())


@router.delete("/{scan_id}/remove")
async def remove_scan(
    scan_id: str,
    svc: ExtractionService = Depends(_extraction_service),
) -> Dict[str, Any]:
    raise HTTPException(status_code=501, detail="remove_scan implemented in Phase 2")
