from __future__ import annotations

import hashlib
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from src.app.security.hmac import (
    _NONCE_LOCK,
    _NONCE_STORE,
    _build_canonical_string,
    _compute_signature,
    _constant_time_compare,
    build_hmac_headers,
)

COORDINATOR_SECRET = "test-coordinator-secret-32chars!!"
ENGINEER_SECRET = "test-engineer-secret-32chars!!!!"


def _make_app():
    import os
    os.environ["HMAC_ENABLED"] = "true"
    os.environ["HMAC_SECRET_KEY_CORE"] = COORDINATOR_SECRET
    os.environ["HMAC_SECRET_KEY_ENGINEER"] = ENGINEER_SECRET
    os.environ["HMAC_SIGNATURE_MAX_AGE"] = "300"
    from src.app.core.config import get_settings
    get_settings.cache_clear()
    from src.app.main import create_app
    return create_app()


@pytest.fixture(autouse=True)
def restore_settings_after_test():
    """Ensure HMAC env settings are restored after each test so other tests aren't polluted."""
    import os
    yield
    # Restore to HMAC disabled (matching conftest.py)
    os.environ["HMAC_ENABLED"] = "false"
    from src.app.core.config import get_settings
    get_settings.cache_clear()


def _headers(method: str, path: str, body: bytes = b"", client_id: str = "coordinator", secret: str = COORDINATOR_SECRET, ts_offset: int = 0, nonce: str | None = None):
    ts = int(time.time()) + ts_offset
    return build_hmac_headers(method, path, body, secret, client_id, timestamp=ts, nonce=nonce)


# Clear nonce store between tests
@pytest.fixture(autouse=True)
def clear_nonces():
    with _NONCE_LOCK:
        _NONCE_STORE.clear()
    yield
    with _NONCE_LOCK:
        _NONCE_STORE.clear()


# ---------------------------------------------------------------------------
# canonical string + signature primitives
# ---------------------------------------------------------------------------

def test_canonical_string_structure():
    body = b'{"foo": "bar"}'
    c = _build_canonical_string("POST", "/api/scan/start", "1234567890", "abc-nonce", body)
    lines = c.split("\n")
    assert lines[0] == "POST"
    assert lines[1] == "/api/scan/start"
    assert lines[2] == "1234567890"
    assert lines[3] == "abc-nonce"
    assert lines[4] == hashlib.sha256(body).hexdigest()


def test_signature_is_deterministic():
    canonical = "POST\n/api/scan/start\n12345\nnonce\nabc"
    s1 = _compute_signature(canonical, "secret")
    s2 = _compute_signature(canonical, "secret")
    assert s1 == s2
    s3 = _compute_signature(canonical, "different-secret")
    assert s1 != s3


def test_constant_time_compare():
    assert _constant_time_compare("abc", "abc") is True
    assert _constant_time_compare("abc", "xyz") is False


# ---------------------------------------------------------------------------
# endpoint protection tests (need HMAC enabled)
# ---------------------------------------------------------------------------

def test_valid_coordinator_signature_passes():
    app = _make_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        path = "/api/key/verify"
        hdrs = _headers("GET", path)
        r = c.get(path, headers=hdrs)
        assert r.status_code == 200
        assert r.json()["client_id"] == "coordinator"


def test_missing_headers_returns_401():
    app = _make_app()
    with TestClient(app) as c:
        r = c.get("/api/key/verify")
        assert r.status_code == 401
        assert "missing_auth_headers" in str(r.json())


def test_invalid_signature_returns_401():
    app = _make_app()
    with TestClient(app) as c:
        path = "/api/key/verify"
        hdrs = _headers("GET", path)
        hdrs["X-SF-Signature"] = "invalidsignature" + "x" * 48
        r = c.get(path, headers=hdrs)
        assert r.status_code == 401
        assert "invalid_signature" in str(r.json())


def test_stale_timestamp_returns_401():
    app = _make_app()
    with TestClient(app) as c:
        path = "/api/key/verify"
        hdrs = _headers("GET", path, ts_offset=-400)  # 400s old, max is 300
        r = c.get(path, headers=hdrs)
        assert r.status_code == 401
        assert "expired_timestamp" in str(r.json())


def test_replayed_nonce_returns_401():
    app = _make_app()
    fixed_nonce = uuid.uuid4().hex
    with TestClient(app) as c:
        path = "/api/key/verify"
        # First request with this nonce
        hdrs1 = _headers("GET", path, nonce=fixed_nonce)
        r1 = c.get(path, headers=hdrs1)
        assert r1.status_code == 200
        # Second request with same nonce - must be rejected
        hdrs2 = _headers("GET", path, nonce=fixed_nonce)
        r2 = c.get(path, headers=hdrs2)
        assert r2.status_code == 401
        assert "nonce_replayed" in str(r2.json())


def test_invalid_client_id_returns_401():
    app = _make_app()
    with TestClient(app) as c:
        path = "/api/key/verify"
        hdrs = _headers("GET", path, client_id="unknown-client")
        r = c.get(path, headers=hdrs)
        assert r.status_code == 401
        assert "invalid_client_id" in str(r.json())


def test_engineer_can_access_readonly_endpoint():
    app = _make_app()
    with TestClient(app) as c:
        path = "/api/key/verify"
        hdrs = _headers("GET", path, client_id="engineer", secret=ENGINEER_SECRET)
        r = c.get(path, headers=hdrs)
        assert r.status_code == 200
        assert r.json()["role"] == "read_only"


def test_engineer_cannot_access_write_endpoint():
    app = _make_app()
    with TestClient(app) as c:
        path = "/api/scan/start"
        body = b'{"organization_id":"org1","salesforce_credentials":{"grant_type":"password"}}'
        hdrs = _headers("POST", path, body=body, client_id="engineer", secret=ENGINEER_SECRET)
        r = c.post(path, content=body, headers={**hdrs, "Content-Type": "application/json"})
        assert r.status_code == 403


def test_coordinator_can_access_write_endpoint():
    app = _make_app()
    with TestClient(app) as c:
        path = "/api/scan/start"
        body = b'{"organization_id":"org1","salesforce_credentials":{"grant_type":"password","username":"u","password":"p"}}'
        hdrs = _headers("POST", path, body=body)
        r = c.post(path, content=body, headers={**hdrs, "Content-Type": "application/json"})
        # Should not be 401 or 403 - will be 202 (accepted) or some other response
        assert r.status_code not in (401, 403)


def test_body_tampering_returns_401():
    app = _make_app()
    with TestClient(app) as c:
        path = "/api/scan/start"
        original_body = b'{"organization_id":"org1","salesforce_credentials":{}}'
        hdrs = _headers("POST", path, body=original_body)
        tampered_body = b'{"organization_id":"evil-org","salesforce_credentials":{}}'
        r = c.post(path, content=tampered_body, headers={**hdrs, "Content-Type": "application/json"})
        assert r.status_code == 401
        assert "invalid_signature" in str(r.json())


def test_wrong_key_returns_401():
    app = _make_app()
    with TestClient(app) as c:
        path = "/api/key/verify"
        hdrs = _headers("GET", path, client_id="coordinator", secret="wrong-secret-entirely-wrong!!")
        r = c.get(path, headers=hdrs)
        assert r.status_code == 401
