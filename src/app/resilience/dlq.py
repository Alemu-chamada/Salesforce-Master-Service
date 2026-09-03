from __future__ import annotations

from typing import Any, Dict, Optional

from src.app.core.logging_setup import get_logger

log = get_logger(__name__)

SENSITIVE_KEYS = {
    "password",
    "client_secret",
    "access_token",
    "refresh_token",
    "private_key",
    "secret",
    "token",
    "security_token",
}


def scrub_payload(payload: Any) -> Any:
    """Placeholder payload scrubber. Implemented in Phase 2."""
    return None


def write_to_dlq(
    target_service: str,
    operation: str,
    payload: Any,
    attempts: int,
    error: BaseException | str,
    organization_id: Optional[str] = None,
    scan_id: Optional[str] = None,
) -> None:
    """Placeholder DLQ writer. Implemented in Phase 2."""
    log.warning(
        "DLQ placeholder: target=%s op=%s attempts=%s error=%s",
        target_service,
        operation,
        attempts,
        str(error)[:200],
    )
    return None
