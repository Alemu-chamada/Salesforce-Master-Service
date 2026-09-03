from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("HEALTH_CHECK_DB_ENABLED", "false")
os.environ.setdefault("HEALTH_CHECK_MINIO_ENABLED", "false")
os.environ.setdefault("HMAC_ENABLED", "false")
os.environ.setdefault("SF_BULK_SUPPORTED_OBJECTS", "Account,Contact,Opportunity")
os.environ.setdefault("EXTERNAL_CALL_RETRY_DELAYS", "1,2,4")
os.environ.setdefault("DATA_ROOT_DIR", str(Path(__file__).parent.parent / "data" / "test_scans"))

from src.app.core.config import get_settings

get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    get_settings.cache_clear()
    from src.app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
