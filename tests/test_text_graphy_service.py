import json
import logging
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


class SequencedHTTPClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, timeout=10):
        self.calls.append((url, timeout))
        if not self._responses:
            raise AssertionError("No more responses configured for SequencedHTTPClient")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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


def test_extract_sources_supports_format_grouping():
    payload = _build_payload()
    payload["video"] = {
        "mp4": {
            "sd": "https://coverr.example/autumn-sd.mp4",
            "hd": "https://coverr.example/autumn-hd.mp4",
        },
        "webm": {
            "sd": "https://coverr.example/autumn-sd.webm",
        },
    }

    http = DummyHTTPClient(payload)
    service = TextGraphyService(http_client=http, translator=FakeTranslator())

    plan = service.build_plan(
        coverr_reference="autumn-sun",
        lyrics_text="Line one\nLine two",
        audio_url=None,
    )

    quality_format_pairs = {(source.quality, source.format) for source in plan.video.sources}

    assert ("sd", "mp4") in quality_format_pairs
    assert ("hd", "mp4") in quality_format_pairs

    mp4_sources = [source for source in plan.video.sources if source.format == "mp4"]
    assert mp4_sources
    assert all(source.mime_type == "video/mp4" for source in mp4_sources)


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
    assert plan.video.sources[0].mime_type == "video/mp4"

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


def test_service_initialises_without_optional_translator(monkeypatch):
    payload = _build_payload()
    http = DummyHTTPClient(payload)
    monkeypatch.setattr("app.backend.services.text_graphy.GoogleTranslator", None)

    service = TextGraphyService(http_client=http)

    plan = service.build_plan(
        coverr_reference="https://coverr.co/videos/autumn-sun",
        lyrics_text="Line one\nLine two",
        audio_url="https://audio.example/song.mp3",
        audio_duration=120,
    )

    assert [line.translated for line in plan.lines] == ["Line one", "Line two"]
    assert service._token_label == "مترجم خودکار فعال نیست"
    assert service._token_hint is None


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


def test_exception_metadata_reports_origin():
    service = TextGraphyService(
        http_client=DummyHTTPClient(_build_payload()),
        translator=FakeTranslator(),
    )

    def _trigger_error():
        raise ValueError("boom")

    with pytest.raises(ValueError) as caught:
        _trigger_error()

    metadata = service._exception_metadata(caught.value)
    assert metadata["error_type"] == "ValueError"
    assert metadata["error_origin_function"] == "_trigger_error"
    assert metadata["error_origin_line"] > 0


class ErroringResponse:
    def __init__(self, status_code=500, text="boom"):
        self.status_code = status_code
        self.text = text

    def json(self):  # pragma: no cover - should not be called
        raise AssertionError("json() should not be invoked for error responses")


class ErroringHTTPClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, timeout=10):
        self.calls.append((url, timeout))
        return self.response


def test_service_logs_include_location_in_message(caplog):
    response = ErroringResponse(status_code=404, text="missing")
    http = ErroringHTTPClient(response)
    service = TextGraphyService(http_client=http, translator=FakeTranslator())

    with caplog.at_level(logging.ERROR, logger="app.backend.services.text_graphy"):
        with pytest.raises(CoverrAPIError):
            service.fetch_coverr_video("missing-video")

    assert http.calls
    error_logs = [record.message for record in caplog.records if record.levelno >= logging.ERROR]
    assert any("service_location=" in message for message in error_logs)


def test_fetch_coverr_fallback_when_primary_endpoint_fails():
    payload = _build_payload()
    error_response = ErroringResponse(status_code=404, text="missing")
    http = SequencedHTTPClient([error_response, DummyResponse(payload)])
    service = TextGraphyService(http_client=http, translator=FakeTranslator())

    video = service.fetch_coverr_video("cozy-diner-scene-with-neon-eat-sign")

    assert len(http.calls) == 2
    first_url, _ = http.calls[0]
    second_url, _ = http.calls[1]
    assert first_url.startswith("https://api.coverr.co/videos/")
    assert second_url.startswith("https://coverr.co/api/v3/videos")
    assert video.identifier == payload["id"]


def test_fetch_coverr_exhaustive_fallback_to_slug_query():
    payload = _build_payload()
    error_responses = [ErroringResponse(status_code=404, text="missing") for _ in range(7)]
    http = SequencedHTTPClient([*error_responses, DummyResponse(payload)])
    service = TextGraphyService(http_client=http, translator=FakeTranslator())

    video = service.fetch_coverr_video("cozy-diner-scene-with-neon-eat-sign")

    assert len(http.calls) == 8
    urls = [url for url, _ in http.calls]
    assert urls[0].startswith("https://api.coverr.co/videos/")
    assert any(url.startswith("https://coverr.co/api/v3/videos?slug=") for url in urls)
    assert urls[-1].startswith("https://coverr.co/api/videos?slug=")
    assert video.identifier == payload["id"]
