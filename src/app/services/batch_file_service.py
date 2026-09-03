from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from src.app.core.config import get_settings
from src.app.core.logging_setup import get_logger

log = get_logger(__name__)


class BatchFileService:
    """CSV I/O for extracted Bulk API results. Full behavior Phase 2."""

    def __init__(self, data_root: Optional[str] = None) -> None:
        settings = get_settings()
        self.data_root = Path(data_root or settings.DATA_ROOT_DIR).resolve()

    def scan_dir(self, scan_id: str, stage: str = "extracted") -> Path:
        directory = self.data_root / scan_id / stage
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def save_results_to_disk(
        self, scan_id: str, object_name: str, csv_stream: Iterator[str]
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def read_csv_file(
        self,
        path: str,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_file_info(self, scan_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def infer_schema(self, path: str) -> Dict[str, Any]:
        raise NotImplementedError

    def cleanup_extracted_files(self, scan_id: str) -> None:
        raise NotImplementedError
