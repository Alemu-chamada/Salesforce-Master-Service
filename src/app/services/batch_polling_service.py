from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from src.app.core.logging_setup import get_logger
from src.app.services.job_service import JobService

log = get_logger(__name__)


class BatchPollingService:
    """Submits Bulk API jobs per object, polls, downloads. Implemented Phase 2."""

    def __init__(self, db: Session, job_service: JobService) -> None:
        self.db = db
        self.job_service = job_service

    async def submit_batch_jobs(self, scan_id: str, objects: List[str]) -> Dict[str, Any]:
        raise NotImplementedError

    async def check_and_update_status(self, scan_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def poll_until_ready(
        self,
        scan_id: str,
        max_wait_minutes: int = 120,
        check_interval_seconds: int = 10,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    async def download_results(self, scan_id: str) -> Dict[str, Any]:
        raise NotImplementedError
