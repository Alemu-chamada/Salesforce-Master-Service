from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.app.core.utils import utcnow
from src.app.db.base import Base
from src.app.models.enums import JobStatus


class Job(Base):
    __tablename__ = "jobs"

    scan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status_enum"),
        default=JobStatus.PENDING,
        index=True,
        nullable=False,
    )

    request_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    cancelled_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch_job_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    batch_status: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    batch_requested_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    downloaded_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    file_paths: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    file_sizes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    extracted_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    entity_record_counts: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    normalized_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    normalization_stats: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    minio_uploaded_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    minio_object_keys: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    last_heartbeat: Mapped[_dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    completed_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_jobs_org_status_created", "organization_id", "status", "created_at"),
    )
