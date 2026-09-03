from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.app.core.logging_setup import get_logger
from src.app.models import AuditLog, AuditEventCategory, AuditOutcome

log = get_logger(__name__)


class AuditService:
    """Fire-and-forget inserts into audit_logs. Non-blocking via asyncio.create_task."""

    def __init__(self, db_factory: Any) -> None:
        self._db_factory = db_factory

    def _sync_write(
        self,
        event_category: AuditEventCategory | str,
        event_type: str,
        outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
        organization_id: Optional[str] = None,
        actor_client_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        entity_type: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        http_method: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_ip: Optional[str] = None,
        status_code: Optional[int] = None,
        severity: str = "info",
        error_detail: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            db: Session = next(self._db_factory()) if callable(self._db_factory) else self._db_factory()
            row = AuditLog(
                event_category=AuditEventCategory(event_category)
                if isinstance(event_category, str)
                else event_category,
                event_type=event_type,
                outcome=AuditOutcome(outcome) if isinstance(outcome, str) else outcome,
                organization_id=organization_id,
                actor_client_id=actor_client_id,
                actor_role=actor_role,
                entity_type=entity_type,
                resource_type=resource_type,
                resource_id=resource_id,
                http_method=http_method,
                endpoint=endpoint,
                request_ip=request_ip,
                status_code=status_code,
                severity=severity,
                error_detail=error_detail,
                extra_metadata=extra_metadata or {},
            )
            db.add(row)
            db.commit()
            db.close()
        except Exception as exc:  # pragma: no cover - never break caller
            log.warning("AuditService write failed: %s", exc)

    async def write_audit(
        self,
        event_category: AuditEventCategory | str,
        event_type: str,
        outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
        organization_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._sync_write(
                event_category=event_category,
                event_type=event_type,
                outcome=outcome,
                organization_id=organization_id,
                **kwargs,
            ),
        )

    def write_audit_nonblocking(
        self,
        event_category: AuditEventCategory | str,
        event_type: str,
        **kwargs: Any,
    ) -> None:
        try:
            asyncio.create_task(
                self.write_audit(event_category, event_type, **kwargs)
            )
        except RuntimeError:  # no running loop (e.g. tests)
            self._sync_write(event_category, event_type, **kwargs)
