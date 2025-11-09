"""Structured logging utilities for background jobs."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, MutableMapping
from uuid import uuid4


_RESERVED_LOG_RECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "process",
    "processName",
    "message",
    "asctime",
}


class JsonLogFormatter(logging.Formatter):
    """Serialize log records to JSON with ISO timestamps."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 - override
        log_record: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_ATTRS:
                continue
            log_record[key] = self._coerce_value(value)

        return json.dumps(log_record, ensure_ascii=False)

    @staticmethod
    def _coerce_value(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        return value


@dataclass(slots=True)
class JobContext:
    """Holds contextual metadata and logger for a background job."""

    job_id: str
    media_id: str | int | None
    campaign_id: str | int | None
    logger: logging.LoggerAdapter
    log_path: Path
    _handler: logging.Handler
    _base_logger: logging.Logger

    def close(self) -> None:
        """Detach handlers associated with this job context."""

        self._base_logger.removeHandler(self._handler)
        self._handler.close()


def _build_logger_adapter(
    *,
    job_id: str,
    media_id: str | int | None,
    campaign_id: str | int | None,
    base_logger: logging.Logger,
) -> logging.LoggerAdapter:
    context: MutableMapping[str, Any] = {
        "job_id": job_id,
        "media_id": media_id,
        "campaign_id": campaign_id,
    }
    return logging.LoggerAdapter(base_logger, context)


@contextmanager
def job_context(
    *,
    media_id: str | int | None = None,
    campaign_id: str | int | None = None,
    log_dir: str | Path | None = None,
    extra_context: Mapping[str, Any] | None = None,
) -> Iterator[JobContext]:
    """Create a structured logging context for background job execution."""

    job_id = uuid4().hex
    base_log_dir = Path(log_dir) if log_dir is not None else Path("logs") / "jobs"
    base_log_dir.mkdir(parents=True, exist_ok=True)
    log_path = base_log_dir / f"{job_id}.log"

    base_logger = logging.getLogger(f"social_admin.job.{job_id}")
    base_logger.setLevel(logging.INFO)
    base_logger.propagate = False

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonLogFormatter())
    base_logger.addHandler(handler)

    adapter = _build_logger_adapter(
        job_id=job_id,
        media_id=media_id,
        campaign_id=campaign_id,
        base_logger=base_logger,
    )

    if extra_context:
        adapter.extra.update(extra_context)  # type: ignore[attr-defined]

    context = JobContext(
        job_id=job_id,
        media_id=media_id,
        campaign_id=campaign_id,
        logger=adapter,
        log_path=log_path,
        _handler=handler,
        _base_logger=base_logger,
    )

    adapter.info("job_started")
    try:
        yield context
        adapter.info("job_completed")
    except Exception:
        adapter.exception("job_failed")
        raise
    finally:
        context.close()
