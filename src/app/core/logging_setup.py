from __future__ import annotations

import logging
import sys
from typing import Any, Dict

from pythonjsonlogger import jsonlogger

from src.app.core.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if settings.APP_ENV.lower() in {"dev", "development", "local"}:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(module)s %(funcName)s %(lineno)d"
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)

    for noisy in ("urllib3", "httpx", "botocore", "boto3"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_context(**kwargs: Any) -> Dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}
