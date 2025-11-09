"""Services related to Job creation workflows."""

from __future__ import annotations

import logging
from typing import Callable, Iterable, Mapping

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Campaign, Job, JobMedia


logger = logging.getLogger(__name__)


class JobService:
    """High-level helper for creating jobs with related entities."""

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory: Callable[[], Session] = session_factory or SessionLocal

    @staticmethod
    def _validate_media_payload(media_payload: Mapping[str, object]) -> None:
        if not media_payload.get("media_url"):
            raise ValueError("Job media requires a 'media_url'.")
        if not media_payload.get("media_type"):
            raise ValueError("Job media requires a 'media_type'.")

    @staticmethod
    def _validate_campaign_payload(campaign_payload: Mapping[str, object]) -> None:
        if not campaign_payload.get("name"):
            raise ValueError("Campaign requires a 'name'.")

    def create_job_with_media_and_campaign(
        self,
        job_payload: Mapping[str, object],
        media_payloads: Iterable[Mapping[str, object]],
        campaign_payload: Mapping[str, object],
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

        with self._session_factory() as session:
            with session.begin():
                job = Job(**job_payload)
                session.add(job)
                session.flush()
                logger.debug("Job persisted", extra={"job_id": job.id})

                for payload in media_payloads:
                    self._validate_media_payload(payload)
                    media = JobMedia(job=job, **payload)
                    session.add(media)
                    logger.debug(
                        "Attached media to job",
                        extra={"job_id": job.id, "media_type": payload.get("media_type")},
                    )

                self._validate_campaign_payload(campaign_payload)
                campaign = Campaign(job=job, **campaign_payload)
                session.add(campaign)
                logger.debug(
                    "Campaign associated with job",
                    extra={"job_id": job.id, "campaign_name": campaign_payload.get("name")},
                )

            session.refresh(job)
            logger.info("Job creation transaction committed", extra={"job_id": job.id})

        return job


def create_job_with_media_and_campaign(
    job_payload: Mapping[str, object],
    media_payloads: Iterable[Mapping[str, object]],
    campaign_payload: Mapping[str, object],
) -> Job:
    """Backward-compatible helper that proxies to :class:`JobService`."""

    return JobService().create_job_with_media_and_campaign(
        job_payload=job_payload,
        media_payloads=media_payloads,
        campaign_payload=campaign_payload,
    )
