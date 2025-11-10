"""Utilities for emitting structured API request logs."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Mapping, MutableMapping


_SEPARATOR = "\t"
_API_LOGGER = logging.getLogger("app.api")


def _serialize_fields(fields: Mapping[str, object]) -> str:
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return _SEPARATOR.join(parts)


def _format_message(event: str, *, fields: Mapping[str, object]) -> str:
    serialized = _serialize_fields(fields)
    if serialized:
        return _SEPARATOR.join((event, serialized))
    return event


def log_request_start(method: str, url: str, **fields: object) -> float:
    """Emit a start log entry for an outgoing API request."""

    payload: MutableMapping[str, object] = {"method": method.upper(), "url": url}
    payload.update(fields)
    _API_LOGGER.info(_format_message("request_start", fields=payload))
    return perf_counter()


def log_request_success(
    method: str,
    url: str,
    *,
    status: int,
    started_at: float,
    **fields: object,
) -> None:
    """Emit a completion log entry for a successful API request."""

    duration = perf_counter() - started_at
    payload: MutableMapping[str, object] = {
        "method": method.upper(),
        "url": url,
        "status": status,
        "duration": f"{duration:.3f}",
    }
    payload.update(fields)
    _API_LOGGER.info(_format_message("request_success", fields=payload))


def log_request_failure(
    method: str,
    url: str,
    *,
    started_at: float,
    error: BaseException,
    **fields: object,
) -> None:
    """Emit a log entry describing a failed API request."""

    duration = perf_counter() - started_at
    payload: MutableMapping[str, object] = {
        "method": method.upper(),
        "url": url,
        "duration": f"{duration:.3f}",
        "error": error.__class__.__name__,
        "details": str(error),
    }
    payload.update(fields)
    _API_LOGGER.warning(_format_message("request_failure", fields=payload))
