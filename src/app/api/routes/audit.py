from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.app.db.session import get_db
from src.app.models import AuditLog
from src.app.security.hmac import hmac_auth_readonly

router = APIRouter(dependencies=[Depends(hmac_auth_readonly)])


@router.get("/logs")
async def get_audit_logs(
    organization_id: str | None = Query(default=None),
    event_category: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = db.query(AuditLog)
    if organization_id: query = query.filter(AuditLog.organization_id == organization_id)
    if event_category: query = query.filter(AuditLog.event_category == event_category)
    if event_type: query = query.filter(AuditLog.event_type == event_type)
    if outcome: query = query.filter(AuditLog.outcome == outcome)
    total = query.count()
    rows = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [{"id": row.id, "event_category": row.event_category.value, "event_type": row.event_type, "organization_id": row.organization_id, "outcome": row.outcome.value, "created_at": row.created_at.isoformat()} for row in rows], "page": page, "page_size": page_size, "total": total}


@router.get("/stats")
async def get_audit_stats(window_minutes: int = Query(default=60, ge=1), db: Session = Depends(get_db)) -> dict[str, Any]:
    from src.app.core.utils import utcnow
    cutoff = utcnow() - __import__("datetime").timedelta(minutes=window_minutes)
    rows = db.query(AuditLog.outcome, func.count(AuditLog.id)).filter(AuditLog.created_at >= cutoff).group_by(AuditLog.outcome).all()
    return {"window_minutes": window_minutes, "counts_by_outcome": {outcome.value: count for outcome, count in rows}}
