from __future__ import annotations

import csv
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from src.app.core.config import get_settings
from src.app.core.logging_setup import get_logger

log = get_logger(__name__)


class BatchFileService:
    """CSV I/O for extracted Bulk API results. Full behavior Phase 2."""

    def __init__(self, data_root: str | None = None) -> None:
        settings = get_settings()
        self.data_root = Path(data_root or settings.DATA_ROOT_DIR).resolve()

    def scan_dir(self, scan_id: str, stage: str = "extracted") -> Path:
        self._validate_component(scan_id)
        self._validate_component(stage)
        directory = self.data_root / scan_id / stage
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @staticmethod
    def _validate_component(value: str) -> None:
        if not value or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError("path component contains invalid characters")

    def _safe_file(self, scan_id: str, object_name: str) -> Path:
        self._validate_component(scan_id)
        self._validate_component(object_name)
        path = (self.scan_dir(scan_id) / f"{object_name}.csv").resolve()
        root = self.data_root.resolve()
        if root not in path.parents:
            raise ValueError("result path escapes data root")
        return path

    def save_results_to_disk(
        self, scan_id: str, object_name: str, csv_stream: Iterator[str]
    ) -> dict[str, Any]:
        path = self._safe_file(scan_id, object_name)
        rows = 0
        size = 0
        with path.open("wb") as output:
            for chunk in csv_stream:
                data = chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk)
                output.write(data)
                size += len(data)
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                rows = max(0, sum(1 for _ in csv.DictReader(source)))
        except (UnicodeError, csv.Error) as exc:
            path.unlink(missing_ok=True)
            raise ValueError(f"malformed CSV for {object_name}: {exc}") from exc
        return {"object_name": object_name, "path": str(path), "file_size": size, "record_count": rows}

    async def save_async_results_to_disk(self, scan_id: str, object_name: str, csv_stream: Any) -> dict[str, Any]:
        path = self._safe_file(scan_id, object_name)
        size = 0
        try:
            with path.open("wb") as output:
                async for chunk in csv_stream:
                    data = chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk)
                    output.write(data)
                    size += len(data)
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                rows = max(0, sum(1 for _ in csv.DictReader(source)))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return {"object_name": object_name, "path": str(path), "file_size": size, "record_count": rows}

    def read_csv_file(
        self,
        path: str,
        page: int | None = None,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        file_path = Path(path).resolve()
        if not file_path.is_file() or self.data_root.resolve() not in file_path.parents:
            raise ValueError("CSV path is outside the configured data root")
        start = 0 if page is None else max(0, (page - 1) * (page_size or 0))
        limit = None if page_size is None else max(0, page_size)
        records: list[dict[str, Any]] = []
        with file_path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            for index, row in enumerate(reader):
                if index < start:
                    continue
                if limit is not None and len(records) >= limit:
                    break
                records.append(dict(row))
        return records

    def get_file_info(self, scan_id: str) -> dict[str, Any]:
        directory = self.scan_dir(scan_id)
        result: dict[str, Any] = {"files": [], "total_records": 0}
        for path in sorted(directory.glob("*.csv")):
            info = {"object_name": path.stem, "path": str(path), "file_size": path.stat().st_size}
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                info["record_count"] = max(0, sum(1 for _ in csv.DictReader(source)))
            result["files"].append(info)
            result["total_records"] += info["record_count"]
        return result

    def infer_schema(self, path: str) -> dict[str, Any]:
        records = self.read_csv_file(path, page=1, page_size=100)
        fields: dict[str, str] = {}
        for record in records:
            for key, value in record.items():
                if value in (None, ""):
                    continue
                current = fields.get(key, "string")
                if current == "string":
                    if value.lower() in {"true", "false"}:
                        fields[key] = "boolean"
                    else:
                        try:
                            int(value)
                            fields[key] = "integer"
                        except ValueError:
                            try:
                                float(value)
                                fields[key] = "number"
                            except ValueError:
                                fields[key] = "string"
        return fields

    def cleanup_extracted_files(self, scan_id: str) -> None:
        self._validate_component(scan_id)
        directory = (self.data_root / scan_id / "extracted").resolve()
        if self.data_root.resolve() not in directory.parents:
            raise ValueError("cleanup path escapes data root")
        if directory.exists():
            shutil.rmtree(directory)
