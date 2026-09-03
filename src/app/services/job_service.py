from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.app.core.logging_setup import get_logger
from src.app.models import (
    Job,
    JobStatus,
    JobStatusTransition,
)
from src.app.core.utils import utcnow

log = get_logger(__name__)


class JobService:
    """Tracking and state-machine for scan jobs.

    Full behavior implemented in Phase 2+; placeholders ensure routing + tests work.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_job(
        self,
        scan_id: str,
        organization_id: Optional[str],
        request_config: Optional[Dict[str, Any]] = None,
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

    def get_job(self, scan_id: str) -> Optional[Job]:
        return self.db.get(Job, scan_id)

    def update_job_status(self, scan_id: str, status: JobStatus) -> Optional[Job]:
        job = self.get_job(scan_id)
        if job is None:
            return None
        current: JobStatus = job.status
        if not JobStatusTransition.is_valid_transition(current, status):
            log.warning(
                "Refusing status transition scan_id=%s %s -> %s",
                scan_id,
                current.value,
                status.value,
            )
            return job
        job.status = status
        job.updated_at = utcnow()
        if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            job.completed_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def update_heartbeat(self, scan_id: str) -> Optional[Job]:
        job = self.get_job(scan_id)
        if job is None:
            return None
        job.last_heartbeat = utcnow()
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def fail_job(self, scan_id: str, error: BaseException | str) -> Optional[Job]:
        job = self.get_job(scan_id)
        if job is None:
            return None
        msg = str(error) if isinstance(error, BaseException) else error
        job.status = JobStatus.FAILED
        job.error_message = msg[:4000]
        job.completed_at = utcnow()
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def cancel_job(self, scan_id: str, reason: Optional[str] = None, actor: Optional[str] = None) -> Optional[Job]:
        job = self.get_job(scan_id)
        if job is None:
            return None
        job.status = JobStatus.CANCELLED
        job.cancel_reason = reason
        job.cancelled_by = actor
        job.completed_at = utcnow()
        job.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_pipeline_progress(self, scan_id: str) -> Dict[str, Any]:
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
