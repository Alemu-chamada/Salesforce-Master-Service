from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.app.audit.audit_service import AuditService
from src.app.core.config import get_settings
from src.app.core.logging_setup import get_logger
from src.app.db.session import get_session_factory
from src.app.models import JobStatus
from src.app.normalization.normalizers import NORMALIZER_REGISTRY
from src.app.resilience.dlq import write_to_dlq
from src.app.services.batch_file_service import BatchFileService
from src.app.services.job_service import JobService
from src.app.storage.minio_client import MinIOClient

log = get_logger(__name__)


class NormalizationService:
    """Runs per-object normalizers and persists output tables. Implemented Phase 3."""

    def __init__(self, db: Session, job_service: JobService, *, file_service: BatchFileService | None = None, minio_client: MinIOClient | None = None) -> None:
        self.db = db
        self.job_service = job_service
        self.file_service = file_service or BatchFileService()
        settings = get_settings()
        self.minio_client = minio_client or MinIOClient(settings.MINIO_ENDPOINT, settings.MINIO_ACCESS_KEY, settings.MINIO_SECRET_KEY, settings.MINIO_BUCKET, settings.MINIO_SECURE)
        self.audit = AuditService(get_session_factory)

    async def normalize_scan(
        self,
        scan_id: str,
        output_format: str = "parquet",
        save_to_disk: bool = True,
        upload_to_minio: bool = False,
        processing_date: str | None = None,
    ) -> dict[str, Any]:
        job = self.job_service.get_job(scan_id)
        if job is None:
            raise ValueError(f"scan {scan_id} not found")
        if job.status != JobStatus.EXTRACTED:
            raise ValueError("normalization requires an EXTRACTED scan")
        self.job_service.start_normalization(scan_id)
        self.job_service.update_heartbeat(scan_id)
        output_dir = self.file_service.data_root / scan_id / "normalized"
        all_tables, paths = {}, {}
        try:
            for file_info in self.file_service.get_file_info(scan_id)["files"]:
                self.job_service.update_heartbeat(scan_id)
                normalizer = NORMALIZER_REGISTRY.get(file_info["object_name"])
                if normalizer is None:
                    continue
                records = self.file_service.read_csv_file(file_info["path"])
                tables = normalizer.normalize(records)
                all_tables.update(tables)
                self.job_service.update_heartbeat(scan_id)
                if save_to_disk or upload_to_minio:
                    paths.update(normalizer.save_to_files(tables, str(output_dir), output_format))
            stats = {name: len(rows) for name, rows in all_tables.items()}
            self.job_service.complete_normalization(scan_id, stats)
            self.audit.write_audit_nonblocking("normalization", "normalization_success", organization_id=job.organization_id, resource_id=scan_id, extra_metadata=stats)
            if upload_to_minio:
                self.job_service.start_minio_upload(scan_id)
                self.job_service.update_heartbeat(scan_id)
                date = processing_date or __import__("datetime").date.today().isoformat()
                try:
                    keys = self.minio_client.upload_normalized_data(scan_id, job.organization_id or "unknown", date, paths)
                except Exception as exc:
                    write_to_dlq("minio", "upload_normalized_data", {"scan_id": scan_id, "tables": list(paths)}, get_settings().EXTERNAL_CALL_MAX_RETRIES + 1, exc, job.organization_id, scan_id)
                    self.audit.write_audit_nonblocking("external", "minio_upload_failure", outcome="failure", organization_id=job.organization_id, resource_id=scan_id, error_detail=str(exc)[:4000])
                    raise
                self.job_service.complete_minio_upload(scan_id, {str(index): key for index, key in enumerate(keys)})
                self.job_service.update_heartbeat(scan_id)
                self.job_service.update_job_status(scan_id, JobStatus.COMPLETED)
                self.audit.write_audit_nonblocking("external", "minio_upload_success", organization_id=job.organization_id, resource_id=scan_id, extra_metadata={"object_keys": keys})
            updated = self.job_service.get_job(scan_id)
            return {"scan_id": scan_id, "status": updated.status.value if updated else "UNKNOWN", "tables": stats, "paths": paths}
        except Exception as exc:
            self.job_service.fail_job(scan_id, exc)
            self.audit.write_audit_nonblocking("normalization", "normalization_failure", outcome="failure", organization_id=job.organization_id, resource_id=scan_id, error_detail=str(exc)[:4000])
            raise

    async def normalize_single_object(
        self, scan_id: str, object_name: str
    ) -> dict[str, Any]:
        if object_name not in NORMALIZER_REGISTRY:
            raise ValueError(f"unsupported Salesforce object: {object_name}")
        job = self.job_service.get_job(scan_id)
        if job is None:
            raise ValueError(f"scan {scan_id} not found")
        info = next((item for item in self.file_service.get_file_info(scan_id)["files"] if item["object_name"] == object_name), None)
        if info is None:
            raise FileNotFoundError(f"no extracted file for {object_name}")
        tables = NORMALIZER_REGISTRY[object_name].normalize(self.file_service.read_csv_file(info["path"]))
        paths = NORMALIZER_REGISTRY[object_name].save_to_files(tables, str(self.file_service.data_root / scan_id / "normalized"))
        return {"scan_id": scan_id, "object_name": object_name, "tables": NORMALIZER_REGISTRY[object_name].get_statistics(tables), "paths": paths}

    def list_normalized_tables(self, scan_id: str) -> list[dict[str, Any]]:
        directory = self.file_service.data_root / scan_id / "normalized"
        if not directory.exists():
            return []
        return [{"table_name": path.stem, "path": str(path), "file_size": path.stat().st_size} for path in sorted(directory.iterdir()) if path.is_file()]

    @staticmethod
    def supported_objects() -> list[dict[str, Any]]:
        from src.app.normalization.normalizers import SUPPORTED_OBJECTS_CATALOG

        return [
            {"object_name": name, "output_tables": tables}
            for name, tables in SUPPORTED_OBJECTS_CATALOG.items()
        ]
