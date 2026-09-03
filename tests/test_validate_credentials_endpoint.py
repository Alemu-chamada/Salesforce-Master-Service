from __future__ import annotations

import asyncio
import httpx
import pytest

from src.app.salesforce.auth_client import SalesforceAuthClient
from src.app.core.config import get_settings
from src.app.core.utils import utcnow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RouteTransport(httpx.MockTransport):
    def __init__(self):
        self._routes = []
        super().__init__(self._handler)

    def register(self, method, url_contains, responder):
        self._routes.append((method.upper(), url_contains, responder))

    def _handler(self, request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        for method, needle, responder in self._routes:
            if request.method != method:
                continue
            if needle in url_str:
                result = responder(request)
                return result
        return httpx.Response(404, json={"error": "not found"})


def _make_client():
    transport = _RouteTransport()
    client = SalesforceAuthClient(get_settings(), httpx_client=httpx.AsyncClient(transport=transport))
    return client, transport


# ---------------------------------------------------------------------------
# validate-credentials endpoint tests (mocking auth client at DI)
# ---------------------------------------------------------------------------


def test_validate_credentials_endpoint_200_with_hmac(client):
    """
    Replace the auth_client dependency with one backed by a MockTransport.
    The HMAC placeholder in Phase 1-2 always passes.
    """
    from src.app.api.routes import credentials as creds_router

    class _FakeAuthClient:
        async def validate_credentials(self, creds):
            return {
                "valid": True,
                "identity": {
                    "user_id": "005fake",
                    "organization_id": "00Dfake",
                    "username": "user@ex.com",
                },
                "instance_url": "https://ex.my.salesforce.com",
                "token_type": "Bearer",
            }

        def clear_cache(self):
            return None

    def _fake_dep():
        return _FakeAuthClient()

    original = creds_router._auth_client
    try:
        creds_router._auth_client = _fake_dep
        r = client.post(
            "/api/validate-credentials",
            json={"grant_type": "password", "username": "u", "password": "p"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["valid"] is True
        assert body["identity"]["user_id"] == "005fake"
        assert body["identity"]["organization_id"] == "00Dfake"
        assert body["error"] is None
    finally:
        creds_router._auth_client = original


def test_validate_credentials_endpoint_translates_invalid_creds_to_401(client):
    from src.app.api.routes import credentials as creds_router
    from src.app.salesforce.exceptions import SalesforceInvalidCredentialsError

    class _BadAuth:
        async def validate_credentials(self, creds):
            raise SalesforceInvalidCredentialsError("bad creds", error_code="invalid_grant")

        def clear_cache(self):
            return None

    def _fake():
        return _BadAuth()

    original = creds_router._auth_client
    try:
        creds_router._auth_client = _fake
        r = client.post(
            "/api/validate-credentials",
            json={"grant_type": "password", "username": "u", "password": "wrong"},
        )
        assert r.status_code == 401
        detail = r.json()["detail"]
        assert detail["error_code"] == "invalid_grant"
        assert detail["retryable"] is False
    finally:
        creds_router._auth_client = original


def test_validate_credentials_endpoint_translates_timeout_to_504(client):
    from src.app.api.routes import credentials as creds_router
    from src.app.salesforce.exceptions import SalesforceTimeoutError

    class _SlowAuth:
        async def validate_credentials(self, creds):
            raise SalesforceTimeoutError("salesforce did not respond")

        def clear_cache(self):
            return None

    def _fake():
        return _SlowAuth()

    original = creds_router._auth_client
    try:
        creds_router._auth_client = _fake
        r = client.post(
            "/api/validate-credentials",
            json={"grant_type": "password", "username": "u", "password": "p"},
        )
        assert r.status_code == 504
    finally:
        creds_router._auth_client = original


# ---------------------------------------------------------------------------
# Credentials never persisted: confirm client cache is cleared via endpoint code path
# ---------------------------------------------------------------------------

def test_validate_credentials_route_clears_cache_after_use(monkeypatch):
    from src.app.api.routes import credentials as creds_router

    calls = {"clear_cache": 0, "validate": 0}

    class _RememberAuth:
        async def validate_credentials(self, creds):
            calls["validate"] += 1
            return {"valid": True, "identity": {"user_id": "u"}}

        def clear_cache(self):
            calls["clear_cache"] += 1

    def _fake():
        return _RememberAuth()

    from fastapi.testclient import TestClient
    from src.app.main import create_app

    original = creds_router._auth_client
    try:
        creds_router._auth_client = _fake
        with TestClient(create_app()) as c:
            c.post(
                "/api/validate-credentials",
                json={"grant_type": "password", "username": "u", "password": "p"},
            )
        assert calls["validate"] == 1
        assert calls["clear_cache"] == 1
    finally:
        creds_router._auth_client = original


# ---------------------------------------------------------------------------
# FastAPI routing for /scan/{id}/status + /health baseline passes unchanged
# ---------------------------------------------------------------------------

def test_existing_routes_still_work_after_phase2_changes(client):
    # Health
    h = client.get("/api/health")
    assert h.status_code == 200

    # Stats
    s = client.get("/api/stats")
    assert s.status_code == 200

    # Batch info returns 200 with supported_objects
    b = client.get("/api/batch/info")
    assert b.status_code == 200
    assert "supported_objects" in b.json()

    # supported-objects returns a list
    n = client.get("/api/normalization/supported-objects")
    assert n.status_code == 200 and isinstance(n.json(), list)

    # scan/list 200 with empty items
    lst = client.get("/api/scan/list")
    assert lst.status_code == 200
    assert lst.json()["items"] == []

    # key/verify returns client_id + role
    k = client.get("/api/key/verify")
    assert k.status_code == 200 and k.json()["signature_valid"] is True
