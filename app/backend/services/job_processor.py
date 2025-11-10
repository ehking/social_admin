"""Utilities for reprocessing stored jobs after service restarts."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, Optional

import requests
from requests import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..http_logging import log_request_failure, log_request_start, log_request_success
from ..logging_utils import job_context
from ..models import Job, JobMedia


LOGGER = logging.getLogger(__name__)


class JobProcessingError(RuntimeError):
    """Represents a handled error while reprocessing a job."""

    def __init__(self, message: str, *, code: str, context: Optional[Dict[str, object]] = None):
        super().__init__(message)
        self.code = code
        self.context = context or {}


@contextmanager
def _stage_logger(
    logger: logging.Logger | logging.LoggerAdapter, stage: str, **extra: object
) -> Iterator[Dict[str, object]]:
    payload: Dict[str, object] = {"stage": stage, **extra}
    logger.info("stage_started", extra=payload)
    try:
        yield payload
    except Exception:
        logger.exception("stage_failed", extra=payload)
        raise
    else:
        logger.info("stage_completed", extra=payload)


@dataclass(slots=True)
class JobProcessor:
    """Re-run video jobs so operators can inspect their status and failures."""

    session_factory: Callable[[], Session] | None = None
    log_directory: Path | None = None
    request_timeout: float = 5.0

    def __post_init__(self) -> None:
        if self.session_factory is None:
            self.session_factory = SessionLocal

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def process_pending_jobs(self) -> None:
        """Process jobs that have not reached the completed state."""

        try:
            job_ids = self._collect_jobs_for_reprocessing()
        except Exception:
            LOGGER.exception("Failed to inspect jobs for reprocessing")
            return

        if not job_ids:
            LOGGER.info("No jobs require reprocessing")
            return

        LOGGER.info("Reprocessing %d pending/failed jobs", len(job_ids))
        for job_id in job_ids:
            try:
                self._process_single_job(job_id)
            except Exception:
                LOGGER.exception("Unhandled error while reprocessing job", extra={"job_id": job_id})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _collect_jobs_for_reprocessing(self) -> Iterable[int]:
        with self.session_factory() as session:  # type: ignore[misc]
            # Reset jobs that were mid-flight when the service stopped.
            updated = (
                session.query(Job)
                .filter(Job.status == "processing")
                .update({"status": "pending"}, synchronize_session=False)
            )
            if updated:
                LOGGER.info("Reset %d in-flight jobs back to pending", updated)
            session.commit()

            statement = (
                select(Job.id)
                .where(Job.status.in_(["pending", "failed"]))
                .order_by(Job.created_at.asc())
            )
            return [row[0] for row in session.execute(statement).all()]

    def _process_single_job(self, job_id: int) -> None:
        with self.session_factory() as session:  # type: ignore[misc]
            job = session.get(Job, job_id)
            if job is None:
                LOGGER.warning("Job %s disappeared before processing", job_id)
                return

            job.status = "processing"
            job.progress_percent = max(int(job.progress_percent or 0), 10)
            job.error_details = None
            session.flush()
            session.refresh(job)

            with job_context(
                media_id=job.media[0].id if job.media else None,
                campaign_id=job.campaign.id if job.campaign else None,
                log_dir=self.log_directory,
                extra_context={
                    "job_db_id": job.id,
                    "job_title": job.title,
                    "job_status": job.status,
                },
                log_identifier=f"job-{job.id}",
            ) as log_ctx:
                logger = log_ctx.logger
                logger.info(
                    "job_reprocessing_started",
                    extra={
                        "job_id": job.id,
                        "media_count": len(job.media),
                        "campaign_id": job.campaign.id if job.campaign else None,
                    },
                )

                try:
                    self._validate_job(session, job, logger)
                except JobProcessingError as exc:
                    job.status = "failed"
                    job.progress_percent = 100
                    self._record_error_details(job, error=exc)
                    session.add(job)
                    session.commit()
                    logger.error(
                        "job_reprocessing_failed",
                        extra={
                            "error": str(exc),
                            "error_code": exc.code,
                            "error_context": exc.context,
                        },
                    )
                    return
                except Exception as exc:
                    job.status = "failed"
                    job.progress_percent = 100
                    self._record_error_details(job, unexpected_error=exc)
                    session.add(job)
                    session.commit()
                    logger.exception(
                        "job_reprocessing_failed",
                        extra={"error_code": "unexpected"},
                    )
                    return

                job.status = "completed"
                job.progress_percent = 100
                job.error_details = None
                session.add(job)
                session.commit()
                logger.info(
                    "job_reprocessing_completed",
                    extra={"job_id": job.id, "log_path": str(log_ctx.log_path)},
                )

    def _validate_job(self, session: Session, job: Job, logger: logging.LoggerAdapter) -> None:
        if not job.media:
            raise JobProcessingError(
                "Job does not have any media to process",
                code="missing_media",
                context={"job_id": job.id},
            )

        media_progress_step = max(80 // len(job.media), 5)
        for index, media in enumerate(job.media, start=1):
            with _stage_logger(
                logger,
                "validate_media",
                media_index=index,
                media_id=media.id,
                media_type=media.media_type,
            ):
                validation_context = self._validate_media_source(media)
                logger.info("media_validated", extra=validation_context)

            # Update progress incrementally so the UI reflects activity.
            job.progress_percent = min(90, int(job.progress_percent or 0) + media_progress_step)
            session.flush()

    def _validate_media_source(self, media: JobMedia) -> Dict[str, object]:
        source = media.media_url or media.storage_url
        if not source:
            raise JobProcessingError(
                "Media entry does not have an accessible URL",
                code="missing_url",
                context={"media_id": media.id},
            )

        if source.startswith("http://") or source.startswith("https://"):
            return self._check_remote_media(source, media)

        path = self._resolve_local_path(source)
        if not path.exists():
            raise JobProcessingError(
                "Referenced media file does not exist",
                code="missing_file",
                context={"media_id": media.id, "path": str(path)},
            )

        return {
            "media_id": media.id,
            "media_url": source,
            "resolved_path": str(path.resolve()),
        }

    def _check_remote_media(self, url: str, media: JobMedia) -> Dict[str, object]:
        started_at = log_request_start(
            "HEAD",
            url,
            job_id=media.job_id,
            media_id=media.id,
            timeout=self.request_timeout,
        )
        try:
            response: Response = requests.head(
                url,
                timeout=self.request_timeout,
                allow_redirects=True,
            )
            response.raise_for_status()
            log_request_success(
                "HEAD",
                url,
                status=response.status_code,
                started_at=started_at,
                job_id=media.job_id,
                media_id=media.id,
            )
        except requests.RequestException as exc:  # pragma: no cover - network errors vary
            log_request_failure(
                "HEAD",
                url,
                started_at=started_at,
                error=exc,
                job_id=media.job_id,
                media_id=media.id,
            )
            raise JobProcessingError(
                "Unable to reach remote media URL",
                code="network_error",
                context={"media_id": media.id, "media_url": url, "error": str(exc)},
            ) from exc

        status_code = response.status_code
        if status_code in {405, 501}:
            response.close()
            return self._verify_remote_with_get(url, media)

        response.close()

        if status_code >= 400:
            raise JobProcessingError(
                "Remote media URL responded with an error",
                code="bad_status",
                context={
                    "media_id": media.id,
                    "media_url": url,
                    "status_code": status_code,
                    "method": "HEAD",
                },
            )

        return {
            "media_id": media.id,
            "media_url": url,
            "status_code": status_code,
            "method": "HEAD",
        }

    def _verify_remote_with_get(self, url: str, media: JobMedia) -> Dict[str, object]:
        """Fallback when remote servers reject HEAD requests."""

        try:
            response: Response = requests.get(
                url,
                timeout=self.request_timeout,
                allow_redirects=True,
                stream=True,
            )
        except requests.RequestException as exc:  # pragma: no cover - network errors vary
            raise JobProcessingError(
                "Unable to reach remote media URL",
                code="network_error",
                context={"media_id": media.id, "media_url": url, "error": str(exc)},
            ) from exc

        status_code = response.status_code
        response.close()

        if status_code >= 400:
            raise JobProcessingError(
                "Remote media URL responded with an error",
                code="bad_status",
                context={
                    "media_id": media.id,
                    "media_url": url,
                    "status_code": status_code,
                    "method": "GET",
                },
            )

        return {
            "media_id": media.id,
            "media_url": url,
            "status_code": status_code,
            "method": "GET",
        }

    def _localize_error_message(self, code: str, *, default: str) -> str:
        message = self._ERROR_MESSAGES.get(code)
        if message:
            return message
        return default

    def _record_error_details(
        self,
        job: Job,
        *,
        error: JobProcessingError | None = None,
        unexpected_error: Exception | None = None,
    ) -> None:
        if error is not None:
            message = self._localize_error_message(error.code, default=str(error))
            payload: Dict[str, object] = {
                "message": message,
                "code": error.code,
            }
            if error.context:
                payload["context"] = error.context
        elif unexpected_error is not None:
            message = self._ERROR_MESSAGES["unexpected"]
            payload = {
                "message": message,
                "code": "unexpected",
                "context": {
                    "error": unexpected_error.__class__.__name__,
                    "details": str(unexpected_error),
                },
            }
        else:  # pragma: no cover - defensive guard
            payload = {"message": "", "code": "unknown"}

        try:
            job.error_details = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):  # pragma: no cover - defensive guard
            job.error_details = json.dumps(
                {"message": payload.get("message"), "code": payload.get("code")},
                ensure_ascii=False,
            )

    @staticmethod
    def _resolve_local_path(source: str) -> Path:
        if source.startswith("file://"):
            return Path(source[7:])
        candidate = Path(source)
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    _ERROR_MESSAGES = {
        "missing_media": "هیچ رسانه‌ای برای پردازش وظیفه یافت نشد.",
        "missing_url": "آدرس فایل رسانه در دسترس نیست.",
        "missing_file": "فایل رسانه‌ای که برای پردازش نیاز است یافت نشد.",
        "network_error": "دسترسی به آدرس فایل رسانه امکان‌پذیر نبود.",
        "bad_status": "آدرس فایل رسانه با وضعیت ناموفق پاسخ داد.",
        "unexpected": "خطای غیرمنتظره‌ای هنگام پردازش ویدیو رخ داد.",
    }

