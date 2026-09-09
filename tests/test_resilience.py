from __future__ import annotations

import pytest

from src.app.resilience.dlq import scrub_payload, write_to_dlq
from src.app.resilience.retry import RETRYABLE_STATUS_CODES, is_retryable, retry_call
from src.app.salesforce.exceptions import (
    SalesforceAPIError,
    SalesforceInvalidCredentialsError,
    SalesforceServerError,
    SalesforceTimeoutError,
)

# ---------------------------------------------------------------------------
# is_retryable
# ---------------------------------------------------------------------------

def test_is_retryable_server_error():
    exc = SalesforceServerError("server down", status_code=503)
    assert is_retryable(exc) is True

def test_is_retryable_timeout():
    exc = SalesforceTimeoutError("timeout")
    assert is_retryable(exc) is True

def test_is_retryable_invalid_credentials():
    exc = SalesforceInvalidCredentialsError("bad creds")
    assert is_retryable(exc) is False

def test_is_retryable_retryable_flag_override():
    exc = SalesforceAPIError("custom", retryable=True)
    assert is_retryable(exc) is True
    exc2 = SalesforceAPIError("custom", retryable=False)
    assert is_retryable(exc2) is False

def test_is_retryable_retryable_status_codes():
    for code in RETRYABLE_STATUS_CODES:
        exc = SalesforceAPIError("err", status_code=code)
        assert is_retryable(exc) is True

def test_is_retryable_non_retryable_status_code():
    exc = SalesforceAPIError("err", status_code=400)
    assert is_retryable(exc) is False

def test_is_retryable_httpx_timeout():
    import httpx
    exc = httpx.ReadTimeout("timed out", request=None)
    assert is_retryable(exc) is True

def test_is_retryable_connection_error():
    exc = ConnectionError("refused")
    assert is_retryable(exc) is True

def test_is_retryable_value_error():
    exc = ValueError("bad value")
    assert is_retryable(exc) is False


# ---------------------------------------------------------------------------
# retry_call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_call_succeeds_first_try():
    calls = {"n": 0}
    async def _fn():
        calls["n"] += 1
        return "ok"
    result = await retry_call(_fn, max_retries=3, delays=[0], jitter=False, op_label="test")
    assert result == "ok"
    assert calls["n"] == 1

@pytest.mark.asyncio
async def test_retry_call_retries_on_retryable():
    calls = {"n": 0}
    async def _fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise SalesforceServerError("down", status_code=503)
        return "recovered"
    result = await retry_call(_fn, max_retries=3, delays=[0, 0, 0], jitter=False, op_label="test")
    assert result == "recovered"
    assert calls["n"] == 3

@pytest.mark.asyncio
async def test_retry_call_does_not_retry_non_retryable():
    calls = {"n": 0}
    async def _fn():
        calls["n"] += 1
        raise SalesforceInvalidCredentialsError("bad creds")
    with pytest.raises(SalesforceInvalidCredentialsError):
        await retry_call(_fn, max_retries=3, delays=[0], jitter=False, op_label="test")
    assert calls["n"] == 1

@pytest.mark.asyncio
async def test_retry_call_exhausted_raises_last():
    calls = {"n": 0}
    async def _fn():
        calls["n"] += 1
        raise SalesforceServerError("always down", status_code=500)
    with pytest.raises(SalesforceServerError):
        await retry_call(_fn, max_retries=2, delays=[0, 0], jitter=False, op_label="test")
    assert calls["n"] == 3  # initial + 2 retries

@pytest.mark.asyncio
async def test_retry_call_passes_args_and_kwargs():
    async def _fn(a, b, *, c=0):
        return a + b + c
    result = await retry_call(_fn, 1, 2, c=3, max_retries=0, delays=[], op_label="test")
    assert result == 6


# ---------------------------------------------------------------------------
# scrub_payload
# ---------------------------------------------------------------------------

def test_scrub_payload_redacts_sensitive_keys():
    payload = {
        "username": "user@ex.com",
        "password": "Secret123",
        "access_token": "00DXXX",
        "data": {"client_secret": "shhh", "normal": "value"},
    }
    scrubbed = scrub_payload(payload)
    assert scrubbed["password"] == "***REDACTED***"
    assert scrubbed["access_token"] == "***REDACTED***"
    assert scrubbed["data"]["client_secret"] == "***REDACTED***"
    assert scrubbed["username"] == "user@ex.com"
    assert scrubbed["data"]["normal"] == "value"

def test_scrub_payload_truncates_large_payloads():
    large = {"data": "x" * 200_000}
    result = scrub_payload(large, max_bytes=1000)
    assert result.get("_truncated") is True

def test_scrub_payload_handles_none():
    assert scrub_payload(None) is None

def test_scrub_payload_handles_list():
    payload = [{"token": "secret", "id": "1"}]
    scrubbed = scrub_payload(payload)
    assert isinstance(scrubbed, dict)

def test_scrub_payload_handles_empty_dict():
    assert scrub_payload({}) == {}


# ---------------------------------------------------------------------------
# write_to_dlq
# ---------------------------------------------------------------------------

def test_write_to_dlq_persists_to_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.app.db.base import Base
    from src.app.models.failed_external_call import FailedExternalCall

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    def _factory():
        return SessionLocal()

    write_to_dlq(
        target_service="salesforce",
        operation="create_query_job",
        payload={"object": "Account", "token": "secret"},
        attempts=3,
        error="503 Service Unavailable",
        organization_id="org-1",
        scan_id="scan-abc",
        db_factory=_factory,
    )

    session = SessionLocal()
    row = session.query(FailedExternalCall).first()
    assert row is not None
    assert row.target_service == "salesforce"
    assert row.operation == "create_query_job"
    assert row.organization_id == "org-1"
    assert row.scan_id == "scan-abc"
    assert row.attempts == 3
    assert row.payload["token"] == "***REDACTED***"
    session.close()

def test_write_to_dlq_never_raises(monkeypatch):
    """DLQ errors must be swallowed, never propagated."""
    def _bad_factory():
        raise RuntimeError("DB is down")
    # Should not raise even if DB fails
    write_to_dlq(
        target_service="salesforce",
        operation="test_op",
        payload={"x": 1},
        attempts=1,
        error="boom",
        db_factory=_bad_factory,
    )

def test_write_to_dlq_without_db_factory_logs_warning(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="src.app.resilience.dlq"):
        write_to_dlq(
            target_service="minio",
            operation="upload_file",
            payload={"path": "/tmp/x"},
            attempts=2,
            error="connection refused",
        )
    assert "DLQ" in caplog.text or "minio" in caplog.text
