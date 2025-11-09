import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.database import Base, SessionLocal, engine
from app.models import Campaign, Job, JobMedia
from app.services import create_job_with_media_and_campaign


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

    with pytest.raises(ValueError):
        create_job_with_media_and_campaign(
            job_payload, faulty_media_payloads, campaign_payload
        )

    with SessionLocal() as session:
        assert session.query(Job).count() == 0
        assert session.query(JobMedia).count() == 0
        assert session.query(Campaign).count() == 0
