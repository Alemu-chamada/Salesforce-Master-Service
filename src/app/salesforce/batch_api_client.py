from __future__ import annotations

import time
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from src.app.core.logging_setup import get_logger
from src.app.core.utils import safe_get
from src.app.salesforce.auth_client import _mask, _scrub
from src.app.salesforce.exceptions import (
    SalesforceAPIError,
    SalesforceInvalidRequestError,
    SalesforceServerError,
    SalesforceTimeoutError,
    classify_http_error,
)

log = get_logger(__name__)

_VALID_OPERATIONS = {"query", "queryAll"}


def _headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "salesforce-master-service/0.1",
    }


def _validate_job_id(job_id: str) -> None:
    if not job_id or not isinstance(job_id, str):
        raise SalesforceInvalidRequestError("job_id is required and must be a non-empty string")


class SalesforceBatchAPIClient:
    """Salesforce Bulk API 2.0 thin wrapper.

    Implements the surface used by the extraction pipeline:
      * create_query_job (POST /services/data/v{}/jobs/query)
      * get_job_status    (GET  /services/data/v{}/jobs/query/{id})
      * get_job_results   (GET  /services/data/v{}/jobs/query/{id}/results)
      * abort_job         (PATCH /services/data/v{}/jobs/query/{id}  state=Aborted)
      * close_job         (PATCH /services/data/v{}/jobs/query/{id}  state=Closed)

    All HTTP calls use ``httpx`` with configured timeouts.  Sensitive token
    values are stripped from logs via ``_scrub``; the access token header is
    never rendered verbatim.
    """

    def __init__(
        self,
        access_token: str,
        instance_url: str,
        api_version: str,
        *,
        httpx_client: Optional[httpx.AsyncClient] = None,
        timeout_seconds: int = 60,
    ) -> None:
        if not access_token:
            raise SalesforceInvalidRequestError("access_token is required")
        if not instance_url:
            raise SalesforceInvalidRequestError("instance_url is required")
        if not api_version:
            raise SalesforceInvalidRequestError("api_version is required")
        self.access_token = access_token
        self.instance_url = instance_url.rstrip("/")
        if not (self.instance_url.startswith("https://") or self.instance_url.startswith("http://")):
            raise SalesforceInvalidRequestError(f"instance_url must start with https:// or http://: {_mask(instance_url, keep_first=8, keep_last=0)}")
        self.api_version = api_version
        self._base = f"{self.instance_url}/services/data/v{api_version}"
        self._httpx_client = httpx_client
        self._timeout_seconds = max(1, int(timeout_seconds or 60))

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------
    async def create_query_job(
        self,
        object_name: str,
        soql: str,
        operation: str = "query",
        column_delimiter: str = "COMMA",
        line_ending: str = "LF",
    ) -> Dict[str, Any]:
        if not object_name:
            raise SalesforceInvalidRequestError("object_name is required")
        if not soql or not isinstance(soql, str) or not soql.strip():
            raise SalesforceInvalidRequestError("soql is required and must be a non-empty string")
        operation_clean = (operation or "query").strip()
        if operation_clean not in _VALID_OPERATIONS:
            raise SalesforceInvalidRequestError(
                f"operation must be one of {sorted(_VALID_OPERATIONS)}; got {operation_clean!r}"
            )
        body = {
            "operation": operation_clean,
            "object": object_name,
            "query": soql,
            "contentType": "CSV",
            "columnDelimiter": column_delimiter,
            "lineEnding": line_ending,
        }
        log.info(
            "Salesforce Bulk API create query job object=%s operation=%s api=%s",
            object_name,
            operation_clean,
            self.api_version,
            extra={
                "soql_preview": soql[:200],
                "instance_preview": _mask(self.instance_url, keep_first=12, keep_last=0),
            },
        )
        response = await self._request(
            method="POST",
            path="/jobs/query",
            json=body,
            headers_extra={"Content-Type": "application/json"},
        )
        payload = response.get("json")
        job_id = payload.get("id") or payload.get("jobId")
        if not job_id:
            raise SalesforceServerError(
                "Salesforce Bulk API create_query_job response missing id",
                response_payload=payload,
            )
        return {
            "job_id": job_id,
            "operation": payload.get("operation") or operation_clean,
            "object": payload.get("object") or object_name,
            "state": payload.get("state", "Unknown"),
            "created_date": payload.get("createdDate"),
            "system_modstamp": payload.get("systemModstamp"),
            "concurrency_mode": payload.get("concurrencyMode"),
            "content_type": payload.get("contentType"),
            "api_version": payload.get("apiVersion") or self.api_version,
            "raw": payload,
        }

    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        _validate_job_id(job_id)
        response = await self._request("GET", f"/jobs/query/{job_id}")
        payload = response.get("json")
        if not isinstance(payload, dict):
            raise SalesforceServerError(
                f"Salesforce Bulk API get_job_status returned invalid payload for job_id={job_id}",
                response_payload={"raw": str(payload)[:500]},
            )
        return {
            "job_id": payload.get("id") or job_id,
            "operation": payload.get("operation"),
            "object": payload.get("object"),
            "state": payload.get("state", "Unknown"),
            "external_id_field_name": payload.get("externalIdFieldName"),
            "concurrency_mode": payload.get("concurrencyMode"),
            "content_type": payload.get("contentType"),
            "job_type": payload.get("jobType"),
            "number_records_processed": safe_int(payload.get("numberRecordsProcessed")),
            "number_records_failed": safe_int(payload.get("numberRecordsFailed")),
            "retries": safe_int(payload.get("retries")),
            "total_processing_time": safe_int(payload.get("totalProcessingTime")),
            "api_active_processing_time": safe_int(payload.get("apiActiveProcessingTime")),
            "apex_processing_time": safe_int(payload.get("apexProcessingTime")),
            "error_message": payload.get("errorMessage"),
            "created_date": payload.get("createdDate"),
            "system_modstamp": payload.get("systemModstamp"),
            "api_version": payload.get("apiVersion") or self.api_version,
            "raw": payload,
        }

    async def get_job_results(
        self,
        job_id: str,
        locator: Optional[str] = None,
        max_records: Optional[int] = None,
    ) -> AsyncIterator[bytes]:
        """Yield the raw CSV result stream (optionally paged via ``locator``).

        The caller is responsible for concatenating pages or for handling the
        ``Sforce-Locator`` / ``line-ending`` headers.  Returns ``{raw_bytes,
        headers}`` as single bytes chunk with the first chunk carrying an
        ``X-Sfms-Meta`` JSON header.  Use :meth:`get_job_results_paginated`
        for a higher level iterator with automatic locator paging.
        """
        _validate_job_id(job_id)
        params: Dict[str, Any] = {}
        if locator:
            params["locator"] = locator
        if max_records is not None and max_records > 0:
            params["maxRecords"] = int(max_records)

        query = urlencode(params) if params else ""
        path = f"/jobs/query/{job_id}/results" + (f"?{query}" if query else "")
        accept = {"Accept": "text/csv"}
        response = await self._request_raw("GET", path, headers_extra=accept)
        async for chunk in response["stream"]:
            if chunk:
                yield chunk
        # Attach metadata (headers, locator) as a zero-byte sentinel with side-channel
        # via response dict.  Consumers that want headers can read them from the
        # first invocation return value.  Keep it simple: attach to yielded bytes
        # by writing an empty yield with locator encoded as an attribute isn't
        # possible with a bytes generator.  Instead expose them via the public
        # attribute ``last_result_meta``.
        self.last_result_meta = {
            "locator": response.get("locator"),
            "number_of_records": response.get("number_of_records"),
            "content_type": response.get("content_type"),
        }

    async def get_job_results_paginated(
        self, job_id: str, max_records_per_page: Optional[int] = None
    ) -> AsyncIterator[bytes]:
        """Iterate all pages of a Bulk API 2.0 result via the Sforce-Locator header."""
        locator: Optional[str] = None
        while True:
            buffer = bytearray()
            async for chunk in self.get_job_results(job_id, locator=locator, max_records=max_records_per_page):
                buffer.extend(chunk)
                yield chunk
            meta = getattr(self, "last_result_meta", None) or {}
            locator = meta.get("locator")
            if not locator or locator == "null":
                return

    async def abort_job(self, job_id: str) -> Dict[str, Any]:
        return await self._patch_job_state(job_id, state="Aborted")

    async def close_job(self, job_id: str) -> Dict[str, Any]:
        return await self._patch_job_state(job_id, state="Closed")

    async def _patch_job_state(self, job_id: str, *, state: str) -> Dict[str, Any]:
        _validate_job_id(job_id)
        if state not in {"Aborted", "Closed"}:
            raise SalesforceInvalidRequestError(f"Invalid job state transition target: {state}")
        body = {"state": state}
        response = await self._request(
            "PATCH",
            f"/jobs/query/{job_id}",
            json=body,
            headers_extra={"Content-Type": "application/json; charset=UTF-8"},
        )
        payload = response.get("json") if isinstance(response.get("json"), dict) else {"raw": str(response.get("json"))[:500]}
        return {
            "job_id": payload.get("id") or job_id,
            "state": payload.get("state", state),
            "raw": payload,
        }

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------
    def _acquire_client(self) -> httpx.AsyncClient:
        if self._httpx_client is not None:
            return self._httpx_client
        if not hasattr(self, "_default_client"):
            self._default_client = httpx.AsyncClient()
        return self._default_client

    async def aclose(self) -> None:
        client = getattr(self, "_default_client", None)
        if client is not None and client is not self._httpx_client:
            await client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        headers_extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        client = self._acquire_client()
        url = f"{self._base}{path}"
        headers = _headers(self.access_token)
        if headers_extra:
            headers.update(headers_extra)
        timeout = httpx.Timeout(self._timeout_seconds, connect=10.0)
        try:
            resp = await client.request(
                method=method,
                url=url,
                json=json,
                headers=headers,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise SalesforceTimeoutError(
                f"Salesforce Bulk API {method} {self._safe_path(path)} timed out: {exc.__class__.__name__}"
            ) from exc
        except httpx.ConnectError as exc:
            raise SalesforceTimeoutError(
                f"Salesforce Bulk API {method} {self._safe_path(path)} connect error: {exc.__class__.__name__}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SalesforceAPIError(
                f"Salesforce Bulk API {method} {self._safe_path(path)} transport error: {exc.__class__.__name__}",
                retryable=True,
            ) from exc

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text[:500]}

        if 200 <= resp.status_code < 300:
            log.info(
                "Salesforce Bulk API %s %s status=%s elapsed_ms=%s",
                method,
                self._safe_path(path),
                resp.status_code,
                elapsed_ms,
            )
            return {"status_code": resp.status_code, "json": payload, "headers": dict(resp.headers)}

        scrubbed_payload = _scrub(payload)
        message = (
            f"Salesforce Bulk API {method} {self._safe_path(path)} failed "
            f"status={resp.status_code} elapsed_ms={elapsed_ms}"
        )
        if isinstance(payload, list) and len(payload) >= 1 and isinstance(payload[0], dict):
            detail = payload[0].get("message")
            if detail:
                message += f" detail={str(detail)[:300]}"
        raise classify_http_error(
            resp.status_code,
            scrubbed_payload if isinstance(scrubbed_payload, dict) else {"raw": scrubbed_payload},
            message,
        )

    async def _request_raw(
        self,
        method: str,
        path: str,
        *,
        headers_extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        client = self._acquire_client()
        url = f"{self._base}{path}"
        headers = _headers(self.access_token)
        if headers_extra:
            headers.update(headers_extra)
        timeout = httpx.Timeout(self._timeout_seconds, connect=10.0, pool=60.0)
        try:
            req = client.build_request(method=method, url=url, headers=headers, timeout=timeout)
            resp = await client.send(req, stream=True)
        except httpx.TimeoutException as exc:
            raise SalesforceTimeoutError(
                f"Salesforce Bulk API {method} {self._safe_path(path)} download timed out: {exc.__class__.__name__}"
            ) from exc
        except httpx.ConnectError as exc:
            raise SalesforceTimeoutError(
                f"Salesforce Bulk API {method} {self._safe_path(path)} connect error: {exc.__class__.__name__}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SalesforceAPIError(
                f"Salesforce Bulk API {method} {self._safe_path(path)} transport error: {exc.__class__.__name__}",
                retryable=True,
            ) from exc

        if not (200 <= resp.status_code < 300):
            try:
                payload = resp.json()
            except Exception:
                try:
                    payload = {"raw": (await resp.aread()).decode("utf-8", errors="replace")[:500]}
                except Exception:
                    payload = {"raw": "unreadable"}
            try:
                await resp.aclose()
            except Exception:
                pass
            message = (
                f"Salesforce Bulk API {method} {self._safe_path(path)} "
                f"download failed status={resp.status_code}"
            )
            raise classify_http_error(resp.status_code, payload if isinstance(payload, dict) else {"raw": payload}, message)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        locator = resp.headers.get("Sforce-Locator") or None
        if locator and locator.lower() == "null":
            locator = None
        try:
            num_records_header = resp.headers.get("Sforce-NumberOfRecords")
            number_of_records = int(num_records_header) if num_records_header and num_records_header.isdigit() else None
        except Exception:
            number_of_records = None
        log.info(
            "Salesforce Bulk API %s %s status=200 elapsed_ms=%s records=%s has_next_locator=%s",
            method,
            self._safe_path(path),
            elapsed_ms,
            number_of_records,
            bool(locator),
        )

        async def _stream() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                try:
                    await resp.aclose()
                except Exception:
                    pass

        return {
            "stream": _stream(),
            "locator": locator,
            "number_of_records": number_of_records,
            "content_type": resp.headers.get("Content-Type"),
            "elapsed_ms": elapsed_ms,
        }

    @staticmethod
    def _safe_path(path: str) -> str:
        if len(path) <= 120:
            return path
        return path[:80] + "..." + path[-40:]


def safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        stripped = value.replace(",", "").strip()
        if stripped.isdigit():
            return int(stripped)
    try:
        return int(value)
    except Exception:
        return None
