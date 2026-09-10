from __future__ import annotations

import asyncio
import shutil
import uuid
from typing import Any

from sqlalchemy.orm import Session

from src.app.audit.audit_service import AuditService
from src.app.core.config import get_settings
from src.app.core.logging_setup import get_logger
from src.app.db.session import get_session_factory
from src.app.models import JobStatus
from src.app.schemas.common import ScanStartRequest
from src.app.services.batch_file_service import BatchFileService
from src.app.services.batch_polling_service import BatchPollingService
from src.app.services.job_service import JobService

log = get_logger(__name__)


class ExtractionService:
    """Top-level scan orchestrator. Implemented Phase 2+."""

    def __init__(self, db: Session, job_service: JobService, *, polling_service: BatchPollingService | None = None, file_service: BatchFileService | None = None) -> None:
        self.db = db
        self.job_service = job_service
        self.file_service = file_service or BatchFileService()
        self.polling_service = polling_service or BatchPollingService(db, job_service, file_service=self.file_service)
        self._runtime_credentials: dict[str, dict[str, Any]] = {}
        self.audit = AuditService(get_session_factory)

    async def start_scan(self, request_config: ScanStartRequest) -> dict[str, Any]:
        scan_id = f"scan-{uuid.uuid4().hex[:16]}"
        self._runtime_credentials[scan_id] = dict(request_config.salesforce_credentials)
        config = request_config.model_dump(exclude={"salesforce_credentials"})
        self.job_service.create_job(scan_id, request_config.organization_id, config)
        self.audit.write_audit_nonblocking("scan", "scan_created", organization_id=request_config.organization_id, resource_id=scan_id)
        asyncio.create_task(self._execute_batch_workflow(scan_id, request_config.object_names))
        return {"scan_id": scan_id, "status": JobStatus.PENDING.value}

    async def _execute_batch_workflow(self, scan_id: str, objects: list[str] | None = None) -> None:
        try:
            job = self.job_service.get_job(scan_id)
            if job is None:
                raise ValueError(f"scan {scan_id} not found")
            if job.status == JobStatus.CANCELLED:
                return
            if job.extracted_at:
                return
            await self.polling_service.configure(self._runtime_credentials[scan_id])
            settings = get_settings()
            selected = objects or list(settings.SF_BULK_SUPPORTED_OBJECTS)
            if not job.batch_job_ids:
                await self.polling_service.submit_batch_jobs(scan_id, selected)
                await self.polling_service.poll_until_ready(scan_id, settings.SF_BULK_MAX_WAIT_MINUTES, settings.SF_BULK_POLL_INTERVAL_SECONDS)
                await self.polling_service.download_results(scan_id)
            elif job.downloaded_at and not job.extracted_at:
                self.job_service.update_job_status(scan_id, JobStatus.EXTRACTING)
            self.job_service.update_job_status(scan_id, JobStatus.EXTRACTING)
            info = self.file_service.get_file_info(scan_id)
            self.job_service.update_extraction_info(scan_id, {item["object_name"]: item["record_count"] for item in info["files"]})
            self.job_service.update_job_status(scan_id, JobStatus.EXTRACTED)
        except asyncio.CancelledError:
            raise
        except (RuntimeError, ValueError, TypeError, OSError, TimeoutError) as exc:
            self.job_service.fail_job(scan_id, exc)
            current = self.job_service.get_job(scan_id)
            self.audit.write_audit_nonblocking("scan", "scan_failed", outcome="failure", organization_id=(current.organization_id if current else None), resource_id=scan_id, error_detail=str(exc)[:4000])
        finally:
            self._runtime_credentials.pop(scan_id, None)

    async def resume_scan(
        self,
        scan_id: str,
        salesforce_credentials: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = self.job_service.get_job(scan_id)
        if job is None:
            raise ValueError(f"scan {scan_id} not found")
        if salesforce_credentials is not None:
            self._runtime_credentials[scan_id] = dict(salesforce_credentials)
        if scan_id not in self._runtime_credentials:
            raise RuntimeError("Salesforce credentials must be supplied when resuming after a restart")
        target = job.status
        if job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
            target = (
                JobStatus.EXTRACTED
                if job.extracted_at
                else JobStatus.EXTRACTING
                if job.downloaded_at
                else JobStatus.BATCH_PROCESSING
                if job.batch_job_ids
                else JobStatus.PENDING
            )
            if self.job_service.resume_job(scan_id, target) is None:
                raise RuntimeError("scan cannot be resumed from its persisted state")
        if target != JobStatus.EXTRACTED:
            asyncio.create_task(self._execute_batch_workflow(scan_id))
        return {"scan_id": scan_id, "status": job.status.value}

    async def cancel_scan(self, scan_id: str, reason: str | None = None) -> dict[str, Any]:
        job = self.job_service.get_job(scan_id)
        if job is None:
            raise ValueError(f"scan {scan_id} not found")
        for item in job.batch_job_ids or []:
            if self.polling_service.batch_client is not None:
                try:
                    from src.app.resilience.retry import retry_call
                    await retry_call(self.polling_service.batch_client.abort_job, item["job_id"], op_label="salesforce.abort_job")
                except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                    log.warning("Remote batch abort failed scan_id=%s: %s", scan_id, exc.__class__.__name__)
        updated = self.job_service.cancel_job(scan_id, reason=reason)
        self._runtime_credentials.pop(scan_id, None)
        self.audit.write_audit_nonblocking("scan", "scan_cancelled", organization_id=job.organization_id, resource_id=scan_id)
        return {"scan_id": scan_id, "status": updated.status.value if updated else None}

    def get_scan_status(self, scan_id: str) -> dict[str, Any] | None:
        job = self.job_service.get_job(scan_id)
        if job is None:
            return None
        return {
            "scan_id": job.scan_id,
            "organization_id": job.organization_id,
            "status": job.status.value,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error_message": job.error_message,
            "pipeline_progress": self.job_service.get_pipeline_progress(scan_id),
            "entity_record_counts": job.entity_record_counts or {},
        }

    def get_scan_statistics(self) -> dict[str, int]:
        return self.job_service.get_statistics()

    def remove_scan(self, scan_id: str) -> bool:
        job = self.job_service.get_job(scan_id)
        if job is None:
            return False
        if job.status not in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            raise ValueError("active scans cannot be removed")
        scan_dir = self.file_service.data_root / scan_id
        if scan_dir.exists():
            shutil.rmtree(scan_dir)
        self.db.delete(job)
        self.db.commit()
        self.audit.write_audit_nonblocking("scan", "scan_removed", organization_id=job.organization_id, resource_id=scan_id)
        return True
