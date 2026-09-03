from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.app.core.logging_setup import get_logger

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
        return None

    def upload_file(self, local_path: str, object_key: str) -> Dict[str, Any]:
        raise NotImplementedError

    def upload_directory(self, local_dir: str, prefix: str) -> Dict[str, Any]:
        raise NotImplementedError

    def upload_normalized_data(
        self,
        scan_id: str,
        organization_id: str,
        processing_date: str,
        tables: Dict[str, str],
    ) -> List[str]:
        raise NotImplementedError

    def check_connectivity(self) -> bool:
        """Lightweight placeholder. Replaced with real bucket-exists call in Phase 3."""
        return False
