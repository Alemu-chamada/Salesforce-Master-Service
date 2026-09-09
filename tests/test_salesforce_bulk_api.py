from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.app.salesforce.batch_api_client import SalesforceBatchAPIClient
from src.app.salesforce.exceptions import (
    SalesforceAPIError,
    SalesforceForbiddenError,
    SalesforceInvalidRequestError,
    SalesforceNotFoundError,
    SalesforceServerError,
    SalesforceTimeoutError,
    SalesforceUnauthorizedError,
    classify_http_error,
)

BASE = "https://example.my.salesforce.com/services/data/v59.0"
TOKEN = "00D!token"


class _Handler:
    """Callable httpx.MockTransport handler using an internal dict router keyed by (method, path prefix)."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, str, Any]] = []
        self.calls: list[httpx.Request] = []

    def register(self, method: str, path_contains: str, responder) -> None:
        self.routes.append((method.upper(), path_contains, responder))

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url_path = request.url.path + ("?" + str(request.url.query) if request.url.query else "")
        for method, needle, responder in self.routes:
            if request.method != method:
                continue
            if needle not in url_path:
                continue
            import inspect
            result = responder(request)
            if inspect.iscoroutine(result):
                result = await result
            if isinstance(result, httpx.Response):
                return result
            return result
        return httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "no route"}])


def _transport() -> tuple[httpx.MockTransport, _Handler]:
    h = _Handler()
    return httpx.MockTransport(h), h


def _client(token: str = TOKEN, instance: str = "https://example.my.salesforce.com", api: str = "59.0", transport=None) -> tuple[SalesforceBatchAPIClient, _Handler]:
    t, handler = _transport()
    transport = transport or t
    client = SalesforceBatchAPIClient(
        access_token=token,
        instance_url=instance,
        api_version=api,
        httpx_client=httpx.AsyncClient(transport=transport),
    )
    return client, handler


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_constructor_rejects_missing_args():
    with pytest.raises(SalesforceInvalidRequestError):
        SalesforceBatchAPIClient("", "https://x.example", "59.0")
    with pytest.raises(SalesforceInvalidRequestError):
        SalesforceBatchAPIClient(TOKEN, "", "59.0")
    with pytest.raises(SalesforceInvalidRequestError):
        SalesforceBatchAPIClient(TOKEN, "https://x.example", "")
    with pytest.raises(SalesforceInvalidRequestError):
        SalesforceBatchAPIClient(TOKEN, "example.my.salesforce.com", "59.0")


@pytest.mark.asyncio
async def test_create_query_job_validates_inputs():
    client, _ = _client()
    with pytest.raises(SalesforceInvalidRequestError):
        await client.create_query_job("", "select id from account")
    with pytest.raises(SalesforceInvalidRequestError):
        await client.create_query_job("Account", "  ")
    with pytest.raises(SalesforceInvalidRequestError):
        await client.create_query_job("Account", "select id", operation="upsert")


# ---------------------------------------------------------------------------
# Core methods (happy path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_query_job_happy_path():
    client, h = _client()
    job_state = {
        "id": "750B00000000001AAA",
        "operation": "query",
        "object": "Account",
        "createdDate": "2025-01-02T03:04:05.000Z",
        "systemModstamp": "2025-01-02T03:04:05.000Z",
        "state": "UploadComplete",
        "concurrencyMode": "Parallel",
        "contentType": "CSV",
        "apiVersion": 59.0,
    }

    def _create(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        import json as _json
        body = _json.loads(request.content)
        assert body["operation"] == "query"
        assert body["object"] == "Account"
        assert "SELECT Id, Name" in body["query"]
        return httpx.Response(200, json=job_state)

    h.register("POST", "/jobs/query", _create)
    result = await client.create_query_job(
        "Account",
        "SELECT Id, Name FROM Account",
    )
    assert result["job_id"] == "750B00000000001AAA"
    assert result["state"] == "UploadComplete"
    assert result["raw"]["object"] == "Account"


@pytest.mark.asyncio
async def test_get_job_status_happy_path():
    client, h = _client()

    def _status(request):
        return httpx.Response(
            200,
            json={
                "id": "750B00000000001AAA",
                "operation": "query",
                "object": "Contact",
                "state": "JobComplete",
                "numberRecordsProcessed": "42",
                "numberRecordsFailed": "0",
                "retries": 0,
                "totalProcessingTime": 3210,
                "apiActiveProcessingTime": 3200,
                "apexProcessingTime": 0,
                "systemModstamp": "2025-01-02T03:04:08.000Z",
            },
        )

    h.register("GET", "/jobs/query/750B00000000001AAA", _status)
    s = await client.get_job_status("750B00000000001AAA")
    assert s["state"] == "JobComplete"
    assert s["object"] == "Contact"
    assert s["number_records_processed"] == 42
    assert s["number_records_failed"] == 0
    assert s["total_processing_time"] == 3210


@pytest.mark.asyncio
async def test_get_job_results_single_page_stream():
    client, h = _client()
    csv_body = b"Id,Name\n001A,Alpha\n001B,Beta\n"

    async def _responder(request) -> httpx.Response:
        headers = {
            "Sforce-Locator": "",
            "Sforce-NumberOfRecords": "2",
            "Content-Type": "text/csv",
        }
        return httpx.Response(200, content=csv_body, headers=headers)

    h.register("GET", "/jobs/query/750B/results", _responder)
    collected = bytearray()
    async for chunk in client.get_job_results("750B"):
        collected.extend(chunk)
    assert bytes(collected) == csv_body
    assert client.last_result_meta["locator"] in (None, "")
    assert client.last_result_meta["number_of_records"] == 2


@pytest.mark.asyncio
async def test_get_job_results_paginated_multiple_pages():
    client, h = _client()
    page1 = b"Id,Name\n001A,Alpha\n001B,Beta\n"
    page2 = b"001C,Gamma\n001D,Delta\n"

    state = {"page": 1}

    async def _responder(request) -> httpx.Response:
        url_str = str(request.url)
        if state["page"] == 1:
            state["page"] = 2
            return httpx.Response(
                200,
                content=page1,
                headers={
                    "Sforce-Locator": "next-page-token",
                    "Sforce-NumberOfRecords": "2",
                },
            )
        # Page 2 must be triggered with locator=next-page-token
        assert "locator=next-page-token" in url_str
        return httpx.Response(
            200,
            content=page2,
            headers={"Sforce-Locator": "", "Sforce-NumberOfRecords": "2"},
        )

    h.register("GET", "/jobs/query/750B/results", _responder)
    collected = bytearray()
    async for chunk in client.get_job_results_paginated("750B", max_records_per_page=2):
        collected.extend(chunk)
    assert bytes(collected) == page1 + page2


@pytest.mark.asyncio
async def test_abort_and_close_job():
    client, h = _client()
    last_state = {"state": None}

    def _patch(request):
        import json as _json
        body = _json.loads(request.content)
        last_state["state"] = body["state"]
        return httpx.Response(
            200,
            json={"id": "750B", "state": body["state"]},
        )

    h.register("PATCH", "/jobs/query/750B", _patch)
    aborted = await client.abort_job("750B")
    assert aborted["state"] == "Aborted"
    assert last_state["state"] == "Aborted"
    closed = await client.close_job("750B")
    assert closed["state"] == "Closed"


@pytest.mark.asyncio
async def test_get_job_status_requires_job_id():
    client, _ = _client()
    with pytest.raises(SalesforceInvalidRequestError):
        await client.get_job_status("")


# ---------------------------------------------------------------------------
# HTTP error classification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_401_is_unauthorized():
    client, h = _client()
    def _r(req):
        return httpx.Response(401, json=[{"errorCode": "INVALID_SESSION_ID", "message": "Session expired"}])
    h.register("GET", "/jobs/query/750B", _r)
    with pytest.raises(SalesforceUnauthorizedError) as exc:
        await client.get_job_status("750B")
    assert exc.value.status_code == 401
    assert exc.value.retryable is False
    assert exc.value.error_code == "INVALID_SESSION_ID"


@pytest.mark.asyncio
async def test_http_403_is_forbidden():
    client, h = _client()
    def _r(req):
        return httpx.Response(403, json=[{"errorCode": "API_DISABLED_FOR_ORG", "message": "Bulk API disabled"}])
    h.register("POST", "/jobs/query", _r)
    with pytest.raises(SalesforceForbiddenError) as exc:
        await client.create_query_job("Account", "SELECT Id FROM Account")
    assert exc.value.status_code == 403
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_http_400_is_invalid_request():
    client, h = _client()
    def _r(req):
        return httpx.Response(400, json=[{"errorCode": "MALFORMED_QUERY", "message": "field Foo__c does not exist"}])
    h.register("POST", "/jobs/query", _r)
    with pytest.raises(SalesforceInvalidRequestError) as exc:
        await client.create_query_job("Account", "SELECT Foo__c FROM Account")
    assert exc.value.status_code == 400
    assert exc.value.error_code == "MALFORMED_QUERY"
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_http_404_is_not_found():
    client, h = _client()
    def _r(req):
        return httpx.Response(404, json=[{"errorCode": "JOB_NOT_FOUND", "message": "No such job"}])
    h.register("GET", "/jobs/query/NOPE", _r)
    with pytest.raises(SalesforceNotFoundError) as exc:
        await client.get_job_status("NOPE")
    assert exc.value.status_code == 404
    assert exc.value.error_code == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_http_500_and_503_are_retryable_server_errors():
    client, h = _client()

    calls = {"n": 0}
    def _r(req):
        calls["n"] += 1
        return httpx.Response(503, json=[{"errorCode": "SERVER_UNAVAILABLE", "message": "down"}])

    h.register("GET", "/jobs/query/J1", _r)
    with pytest.raises(SalesforceServerError) as exc:
        await client.get_job_status("J1")
    assert exc.value.status_code == 503
    assert exc.value.retryable is True

    # 500
    client2, h2 = _client()
    def _r500(req):
        return httpx.Response(500, text="Internal Server Error")
    h2.register("GET", "/jobs/query/J1", _r500)
    with pytest.raises(SalesforceServerError):
        await client2.get_job_status("J1")


@pytest.mark.asyncio
async def test_download_429_is_retryable_server_error():
    client, h = _client()
    async def _r(req):
        return httpx.Response(429, json={"error": "too many requests"})
    h.register("GET", "/jobs/query/J1/results", _r)
    async def _collect():
        data = bytearray()
        async for chunk in client.get_job_results("J1"):
            data.extend(chunk)
        return data
    with pytest.raises(SalesforceServerError) as exc:
        await _collect()
    assert exc.value.status_code == 429
    assert exc.value.retryable is True


@pytest.mark.asyncio
async def test_timeout_exception_classified_as_timeout():
    def _boom(req):
        raise httpx.ConnectTimeout("took too long")
    client, _ = _client(transport=httpx.MockTransport(_boom))
    with pytest.raises(SalesforceTimeoutError) as exc:
        await client.create_query_job("Account", "SELECT Id FROM Account")
    assert exc.value.retryable is True
    assert exc.value.status_code is None


@pytest.mark.asyncio
async def test_connect_error_is_timeout():
    def _boom(req):
        raise httpx.ConnectError("unreachable")
    client, _ = _client(transport=httpx.MockTransport(_boom))
    with pytest.raises(SalesforceTimeoutError) as exc:
        await client.get_job_status("J1")
    assert exc.value.retryable is True


def test_classify_http_error_exhaustive():
    def mk(code, payload=None):
        return classify_http_error(code, payload or {}, f"msg for {code}")

    assert isinstance(mk(400), SalesforceInvalidRequestError)
    assert isinstance(mk(401, [{"errorCode": "INVALID_SESSION_ID"}]), SalesforceUnauthorizedError)
    assert isinstance(mk(403), SalesforceForbiddenError)
    assert isinstance(mk(404), SalesforceNotFoundError)
    assert isinstance(mk(500), SalesforceServerError)
    assert isinstance(mk(502), SalesforceServerError)
    assert isinstance(mk(429), SalesforceServerError)
    assert mk(500).retryable is True
    assert mk(400).retryable is False
    # unknown 4xx -> base SalesforceAPIError
    err = mk(418)
    assert isinstance(err, SalesforceAPIError)
    assert not isinstance(err, (SalesforceInvalidRequestError, SalesforceServerError))
    assert err.status_code == 418


@pytest.mark.asyncio
async def test_create_query_job_missing_id_is_server_error():
    client, h = _client()
    def _r(req):
        return httpx.Response(200, json={"state": "UploadComplete"})  # no id!
    h.register("POST", "/jobs/query", _r)
    with pytest.raises(SalesforceServerError):
        await client.create_query_job("Account", "SELECT Id FROM Account")


@pytest.mark.asyncio
async def test_close_with_unknown_state_raises():
    _, _ = _client()
    from src.app.salesforce.batch_api_client import SalesforceBatchAPIClient as S
    c = S(TOKEN, "https://example.my.salesforce.com", "59.0")
    with pytest.raises(SalesforceInvalidRequestError):
        await c._patch_job_state("X", state="Done")
