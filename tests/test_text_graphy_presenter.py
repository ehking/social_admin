import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.backend.services.text_graphy import (
    CoverrVideoMetadata,
    CoverrVideoSource,
    TextGraphyLine,
    TextGraphyPlan,
)
from app.ui.app_presenters.text_graphy_presenter import TextGraphyPresenter


class DummyTemplates:
    def __init__(self):
        self.calls = []

    def TemplateResponse(self, template_name, context):
        self.calls.append((template_name, context))
        return context


class StubTextGraphyService:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def build_plan(self, **kwargs):
        self.calls.append(kwargs)
        return self.plan


@pytest.fixture
def sample_plan():
    video = CoverrVideoMetadata(
        identifier="sample",
        title="Sample Video",
        thumbnail_url="https://coverr.example/thumb.jpg",
        preview_url="https://coverr.example/preview.mp4",
        sources=(
            CoverrVideoSource(
                quality="sd",
                format="mp4",
                url="https://coverr.example/sample.mp4",
            ),
        ),
    )
    lines = (
        TextGraphyLine(index=0, original="Line 1", translated="خط یک", start=0.0, end=4.0),
        TextGraphyLine(index=1, original="Line 2", translated="خط دو", start=4.0, end=8.0),
    )
    return TextGraphyPlan(video=video, lines=lines, audio_url="https://audio.example/song.mp3", total_duration=8.0)


def test_create_text_graphy_renders_context(sample_plan):
    templates = DummyTemplates()
    service = StubTextGraphyService(sample_plan)
    presenter = TextGraphyPresenter(templates, service)

    request = SimpleNamespace()
    user = SimpleNamespace()

    context = presenter.create_text_graphy(
        request=request,
        user=user,
        coverr_reference="sample",
        music_url="https://audio.example/song.mp3",
        music_duration="01:20",
        lyrics_text="Line 1\nLine 2",
    )

    assert templates.calls
    template_name, rendered_context = templates.calls[-1]
    assert template_name == "text_graphy.html"
    assert rendered_context["info"] == "پیش‌نمایش تکس گرافی با موفقیت ساخته شد."
    assert rendered_context["result"]["video"].identifier == "sample"
    assert "lines_json" in rendered_context["result"]

    assert service.calls
    call = service.calls[0]
    assert call["audio_duration"] == pytest.approx(80.0)


def test_create_text_graphy_with_invalid_duration_sets_error(sample_plan):
    templates = DummyTemplates()
    service = StubTextGraphyService(sample_plan)
    presenter = TextGraphyPresenter(templates, service)

    request = SimpleNamespace()
    user = SimpleNamespace()

    context = presenter.create_text_graphy(
        request=request,
        user=user,
        coverr_reference="sample",
        music_url=None,
        music_duration="invalid",
        lyrics_text="Line 1",
    )

    assert templates.calls
    _, rendered_context = templates.calls[-1]
    assert rendered_context["error"].startswith("فرمت مدت زمان")
    assert service.calls == []


def test_parse_duration_formats():
    templates = DummyTemplates()
    # The service is not used for this test; create a dummy stub.
    presenter = TextGraphyPresenter(templates, StubTextGraphyService(None))

    assert presenter._parse_duration("90") == 90.0
    assert presenter._parse_duration("01:30") == pytest.approx(90.0)
    assert presenter._parse_duration("01:02:03") == pytest.approx(3723.0)

    with pytest.raises(ValueError):
        presenter._parse_duration("01:02:03:04")
