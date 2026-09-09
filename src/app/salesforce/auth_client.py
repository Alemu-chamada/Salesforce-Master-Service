from __future__ import annotations

import base64
import datetime as _dt
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from src.app.core.logging_setup import get_logger
from src.app.core.utils import utcnow
from src.app.resilience.retry import RETRYABLE_STATUS_CODES, retry_call
from src.app.salesforce.exceptions import (
    SalesforceAPIError,
    SalesforceAuthenticationError,
    SalesforceForbiddenError,
    SalesforceInvalidCredentialsError,
    SalesforceInvalidRequestError,
    SalesforceTimeoutError,
    classify_http_error,
)

log = get_logger(__name__)

_AUTH_INVALID_CODES = {
    "invalid_client_id",
    "invalid_client",
    "invalid_grant",
    "inactive_org",
    "inactive_user",
    "invalid_password",
    "ip_restriction_exception",
    "invalid_client_credentials",
}

_SENSITIVE_KEYS = {
    "password",
    "client_secret",
    "access_token",
    "refresh_token",
    "private_key",
    "secret",
    "token",
    "security_token",
    "signature",
    "code",
    "jwt",
    "assertion",
    "client_assertion",
}

_CACHE_MIN_LIFETIME_SECONDS = 120
_CACHE_NEAR_EXPIRY_WINDOW = 60


