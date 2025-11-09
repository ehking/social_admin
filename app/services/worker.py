"""Utilities for coordinating background worker resources."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import AppSettings, get_settings


class Worker:
    """Helper class that manages worker-scoped temporary directories."""

    def __init__(self, *, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.temp_root = Path(self.settings.worker_temp_dir).resolve()
        self.temp_root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def temporary_directory(self, *, prefix: str = "job-") -> Iterator[Path]:
        """Yield a temporary directory under the configured worker root."""

        path = Path(tempfile.mkdtemp(dir=self.temp_root, prefix=prefix))
        try:
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)

    def cleanup(self) -> None:
        """Remove empty temporary directories left behind by previous runs."""

        if not self.temp_root.exists():
            return
        for child in self.temp_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
