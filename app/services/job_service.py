"""Services related to Job creation workflows."""

from __future__ import annotations

from typing import Iterable, Mapping

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Campaign, Job, JobMedia


def _validate_media_payload(media_payload: Mapping[str, object]) -> None:
    if not media_payload.get("media_url"):
        raise ValueError("Job media requires a 'media_url'.")
    if not media_payload.get("media_type"):
        raise ValueError("Job media requires a 'media_type'.")


def _validate_campaign_payload(campaign_payload: Mapping[str, object]) -> None:
    if not campaign_payload.get("name"):
        raise ValueError("Campaign requires a 'name'.")


def create_job_with_media_and_campaign(
    job_payload: Mapping[str, object],
    media_payloads: Iterable[Mapping[str, object]],
    campaign_payload: Mapping[str, object],
) -> Job:
    """Create a job and its related media and campaign inside a single transaction."""

    with SessionLocal() as session:  # type: Session
        with session.begin():
            job = Job(**job_payload)
            session.add(job)
            session.flush()

            media_objects = []
            for payload in media_payloads:
                _validate_media_payload(payload)
                media = JobMedia(job=job, **payload)
                session.add(media)
                media_objects.append(media)

            _validate_campaign_payload(campaign_payload)
            campaign = Campaign(job=job, **campaign_payload)
            session.add(campaign)

        session.refresh(job)

    return job
