from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.app.core.logging_setup import get_logger
from src.app.services.job_service import JobService
from src.app.normalization.normalizers import NORMALIZER_REGISTRY

log = get_logger(__name__)


class NormalizationService:
    """Runs per-object normalizers and persists output tables. Implemented Phase 3."""

    def __init__(self, db: Session, job_service: JobService) -> None:
        self.db = db
        self.job_service = job_service

    async def normalize_scan(
        self,
        scan_id: str,
        output_format: str = "parquet",
        save_to_disk: bool = True,
        upload_to_minio: bool = False,
        processing_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    async def normalize_single_object(
        self, scan_id: str, object_name: str
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def list_normalized_tables(self, scan_id: str) -> List[Dict[str, Any]]:
        return []

    @staticmethod
    def supported_objects() -> List[Dict[str, Any]]:
        from src.app.normalization.normalizers import SUPPORTED_OBJECTS_CATALOG

        return [
            {"object_name": name, "output_tables": tables}
            for name, tables in SUPPORTED_OBJECTS_CATALOG.items()
        ]
