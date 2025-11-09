"""Tools for assembling short vertical videos with trending audio and Persian captions."""

from __future__ import annotations

import json
import logging
import tempfile
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import arabic_reshaper
import requests
from bidi.algorithm import get_display
from deep_translator import GoogleTranslator
from moviepy.editor import AudioFileClip, ColorClip, CompositeVideoClip, TextClip

from app.logging_utils import JobContext, job_context


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
    ) -> None:
        self.font_path = Path(font_path)
        if not self.font_path.exists():
            raise FileNotFoundError(f"Font not found: {self.font_path}")

        self.width = width
        self.height = height
        self.background_color = background_color
        self.translator = translator or GoogleTranslator(source="auto", target="fa")

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
    # High-level orchestration
    # ------------------------------------------------------------------
    def generate_trend_video(
        self,
        *,
        track: TrendingTrack,
        caption_template: str,
        output_path: Path,
        translate: bool = True,
        job_ctx: JobContext | None = None,
        media_id: str | int | None = None,
        campaign_id: str | int | None = None,
        log_dir: Path | str | None = None,
    ) -> Path:
        """Generate a captioned video for the provided track."""

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

        with context_manager as active_ctx, tempfile.TemporaryDirectory() as temp_dir:
            logger = active_ctx.logger
            audio_path = Path(temp_dir) / "preview.m4a"

            logger.info(
                "download_started",
                extra={
                    "preview_url": track.preview_url,
                    "track_title": track.title,
                    "track_artist": track.artist,
                },
            )
            try:
                self.download_preview(track, destination=audio_path)
            except Exception:
                logger.exception(
                    "download_failed",
                    extra={"preview_url": track.preview_url},
                )
                raise
            logger.info(
                "download_completed",
                extra={"audio_path": str(audio_path)},
            )

            logger.info(
                "render_started",
                extra={
                    "output_path": str(output_path),
                    "caption_text": caption_text,
                },
            )
            try:
                video_path = self.assemble_video(
                    audio_path=audio_path,
                    text=caption_text,
                    output_path=output_path,
                )
            except Exception:
                logger.exception(
                    "render_failed",
                    extra={"output_path": str(output_path)},
                )
                raise
            logger.info(
                "render_completed",
                extra={"video_path": str(video_path)},
            )

            logger.info(
                "upload_started",
                extra={"destination": str(output_path)},
            )
            try:
                if not output_path.exists():
                    raise FileNotFoundError(f"Rendered video not found at {output_path}")
            except Exception:
                logger.exception(
                    "upload_failed",
                    extra={"destination": str(output_path)},
                )
                raise
            logger.info(
                "upload_completed",
                extra={"destination": str(output_path)},
            )

            return video_path

    # ------------------------------------------------------------------
    # Serialization helpers for inspection or caching
    # ------------------------------------------------------------------
    @staticmethod
    def serialize_tracks(tracks: Iterable[TrendingTrack], *, destination: Path) -> Path:
        data = [track.__dict__ for track in tracks]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return destination

