from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.utils import utcnow
from src.app.db.base import Base
from src.app.models.enums import AuditEventCategory, AuditOutcome


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    event_category: Mapped[AuditEventCategory] = mapped_column(
        Enum(AuditEventCategory, name="audit_event_category_enum"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    actor_client_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    http_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    outcome: Mapped[AuditOutcome] = mapped_column(
        Enum(AuditOutcome, name="audit_outcome_enum"), index=True, nullable=False
    )
    severity: Mapped[str] = mapped_column(String(16), default="info")
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False
    )

    __table_args__ = (
        Index(
            "ix_audit_org_category_created",
            "organization_id",
            "event_category",
            "created_at",
        ),
        Index(
            "ix_audit_resource_category_outcome",
            "resource_id",
            "event_category",
            "outcome",
        ),
    )
