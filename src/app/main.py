from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from src.app.api.routes import (
    audit as audit_router,
)
from src.app.api.routes import (
    batch as batch_router,
)
from src.app.api.routes import (
    credentials as credentials_router,
)
from src.app.api.routes import (
    key as key_router,
)
from src.app.api.routes import (
    maintenance as maintenance_router,
)
from src.app.api.routes import (
    normalization as normalization_router,
)
from src.app.api.routes import (
    public as public_router,
)
from src.app.api.routes import (
    scan as scan_router,
)
from src.app.core.config import get_settings
from src.app.core.logging_setup import get_logger, setup_logging
from src.app.core.utils import deep_serialize
from src.app.db.base import Base
from src.app.db.session import get_engine, get_session_factory
from src.app.services.job_service import JobService

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    settings = get_settings()
    try:
        Base.metadata.create_all(bind=get_engine())
        session = get_session_factory()()
        try:
            crashed_ids = JobService(session).detect_crashed_jobs()
            if crashed_ids:
                log.warning("Marked %d stale jobs as failed during startup", len(crashed_ids))
        finally:
            session.close()
    except (RuntimeError, SQLAlchemyError, ValueError) as exc:
        log.warning("Database schema initialization failed: %s", exc.__class__.__name__)
    log.info(
        "Starting %s env=%s debug=%s prefix=%s",
        settings.APP_NAME,
        settings.APP_ENV,
        settings.DEBUG,
        settings.API_PREFIX,
    )
    yield
    log.info("Shutting down %s", settings.APP_NAME)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        description="On-demand Salesforce data extraction, normalization, and publishing service.",
        version="0.1.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = settings.API_PREFIX.rstrip("/")
    app.include_router(scan_router.router, prefix=f"{prefix}/scan", tags=["scan"])
    app.include_router(batch_router.router, prefix=f"{prefix}/batch", tags=["batch"])
    app.include_router(
        normalization_router.router,
        prefix=f"{prefix}/normalization",
        tags=["normalization"],
    )
    app.include_router(
        maintenance_router.router,
        prefix=f"{prefix}/maintenance",
        tags=["maintenance"],
    )
    app.include_router(key_router.router, prefix=f"{prefix}/key", tags=["key"])
    app.include_router(audit_router.router, prefix=f"{prefix}/audit", tags=["audit"])
    app.include_router(credentials_router.router, prefix=f"{prefix}", tags=["credentials"])
    app.include_router(public_router.router, prefix=f"{prefix}", tags=["public"])

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
        payload = {
            "detail": "internal server error",
            "error_type": exc.__class__.__name__,
        }
        if settings.DEBUG:
            payload["debug"] = str(exc)
        return JSONResponse(
            status_code=500,
            content=deep_serialize(payload),
        )

    return app


app = create_app()
