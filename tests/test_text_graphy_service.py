import json
import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.backend.services.text_graphy import (
    CoverrAPIError,
    CoverrVideoSource,
    LyricsProcessingError,
    TextGraphyService,
    TextGraphyDiagnostics,
)


class FakeTranslator:
    def translate(self, text: str) -> str:
        return f"{text}-fa"


class DummyResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class DummyHTTPClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, timeout=10):
        self.calls.append((url, timeout))
        return DummyResponse(self.payload)


class FlakyHTTPClient:
    def __init__(self, payload, failures, exception_type=ConnectionError):
        self.payload = payload
        self.failures = failures
        self.exception_type = exception_type
        self.calls = 0

    def get(self, url, timeout=10):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exception_type("boom")
        return DummyResponse(self.payload)


def _build_payload():
    return {
        "id": "autumn-sun",
        "title": "Autumn Sun",
        "thumbnail": "https://coverr.example/thumb.jpg",
        "preview": "https://coverr.example/preview.mp4",
        "video": {
            "sd": {"mp4": "https://coverr.example/autumn-sd.mp4"},
            "hd": {"mp4": "https://coverr.example/autumn-hd.mp4"},
        },
    }


def test_build_plan_translates_and_spreads_timeline():
    payload = _build_payload()
    http = DummyHTTPClient(payload)
    service = TextGraphyService(http_client=http, translator=FakeTranslator())

    plan = service.build_plan(
        coverr_reference="https://coverr.co/videos/autumn-sun",
        lyrics_text="Line one\nLine two",
        audio_url="https://audio.example/song.mp3",
        audio_duration=120,
    )

    assert http.calls
    url, timeout = http.calls[0]
    assert url.endswith("/autumn-sun")
    assert timeout == 10

    assert plan.video.identifier == "autumn-sun"
    assert plan.video.sources[0] == CoverrVideoSource(
        quality="sd",
        format="mp4",
        url="https://coverr.example/autumn-sd.mp4",
    )

    assert len(plan.lines) == 2
    assert plan.lines[0].translated == "Line one-fa"
    assert plan.lines[0].start == pytest.approx(0.0)
    assert plan.lines[0].end == pytest.approx(60.0)
    assert plan.lines[1].start == pytest.approx(60.0)
    assert plan.lines[1].end == pytest.approx(120.0)

    assert plan.total_duration == pytest.approx(120.0)

    webvtt = plan.as_webvtt()
    assert webvtt.startswith("WEBVTT")
    exported = json.loads(plan.lines_json())
    assert exported[0]["translated"] == "Line one-fa"

    plan_with_diag, diagnostics = service.build_plan_with_diagnostics(
        coverr_reference="autumn-sun",
        lyrics_text="Line one\nLine two",
        audio_url="https://audio.example/song.mp3",
        audio_duration=120,
    )
    assert isinstance(diagnostics, TextGraphyDiagnostics)
    assert diagnostics.stages
    assert diagnostics.stages[0].status == "completed"
    assert diagnostics.token_label.startswith("FakeTranslator")
    assert plan_with_diag.total_duration == plan.total_duration


def test_fetch_coverr_retries_on_connection_error():
    payload = _build_payload()
    http = FlakyHTTPClient(payload, failures=1)
    service = TextGraphyService(
        http_client=http,
        translator=FakeTranslator(),
        request_retries=2,
        retry_backoff=0.0,
    )

    plan = service.build_plan(
        coverr_reference="autumn-sun",
        lyrics_text="Line one\nLine two",
        audio_url=None,
    )

    assert http.calls == 2
    assert plan.video.identifier == "autumn-sun"


def test_fetch_coverr_raises_after_exhausting_retries():
    payload = _build_payload()
    http = FlakyHTTPClient(payload, failures=5)
    service = TextGraphyService(
        http_client=http,
        translator=FakeTranslator(),
        request_retries=1,
        retry_backoff=0.0,
    )

    with pytest.raises(CoverrAPIError):
        service.build_plan(
            coverr_reference="autumn-sun",
            lyrics_text="Line one\nLine two",
            audio_url=None,
        )

    assert http.calls == 2


def test_build_plan_raises_for_empty_lyrics():
    service = TextGraphyService(
        http_client=DummyHTTPClient(_build_payload()),
        translator=FakeTranslator(),
    )

    with pytest.raises(LyricsProcessingError):
        service.build_plan(
            coverr_reference="autumn-sun",
            lyrics_text="\n\n  ",
            audio_url=None,
        )
