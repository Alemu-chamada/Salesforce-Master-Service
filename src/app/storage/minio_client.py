from __future__ import annotations

from pathlib import Path
from typing import Any

from src.app.core.logging_setup import get_logger
from src.app.resilience.retry import retry_call_sync

log = get_logger(__name__)


class MinIOClient:
    """MinIO upload client. Full implementation in Phase 3."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.secure = secure

    def ensure_bucket_exists(self) -> None:
        from minio import Minio
        client = Minio(self.endpoint, access_key=self.access_key, secret_key=self.secret_key, secure=self.secure)
        if not client.bucket_exists(self.bucket):
            client.make_bucket(self.bucket)

    def upload_file(self, local_path: str, object_key: str) -> dict[str, Any]:
        from minio import Minio
        path = Path(local_path)
        if not path.is_file():
            raise FileNotFoundError(local_path)
        retry_call_sync(self.ensure_bucket_exists, op_label="minio.ensure_bucket")
        client = Minio(self.endpoint, access_key=self.access_key, secret_key=self.secret_key, secure=self.secure)
        result = retry_call_sync(client.fput_object, self.bucket, object_key, str(path), content_type="application/octet-stream", op_label="minio.upload_file")
        return {"bucket": self.bucket, "object_key": result.object_name, "size": path.stat().st_size}

    def upload_directory(self, local_dir: str, prefix: str) -> dict[str, Any]:
        root = Path(local_dir).resolve()
        if not root.is_dir():
            raise FileNotFoundError(local_dir)
        return {str(path.relative_to(root)): self.upload_file(str(path), f"{prefix.rstrip('/')}/{path.relative_to(root).as_posix()}") for path in root.rglob("*") if path.is_file()}

    def upload_normalized_data(
        self,
        scan_id: str,
        organization_id: str,
        processing_date: str,
        tables: dict[str, str],
    ) -> list[str]:
        keys = []
        for table_name, local_path in tables.items():
            object_key = f"salesforce/{table_name}/glynac_organization_id={organization_id}/processing_date={processing_date}/{table_name}.parquet"
            self.upload_file(local_path, object_key)
            keys.append(object_key)
        return keys

    def check_connectivity(self) -> bool:
        """Lightweight placeholder. Replaced with real bucket-exists call in Phase 3."""
        try:
            retry_call_sync(self.ensure_bucket_exists, op_label="minio.ensure_bucket")
            return True
        except (OSError, ValueError, RuntimeError, TypeError) as exc:
            log.warning("MinIO connectivity check failed endpoint=%s bucket=%s error=%s", self.endpoint, self.bucket, exc.__class__.__name__)
            return False
