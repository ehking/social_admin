"""Logging configuration helpers for the Social Admin application."""
from __future__ import annotations

import logging
from logging.config import dictConfig
from typing import Any, Dict

DEFAULT_LOGGING_CONFIG: Dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    },
    "loggers": {
        "": {"handlers": ["console"], "level": "INFO"},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"level": "INFO"},
    },
}


def configure_logging(config: Dict[str, Any] | None = None) -> None:
    """Configure the Python logging system for the application.

    Parameters
    ----------
    config:
        Optional dictConfig-compatible configuration. When omitted, the
        :data:`DEFAULT_LOGGING_CONFIG` is used.
    """

    dictConfig(config or DEFAULT_LOGGING_CONFIG)
    logging.getLogger(__name__).debug("Logging configured", extra={"config": config})
