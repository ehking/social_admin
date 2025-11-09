"""Application configuration helpers."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

LOGGER = logging.getLogger(__name__)


def _read_int(env_name: str, default: int) -> int:
    value = os.getenv(env_name)
    if value is None:
        return default
    try:
        parsed = int(value)
        if parsed <= 0:
            raise ValueError
        return parsed
    except ValueError:
        LOGGER.warning("Invalid value for %s: %s. Falling back to %s.", env_name, value, default)
        return default


def _read_float(env_name: str, default: float) -> float:
    value = os.getenv(env_name)
    if value is None:
        return default
    try:
        parsed = float(value)
        if parsed <= 0:
            raise ValueError
        return parsed
    except ValueError:
        LOGGER.warning("Invalid value for %s: %s. Falling back to %s.", env_name, value, default)
        return default


@dataclass(frozen=True, slots=True)
class TrendingRequestBackoff:
    """Configuration values for backoff retries when calling trending APIs."""

    max_attempts: int
    min_seconds: float
    max_seconds: float


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Top level configuration container for the application."""

    trending_request_backoff: TrendingRequestBackoff

    @classmethod
    def load(cls) -> "AppSettings":
        min_seconds = _read_float("TRENDING_REQUEST_BACKOFF_MIN_SECONDS", 1.0)
        max_seconds = _read_float("TRENDING_REQUEST_BACKOFF_MAX_SECONDS", 30.0)
        if max_seconds < min_seconds:
            LOGGER.warning(
                "TRENDING_REQUEST_BACKOFF_MAX_SECONDS (%s) is lower than the minimum (%s). Using minimum value.",
                max_seconds,
                min_seconds,
            )
            max_seconds = min_seconds
        return cls(
            trending_request_backoff=TrendingRequestBackoff(
                max_attempts=_read_int("TRENDING_REQUEST_MAX_ATTEMPTS", 5),
                min_seconds=min_seconds,
                max_seconds=max_seconds,
            )
        )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return the cached application settings instance."""

    return AppSettings.load()

