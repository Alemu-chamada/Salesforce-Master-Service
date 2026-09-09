from __future__ import annotations

import json
from typing import Any

from src.app.core.logging_setup import get_logger

log = get_logger(__name__)

SENSITIVE_KEYS = {
    "password", "client_secret", "access_token", "refresh_token",
    "private_key", "secret", "token", "security_token", "signature",
    "assertion", "jwt", "client_assertion", "authorization",
}


def scrub_payload(payload: Any, max_bytes: int = 65536) -> dict[str, Any] | None:
    """Scrub sensitive keys from payload and return a safe dict capped at max_bytes."""
    if payload is None:
        return None
    try:
        scrubbed = _deep_scrub(payload)
        serialized = json.dumps(scrubbed, default=str)
        if len(serialized.encode("utf-8")) > max_bytes:
            return {"_truncated": True, "size_bytes": len(serialized.encode("utf-8"))}
        return scrubbed if isinstance(scrubbed, dict) else {"data": scrubbed}
    except (TypeError, ValueError):
        return {"_scrub_error": True}


def _deep_scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: "***REDACTED***" if isinstance(k, str) and k.lower() in SENSITIVE_KEYS else _deep_scrub(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_deep_scrub(x) for x in value]
    return value


def write_to_dlq(
    target_service: str,
    operation: str,
    payload: Any,
    attempts: int,
    error: BaseException | str,
    organization_id: str | None = None,
    scan_id: str | None = None,
    db_factory: Any = None,
) -> None:
    """Persist a failed external call to the dead-letter queue table.

    Never raises. DLQ failures are logged but do not propagate.
    """
    try:
        from src.app.core.config import get_settings
        settings = get_settings()
        max_bytes = getattr(settings, "DLQ_PAYLOAD_MAX_BYTES", 65536)
        scrubbed = scrub_payload(payload, max_bytes=max_bytes)

        error_str = str(error)[:4000] if error else None
        status_code = getattr(error, "status_code", None)
        if status_code is not None:
            error_str = f"status_code={status_code}; {error_str}"

        if db_factory is not None:
            _persist_to_db(
                db_factory=db_factory,
                target_service=target_service,
                operation=operation,
                organization_id=organization_id,
                scan_id=scan_id,
                scrubbed_payload=scrubbed,
                attempts=attempts,
                error_str=error_str,
            )
        else:
            log.warning(
                "DLQ write (no db): target=%s op=%s org=%s scan=%s attempts=%d error=%s",
                target_service, operation, organization_id, scan_id, attempts,
                error_str[:200] if error_str else None,
            )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as dlq_exc:  # pragma: no cover - DLQ must never crash caller
        log.error("DLQ write failed (suppressed): %s", dlq_exc)


def _persist_to_db(
    *,
    db_factory: Any,
    target_service: str,
    operation: str,
    organization_id: str | None,
    scan_id: str | None,
    scrubbed_payload: dict[str, Any] | None,
    attempts: int,
    error_str: str | None,
) -> None:
    import json

    from src.app.models.enums import DLQStatus
    from src.app.models.failed_external_call import FailedExternalCall

    payload_bytes = len(json.dumps(scrubbed_payload, default=str).encode("utf-8")) if scrubbed_payload else 0

    try:
        if hasattr(db_factory, "__next__") or hasattr(db_factory, "send"):
            db = next(db_factory())
        elif callable(db_factory):
            db = db_factory()
        else:
            db = db_factory

        row = FailedExternalCall(
            target_service=target_service[:64],
            operation=operation[:128],
            organization_id=organization_id,
            scan_id=scan_id,
            payload=scrubbed_payload,
            payload_size_bytes=payload_bytes,
            attempts=attempts,
            last_error=error_str,
            status=DLQStatus.NEW,
        )
        db.add(row)
        db.commit()
        db.close()
        log.info(
            "DLQ persisted target=%s op=%s org=%s scan=%s attempts=%d",
            target_service, operation, organization_id, scan_id, attempts,
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        log.error("DLQ DB persist failed (suppressed): %s", exc)
