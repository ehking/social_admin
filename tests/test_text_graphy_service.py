import json
import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.backend.services.text_graphy import (
    CoverrVideoSource,
    LyricsProcessingError,
    TextGraphyService,
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
