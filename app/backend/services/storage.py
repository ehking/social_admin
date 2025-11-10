"""Storage abstractions for persisting generated media."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from ..config import AppSettings, get_settings


logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Raised when a storage operation fails."""


@dataclass(slots=True)
class StorageResult:
    """Represents the outcome of a storage upload operation."""

    key: str
    url: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise StorageError("Storage key must be a non-empty string")


class StorageService(Protocol):
    """Minimal protocol implemented by storage services."""

    def upload_file(
        self,
        source: Path,
        *,
        destination_name: str | None = None,
        content_type: str | None = None,
    ) -> StorageResult:
        ...

    def delete_object(self, key: str) -> None:
        ...


class LocalFilesystemStorage:
    """Store files on the local filesystem (useful for development/testing)."""

    def __init__(self, *, base_path: Path) -> None:
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.debug("Local storage initialised", extra={"base_path": str(self.base_path)})

    def _resolve_destination(self, destination_name: str | None, source: Path) -> Path:
        if destination_name:
            destination = Path(destination_name)
            if destination.is_absolute():
                raise StorageError("Destination name must be relative when using local storage")
        else:
            destination = Path(f"{uuid4().hex}{source.suffix}")

        final_path = (self.base_path / destination).resolve()
        if self.base_path not in final_path.parents and final_path != self.base_path:
            raise StorageError("Destination escapes storage root")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        return final_path

    def upload_file(
        self,
        source: Path,
        *,
        destination_name: str | None = None,
        content_type: str | None = None,
    ) -> StorageResult:
        del content_type  # Content type is unused for local storage
        source = Path(source)
        if not source.exists():
            raise StorageError(f"Source file does not exist: {source}")

        destination = self._resolve_destination(destination_name, source)
        shutil.copy2(source, destination)
        relative_key = str(destination.relative_to(self.base_path))
        logger.info(
            "Stored file locally",
            extra={"source": str(source), "destination": relative_key},
        )
        return StorageResult(key=relative_key, url=destination.as_uri())

    def delete_object(self, key: str) -> None:
        target = (self.base_path / key).resolve()
        if self.base_path not in target.parents and target != self.base_path:
            raise StorageError("Attempted to delete outside storage root")
        try:
            target.unlink()
        except FileNotFoundError:
            return
        logger.info("Deleted local storage object", extra={"key": key})


class S3Storage:
    """Store files on an S3 compatible object storage."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str | None = None,
        client: object | None = None,
    ) -> None:
        try:
            if client is None:
                import boto3  # type: ignore

                self.client = boto3.client("s3")
            else:
                self.client = client
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise StorageError("boto3 is required for S3 storage") from exc

        self.bucket = bucket
        self.prefix = prefix.strip("/") if prefix else ""
        logger.debug(
            "S3 storage initialised",
            extra={"bucket": self.bucket, "prefix": self.prefix or None},
        )

    def _build_key(self, destination_name: str | None, source: Path) -> str:
        key = destination_name or f"{uuid4().hex}{source.suffix}"
        if self.prefix:
            return f"{self.prefix}/{key}".strip("/")
        return key

    def upload_file(
        self,
        source: Path,
        *,
        destination_name: str | None = None,
        content_type: str | None = None,
    ) -> StorageResult:
        source = Path(source)
        if not source.exists():
            raise StorageError(f"Source file does not exist: {source}")

        key = self._build_key(destination_name, source)
        extra_args = {"ContentType": content_type} if content_type else None
        try:
            if extra_args:
                self.client.upload_file(str(source), self.bucket, key, ExtraArgs=extra_args)
            else:
                self.client.upload_file(str(source), self.bucket, key)
        except Exception as exc:  # pragma: no cover - network operations are not tested
            raise StorageError(f"Failed to upload file to S3: {exc}") from exc
        logger.info(
            "Uploaded file to S3",
            extra={"bucket": self.bucket, "key": key, "source": str(source)},
        )
        return StorageResult(key=key, url=f"s3://{self.bucket}/{key}")

    def delete_object(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # pragma: no cover - network operations are not tested
            raise StorageError(f"Failed to delete S3 object {key}: {exc}") from exc
        logger.info("Deleted S3 object", extra={"bucket": self.bucket, "key": key})


def get_storage_service(settings: AppSettings | None = None) -> StorageService:
    """Return the configured storage service instance."""

    settings = settings or get_settings()

    if settings.storage_backend == "local":
        storage = LocalFilesystemStorage(base_path=settings.storage_local_base_path)
        logger.debug("Using local storage backend", extra={"base_path": str(settings.storage_local_base_path)})
        return storage

    if settings.storage_backend == "s3":
        if not settings.storage_s3_bucket:
            raise StorageError("STORAGE_S3_BUCKET is required when using the S3 backend")
        storage = S3Storage(bucket=settings.storage_s3_bucket, prefix=settings.storage_s3_prefix)
        logger.debug(
            "Using S3 storage backend",
            extra={"bucket": settings.storage_s3_bucket, "prefix": settings.storage_s3_prefix},
        )
        return storage

    raise StorageError(f"Unsupported storage backend: {settings.storage_backend}")
