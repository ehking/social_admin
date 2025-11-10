"""Utilities for coordinating background worker resources."""

from __future__ import annotations

import logging
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import AppSettings, get_settings


logger = logging.getLogger(__name__)


class Worker:
    """Helper class that manages worker-scoped temporary directories."""

    def __init__(self, *, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.temp_root = Path(self.settings.worker_temp_dir).resolve()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        logger.debug(
            "Worker initialised",
            extra={"temp_root": str(self.temp_root), "settings": self.settings.worker_temp_dir},
        )

    @contextmanager
    def temporary_directory(self, *, prefix: str = "job-") -> Iterator[Path]:
        """Yield a temporary directory under the configured worker root."""

        path = Path(tempfile.mkdtemp(dir=self.temp_root, prefix=prefix))
        logger.info(
            "Created worker temporary directory",
            extra={"path": str(path), "prefix": prefix},
        )
        try:
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)
            logger.info(
                "Cleaned up worker temporary directory",
                extra={"path": str(path)},
            )

    def cleanup(self) -> None:
        """Remove empty temporary directories left behind by previous runs."""

        if not self.temp_root.exists():
            return
        for child in self.temp_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
                logger.debug(
                    "Removed leftover worker directory",
                    extra={"path": str(child)},
                )
            else:
                child.unlink(missing_ok=True)
                logger.debug(
                    "Removed stray worker file",
                    extra={"path": str(child)},
                )
