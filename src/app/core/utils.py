from __future__ import annotations

import datetime as _dt
import uuid
from collections.abc import Iterable
from decimal import Decimal
from enum import Enum
from typing import Any


def deep_serialize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: deep_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [deep_serialize(v) for v in obj]
    if isinstance(obj, uuid.UUID):
        return obj.hex
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return obj


def calculate_duration(
    start: _dt.datetime | None, end: _dt.datetime | None
) -> float | None:
    if start is None or end is None:
        return None
    if end < start:
        return 0.0
    return round((end - start).total_seconds(), 3)


def build_pagination_info(page: int, page_size: int, total: int) -> dict[str, Any]:
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.UTC)


def chunks(iterable: Iterable[Any], size: int) -> Iterable[list[Any]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    batch: list[Any] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def safe_get(record: dict[str, Any], key: str, default: Any = None) -> Any:
    if not isinstance(record, dict):
        return default
    value = record.get(key, default)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped != "" else default
    return value
