from __future__ import annotations

import hashlib
import hmac as _hmac
import time
from collections import OrderedDict
from threading import Lock

from fastapi import HTTPException, Request

from src.app.audit.audit_service import AuditService
from src.app.core.config import get_settings
from src.app.core.logging_setup import get_logger
from src.app.db.session import get_session_factory

log = get_logger(__name__)

# Nonce replay store: {nonce: expiry_epoch}
_NONCE_STORE: OrderedDict = OrderedDict()
_NONCE_LOCK = Lock()
_NONCE_MAX_SIZE = 10000


class HMACAuthData:
    def __init__(
        self,
        client_id: str,
        role: str,
        signature: str,
        timestamp: str,
        nonce: str,
    ) -> None:
        self.client_id = client_id
        self.role = role
        self.signature = signature
        self.timestamp = timestamp
        self.nonce = nonce


def _evict_expired_nonces(max_age: int) -> None:
    """Remove expired nonces from the replay store."""
    now = time.time()
    with _NONCE_LOCK:
        expired = [k for k, exp in _NONCE_STORE.items() if now > exp]
        for k in expired:
            del _NONCE_STORE[k]


def _check_and_register_nonce(nonce: str, max_age: int) -> bool:
    """Return True if nonce is new (not replayed). Register it."""
    _evict_expired_nonces(max_age)
    now = time.time()
    with _NONCE_LOCK:
        if nonce in _NONCE_STORE:
            return False
        if len(_NONCE_STORE) >= _NONCE_MAX_SIZE:
            # evict oldest
            _NONCE_STORE.popitem(last=False)
        _NONCE_STORE[nonce] = now + max_age + 60
        return True


def _build_canonical_string(method: str, path: str, timestamp: str, nonce: str, body_bytes: bytes) -> str:
    """Build canonical string per spec:
    METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY)
    """
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"


def _compute_signature(canonical: str, secret: str) -> str:
    return _hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _constant_time_compare(a: str, b: str) -> bool:
    return _hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def _verify_hmac(request: Request, require_full_access: bool = False) -> HMACAuthData:
    settings = get_settings()

    if not settings.HMAC_ENABLED:
        return HMACAuthData(
            client_id="coordinator",
            role="full",
            signature="hmac-disabled",
            timestamp="0",
            nonce="hmac-disabled",
        )

    # Extract headers
    sig = request.headers.get("X-SF-Signature")
    timestamp = request.headers.get("X-SF-Timestamp")
    client_id = request.headers.get("X-SF-Client-ID")
    nonce = request.headers.get("X-SF-Nonce")

    if not all([sig, timestamp, client_id, nonce]):
        _audit_auth_failure(request, client_id, "missing_headers")
        raise HTTPException(
            status_code=401,
            detail={"error": "missing_auth_headers", "required": ["X-SF-Signature", "X-SF-Timestamp", "X-SF-Client-ID", "X-SF-Nonce"]},
        )
    assert sig is not None
    assert timestamp is not None
    assert client_id is not None
    assert nonce is not None

    # Timestamp freshness
    try:
        req_time = int(timestamp)
        now = int(time.time())
        age = abs(now - req_time)
    except (ValueError, TypeError):
        _audit_auth_failure(request, client_id, "invalid_timestamp")
        raise HTTPException(status_code=401, detail={"error": "invalid_timestamp"})

    max_age = settings.HMAC_SIGNATURE_MAX_AGE
    if age > max_age:
        _audit_auth_failure(request, client_id, "expired_timestamp")
        raise HTTPException(status_code=401, detail={"error": "expired_timestamp", "age_seconds": age, "max_age": max_age})

    # Client ID + key lookup
    if client_id == "coordinator":
        secret = settings.HMAC_SECRET_KEY_CORE
        role = "full"
    elif client_id == "engineer":
        secret = settings.HMAC_SECRET_KEY_ENGINEER
        role = "read_only"
    else:
        _audit_auth_failure(request, client_id, "invalid_client")
        raise HTTPException(status_code=401, detail={"error": "invalid_client_id"})

    # Role restriction: engineer can only do GET
    if require_full_access and role == "read_only":
        _audit_auth_failure(request, client_id, "insufficient_permissions")
        raise HTTPException(status_code=403, detail={"error": "read_only_client_cannot_write"})

    # Nonce replay
    if not _check_and_register_nonce(nonce, max_age):
        _audit_auth_failure(request, client_id, "nonce_replay")
        raise HTTPException(status_code=401, detail={"error": "nonce_replayed"})

    # Build canonical string and verify signature
    body_bytes = await request.body()
    canonical = _build_canonical_string(
        method=request.method,
        path=request.url.path,
        timestamp=timestamp,
        nonce=nonce,
        body_bytes=body_bytes,
    )
    expected_sig = _compute_signature(canonical, secret)

    if not _constant_time_compare(sig, expected_sig):
        # Remove nonce since signature is invalid (allow retry with correct sig)
        with _NONCE_LOCK:
            _NONCE_STORE.pop(nonce, None)
        _audit_auth_failure(request, client_id, "invalid_signature")
        raise HTTPException(status_code=401, detail={"error": "invalid_signature"})

    _audit_auth_success(request, client_id, role)
    return HMACAuthData(
        client_id=client_id,
        role=role,
        signature="***",
        timestamp=timestamp,
        nonce=nonce,
    )


def _audit_auth_failure(request: Request, client_id: str | None, reason: str) -> None:
    log.warning(
        "HMAC auth failure reason=%s client_id=%s method=%s path=%s ip=%s",
        reason, client_id, request.method, request.url.path,
        request.client.host if request.client else "unknown",
    )
    AuditService(get_session_factory).write_audit_nonblocking(
        "auth", reason, outcome="unauthorized", actor_client_id=client_id,
        http_method=request.method, endpoint=request.url.path,
        request_ip=request.client.host if request.client else None,
    )


def _audit_auth_success(request: Request, client_id: str, role: str) -> None:
    log.info(
        "HMAC auth success client_id=%s role=%s method=%s path=%s",
        client_id, role, request.method, request.url.path,
    )
    AuditService(get_session_factory).write_audit_nonblocking(
        "auth", "authentication_success", outcome="success",
        actor_client_id=client_id, actor_role=role, http_method=request.method,
        endpoint=request.url.path, request_ip=request.client.host if request.client else None,
    )


async def hmac_auth_required(request: Request) -> HMACAuthData:
    """FastAPI dependency: full access required (coordinator only)."""
    return await _verify_hmac(request, require_full_access=True)


async def hmac_auth_readonly(request: Request) -> HMACAuthData:
    """FastAPI dependency: read-only access allowed (coordinator or engineer)."""
    return await _verify_hmac(request, require_full_access=False)


# Utility for tests / callers to generate valid HMAC headers
def build_hmac_headers(
    method: str,
    path: str,
    body: bytes,
    secret: str,
    client_id: str,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Helper to build valid HMAC headers for a request."""
    import uuid
    ts = str(timestamp or int(time.time()))
    nc = nonce or uuid.uuid4().hex
    canonical = _build_canonical_string(method, path, ts, nc, body)
    sig = _compute_signature(canonical, secret)
    return {
        "X-SF-Signature": sig,
        "X-SF-Timestamp": ts,
        "X-SF-Client-ID": client_id,
        "X-SF-Nonce": nc,
    }
