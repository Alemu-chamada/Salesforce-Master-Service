from __future__ import annotations

import asyncio
import time
from typing import Any

from sqlalchemy.orm import Session

from src.app.audit.audit_service import AuditService
from src.app.core.config import get_settings
from src.app.core.logging_setup import get_logger
from src.app.db.session import get_session_factory
from src.app.models import JobStatus
from src.app.resilience.dlq import write_to_dlq
from src.app.resilience.retry import retry_call
from src.app.salesforce.auth_client import SalesforceAuthClient
from src.app.salesforce.batch_api_client import SalesforceBatchAPIClient
from src.app.salesforce.queries import query_for
from src.app.services.batch_file_service import BatchFileService
from src.app.services.job_service import JobService

log = get_logger(__name__)


class BatchPollingService:
    """Submits Bulk API jobs per object, polls, downloads. Implemented Phase 2."""

    def __init__(self, db: Session, job_service: JobService, *, auth_client: SalesforceAuthClient | None = None, file_service: BatchFileService | None = None) -> None:
        self.db = db
        self.job_service = job_service
        self.auth_client = auth_client
        self.file_service = file_service or BatchFileService()
        self.batch_client: SalesforceBatchAPIClient | None = None
        self.audit = AuditService(get_session_factory)

    async def configure(self, credentials: dict[str, Any]) -> SalesforceBatchAPIClient:
        settings = get_settings()
        auth = self.auth_client or SalesforceAuthClient(settings)
        token = await auth.get_access_token(credentials)
        self.batch_client = SalesforceBatchAPIClient(
            token["access_token"], token["instance_url"], settings.SF_API_VERSION,
            timeout_seconds=settings.SF_TIMEOUT_SECONDS,
        )
        return self.batch_client

    async def submit_batch_jobs(self, scan_id: str, objects: list[str]) -> dict[str, Any]:
        if not objects:
            raise ValueError("at least one Salesforce object is required")
        if self.batch_client is None:
            raise RuntimeError("BatchPollingService is not configured")
        self.job_service.update_job_status(scan_id, JobStatus.BATCH_REQUESTED)
        ids: list[dict[str, Any]] = []
        statuses: dict[str, Any] = {}
        job = self.job_service.get_job(scan_id)
        organization_id = job.organization_id if job else None
        for object_name in objects:
            operation = f"create_query_job:{object_name}"
            try:
                result = await retry_call(
                    self.batch_client.create_query_job,
                    object_name,
                    query_for(object_name),
                    op_label=operation,
                )
            except Exception as exc:
                if getattr(exc, "retryable", False):
                    write_to_dlq("salesforce", operation, {"object_name": object_name}, get_settings().EXTERNAL_CALL_MAX_RETRIES + 1, exc, organization_id, scan_id)
                raise
            ids.append({"object_name": object_name, "job_id": result["job_id"]})
            statuses[object_name] = result.get("state", "UploadComplete")
        self.job_service.update_batch_info(scan_id, ids, statuses)
        self.job_service.update_job_status(scan_id, JobStatus.BATCH_PROCESSING)
        self.job_service.update_heartbeat(scan_id)
        self.audit.write_audit_nonblocking("external", "batch_submission_success", organization_id=organization_id, resource_id=scan_id, extra_metadata={"objects": objects})
        return {"batch_job_ids": ids, "batch_status": statuses}

    async def check_and_update_status(self, scan_id: str) -> dict[str, Any]:
        job = self.job_service.get_job(scan_id)
        if job is None or not job.batch_job_ids or self.batch_client is None:
            raise ValueError(f"batch jobs unavailable for scan {scan_id}")
        statuses = {}
        failed = []
        for item in job.batch_job_ids:
            name, job_id = item["object_name"], item["job_id"]
            operation = f"get_job_status:{name}"
            try:
                status = await retry_call(self.batch_client.get_job_status, job_id, op_label=operation)
            except Exception as exc:
                if getattr(exc, "retryable", False):
                    write_to_dlq("salesforce", operation, {"job_id": job_id}, get_settings().EXTERNAL_CALL_MAX_RETRIES + 1, exc, job.organization_id, scan_id)
                raise
            state = status.get("state", "Unknown")
            statuses[name] = status
            if state in {"Failed", "Aborted"}:
                failed.append(f"{name}: {status.get('error_message') or state}")
        self.job_service.update_batch_info(scan_id, batch_status=statuses)
        self.job_service.update_heartbeat(scan_id)
        if failed:
            self.audit.write_audit_nonblocking("external", "batch_failure", outcome="failure", organization_id=job.organization_id, resource_id=scan_id, extra_metadata={"errors": failed})
            raise RuntimeError("Salesforce batch failure: " + "; ".join(failed))
        states = {value.get("state") for value in statuses.values()}
        if states and states <= {"JobComplete"}:
            self.job_service.update_job_status(scan_id, JobStatus.BATCH_READY)
            return {"ready": True, "statuses": statuses}
        return {"ready": False, "statuses": statuses}

    async def poll_until_ready(
        self,
        scan_id: str,
        max_wait_minutes: int = 120,
        check_interval_seconds: int = 10,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max_wait_minutes * 60
        while time.monotonic() <= deadline:
            result = await self.check_and_update_status(scan_id)
            if result["ready"]:
                return result
            await asyncio.sleep(max(0, check_interval_seconds))
        raise TimeoutError(f"Salesforce batch jobs did not complete within {max_wait_minutes} minutes")

    async def download_results(self, scan_id: str) -> dict[str, Any]:
        batch_client = self.batch_client
        if batch_client is None:
            raise RuntimeError("BatchPollingService is not configured")
        self.job_service.update_job_status(scan_id, JobStatus.DOWNLOADING)
        paths, sizes = {}, {}
        job = self.job_service.get_job(scan_id)
        if job is None:
            raise ValueError(f"scan {scan_id} not found")
        for item in job.batch_job_ids or []:
            object_name, job_id = item["object_name"], item["job_id"]

            async def _download(job_id_value: str, object_name_value: str) -> dict[str, Any]:
                chunks = batch_client.get_job_results_paginated(job_id_value)
                return await self.file_service.save_async_results_to_disk(scan_id, object_name_value, chunks)

            try:
                info = await retry_call(_download, job_id, object_name, op_label=f"get_job_results:{object_name}")
            except Exception as exc:
                if getattr(exc, "retryable", False):
                    write_to_dlq("salesforce", f"get_job_results:{object_name}", {"job_id": job_id}, get_settings().EXTERNAL_CALL_MAX_RETRIES + 1, exc, job.organization_id, scan_id)
                raise
            paths[object_name], sizes[object_name] = info["path"], info["file_size"]
            try:
                await retry_call(batch_client.close_job, job_id, op_label=f"close_job:{object_name}")
            except Exception as exc:
                if getattr(exc, "retryable", False):
                    write_to_dlq("salesforce", f"close_job:{object_name}", {"job_id": job_id}, get_settings().EXTERNAL_CALL_MAX_RETRIES + 1, exc, job.organization_id, scan_id)
                raise
            self.job_service.update_heartbeat(scan_id)
        self.job_service.update_download_info(scan_id, paths, sizes)
        self.job_service.update_job_status(scan_id, JobStatus.DOWNLOADED)
        return {"file_paths": paths, "file_sizes": sizes}
