from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.app.core.logging_setup import get_logger
from src.app.core.utils import utcnow
from src.app.models import (
    IN_PROGRESS_STATUSES,
    Job,
    JobStatus,
    JobStatusTransition,
)

log = get_logger(__name__)


class JobService:
    """Tracking and state-machine for scan jobs."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def create_job(
        self,
        scan_id: str,
        organization_id: str | None,
        request_config: dict[str, Any] | None = None,
    ) -> Job:
        job = Job(
            scan_id=scan_id,
            organization_id=organization_id,
            status=JobStatus.PENDING,
            request_config=request_config or {},
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        log.info("Created job scan_id=%s org=%s", scan_id, organization_id)
        return job

    def get_job(self, scan_id: str) -> Job | None:
        return self.db.get(Job, scan_id)

    def update_job_status(self, scan_id: str, status: JobStatus) -> Job | None:
        job = self.get_job(scan_id)
        if job is None:
            return None
        current: JobStatus = job.status
        if not JobStatusTransition.is_valid_transition(current, status):
            log.warning(
                "Refusing status transition scan_id=%s %s -> %s",
                scan_id, current.value, status.value,
            )
            return job
        job.status = status
        job.updated_at = utcnow()
        if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            job.completed_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def resume_job(self, scan_id: str, status: JobStatus) -> Job | None:
        """Re-enter the persisted pipeline at an explicitly selected stage."""
        job = self.get_job(scan_id)
        if job is None or job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
            return None
        if status not in JobStatusTransition.MAIN_CHAIN:
            return None
        job.status = status
        job.error_message = None
        job.completed_at = None
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def update_heartbeat(self, scan_id: str) -> Job | None:
        job = self.get_job(scan_id)
        if job is None:
            return None
        job.last_heartbeat = utcnow()
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def fail_job(self, scan_id: str, error: BaseException | str) -> Job | None:
        job = self.get_job(scan_id)
        if job is None or job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return None
        msg = str(error) if isinstance(error, BaseException) else error
        job.status = JobStatus.FAILED
        job.error_message = msg[:4000]
        job.completed_at = utcnow()
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def cancel_job(self, scan_id: str, reason: str | None = None, actor: str | None = None) -> Job | None:
        job = self.get_job(scan_id)
        if job is None or job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return None
        job.status = JobStatus.CANCELLED
        job.cancel_reason = reason
        job.cancelled_by = actor
        job.completed_at = utcnow()
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    # ------------------------------------------------------------------
    # Batch phase
    # ------------------------------------------------------------------

    def update_batch_info(
        self,
        scan_id: str,
        batch_job_ids: list[Any] | None = None,
        batch_status: dict[str, Any] | None = None,
    ) -> Job | None:
        job = self.get_job(scan_id)
        if job is None:
            return None
        if batch_job_ids is not None:
            job.batch_job_ids = batch_job_ids
        if batch_status is not None:
            job.batch_status = batch_status
        if job.batch_requested_at is None:
            job.batch_requested_at = utcnow()
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    # ------------------------------------------------------------------
    # Download phase
    # ------------------------------------------------------------------

    def update_download_info(
        self,
        scan_id: str,
        file_paths: dict[str, Any] | None = None,
        file_sizes: dict[str, Any] | None = None,
    ) -> Job | None:
        job = self.get_job(scan_id)
        if job is None:
            return None
        if file_paths is not None:
            job.file_paths = file_paths
        if file_sizes is not None:
            job.file_sizes = file_sizes
        job.downloaded_at = utcnow()
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    # ------------------------------------------------------------------
    # Extraction phase
    # ------------------------------------------------------------------

    def update_extraction_info(
        self,
        scan_id: str,
        extracted_file_counts: dict[str, Any] | None = None,
    ) -> Job | None:
        job = self.get_job(scan_id)
        if job is None:
            return None
        if extracted_file_counts is not None:
            job.entity_record_counts = extracted_file_counts
        job.extracted_at = utcnow()
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def store_entity_record_counts(
        self, scan_id: str, counts_by_object: dict[str, int]
    ) -> Job | None:
        job = self.get_job(scan_id)
        if job is None:
            return None
        existing = dict(job.entity_record_counts or {})
        existing.update(counts_by_object)
        job.entity_record_counts = existing
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    # ------------------------------------------------------------------
    # Normalization phase
    # ------------------------------------------------------------------

    def start_normalization(self, scan_id: str) -> Job | None:
        return self.update_job_status(scan_id, JobStatus.NORMALIZING)

    def complete_normalization(
        self, scan_id: str, stats: dict[str, Any] | None = None
    ) -> Job | None:
        job = self.update_job_status(scan_id, JobStatus.NORMALIZED)
        if job is None or job.status != JobStatus.NORMALIZED:
            return job
        job.normalized_at = utcnow()
        job.normalization_stats = stats or {}
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    # ------------------------------------------------------------------
    # MinIO upload phase
    # ------------------------------------------------------------------

    def start_minio_upload(self, scan_id: str) -> Job | None:
        return self.update_job_status(scan_id, JobStatus.UPLOADING_TO_MINIO)

    def complete_minio_upload(
        self, scan_id: str, uploaded_keys: dict[str, Any] | None = None
    ) -> Job | None:
        job = self.update_job_status(scan_id, JobStatus.UPLOADED_TO_MINIO)
        if job is None or job.status != JobStatus.UPLOADED_TO_MINIO:
            return job
        job.minio_uploaded_at = utcnow()
        job.minio_object_keys = uploaded_keys or {}
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    # ------------------------------------------------------------------
    # Progress + listing
    # ------------------------------------------------------------------

    def get_pipeline_progress(self, scan_id: str) -> dict[str, Any]:
        job = self.get_job(scan_id)
        if job is None:
            return {}
        return {
            "status": job.status.value,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "batch_requested_at": job.batch_requested_at.isoformat() if job.batch_requested_at else None,
            "downloaded_at": job.downloaded_at.isoformat() if job.downloaded_at else None,
            "extracted_at": job.extracted_at.isoformat() if job.extracted_at else None,
            "normalized_at": job.normalized_at.isoformat() if job.normalized_at else None,
            "minio_uploaded_at": job.minio_uploaded_at.isoformat() if job.minio_uploaded_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "last_heartbeat": job.last_heartbeat.isoformat() if job.last_heartbeat else None,
        }

    def get_pipeline_info(self) -> dict[str, Any]:
        """Return service-level pipeline info (supported objects, etc.)."""
        from src.app.core.config import get_settings
        settings = get_settings()
        return {
            "supported_objects": list(settings.SF_BULK_SUPPORTED_OBJECTS),
            "poll_interval_seconds": settings.SF_BULK_POLL_INTERVAL_SECONDS,
            "max_wait_minutes": settings.SF_BULK_MAX_WAIT_MINUTES,
        }

    def list_jobs(
        self,
        organization_id: str | None = None,
        status: JobStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        query = self.db.query(Job)
        if organization_id:
            query = query.filter(Job.organization_id == organization_id)
        if status:
            query = query.filter(Job.status == status)
        total = query.count()
        offset = (page - 1) * page_size
        jobs = query.order_by(Job.created_at.desc()).offset(offset).limit(page_size).all()
        return {
            "items": [self._job_to_dict(j) for j in jobs],
            "total": total,
        }

    def get_statistics(self) -> dict[str, int]:
        rows = self.db.query(Job.status, func.count(Job.scan_id)).group_by(Job.status).all()
        return {row[0].value: row[1] for row in rows}

    def _job_to_dict(self, job: Job) -> dict[str, Any]:
        from src.app.core.utils import deep_serialize
        return deep_serialize({
            "scan_id": job.scan_id,
            "organization_id": job.organization_id,
            "status": job.status.value,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "completed_at": job.completed_at,
            "error_message": job.error_message,
            "entity_record_counts": job.entity_record_counts or {},
            "batch_job_ids": job.batch_job_ids or [],
            "file_paths": job.file_paths or {},
            "last_heartbeat": job.last_heartbeat,
        })

    # ------------------------------------------------------------------
    # Crash detection
    # ------------------------------------------------------------------

    def detect_crashed_jobs(self, timeout_minutes: int = 30) -> list[str]:
        """Find in-progress jobs whose heartbeat has gone stale and mark them FAILED."""
        cutoff = utcnow() - _dt.timedelta(minutes=timeout_minutes)
        crashed_ids = []
        for status in IN_PROGRESS_STATUSES:
            jobs = (
                self.db.query(Job)
                .filter(
                    Job.status == status,
                    (Job.last_heartbeat < cutoff) | (Job.last_heartbeat.is_(None)),
                )
                .all()
            )
            for job in jobs:
                log.warning(
                    "Crash detected scan_id=%s status=%s last_heartbeat=%s",
                    job.scan_id, job.status.value,
                    job.last_heartbeat.isoformat() if job.last_heartbeat else "never",
                )
                previous_status = job.status.value
                job.status = JobStatus.FAILED
                job.error_message = (
                    f"crash detected: job was in status {previous_status} "
                    f"with no heartbeat for >{timeout_minutes} minutes"
                )
                job.completed_at = utcnow()
                job.updated_at = utcnow()
                crashed_ids.append(job.scan_id)
        if crashed_ids:
            self.db.commit()
        return crashed_ids

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_old_jobs(self, days_old: int = 30) -> int:
        """Delete jobs (and associated data) older than `days_old` days. Returns deleted count."""
        cutoff = utcnow() - _dt.timedelta(days=days_old)
        old_jobs = (
            self.db.query(Job)
            .filter(Job.created_at < cutoff)
            .all()
        )
        count = len(old_jobs)
        for job in old_jobs:
            self.db.delete(job)
        if count:
            self.db.commit()
        log.info("Cleaned up %d old jobs older than %d days", count, days_old)
        return count
