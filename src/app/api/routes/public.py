from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter

from src.app.core.config import get_settings
from src.app.core.logging_setup import get_logger
from src.app.core.utils import utcnow
from src.app.db.session import check_db_connectivity
from src.app.schemas.common import HealthComponent, HealthResponse, ServiceStatsResponse

router = APIRouter()

log = get_logger(__name__)

_SERVICE_STARTED_AT = utcnow()
_REQUEST_COUNTER = 0


@router.get("/health")
async def health() -> HealthResponse:
    settings = get_settings()
    components: Dict[str, HealthComponent] = {}

    if settings.HEALTH_CHECK_DB_ENABLED:
        t0 = time.perf_counter()
        db_ok = check_db_connectivity(timeout=3.0)
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        components["database"] = HealthComponent(
            status="healthy" if db_ok else "unhealthy",
            latency_ms=latency_ms if db_ok else None,
            error=None if db_ok else "database connectivity failed",
        )

    if settings.HEALTH_CHECK_MINIO_ENABLED:
        components["minio"] = HealthComponent(
            status="degraded",
            error="MinIO client not wired in Phase 1",
        )

    overall = "healthy"
    for c in components.values():
        if c.status == "unhealthy":
            overall = "unhealthy"
            break
        if c.status == "degraded" and overall == "healthy":
            overall = "degraded"

    return HealthResponse(
        status=overall,
        app_env=settings.APP_ENV,
        components=components,
    )


@router.get("/stats")
async def service_stats() -> ServiceStatsResponse:
    global _REQUEST_COUNTER
    _REQUEST_COUNTER += 1
    now = utcnow()
    uptime = max(0.0, (now - _SERVICE_STARTED_AT).total_seconds())
    return ServiceStatsResponse(
        started_at=_SERVICE_STARTED_AT.isoformat(),
        uptime_seconds=round(uptime, 2),
        requests_total=_REQUEST_COUNTER,
    )
