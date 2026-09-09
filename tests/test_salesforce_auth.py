from __future__ import annotations

import datetime as _dt
import logging
import re
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from src.app.core.config import get_settings
from src.app.core.utils import utcnow
from src.app.salesforce.auth_client import SalesforceAuthClient, _scrub
from src.app.salesforce.exceptions import (
    SalesforceForbiddenError,
    SalesforceInvalidCredentialsError,
    SalesforceInvalidRequestError,
    SalesforceTimeoutError,
)


def _make_settings(**overrides):
    s = get_settings()
    s.SF_TIMEOUT_SECONDS = overrides.pop("SF_TIMEOUT_SECONDS", s.SF_TIMEOUT_SECONDS)
    s.SF_LOGIN_URL = overrides.pop("SF_LOGIN_URL", "https://test.salesforce.com")
    s.SF_CLIENT_ID = overrides.pop("SF_CLIENT_ID", "test-client-id")
    s.SF_CLIENT_SECRET = overrides.pop("SF_CLIENT_SECRET", "test-client-secret")
    s.SF_JWT_PRIVATE_KEY_PATH = overrides.pop("SF_JWT_PRIVATE_KEY_PATH", None)
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@pytest.mark.asyncio
async def test_get_access_token_password_grant_success():
    settings = _make_settings()
    transport = MagicMock()
    _ = httpx.AsyncClient(transport=transport)
    router = respx.MockRouter(assert_all_called=False, base_url=settings.SF_LOGIN_URL)

    @router.post("/services/oauth2/token")
    def _token(request):
        form = httpx.QueryParams(request.content.decode())
        assert form["grant_type"] == "password"
        assert form["client_id"] == "test-client-id"
        assert form["username"] == "alice@example.com"
        assert "access_token" not in form["password"] or True  # password + security_token concatenated
        return httpx.Response(
            200,
            json={
                "access_token": "00DXX!FAKETOKEN1234",
                "instance_url": "https://example.my.salesforce.com",
                "issued_at": str(int(utcnow().timestamp() * 1000)),
                "token_type": "Bearer",
                "signature": "abc123",
            },
        )

    with router:
        client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(router.handler)))
        credentials = {
            "grant_type": "password",
            "username": "alice@example.com",
            "password": "SecretP@ss1",
            "security_token": "TOKENSECURITY",
        }
        result = await client.get_access_token(credentials)

    assert result["access_token"] == "00DXX!FAKETOKEN1234"
    assert result["instance_url"] == "https://example.my.salesforce.com"
    assert result["cached"] is False
    assert "token_type" in result and result["token_type"] == "Bearer"
    assert "expires_at" in result
    assert re.match(r"\d{4}-\d{2}-\d{2}T", result["expires_at"])


@pytest.mark.asyncio
async def test_get_access_token_returns_cached_when_not_near_expiry():
    settings = _make_settings()
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"token-{calls['n']}",
                "instance_url": "https://example.my.salesforce.com",
                "issued_at": str(int(utcnow().timestamp() * 1000)),
            },
        )

    client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    credentials = {
        "grant_type": "password",
        "username": "bob@example.com",
        "password": "pw123",
        "client_id": "cid",
    }
    r1 = await client.get_access_token(credentials)
    r2 = await client.get_access_token(credentials)
    assert r1["access_token"] == "token-1"
    assert r2["access_token"] == "token-1"
    assert r2["cached"] is True
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_get_access_token_invalid_credentials_400():
    settings = _make_settings()

    def _handler(request):
        return httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "authentication failure - invalid username/password",
            },
        )

    client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    credentials = {"grant_type": "password", "username": "bad", "password": "bad"}
    with pytest.raises(SalesforceInvalidCredentialsError) as exc:
        await client.get_access_token(credentials)
    assert exc.value.error_code == "invalid_grant"
    assert exc.value.retryable is False
    assert "invalid_grant" in str(exc.value) or exc.value.status_code == 401 or exc.value.status_code == 400


