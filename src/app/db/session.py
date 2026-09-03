from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.app.core.config import get_settings
from src.app.core.logging_setup import get_logger

log = get_logger(__name__)


def build_engine(settings=None):
    settings = settings or get_settings()
    url = settings.DATABASE_URL
    is_sqlite = url.startswith("sqlite")
    kwargs = {"pool_pre_ping": True, "future": True}
    if not is_sqlite:
        kwargs["pool_size"] = settings.DB_POOL_SIZE
        kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
    return create_engine(url, **kwargs)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_db_connectivity(timeout: float = 3.0) -> bool:
    try:
        engine = build_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("DB connectivity check failed: %s", exc)
        return False
