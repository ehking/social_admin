import pathlib
import sys
from contextlib import contextmanager
from types import SimpleNamespace

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import shutil

from app.backend.services import trending_video
from app.backend.services.storage import StorageResult
from app.backend.services.trending_video import TrendingTrack, TrendingVideoCreator


DUMMY_DURATION = 4.25


class DummyAudioClip:
    def __init__(self, path: str):
        self.path = path
        self.duration = DUMMY_DURATION


class DummyColorClip:
    def __init__(self, *, size, color):
        self.size = size
        self.color = color
        self.duration = None

    def set_duration(self, duration):
        self.duration = duration
        return self


class DummyCompositeVideoClip:
    def __init__(self, clips):
        self.clips = clips
        self.audio = None
        self.write_args = None

    def set_audio(self, audio):
        self.audio = audio
        return self

    def write_videofile(self, filename, **kwargs):
        pathlib.Path(filename).write_bytes(b"video")
        self.write_args = {"filename": filename, **kwargs}


def test_assemble_video_produces_file_and_metadata(monkeypatch, tmp_path):
    font_path = tmp_path / "dummy-font.ttf"
    font_path.write_text("fake font")
    audio_path = tmp_path / "preview.m4a"
    audio_path.write_bytes(b"audio")
    output_path = tmp_path / "output.mp4"

    created_backgrounds = []
    composite_clips = []
    captured_caption = {}

    monkeypatch.setattr(trending_video, "AudioFileClip", DummyAudioClip)

    def fake_color_clip(size, color):
        clip = DummyColorClip(size=size, color=color)
        created_backgrounds.append(clip)
        return clip

    monkeypatch.setattr(trending_video, "ColorClip", fake_color_clip)

    def fake_composite(clips):
        clip = DummyCompositeVideoClip(clips)
        composite_clips.append(clip)
        return clip

    monkeypatch.setattr(trending_video, "CompositeVideoClip", fake_composite)

    def fake_build_caption(self, text, duration):
        captured_caption["text"] = text
        captured_caption["duration"] = duration
        return SimpleNamespace()

    monkeypatch.setattr(TrendingVideoCreator, "build_caption_clip", fake_build_caption)

    creator = TrendingVideoCreator(font_path=font_path, width=720, height=1280, background_color=(1, 2, 3))

    result = creator.assemble_video(audio_path=audio_path, text="نمونه کپشن", output_path=output_path)

    assert result == output_path
    assert output_path.exists()

    assert captured_caption == {"text": "نمونه کپشن", "duration": DUMMY_DURATION}

    assert created_backgrounds and created_backgrounds[0].size == (720, 1280)
    assert created_backgrounds[0].color == (1, 2, 3)
    assert created_backgrounds[0].duration == DUMMY_DURATION

    assert composite_clips, "CompositeVideoClip should be constructed"
    composite = composite_clips[0]
    assert composite.audio.path == str(audio_path)
    assert composite.write_args is not None
    assert composite.write_args["filename"] == str(output_path)
    assert composite.write_args["fps"] == 30
    assert composite.write_args["codec"] == "libx264"
    assert composite.write_args["audio_codec"] == "aac"
    assert composite.write_args["remove_temp"] is True
    assert composite.write_args["temp_audiofile"].endswith(".temp-audio.m4a")


def test_generate_trend_video_creates_local_copy(monkeypatch, tmp_path):
    font_path = tmp_path / "dummy-font.ttf"
    font_path.write_text("fake font")
    output_path = tmp_path / "export" / "custom-name.mp4"
    track = TrendingTrack(title="نمونه", artist="خواننده", preview_url="https://example.com/preview.m4a")

    class DummyWorker:
        @contextmanager
        def temporary_directory(self, *, prefix: str = "job-"):
            temp_dir = tmp_path / f"{prefix}temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            try:
                yield temp_dir
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

    class DummyStorageService:
        def __init__(self):
            self.calls = []

        def upload_file(self, source, *, destination_name=None, content_type=None):
            path = pathlib.Path(source)
            self.calls.append(
                {
                    "source": path,
                    "destination_name": destination_name,
                    "content_type": content_type,
                }
            )
            return StorageResult(key=destination_name or path.name, url=f"http://storage/{path.name}")

        def delete_object(self, key):  # pragma: no cover - interface requirement only
            raise NotImplementedError

    dummy_worker = DummyWorker()
    storage_service = DummyStorageService()

    def fake_download_preview(self, track, *, destination):
        destination.write_bytes(b"audio-bytes")
        return destination

    def fake_assemble(self, audio_path, text, *, output_path):
        assert audio_path.read_bytes() == b"audio-bytes"
        output_path.write_bytes(b"video-bytes")
        return output_path

    monkeypatch.setattr(TrendingVideoCreator, "download_preview_sync", fake_download_preview)
    monkeypatch.setattr(TrendingVideoCreator, "assemble_video", fake_assemble)

    creator = TrendingVideoCreator(
        font_path=font_path,
        worker=dummy_worker,
        storage_service=storage_service,
        width=1080,
        height=1920,
    )

    result = creator.generate_trend_video(
        track=track,
        caption_template="ترند داغ: {track}",
        output_path=output_path,
        translate=False,
    )

    assert storage_service.calls, "upload_file should be invoked"
    upload_call = storage_service.calls[0]
    assert upload_call["destination_name"] == "custom-name.mp4"
    assert upload_call["content_type"] == "video/mp4"
    assert upload_call["source"].name == "custom-name.mp4"

    assert output_path.exists()
    assert output_path.read_bytes() == b"video-bytes"

    assert result.storage_key == "custom-name.mp4"
    assert result.storage_url == "http://storage/custom-name.mp4"
    assert result.job_media_id is None
    assert result.local_path == output_path.resolve()


def test_default_job_name_handles_missing_metadata():
    track = TrendingTrack(title="", artist="", preview_url="")

    job_name = TrendingVideoCreator._default_job_name(track)

    assert job_name.startswith("trend-video:")
    assert job_name != "trend-video:"


def test_display_name_falls_back_to_preview_url():
    track = TrendingTrack(title="", artist="", preview_url="https://example")

    assert track.display_name == "https://example"
