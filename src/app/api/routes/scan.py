from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.app.core.utils import build_pagination_info
from src.app.db.session import get_db
from src.app.schemas.common import (
    PaginationInfo,
    ScanListResponse,
    ScanResumeRequest,
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
) -> dict[str, Any]:
    return await svc.start_scan(request)


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
) -> dict[str, Any]:
    try:
        return await svc.cancel_scan(scan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{scan_id}/resume")
async def resume_scan(
    scan_id: str,
    request: ScanResumeRequest | None = None,
    svc: ExtractionService = Depends(_extraction_service),
) -> dict[str, Any]:
    try:
        return await svc.resume_scan(
            scan_id,
            request.salesforce_credentials if request else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/list")
async def list_scans(
    organization_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ScanListResponse:
    result = JobService(db).list_jobs(organization_id=organization_id, page=page, page_size=page_size)
    return ScanListResponse(items=result["items"], pagination=PaginationInfo(**build_pagination_info(page, page_size, result["total"])))


@router.get("/statistics")
async def get_scan_statistics(
    svc: ExtractionService = Depends(_extraction_service),
) -> ScanStatisticsResponse:
    return ScanStatisticsResponse(counts_by_status=svc.get_scan_statistics())


@router.delete("/{scan_id}/remove")
async def remove_scan(
    scan_id: str,
    svc: ExtractionService = Depends(_extraction_service),
) -> dict[str, Any]:
    try:
        return {"removed": svc.remove_scan(scan_id), "scan_id": scan_id}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