def _scrub(value: Any) -> Any:
    """Deep redact sensitive keys and obvious token strings.

    Never raises.  Used before any payload reaches the logger.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS:
                out[k] = "***REDACTED***"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_scrub(x) for x in value]
    if isinstance(value, str):
        s = value
        if len(s) > 20 and not re.search(r"\s", s) and (
            s.lower().startswith(("00d", "bearer ")) or len(s) > 60
        ):
            return _mask(s)
        if any(
            marker in s.lower()
            for marker in ("access_token=", "access_token\"", "password", "client_secret", "grant_type")
        ):
            try:
                parsed = json.loads(s)
                return json.dumps(_scrub(parsed))
            except (TypeError, ValueError):
                return _mask(s, keep_first=0)
        return s
    return value


def _mask(s: str, keep_first: int = 4, keep_last: int = 4) -> str:
    if len(s) <= keep_first + keep_last:
        return "***"
    return f"{s[:keep_first]}...{s[-keep_last:]}"


def _build_cache_key(credentials: dict[str, Any], login_url: str) -> str:
    username = credentials.get("jwt_subject") or credentials.get("username") or ""
    client_id = credentials.get("client_id") or ""
    grant_type = credentials.get("grant_type") or ""
    return f"{login_url}|{grant_type}|{client_id.lower()}|{username.lower()}"

def _setting(settings: Any, name: str, default: Any = None) -> Any:
    value = getattr(settings, name, default)
    if value is default and hasattr(settings, "model_dump"):
        value = settings.model_dump().get(name, default)
    return default if value is None else value


class _CacheEntry:
    __slots__ = ("expires_at", "granted_at", "instance_url", "token")

    def __init__(
        self,
        token: str,
        instance_url: str,
        expires_at: _dt.datetime,
        granted_at: _dt.datetime,
    ) -> None:
        self.token = token
        self.instance_url = instance_url
        self.expires_at = expires_at
        self.granted_at = granted_at

    def is_expired_or_near(self, now: _dt.datetime, near_window: int = _CACHE_NEAR_EXPIRY_WINDOW) -> bool:
        try:
            remaining = (self.expires_at - now).total_seconds()
        except TypeError:  # pragma: no cover - defensive
            return True
        if remaining <= near_window:
            return True
        grant_age = (now - self.granted_at).total_seconds()
        return grant_age <= 0 and False  # pragma: no cover - defensive

    def is_valid(self, now: _dt.datetime) -> bool:
        return (self.expires_at - now).total_seconds() > 0


def _parse_jwt_private_key(value: str | None, path: str | None) -> str | None:
    if value:
        v = value.strip()
        if v:
            return v
    if path:
        try:
            p = Path(path).expanduser()
            if p.is_file():
                content = p.read_text(encoding="utf-8").strip()
                if content:
                    return content
        except OSError:
            return None
    return None


class SalesforceAuthClient:
    """Salesforce OAuth authentication.

    Grants are cached in memory (per-login-url + per-identity) until they are
    near expiry.  Credentials are never persisted to disk, DB, or logs; all
    logging calls go through ``_scrub()``.

    Supports:
      - OAuth 2.0 JWT Bearer flow (preferred when ``jwt_private_key`` present or
        ``SF_JWT_PRIVATE_KEY_PATH`` configured)
      - Username-password (``grant_type=password``) fallback
    """

    def __init__(self, settings: Any, *, httpx_client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.RLock()
        self._httpx_client = httpx_client

    # ------------------------------------------------------------------
    # Token endpoints
    # ------------------------------------------------------------------
    async def get_access_token(self, credentials: dict[str, Any]) -> dict[str, Any]:
        if not credentials:
            raise SalesforceInvalidCredentialsError("credentials payload is empty")

        login_url = credentials.get("login_url") or _setting(self.settings, "SF_LOGIN_URL") or "https://login.salesforce.com"
        login_url = login_url.rstrip("/")
        cache_key = _build_cache_key(credentials, login_url)

        now = utcnow()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None and not cached.is_expired_or_near(now) and cached.is_valid(now):
                return {
                    "access_token": cached.token,
                    "instance_url": cached.instance_url,
                    "expires_at": cached.expires_at.isoformat(),
                    "granted_at": cached.granted_at.isoformat(),
                    "issued_at": str(int(cached.granted_at.timestamp() * 1000)),
                    "cached": True,
                    "token_type": "Bearer",
                }

        grant_type = (credentials.get("grant_type") or "password").lower()
        jwt_key = _parse_jwt_private_key(
            credentials.get("jwt_private_key"),
            credentials.get("jwt_private_key_path")
            or _setting(self.settings, "SF_JWT_PRIVATE_KEY_PATH"),
        )
        prefer_jwt = jwt_key is not None

        if prefer_jwt or grant_type in {"jwt", "jwt_bearer", "urn:ietf:params:oauth:grant-type:jwt-bearer"}:
            if not jwt_key:
                raise SalesforceInvalidCredentialsError(
                    "JWT Bearer flow requested but no jwt_private_key supplied and "
                    "SF_JWT_PRIVATE_KEY_PATH is not configured"
                )
            grant_result = await self._grant_jwt_bearer(
                login_url=login_url,
                client_id=credentials.get("client_id") or _setting(self.settings, "SF_CLIENT_ID"),
                jwt_subject=credentials.get("jwt_subject") or credentials.get("username"),
                private_key=jwt_key,
            )
        elif grant_type == "password":
            grant_result = await self._grant_password(
                login_url=login_url,
                username=credentials.get("username"),
                password=credentials.get("password"),
                security_token=credentials.get("security_token"),
                client_id=credentials.get("client_id") or _setting(self.settings, "SF_CLIENT_ID"),
                client_secret=credentials.get("client_secret") or _setting(self.settings, "SF_CLIENT_SECRET"),
            )
        else:
            raise SalesforceInvalidRequestError(f"Unsupported grant_type: {grant_type}")

        expires_at = self._compute_expires_at(now, grant_result)
        with self._lock:
            self._cache[cache_key] = _CacheEntry(
                token=grant_result["access_token"],
                instance_url=grant_result["instance_url"],
                expires_at=expires_at,
                granted_at=now,
            )

        return {
            "access_token": grant_result["access_token"],
            "instance_url": grant_result["instance_url"],
            "expires_at": expires_at.isoformat(),
            "granted_at": now.isoformat(),
            "issued_at": grant_result.get("issued_at"),
            "token_type": grant_result.get("token_type", "Bearer"),
            "scope": grant_result.get("scope"),
            "cached": False,
        }

    # ------------------------------------------------------------------
    # Credentials validation
    # ------------------------------------------------------------------
    async def validate_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        auth = await self.get_access_token(credentials)
        identity = await self._fetch_identity(
            instance_url=auth["instance_url"],
            access_token=auth["access_token"],
        )
        return {
            "valid": True,
            "identity": identity,
            "instance_url": auth["instance_url"],
            "token_type": auth.get("token_type"),
        }

    # ------------------------------------------------------------------
    # Grant implementations
    # ------------------------------------------------------------------
    async def _grant_password(
        self,
        *,
        login_url: str,
        username: str | None,
        password: str | None,
        security_token: str | None,
        client_id: str | None,
        client_secret: str | None,
    ) -> dict[str, Any]:
        if not username or not password:
            raise SalesforceInvalidCredentialsError("username and password are required for password grant")
        if not client_id:
            raise SalesforceInvalidCredentialsError(
                "client_id is required for password grant (configure SF_CLIENT_ID or pass in credentials)"
            )
        combined = password + (security_token or "")
        data = {
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret or "",
            "username": username,
            "password": combined,
        }
        return await self._do_token_grant(login_url, data, username or "unknown")

    async def _grant_jwt_bearer(
        self,
        *,
        login_url: str,
        client_id: str | None,
        jwt_subject: str | None,
        private_key: str,
    ) -> dict[str, Any]:
        if not client_id:
            raise SalesforceInvalidCredentialsError(
                "client_id is required for JWT Bearer grant (configure SF_CLIENT_ID or pass in credentials)"
            )
        if not jwt_subject:
            raise SalesforceInvalidCredentialsError("jwt_subject / username is required for JWT Bearer grant")
        assertion = self._encode_jwt(client_id=client_id, audience=login_url, subject=jwt_subject, private_key=private_key)
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
        return await self._do_token_grant(login_url, data, jwt_subject)

    def _encode_jwt(self, *, client_id: str, audience: str, subject: str, private_key: str) -> str:
        """Minimal RS256 JWT for Salesforce JWT Bearer flow.

        Kept small and single-purpose: header, body, RSASSA-PKCS1-v1_5 SHA256
        signature.  Avoids a pyjwt dependency.
        """
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
        except ImportError as exc:  # pragma: no cover - env check
            raise SalesforceInvalidRequestError(
                "JWT Bearer grant requires the 'cryptography' package installed"
            ) from exc

        try:
            key = serialization.load_pem_private_key(private_key.encode("utf-8"), password=None)
            if not isinstance(key, rsa.RSAPrivateKey):
                raise TypeError("JWT private key must be an RSA key")
        except Exception as exc:
            raise SalesforceInvalidCredentialsError(f"Invalid JWT private key PEM: {exc.__class__.__name__}") from exc

        now_iat = int(time.time())
        headers = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": client_id,
            "aud": audience,
            "sub": subject,
            "exp": now_iat + 300,
            "iat": now_iat,
        }
        h_b64 = self._b64url(json.dumps(headers, separators=(",", ":")))
        p_b64 = self._b64url(json.dumps(payload, separators=(",", ":")))
        signing_input = f"{h_b64}.{p_b64}".encode("ascii")
        try:
            sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            raise SalesforceInvalidCredentialsError(f"Unable to sign JWT assertion: {exc.__class__.__name__}") from exc
        return f"{h_b64}.{p_b64}.{self._b64url_bytes(sig)}"

    @staticmethod
    def _b64url(s: str) -> str:
        return SalesforceAuthClient._b64url_bytes(s.encode("utf-8"))

    @staticmethod
    def _b64url_bytes(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    # ------------------------------------------------------------------
    # Token HTTP + identity HTTP
    # ------------------------------------------------------------------
    async def _do_token_grant(self, login_url: str, data: dict[str, Any], identity_label: str) -> dict[str, Any]:
        client = self._acquire_client()
        url = f"{login_url}/services/oauth2/token"
        scrubbed_data = _scrub(data)
        log.info(
            "Salesforce token grant begin login=%s user=%s grant=%s",
            login_url,
            identity_label,
            data.get("grant_type"),
            extra={"payload": scrubbed_data},
        )
        start = time.perf_counter()
        try:
            async def _post_token() -> httpx.Response:
                response = await client.post(
                    url,
                    data=data,
                    timeout=httpx.Timeout(_setting(self.settings, "SF_TIMEOUT_SECONDS", 60), connect=10.0),
                )
                if response.status_code in RETRYABLE_STATUS_CODES:
                    try:
                        response_payload = response.json()
                    except ValueError:
                        response_payload = {"raw": response.text[:200]}
                    raise classify_http_error(response.status_code, response_payload, "Salesforce OAuth transient response")
                return response

            response = await retry_call(_post_token, op_label="salesforce.oauth.token")
        except httpx.TimeoutException as exc:
            raise SalesforceTimeoutError(
                f"Salesforce token grant timed out for user={identity_label}: {exc.__class__.__name__}"
            ) from exc
        except httpx.ConnectError as exc:
            raise SalesforceTimeoutError(
                f"Salesforce token grant connect error for user={identity_label}: {exc.__class__.__name__}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SalesforceAuthenticationError(
                f"Salesforce token grant transport error: {exc.__class__.__name__}",
                retryable=True,
            ) from exc

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:200]}

        if response.status_code == 200:
            token = payload.get("access_token")
            instance_url = payload.get("instance_url")
            if not token or not instance_url:
                raise SalesforceAuthenticationError(
                    "Salesforce token grant missing access_token or instance_url",
                    status_code=200,
                    response_payload=_scrub(payload),
                )
            log.info(
                "Salesforce token grant OK status=200 elapsed_ms=%s user=%s",
                elapsed_ms,
                identity_label,
            )
            return {
                "access_token": token,
                "instance_url": instance_url,
                "issued_at": payload.get("issued_at"),
                "token_type": payload.get("token_type", "Bearer"),
                "scope": payload.get("scope"),
                "signature": payload.get("signature"),
                "id": payload.get("id"),
            }

        scrubbed_payload = _scrub(payload)
        message = (
            f"Salesforce token grant failed status={response.status_code} elapsed_ms={elapsed_ms} "
            f"user={identity_label}"
        )
        error = payload.get("error") if isinstance(payload, dict) else None
        error_desc = payload.get("error_description") if isinstance(payload, dict) else None
        if error_desc:
            message += f" description={error_desc[:200]}"
        if error in _AUTH_INVALID_CODES or response.status_code in (401, 400):
            if response.status_code == 403:
                raise SalesforceForbiddenError(message, error_code=error, response_payload=scrubbed_payload)
            raise SalesforceInvalidCredentialsError(
                message,
                error_code=error,
                response_payload=scrubbed_payload,
            )
        raise classify_http_error(response.status_code, scrubbed_payload if isinstance(scrubbed_payload, dict) else {"raw": scrubbed_payload}, message)

    async def _fetch_identity(self, *, instance_url: str, access_token: str) -> dict[str, Any]:
        client = self._acquire_client()
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        url = f"{instance_url}/services/oauth2/userinfo"
        try:
            async def _get_identity() -> httpx.Response:
                response = await client.get(
                    url,
                    headers=headers,
                    timeout=httpx.Timeout(_setting(self.settings, "SF_TIMEOUT_SECONDS", 60), connect=10.0),
                )
                if response.status_code in RETRYABLE_STATUS_CODES:
                    try:
                        response_payload = response.json()
                    except ValueError:
                        response_payload = {"raw": response.text[:200]}
                    raise classify_http_error(response.status_code, response_payload, "Salesforce identity transient response")
                return response

            response = await retry_call(_get_identity, op_label="salesforce.oauth.identity")
        except httpx.TimeoutException as exc:
            raise SalesforceTimeoutError("Salesforce identity call timed out") from exc
        except httpx.ConnectError as exc:
            raise SalesforceTimeoutError(f"Salesforce identity connect error: {exc.__class__.__name__}") from exc
        except httpx.HTTPError as exc:
            raise SalesforceAPIError(f"Salesforce identity transport error: {exc.__class__.__name__}", retryable=True) from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:200]}

        if response.status_code == 200 and isinstance(payload, dict):
            return {
                "user_id": payload.get("user_id"),
                "organization_id": payload.get("organization_id"),
                "username": payload.get("preferred_username") or payload.get("email"),
                "email": payload.get("email"),
                "display_name": payload.get("name"),
                "url": payload.get("url"),
            }

        message = f"Salesforce identity call failed status={response.status_code}"
        raise classify_http_error(response.status_code, payload if isinstance(payload, dict) else {"raw": payload}, message)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _acquire_client(self) -> httpx.AsyncClient:
        if self._httpx_client is not None:
            return self._httpx_client
        if not hasattr(self, "_default_client"):
            self._default_client = httpx.AsyncClient()
        return self._default_client

    async def aclose(self) -> None:  # pragma: no cover - lifecycle hook
        client = getattr(self, "_default_client", None)
        if client is not None and client is not self._httpx_client:
            await client.aclose()

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def invalidate_cache(self, credentials: dict[str, Any], login_url: str | None = None) -> None:
        login_url = login_url or _setting(self.settings, "SF_LOGIN_URL") or "https://login.salesforce.com"
        key = _build_cache_key(credentials, login_url.rstrip("/"))
        with self._lock:
            self._cache.pop(key, None)

    def _compute_expires_at(self, granted_at: _dt.datetime, grant_result: dict[str, Any]) -> _dt.datetime:
        issued_str = grant_result.get("issued_at")
        ttl_seconds: int | None = None
        if isinstance(issued_str, str) and issued_str.isdigit():
            issued_ms = int(issued_str)
            granted_epoch_ms = int(granted_at.timestamp() * 1000)
            drift = max(0, granted_epoch_ms - issued_ms) // 1000
            ttl_seconds = max(_CACHE_MIN_LIFETIME_SECONDS, 1800 - drift)
        if ttl_seconds is None:
            ttl_seconds = 1800
        return granted_at + _dt.timedelta(seconds=ttl_seconds)
