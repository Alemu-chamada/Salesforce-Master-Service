from __future__ import annotations

import datetime as _dt
import uuid
from decimal import Decimal

from src.app.core.utils import (
    build_pagination_info,
    calculate_duration,
    chunks,
    deep_serialize,
    safe_get,
    utcnow,
)


def test_deep_serialize_handles_types():
    payload = {
        "uuid": uuid.UUID("a" * 32),
        "decimal": Decimal("12.34"),
        "datetime": _dt.datetime(2025, 1, 2, 3, 4, 5, tzinfo=_dt.UTC),
        "date": _dt.date(2025, 1, 2),
        "list": [1, "x", Decimal(2)],
    }
    result = deep_serialize(payload)
    assert result["uuid"] == "a" * 32
    assert result["decimal"] == "12.34"
    assert result["datetime"].startswith("2025-01-02T03:04:05")
    assert result["date"] == "2025-01-02"
    assert result["list"][2] == "2"


def test_duration_and_pagination():
    start = _dt.datetime(2025, 1, 1, 0, 0, 0, tzinfo=_dt.UTC)
    end = _dt.datetime(2025, 1, 1, 0, 0, 10, 500000, tzinfo=_dt.UTC)
    assert calculate_duration(start, end) == 10.5
    assert calculate_duration(start, None) is None
    assert calculate_duration(end, start) == 0.0

    p = build_pagination_info(2, 10, 25)
    assert p["page"] == 2
    assert p["total_pages"] == 3
    assert p["has_next"] is True
    assert p["has_prev"] is True


def test_chunks_and_safe_get():
    assert list(chunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert safe_get({"a": "  x  ", "b": "", "c": None}, "a") == "x"
    assert safe_get({"a": "  "}, "a", "default") == "default"
    assert safe_get(None, "a", 42) == 42


def test_utcnow_is_timezone_aware():
    n = utcnow()
    assert n.tzinfo is not None
    assert n.tzinfo.utcoffset(n) == _dt.timedelta(0)
