"""Tools for assembling short vertical videos with trending audio and Persian captions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import arabic_reshaper
import requests
from bidi.algorithm import get_display
from deep_translator import GoogleTranslator
from moviepy.editor import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    TextClip,
)
from sqlalchemy.orm import Session

from app import models
from app.config import AppSettings, get_settings

from .storage import StorageResult, StorageService, StorageError, get_storage_service
from .worker import Worker

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TrendingTrack:
    """Metadata for a trending music track."""

    title: str
    artist: str
    preview_url: str

    @property
    def display_name(self) -> str:
        return f"{self.title} — {self.artist}" if self.artist else self.title


@dataclass(slots=True)
class GeneratedMedia:
    """Result metadata returned after generating and uploading a video."""

    storage_key: str
    storage_url: str | None
    job_media_id: int | None = None


class TrendingVideoCreator:
    """High level helper for creating captioned videos with trending audio previews."""

    def __init__(
        self,
        *,
        font_path: Path,
        width: int = 1080,
        height: int = 1920,
        background_color: tuple[int, int, int] = (0, 0, 0),
        translator: Optional[GoogleTranslator] = None,
        worker: Worker | None = None,
        storage_service: StorageService | None = None,
        db_session: Session | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        self.font_path = Path(font_path)
        if not self.font_path.exists():
            raise FileNotFoundError(f"Font not found: {self.font_path}")

        self.width = width
        self.height = height
        self.background_color = background_color
        self.translator = translator or GoogleTranslator(source="auto", target="fa")
        self.settings = settings or get_settings()
        self.worker = worker or Worker(settings=self.settings)
        self.storage_service = storage_service or get_storage_service(self.settings)
        self.db_session = db_session

    # ------------------------------------------------------------------
    # Data acquisition helpers
    # ------------------------------------------------------------------
    @staticmethod
    def fetch_trending_tracks(*, country: str = "us", limit: int = 10) -> List[TrendingTrack]:
        """Fetch trending songs from the Apple Music RSS feed."""

        url = f"https://itunes.apple.com/{country}/rss/topsongs/limit={limit}/json"
        LOGGER.debug("Fetching top songs from %s", url)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()

        entries: Iterable[dict] = payload.get("feed", {}).get("entry", [])
        tracks: List[TrendingTrack] = []
        for entry in entries:
            title = entry.get("im:name", {}).get("label", "")
            artist = entry.get("im:artist", {}).get("label", "")
            preview_url = ""
            for link in entry.get("link", []):
                attributes = link.get("attributes", {})
                if attributes.get("type") == "audio/x-m4a" and "href" in attributes:
                    preview_url = attributes["href"]
                    break
            if title and preview_url:
                tracks.append(TrendingTrack(title=title, artist=artist, preview_url=preview_url))

        return tracks

    @staticmethod
    def download_preview(track: TrendingTrack, *, destination: Path) -> Path:
        """Download the audio preview for a track."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(track.preview_url, timeout=10, stream=True) as response:
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        handle.write(chunk)
        return destination

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_persian_text(text: str) -> str:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)

    def translate_to_persian(self, text: str) -> str:
        translated = self.translator.translate(text)
        LOGGER.debug("Translated text: %s", translated)
        return self._normalize_persian_text(translated)

    # ------------------------------------------------------------------
    # Video rendering
    # ------------------------------------------------------------------
    def build_caption_clip(self, text: str, duration: float) -> TextClip:
        normalized = self._normalize_persian_text(text)
        return (
            TextClip(
                normalized,
                font=str(self.font_path),
                fontsize=80,
                color="white",
                method="caption",
                size=(self.width - 120, None),
            )
            .set_duration(duration)
            .set_position("center")
        )

    def assemble_video(
        self,
        audio_path: Path,
        text: str,
        *,
        output_path: Path,
    ) -> Path:
        """Create a simple vertical video with the provided audio and caption."""

        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        background = ColorClip(
            size=(self.width, self.height),
            color=self.background_color,
        ).set_duration(duration)

        caption = self.build_caption_clip(text=text, duration=duration)
        video = CompositeVideoClip([background, caption]).set_audio(audio_clip)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        video.write_videofile(  # type: ignore[no-untyped-call]
            str(output_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=str(output_path.with_suffix(".temp-audio.m4a")),
            remove_temp=True,
        )
        return output_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize_filename(name: str) -> str:
        safe_chars = [char if char.isalnum() or char in {"-", "_"} else "-" for char in name]
        sanitized = "".join(safe_chars).strip("-_")
        return sanitized or "trend-video"

    @classmethod
    def _derive_output_name(cls, output_path: Path | None, track: TrendingTrack) -> str:
        if output_path:
            base = Path(output_path).stem
        else:
            base = track.title or "trend-video"
            if track.artist:
                base = f"{base}-{track.artist}"
        sanitized = cls._sanitize_filename(base)
        return f"{sanitized}.mp4"

    @staticmethod
    def _default_job_name(track: TrendingTrack) -> str:
        return f"trend-video:{track.display_name}"

    def _record_job_media(self, *, job_name: str, upload_result: StorageResult) -> models.JobMedia:
        if not self.db_session:
            raise RuntimeError("Database session is required to record job media")
        job_media = models.JobMedia(
            job_name=job_name,
            media_type="video/mp4",
            storage_key=upload_result.key,
            storage_url=upload_result.url,
        )
        self.db_session.add(job_media)
        return job_media

    # ------------------------------------------------------------------
    # High-level orchestration
    # ------------------------------------------------------------------
    def generate_trend_video(
        self,
        *,
        track: TrendingTrack,
        caption_template: str,
        output_path: Path | None = None,
        translate: bool = True,
        job_name: str | None = None,
    ) -> GeneratedMedia:
        """Generate, upload, and register a captioned video for the provided track."""

        caption_value = caption_template.format(track=track.display_name)
        if translate:
            caption_text = self.translate_to_persian(caption_value)
        else:
            caption_text = self._normalize_persian_text(caption_value)

        context_manager = (
            nullcontext(job_ctx)
            if job_ctx is not None
            else job_context(media_id=media_id, campaign_id=campaign_id, log_dir=log_dir)
        )

        resolved_job_name = job_name or self._default_job_name(track)
        output_name = self._derive_output_name(output_path, track)

        upload_result: StorageResult | None = None
        job_media_id: int | None = None

        with self.worker.temporary_directory(prefix="trend-video-") as temp_dir:
            audio_path = Path(temp_dir) / "preview.m4a"
            video_path = Path(temp_dir) / output_name
            self.download_preview(track, destination=audio_path)
            self.assemble_video(audio_path=audio_path, text=caption_text, output_path=video_path)

            try:
                upload_result = self.storage_service.upload_file(
                    video_path,
                    destination_name=output_name,
                    content_type="video/mp4",
                )
                LOGGER.info(
                    "Uploaded generated video for %s to storage key %s", track.display_name, upload_result.key
                )
                if self.db_session:
                    job_media = self._record_job_media(job_name=resolved_job_name, upload_result=upload_result)
                    self.db_session.commit()
                    job_media_id = job_media.id
            except Exception:
                LOGGER.exception("Failed to persist generated video for job %s", resolved_job_name)
                if self.db_session:
                    self.db_session.rollback()
                if upload_result:
                    try:
                        self.storage_service.delete_object(upload_result.key)
                    except Exception:
                        LOGGER.warning(
                            "Failed to delete uploaded object %s during rollback", upload_result.key, exc_info=True
                        )
                raise
            finally:
                try:
                    video_path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Failed to remove temporary video file %s", video_path, exc_info=True)

        if not upload_result:
            raise StorageError("Upload did not complete for the generated video")

        return GeneratedMedia(
            storage_key=upload_result.key,
            storage_url=upload_result.url,
            job_media_id=job_media_id,
        )

    # ------------------------------------------------------------------
    # Serialization helpers for inspection or caching
    # ------------------------------------------------------------------
    @staticmethod
    def serialize_tracks(tracks: Iterable[TrendingTrack], *, destination: Path) -> Path:
        data = [track.__dict__ for track in tracks]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return destination

