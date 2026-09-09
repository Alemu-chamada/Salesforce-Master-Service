from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.utils import utcnow
from src.app.db.base import Base
from src.app.models.enums import DLQStatus


class FailedExternalCall(Base):
    __tablename__ = "failed_external_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    target_service: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    operation: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    organization_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    scan_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    payload_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[DLQStatus] = mapped_column(
        Enum(DLQStatus, name="dlq_status_enum"),
        default=DLQStatus.NEW,
        index=True,
        nullable=False,
    )

    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False
    )

    __table_args__ = (
        Index("ix_dlq_service_status_created", "target_service", "status", "created_at"),
    )
