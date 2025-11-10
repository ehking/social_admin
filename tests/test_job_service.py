import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.backend.database import Base, SessionLocal, engine
from app.backend.models import Campaign, Job, JobMedia
from app.backend.services import JobService


@pytest.fixture(autouse=True)
def prepare_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_transaction_rolls_back_on_media_failure():
    job_payload = {"title": "Video Editing", "description": "Edit promo video"}
    faulty_media_payloads = [{"media_type": "video", "media_url": ""}]
    campaign_payload = {"name": "Launch Campaign"}

    service = JobService()

    with pytest.raises(ValueError):
        service.create_job_with_media_and_campaign(
            job_payload, faulty_media_payloads, campaign_payload
        )

    with SessionLocal() as session:
        assert session.query(Job).count() == 0
        assert session.query(JobMedia).count() == 0
        assert session.query(Campaign).count() == 0


def test_media_defaults_to_job_title_when_name_missing():
    job_payload = {"title": "Social Clip", "description": "Short clip"}
    media_payloads = [
        {"media_type": "video/mp4", "media_url": "https://cdn.example/video.mp4"}
    ]
    campaign_payload = {"name": "Awareness"}

    service = JobService()
    job = service.create_job_with_media_and_campaign(
        job_payload, media_payloads, campaign_payload
    )

    with SessionLocal() as session:
        persisted_job = session.get(Job, job.id)

        assert persisted_job is not None
        assert persisted_job.progress_percent == 0
        assert persisted_job.media, "Job should have related media"
        assert persisted_job.media[0].job_name == "Social Clip"


def test_media_storage_key_defaults_to_derived_value_when_missing():
    job_payload = {"title": "Teaser", "description": "Short teaser"}
    media_url = "https://videos.example.com/teaser.mp4"
    media_payloads = [
        {"media_type": "video/mp4", "media_url": media_url, "storage_url": media_url}
    ]
    campaign_payload = {"name": "Teaser Campaign"}

    service = JobService()
    job = service.create_job_with_media_and_campaign(
        job_payload, media_payloads, campaign_payload
    )

    with SessionLocal() as session:
        persisted_job = session.get(Job, job.id)

        assert persisted_job is not None
        assert persisted_job.progress_percent == 0
        assert persisted_job.media, "Job should have related media"
        assert (
            persisted_job.media[0].storage_key
            == "videos.example.com/teaser.mp4"
        )


def test_media_storage_key_handles_trailing_slash_urls():
    job_payload = {"title": "Docs", "description": None}
    media_url = "https://github.com/"
    media_payloads = [
        {"media_type": "video/mp4", "media_url": media_url, "storage_url": media_url}
    ]
    campaign_payload = {"name": "Docs Campaign"}

    service = JobService()
    job = service.create_job_with_media_and_campaign(
        job_payload, media_payloads, campaign_payload
    )

    with SessionLocal() as session:
        persisted_job = session.get(Job, job.id)

        assert persisted_job is not None
        assert persisted_job.progress_percent == 0
        assert persisted_job.media, "Job should have related media"
        assert persisted_job.media[0].storage_key == "github.com"


def test_campaign_payload_requires_non_empty_name():
    job_payload = {"title": "Promo", "description": ""}
    media_payloads = [
        {"media_type": "image/png", "media_url": "https://cdn.example.com/banner.png"}
    ]
    campaign_payload = {"name": "   "}

    service = JobService()

    with pytest.raises(ValueError):
        service.create_job_with_media_and_campaign(
            job_payload, media_payloads, campaign_payload
        )


def test_campaign_name_is_trimmed_before_persist():
    job_payload = {"title": "Promo Video", "description": ""}
    media_payloads = [
        {"media_type": "video/mp4", "media_url": "https://cdn.example.com/video.mp4"}
    ]
    campaign_payload = {"name": "  Launch  "}

    service = JobService()
    job = service.create_job_with_media_and_campaign(
        job_payload, media_payloads, campaign_payload
    )

    with SessionLocal() as session:
        campaign = (
            session.query(Campaign)
            .filter_by(job_id=job.id)
            .one()
        )

        assert campaign.name == "Launch"
