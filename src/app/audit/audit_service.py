from __future__ import annotations

import asyncio
from typing import Any

from src.app.core.logging_setup import get_logger
from src.app.models import AuditEventCategory, AuditLog, AuditOutcome

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
        organization_id: str | None = None,
        actor_client_id: str | None = None,
        actor_role: str | None = None,
        entity_type: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        http_method: str | None = None,
        endpoint: str | None = None,
        request_ip: str | None = None,
        status_code: int | None = None,
        severity: str = "info",
        error_detail: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            if callable(self._db_factory):
                candidate = self._db_factory()
                if hasattr(candidate, "add"):
                    db = candidate
                elif hasattr(candidate, "__next__"):
                    db = next(candidate)
                else:
                    db = candidate()
            else:
                db = self._db_factory
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
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:  # pragma: no cover - never break caller
            log.warning("AuditService write failed: %s", exc)

    async def write_audit(
        self,
        event_category: AuditEventCategory | str,
        event_type: str,
        outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
        organization_id: str | None = None,
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
