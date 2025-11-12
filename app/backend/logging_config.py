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
            "format": "%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s",
        },
        "json": {
            "()": "app.backend.logging_utils.JsonLogFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "service_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "standard",
            "filename": "logs/service.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
        },
        "api_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "standard",
            "filename": "logs/api_requests.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
        },
        "ui_ajax_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": "logs/jobs/ui_ajax.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
        },
    },
    "loggers": {
        "": {"handlers": ["console", "service_file"], "level": "INFO"},
        "app.api": {
            "handlers": ["api_file"],
            "level": "INFO",
            "propagate": False,
        },
        "app.ui.ajax": {
            "handlers": ["ui_ajax_file"],
            "level": "INFO",
            "propagate": False,
        },
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

    for handler in resolved_config.get("handlers", {}).values():
        filename = handler.get("filename") if isinstance(handler, dict) else None
        if not filename:
            continue
        log_path = Path(filename)
        log_path.parent.mkdir(parents=True, exist_ok=True)

    dictConfig(resolved_config)
    logging.captureWarnings(True)
    logging.getLogger(__name__).debug("Logging configured", extra={"config": resolved_config})