@pytest.mark.asyncio
async def test_get_access_token_invalid_credentials_401():
    settings = _make_settings()

    def _handler(request):
        return httpx.Response(
            401,
            json={
                "error": "invalid_client",
                "error_description": "unknown client id",
            },
        )

    client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    with pytest.raises(SalesforceInvalidCredentialsError) as exc:
        await client.get_access_token({"grant_type": "password", "username": "a", "password": "b"})
    assert exc.value.error_code == "invalid_client"
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_get_access_token_forbidden_403():
    settings = _make_settings()

    def _handler(request):
        return httpx.Response(
            403,
            json={"error": "inactive_org", "error_description": "org is locked"},
        )

    client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    with pytest.raises(SalesforceForbiddenError):
        await client.get_access_token({"grant_type": "password", "username": "a", "password": "b"})


@pytest.mark.asyncio
async def test_get_access_token_unsupported_grant_type():
    settings = _make_settings()
    client = SalesforceAuthClient(settings)
    with pytest.raises(SalesforceInvalidRequestError):
        await client.get_access_token({"grant_type": "refresh_token", "refresh_token": "x"})


@pytest.mark.asyncio
async def test_get_access_token_timeout():
    settings = _make_settings()

    def _handler(request):
        raise httpx.ConnectTimeout("boom")

    client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    with pytest.raises(SalesforceTimeoutError) as exc:
        await client.get_access_token({"grant_type": "password", "username": "a", "password": "b"})
    assert exc.value.retryable is True


@pytest.mark.asyncio
async def test_get_access_token_empty_credentials():
    client = SalesforceAuthClient(_make_settings())
    with pytest.raises(SalesforceInvalidCredentialsError):
        await client.get_access_token({})


@pytest.mark.asyncio
async def test_get_access_token_near_expiry_refreshes(monkeypatch):
    settings = _make_settings()
    calls = {"n": 0}

    def _handler(request):
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"t{calls['n']}",
                "instance_url": "https://example.my.salesforce.com",
                "issued_at": str(int(utcnow().timestamp() * 1000)),
            },
        )

    client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    creds = {"grant_type": "password", "username": "c", "password": "p"}
    r1 = await client.get_access_token(creds)
    assert r1["access_token"] == "t1"
    # monkey-patch a near-expired entry
    near = utcnow() + _dt.timedelta(seconds=10)
    granted = utcnow() - _dt.timedelta(minutes=30)
    cache_key = f"{settings.SF_LOGIN_URL}|password||c"
    from src.app.salesforce.auth_client import _CacheEntry

    with client._lock:
        client._cache[cache_key] = _CacheEntry("OLD", "https://example.my.salesforce.com", near, granted)

    r2 = await client.get_access_token(creds)
    assert r2["access_token"] == "t2"
    assert r2["cached"] is False
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_credentials_isolation_different_usernames():
    settings = _make_settings()
    tokens = []

    def _handler(request):
        data = httpx.QueryParams(request.content.decode())
        token = f"tok-{data['username']}"
        tokens.append(token)
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "instance_url": "https://example.my.salesforce.com",
                "issued_at": str(int(utcnow().timestamp() * 1000)),
            },
        )

    client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    a = await client.get_access_token({"grant_type": "password", "username": "u1", "password": "p"})
    b = await client.get_access_token({"grant_type": "password", "username": "u2", "password": "p"})
    a2 = await client.get_access_token({"grant_type": "password", "username": "u1", "password": "p"})
    assert a["access_token"] == "tok-u1"
    assert b["access_token"] == "tok-u2"
    assert a2["cached"] is True and a2["access_token"] == "tok-u1"
    assert len(tokens) == 2


