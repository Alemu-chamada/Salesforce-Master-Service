from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.security.hmac import hmac_auth_required

router = APIRouter(dependencies=[Depends(hmac_auth_required)])


@router.post("/cleanup")
async def cleanup_old_scans(days_old: int = Query(..., ge=1)) -> Dict[str, Any]:
    raise HTTPException(status_code=501, detail="cleanup implemented in Phase 3")


@router.post("/detect-crashed")
async def detect_crashed_jobs(timeout_minutes: int = Query(..., ge=1)) -> Dict[str, Any]:
    raise HTTPException(status_code=501, detail="detect-crashed implemented in Phase 2")
