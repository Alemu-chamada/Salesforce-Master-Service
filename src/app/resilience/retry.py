from __future__ import annotations

from typing import Any, Callable, TypeVar

from src.app.core.logging_setup import get_logger

log = get_logger(__name__)

T = TypeVar("T")


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def is_retryable(exc: BaseException) -> bool:
    """Placeholder classifier. Implemented in Phase 2."""
    return False


async def retry_call(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    delays: list[int] | None = None,
    jitter: bool = True,
    op_label: str = "operation",
    **kwargs: Any,
) -> Any:
    """Placeholder. Implemented in Phase 2."""
    return await fn(*args, **kwargs)
