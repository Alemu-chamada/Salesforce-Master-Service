import pytest

from src.app.resilience.retry import retry_call
from src.app.salesforce.exceptions import SalesforceServerError


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
