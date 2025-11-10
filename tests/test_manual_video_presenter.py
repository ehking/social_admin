from datetime import datetime
import json
from types import SimpleNamespace

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.ui.app_presenters import manual_video_presenter
from app.ui.app_presenters.manual_video_presenter import ManualVideoPresenter


class DummyTemplates:
    def TemplateResponse(self, *_args, **_kwargs):  # pragma: no cover - not used in tests
        raise NotImplementedError


def _create_presenter(tmp_path):
    static_root = tmp_path / "static"
    preview_dir = static_root / "manual_videos"
    return ManualVideoPresenter(
        templates=DummyTemplates(),
        static_root=static_root,
        preview_storage_dir=preview_dir,
    )


def test_build_job_view_includes_stage_and_preview(tmp_path):
    presenter = _create_presenter(tmp_path)

    job = SimpleNamespace(
        id=42,
        title="ویدیو تست",
        campaign=SimpleNamespace(name="کمپین تست"),
        status="processing",
        progress_percent=45,
        created_at=datetime(2024, 1, 1, 10, 0),
        media=[SimpleNamespace(storage_url="https://cdn.example/video.mp4", media_url=None)],
    )

    view = presenter._build_job_view(job)
    assert view.stage_label == "رندر ویدیو"
    assert view.stage_hint.startswith("ویدیو در حال رندر")
    assert view.media_preview_url == "https://cdn.example/video.mp4"
    assert view.local_preview_url is None
    assert view.error_message is None

    presenter.preview_storage_dir.mkdir(parents=True, exist_ok=True)
    local_file = presenter.preview_storage_dir / "job-42.mp4"
    local_file.write_bytes(b"preview")

    view_with_local = presenter._build_job_view(job)
    assert view_with_local.local_preview_url == "/static/manual_videos/job-42.mp4"
    assert view_with_local.local_preview_path == str(local_file.resolve())
    assert view_with_local.error_message is None


def test_build_job_view_includes_error_details(tmp_path):
    presenter = _create_presenter(tmp_path)

    error_payload = {
        "message": "فایل رسانه پیدا نشد.",
        "code": "missing_file",
    }

    job = SimpleNamespace(
        id=77,
        title="نمونه",
        campaign=None,
        status="failed",
        progress_percent=35,
        created_at=None,
        media=[],
        error_details=json.dumps(error_payload, ensure_ascii=False),
    )

    view = presenter._build_job_view(job)
    assert view.error_message == "فایل رسانه پیدا نشد."
    assert view.error_code == "missing_file"
    assert view.stage_hint == "فایل رسانه پیدا نشد."
    assert view.progress_percent == 100


def test_download_manual_video_preview_persists_file(monkeypatch, tmp_path):
    class DummyResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):  # pragma: no cover - simple iterator
            yield b"chunk-data"

    class DummyRequests:
        def __init__(self):
            self.calls = []

        def get(self, url, timeout=15, stream=True):
            self.calls.append((url, timeout, stream))
            return DummyResponse()

    dummy_requests = DummyRequests()
    monkeypatch.setattr(manual_video_presenter, "requests", dummy_requests)

    presenter = _create_presenter(tmp_path)
    url = "https://cdn.example/assets/video.mp4"

    local_path = presenter._download_manual_video_preview(url, job_id=7)

    assert dummy_requests.calls
    assert local_path is not None
    assert local_path.name == "job-7.mp4"
    assert local_path.read_bytes() == b"chunk-data"


def test_should_download_media_filters_non_http():
    presenter = ManualVideoPresenter(templates=DummyTemplates())

    assert presenter._should_download_media("https://example.com/video.mp4")
    assert not presenter._should_download_media("ftp://example.com/video.mp4")
    assert not presenter._should_download_media("/local/path/video.mp4")
