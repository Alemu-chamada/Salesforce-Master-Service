from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.security.hmac import hmac_auth_readonly

router = APIRouter(dependencies=[Depends(hmac_auth_readonly)])


@router.get("/logs")
async def get_audit_logs(
    organization_id: Optional[str] = Query(default=None),
    event_category: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None),
    to_date: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    raise HTTPException(status_code=501, detail="audit/logs implemented in Phase 3")


@router.get("/stats")
async def get_audit_stats(window_minutes: int = Query(default=60, ge=1)) -> Dict[str, Any]:
    raise HTTPException(status_code=501, detail="audit/stats implemented in Phase 3")
