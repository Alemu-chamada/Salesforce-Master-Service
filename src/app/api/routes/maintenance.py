from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.db.session import get_db
from src.app.security.hmac import hmac_auth_required
from src.app.services.job_service import JobService

router = APIRouter(dependencies=[Depends(hmac_auth_required)])


@router.post("/cleanup")
async def cleanup_old_scans(days_old: int = Query(..., ge=1), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"deleted_jobs": JobService(db).cleanup_old_jobs(days_old)}


@router.post("/detect-crashed")
async def detect_crashed_jobs(timeout_minutes: int = Query(..., ge=1), db: Session = Depends(get_db)) -> dict[str, Any]:
    crashed = JobService(db).detect_crashed_jobs(timeout_minutes)
    return {"crashed_scan_ids": crashed, "count": len(crashed)}
