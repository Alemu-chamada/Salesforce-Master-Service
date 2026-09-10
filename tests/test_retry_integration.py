import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.db.base import Base
from src.app.resilience.retry import retry_call
from src.app.salesforce.exceptions import SalesforceServerError
from src.app.services.batch_polling_service import BatchPollingService
from src.app.services.job_service import JobService


@pytest.mark.asyncio
async def test_retry_call_uses_configured_bounds(monkeypatch):
    from src.app.core.config import get_settings
    settings = get_settings()
    settings.EXTERNAL_CALL_MAX_RETRIES = 2
    settings.EXTERNAL_CALL_RETRY_DELAYS = [0]
    settings.EXTERNAL_CALL_MAX_DELAY_SECONDS = 0
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        raise SalesforceServerError("temporary", status_code=503)

    with pytest.raises(SalesforceServerError):
        await retry_call(operation, jitter=False)
    assert calls == 3


@pytest.mark.asyncio
async def test_batch_failure_wires_database_factory_to_dlq(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    jobs = JobService(session)
    jobs.create_job("scan-dlq", "org-1")
    polling = BatchPollingService(session, jobs)

    class FakeBatchClient:
        async def create_query_job(self, object_name, query):
            return {"job_id": "unused"}

    polling.batch_client = FakeBatchClient()
    captured = {}

    async def fail_retry(*args, **kwargs):
        raise SalesforceServerError("temporary", status_code=503)

    def capture_dlq(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)

    monkeypatch.setattr("src.app.services.batch_polling_service.retry_call", fail_retry)
    monkeypatch.setattr("src.app.services.batch_polling_service.write_to_dlq", capture_dlq)

    with pytest.raises(SalesforceServerError):
        await polling.submit_batch_jobs("scan-dlq", ["Account"])

    assert captured["db_factory"] is not None
    assert captured["args"][5] == "org-1"
    assert captured["args"][6] == "scan-dlq"
