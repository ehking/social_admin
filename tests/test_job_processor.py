import json
import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.backend.database import Base, SessionLocal, engine
from app.backend.models import Job
from app.backend.services import JobProcessor, JobService
from app.backend.services import job_processor as job_processor_module


@pytest.fixture(autouse=True)
def reset_database(tmp_path):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    logs_dir = tmp_path / "logs"
    yield logs_dir
    Base.metadata.drop_all(bind=engine)


def _create_job(file_path: pathlib.Path) -> Job:
    service = JobService()
    return service.create_job_with_media_and_campaign(
        job_payload={"title": "Manual Clip", "description": ""},
        media_payloads=[{"media_type": "video/mp4", "media_url": str(file_path)}],
        campaign_payload={"name": "Campaign"},
    )


def test_processor_marks_job_completed_when_media_exists(tmp_path):
    logs_dir = tmp_path / "logs"
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"content")

    job = _create_job(media_path)

    processor = JobProcessor(log_directory=logs_dir)
    processor.process_pending_jobs()

    with SessionLocal() as session:
        refreshed = session.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == "completed"
        assert refreshed.progress_percent == 100
        assert refreshed.error_details is None

    log_files = list(logs_dir.glob("*.log"))
    assert log_files, "Processor should emit job log files"
    assert any(f"job-{job.id}" in path.name for path in log_files)


def test_processor_marks_job_failed_when_media_missing(tmp_path):
    logs_dir = tmp_path / "logs"
    missing_path = tmp_path / "missing.mp4"

    job = _create_job(missing_path)

    processor = JobProcessor(log_directory=logs_dir)
    processor.process_pending_jobs()

    with SessionLocal() as session:
        refreshed = session.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.progress_percent == 100
        assert refreshed.error_details is not None
        details = json.loads(refreshed.error_details)
        assert details["code"] == "missing_file"
        assert "message" in details

    log_files = list(logs_dir.glob("*.log"))
    assert log_files, "Processor should emit job log files for failures"


def test_processor_records_unexpected_errors(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"content")

    job = _create_job(media_path)

    processor = JobProcessor(log_directory=logs_dir)

    def blow_up(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(JobProcessor, "_validate_job", blow_up)
    processor.process_pending_jobs()

    with SessionLocal() as session:
        refreshed = session.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == "failed"
        assert refreshed.error_details is not None
        details = json.loads(refreshed.error_details)
        assert details["code"] == "unexpected"
        assert details["context"]["error"] == "RuntimeError"


def test_processor_falls_back_to_get_when_head_not_allowed(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"

    service = JobService()
    job = service.create_job_with_media_and_campaign(
        job_payload={"title": "Remote Clip", "description": ""},
        media_payloads=[
            {"media_type": "video/mp4", "media_url": "https://cdn.example/video.mp4"}
        ],
        campaign_payload={"name": "Campaign"},
    )

    head_calls: list[dict[str, object]] = []
    get_calls: list[dict[str, object]] = []

    class DummyHeadResponse:
        status_code = 405

        def close(self):
            return None

    class DummyGetResponse:
        status_code = 200

        def close(self):
            return None

    def fake_head(url, timeout=0, allow_redirects=True):
        head_calls.append(
            {"url": url, "timeout": timeout, "allow_redirects": allow_redirects}
        )
        return DummyHeadResponse()

    def fake_get(url, timeout=0, allow_redirects=True, stream=False):
        get_calls.append(
            {
                "url": url,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
                "stream": stream,
            }
        )
        return DummyGetResponse()

    monkeypatch.setattr(job_processor_module.requests, "head", fake_head)
    monkeypatch.setattr(job_processor_module.requests, "get", fake_get)

    processor = JobProcessor(log_directory=logs_dir, request_timeout=1.0)
    processor.process_pending_jobs()

    with SessionLocal() as session:
        refreshed = session.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == "completed"
        assert refreshed.error_details is None

    assert head_calls, "HEAD request should be attempted"
    assert get_calls, "GET fallback should be attempted"
    assert get_calls[0]["stream"] is True
