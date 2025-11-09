"""Application configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Container for runtime configuration values."""

    worker_temp_dir: Path
    storage_backend: str
    storage_local_base_path: Path
    storage_s3_bucket: str | None
    storage_s3_prefix: str | None


def _expand_path(value: str | None, default: str) -> Path:
    """Return a resolved :class:`Path` based on an environment value."""

    candidate = Path(value or default).expanduser()
    return candidate.resolve()


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return the cached application settings."""

    worker_temp_dir = _expand_path(os.getenv("WORKER_TEMP_DIR"), "/tmp/social-admin")
    storage_backend = os.getenv("STORAGE_BACKEND", "local").lower()
    storage_local_base_path = _expand_path(
        os.getenv("STORAGE_LOCAL_BASE_PATH"), "/tmp/social-admin/storage"
    )

    return AppSettings(
        worker_temp_dir=worker_temp_dir,
        storage_backend=storage_backend,
        storage_local_base_path=storage_local_base_path,
        storage_s3_bucket=os.getenv("STORAGE_S3_BUCKET"),
        storage_s3_prefix=os.getenv("STORAGE_S3_PREFIX"),
    )
