from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.app.core.logging_setup import get_logger
from src.app.schemas.common import ScanStartRequest
from src.app.services.job_service import JobService

log = get_logger(__name__)


class ExtractionService:
    """Top-level scan orchestrator. Implemented Phase 2+."""

    def __init__(self, db: Session, job_service: JobService) -> None:
        self.db = db
        self.job_service = job_service

    async def start_scan(self, request_config: ScanStartRequest) -> Dict[str, Any]:
        raise NotImplementedError

    async def resume_scan(self, scan_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def cancel_scan(self, scan_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def get_scan_status(self, scan_id: str) -> Optional[Dict[str, Any]]:
        job = self.job_service.get_job(scan_id)
        if job is None:
            return None
        return {
            "scan_id": job.scan_id,
            "organization_id": job.organization_id,
            "status": job.status.value,
            "error_message": job.error_message,
            "pipeline_progress": self.job_service.get_pipeline_progress(scan_id),
            "entity_record_counts": job.entity_record_counts or {},
        }

    def get_scan_statistics(self) -> Dict[str, int]:
        return {}

    def remove_scan(self, scan_id: str) -> bool:
        raise NotImplementedError