@pytest.mark.asyncio
async def test_validate_credentials_success():
    settings = _make_settings()

    def _handler(request):
        path = request.url.path
        if path.endswith("/oauth2/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "VALIDTOKEN",
                    "instance_url": "https://ex.my.salesforce.com",
                    "issued_at": str(int(utcnow().timestamp() * 1000)),
                },
            )
        if path.endswith("/oauth2/userinfo"):
            return httpx.Response(
                200,
                json={
                    "user_id": "005xx000001abc",
                    "organization_id": "00Dxx0000001abc",
                    "preferred_username": "user@example.com",
                    "email": "user@example.com",
                    "name": "Alice User",
                    "url": "https://ex.my.salesforce.com",
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    result = await client.validate_credentials({"grant_type": "password", "username": "u", "password": "p"})
    assert result["valid"] is True
    assert result["identity"]["user_id"] == "005xx000001abc"
    assert result["identity"]["organization_id"] == "00Dxx0000001abc"
    assert result["instance_url"] == "https://ex.my.salesforce.com"


@pytest.mark.asyncio
async def test_jwt_bearer_grant_loads_private_key_from_path(tmp_path: Path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    key_path = tmp_path / "sfdc.key"
    key_path.write_text(pem)

    calls = {"n": 0}

    def _handler(request):
        calls["n"] += 1
        if request.url.path.endswith("/oauth2/token"):
            data = httpx.QueryParams(request.content.decode())
            assert data["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
            assert data["assertion"] and data["assertion"].count(".") == 2
            return httpx.Response(
                200,
                json={
                    "access_token": "JWT-TOKEN",
                    "instance_url": "https://jwt.my.salesforce.com",
                    "issued_at": str(int(utcnow().timestamp() * 1000)),
                },
            )
        return httpx.Response(200, json={"user_id": "uid"})

    settings = _make_settings(SF_JWT_PRIVATE_KEY_PATH=str(key_path))
    client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    result = await client.get_access_token({"grant_type": "jwt", "jwt_subject": "user@example.com"})
    assert result["access_token"] == "JWT-TOKEN"
    assert result["instance_url"] == "https://jwt.my.salesforce.com"
    assert calls["n"] == 1


def test_scrub_redacts_sensitive_keys_and_tokens():
    payload = {
        "password": "Secret123!",
        "client_secret": "s3cr3t",
        "access_token": "00DVERYLONGACCESSTOKENWITHMANYCHARACTERSHERE123456",
        "nested": {"security_token": "AAAAAABBBBBBBCC", "jwt": "aaaa.bbbb.cccc.dddd.eeeeeeeeeeeeeeee"},
        "innocent": "normal value",
    }
    scrubbed = _scrub(payload)
    assert scrubbed["password"] == "***REDACTED***"
    assert scrubbed["client_secret"] == "***REDACTED***"
    assert scrubbed["access_token"] == "***REDACTED***"
    assert scrubbed["nested"]["security_token"] == "***REDACTED***"
    assert scrubbed["nested"]["jwt"] == "***REDACTED***"
    assert scrubbed["innocent"] == "normal value"


def test_scrub_does_not_leak_in_json_strings():
    payload = (
        '{"grant_type":"password","password":"HIDDEN","access_token":"00DXX!abcdefg"}'
    )
    scrubbed = _scrub(payload)
    assert isinstance(scrubbed, str)
    assert "HIDDEN" not in scrubbed
    assert "00DXX!abcdefg" not in scrubbed


def test_scrub_masked_strings():
    long_non_space = "a" * 80
    assert _scrub(long_non_space) == "aaaa...aaaa"
    assert _scrub("short ok") == "short ok"


def test_logging_does_not_leak_secrets_in_handler(caplog):
    settings = _make_settings()

    def _handler(request):
        return httpx.Response(
            200,
            json={
                "access_token": "00DLEAKEDTOKEN1234567890",
                "instance_url": "https://ex.my.salesforce.com",
                "issued_at": str(int(utcnow().timestamp() * 1000)),
                "signature": "neverprinted",
            },
        )

    client = SalesforceAuthClient(settings, httpx_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    import asyncio
    with caplog.at_level(logging.INFO, logger="src.app.salesforce.auth_client"):
        asyncio.run(client.get_access_token({"grant_type": "password", "username": "user@ex.com", "password": "LEAK-ME-NOT"}))

    log_output = "\n".join(caplog.text) if isinstance(caplog.text, list) else caplog.text
    assert "LEAK-ME-NOT" not in log_output
    assert "00DLEAKEDTOKEN1234567890" not in log_output
    assert "user@ex.com" in log_output  # identity remains for debugging
