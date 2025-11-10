"""Logging configuration helpers for the Social Admin application."""
from __future__ import annotations

import logging
from logging.config import dictConfig
from pathlib import Path
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
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "standard",
            "filename": "logs/app.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
        },
    },
    "loggers": {
        "": {"handlers": ["console", "file"], "level": "INFO"},
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

    resolved_config = config or DEFAULT_LOGGING_CONFIG

    log_path = Path(
        resolved_config["handlers"].get("file", {}).get("filename", "logs/app.log")
    )
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    dictConfig(resolved_config)
    logging.captureWarnings(True)
    logging.getLogger(__name__).debug("Logging configured", extra={"config": resolved_config})
