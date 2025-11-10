"""Services related to Job creation workflows."""

from __future__ import annotations

import logging
from typing import Callable, Iterable, Mapping
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Campaign, Job, JobMedia


logger = logging.getLogger(__name__)


class JobService:
    """High-level helper for creating jobs with related entities."""

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory: Callable[[], Session] = session_factory or SessionLocal

    @staticmethod
    def _normalize_string(value: object | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
        else:
            normalized = str(value).strip()
        return normalized or None

    @classmethod
    def _validate_media_payload(cls, media_payload: Mapping[str, object]) -> None:
        media_url = cls._normalize_string(media_payload.get("media_url"))
        media_type = cls._normalize_string(media_payload.get("media_type"))

        if not media_url:
            raise ValueError("Job media requires a 'media_url'.")
        if not media_type:
            raise ValueError("Job media requires a 'media_type'.")

    @staticmethod
    def _derive_storage_key(
        media_payload: Mapping[str, object],
        *,
        job_id: int,
        media_index: int,
    ) -> str:
        def from_url(candidate: object | None) -> str | None:
            normalized = JobService._normalize_string(candidate)
            if not normalized:
                return None

            parsed = urlparse(normalized)
            if parsed.scheme and parsed.netloc:
                combined = f"{parsed.netloc}{parsed.path}".strip("/")
                if combined:
                    return combined
            elif parsed.path:
                stripped_path = parsed.path.strip("/")
                if stripped_path:
                    return stripped_path

            return normalized

        for key in ("storage_key", "media_url", "storage_url"):
            derived = from_url(media_payload.get(key))
            if derived:
                return derived

        return f"job-{job_id}-media-{media_index}"

    @classmethod
    def _validate_campaign_payload(
        cls, campaign_payload: Mapping[str, object]
    ) -> str:
        name = cls._normalize_string(campaign_payload.get("name"))
        if not name:
            raise ValueError("Campaign requires a 'name'.")
        return name

    def create_job_with_media_and_campaign(
        self,
        job_payload: Mapping[str, object],
        media_payloads: Iterable[Mapping[str, object]],
        campaign_payload: Mapping[str, object],
        *,
        session: Session | None = None,
    ) -> Job:
        """Create a job and its related media and campaign inside a single transaction."""

        media_payloads = list(media_payloads)
        logger.info(
            "Creating job with media and campaign",
            extra={
                "job_payload_keys": sorted(job_payload.keys()),
                "media_count": len(media_payloads),
                "has_campaign": bool(campaign_payload),
            },
        )

        owns_session = session is None
        session_obj = session or self._session_factory()

        try:
            job = Job(**job_payload)
            progress_value = getattr(job, "progress_percent", 0) or 0
            try:
                normalized_progress = int(progress_value)
            except (TypeError, ValueError):  # pragma: no cover - defensive guard
                normalized_progress = 0
            job.progress_percent = max(0, min(100, normalized_progress))
            session_obj.add(job)
            session_obj.flush()
            logger.debug("Job persisted", extra={"job_id": job.id})

            for index, payload in enumerate(media_payloads, start=1):
                self._validate_media_payload(payload)
                media_data = dict(payload)
                media_type = self._normalize_string(media_data.get("media_type"))
                media_url = self._normalize_string(media_data.get("media_url"))
                storage_url = self._normalize_string(media_data.get("storage_url"))

                if media_type:
                    media_data["media_type"] = media_type
                if media_url:
                    media_data["media_url"] = media_url
                if storage_url is not None:
                    media_data["storage_url"] = storage_url
                if not media_data.get("job_name"):
                    media_data["job_name"] = job.title
                storage_key = self._derive_storage_key(
                    media_data, job_id=job.id, media_index=index
                )
                media_data["storage_key"] = storage_key
                media = JobMedia(job=job, **media_data)
                session_obj.add(media)
                logger.debug(
                    "Attached media to job",
                    extra={"job_id": job.id, "media_type": payload.get("media_type")},
                )

            campaign_name = self._validate_campaign_payload(campaign_payload)
            campaign_data = dict(campaign_payload)
            campaign_data["name"] = campaign_name
            campaign = Campaign(job=job, **campaign_data)
            session_obj.add(campaign)
            logger.debug(
                "Campaign associated with job",
                extra={"job_id": job.id, "campaign_name": campaign_payload.get("name")},
            )

            session_obj.commit()
            session_obj.refresh(job)
            logger.info("Job creation transaction committed", extra={"job_id": job.id})
            return job
        except Exception:
            session_obj.rollback()
            raise
        finally:
            if owns_session:
                session_obj.close()


def create_job_with_media_and_campaign(
    job_payload: Mapping[str, object],
    media_payloads: Iterable[Mapping[str, object]],
    campaign_payload: Mapping[str, object],
    *,
    session: Session | None = None,
) -> Job:
    """Backward-compatible helper that proxies to :class:`JobService`."""

    return JobService().create_job_with_media_and_campaign(
        job_payload=job_payload,
        media_payloads=media_payloads,
        campaign_payload=campaign_payload,
        session=session,
    )
