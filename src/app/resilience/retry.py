from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

from src.app.core.logging_setup import get_logger
from src.app.salesforce.exceptions import SalesforceAPIError

log = get_logger(__name__)

T = TypeVar("T")

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def is_retryable(exc: BaseException) -> bool:
    """Classify whether an exception warrants a retry attempt."""
    if isinstance(exc, SalesforceAPIError):
        if exc.retryable is not None:
            return bool(exc.retryable)
        return exc.status_code is not None and exc.status_code in RETRYABLE_STATUS_CODES
    # Transport-level errors
    try:
        import httpx
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
            return True
    except ImportError:
        pass
    # Connection-level OSError (e.g. connection refused)
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


async def retry_call(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int | None = None,
    delays: list | None = None,
    jitter: bool | None = None,
    max_delay: float | None = None,
    op_label: str = "operation",
    **kwargs: Any,
) -> Any:
    """Execute ``fn`` with bounded retries, exponential backoff, and optional jitter.

    Raises the last exception if all attempts fail.
    Never retries non-retryable failures.
    """
    from src.app.core.config import get_settings
    settings = get_settings()
    if max_retries is None:
        max_retries = settings.EXTERNAL_CALL_MAX_RETRIES
    if delays is None:
        delays = list(settings.EXTERNAL_CALL_RETRY_DELAYS)
    if not delays:
        delays = [0]
    if jitter is None:
        jitter = settings.EXTERNAL_CALL_JITTER
    if max_delay is None:
        max_delay = settings.EXTERNAL_CALL_MAX_DELAY_SECONDS

    last_exc: BaseException | None = None
    attempt = 0

    while attempt <= max_retries:
        try:
            return await fn(*args, **kwargs)
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            last_exc = exc
            if not is_retryable(exc):
                log.debug(
                    "retry_call non-retryable failure op=%s attempt=%d/%d: %s",
                    op_label, attempt + 1, max_retries + 1, exc.__class__.__name__,
                )
                raise

            if attempt >= max_retries:
                log.warning(
                    "retry_call exhausted op=%s attempt=%d/%d: %s",
                    op_label, attempt + 1, max_retries + 1, exc.__class__.__name__,
                )
                raise

            delay_idx = min(attempt, len(delays) - 1)
            base_delay = min(float(delays[delay_idx]), max_delay)
            if jitter:
                actual_delay = base_delay * (0.5 + random.random())
            else:
                actual_delay = base_delay

            log.info(
                "retry_call retrying op=%s attempt=%d/%d delay=%.2fs: %s",
                op_label, attempt + 1, max_retries + 1, actual_delay, exc.__class__.__name__,
            )
            await asyncio.sleep(actual_delay)
            attempt += 1

    # Should not reach here
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"retry_call exhausted without exception for op={op_label}")


def retry_call_sync(
    fn: Callable[..., T],
    *args: Any,
    max_retries: int | None = None,
    delays: list | None = None,
    jitter: bool | None = None,
    max_delay: float | None = None,
    op_label: str = "operation",
    **kwargs: Any,
) -> T:
    """Synchronous equivalent used by the synchronous MinIO SDK."""
    from src.app.core.config import get_settings
    settings = get_settings()
    retries = settings.EXTERNAL_CALL_MAX_RETRIES if max_retries is None else max_retries
    retry_delays = list(settings.EXTERNAL_CALL_RETRY_DELAYS if delays is None else delays) or [0]
    use_jitter = settings.EXTERNAL_CALL_JITTER if jitter is None else jitter
    limit = settings.EXTERNAL_CALL_MAX_DELAY_SECONDS if max_delay is None else max_delay
    last_exc: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            last_exc = exc
            if not is_retryable(exc) or attempt >= retries:
                raise
            delay = min(float(retry_delays[min(attempt, len(retry_delays) - 1)]), limit)
            if use_jitter:
                delay *= 0.5 + random.random()
            log.info("retry_call_sync retrying op=%s attempt=%d/%d delay=%.2fs", op_label, attempt + 1, retries + 1, delay)
            time.sleep(delay)
    raise last_exc or RuntimeError(f"retry_call_sync exhausted op={op_label}")
