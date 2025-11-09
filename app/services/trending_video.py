"""Tools for assembling short vertical videos with trending audio and Persian captions."""

from __future__ import annotations

import json
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional

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

from app.config import get_settings

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


def _is_retriable_error(error: requests.exceptions.RequestException) -> bool:
    """Determine whether the raised error is safe to retry."""

    non_retriable = (
        requests.exceptions.InvalidURL,
        requests.exceptions.InvalidSchema,
        requests.exceptions.MissingSchema,
        requests.exceptions.URLRequired,
    )
    if isinstance(error, non_retriable):
        return False

    if isinstance(error, requests.exceptions.HTTPError):
        response = error.response
        if response is None:
            return True
        status = response.status_code
        # Retry on rate limiting and server errors only.
        return status == 429 or status >= 500

    return True


def request_with_backoff(
    url: str,
    *,
    method: Callable[..., requests.Response] = requests.get,
    max_attempts: Optional[int] = None,
    min_backoff: Optional[float] = None,
    max_backoff: Optional[float] = None,
    **request_kwargs: Any,
) -> requests.Response:
    """Execute an HTTP request with exponential backoff and logging."""

    settings = get_settings().trending_request_backoff
    attempts_limit = max_attempts or settings.max_attempts
    backoff_min = min_backoff if min_backoff is not None else settings.min_seconds
    backoff_max = max_backoff if max_backoff is not None else settings.max_seconds

    attempts_limit = max(1, attempts_limit)
    backoff_min = max(0.0, backoff_min)
    backoff_max = max(backoff_min if backoff_min > 0 else 0.0, backoff_max)

    attempt = 1
    method_name = getattr(method, "__name__", str(method))
    while True:
        LOGGER.debug("Attempt %d/%d for %s %s", attempt, attempts_limit, method_name.upper(), url)
        try:
            response = method(url, **request_kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as exc:
            retriable = _is_retriable_error(exc)
            if not retriable:
                LOGGER.error("Non-retriable error calling %s %s: %s", method_name.upper(), url, exc)
                raise

            if attempt >= attempts_limit:
                LOGGER.error(
                    "Request %s %s failed after %d attempts: %s",
                    method_name.upper(),
                    url,
                    attempt,
                    exc,
                )
                raise

            sleep_time = min(backoff_max, backoff_min * (2 ** (attempt - 1))) if backoff_min > 0 else 0
            if sleep_time > 0:
                LOGGER.warning(
                    "Attempt %d/%d for %s %s failed: %s. Retrying in %.2f seconds.",
                    attempt,
                    attempts_limit,
                    method_name.upper(),
                    url,
                    exc,
                    sleep_time,
                )
                time.sleep(sleep_time)
            else:
                LOGGER.warning(
                    "Attempt %d/%d for %s %s failed: %s. Retrying immediately.",
                    attempt,
                    attempts_limit,
                    method_name.upper(),
                    url,
                    exc,
                )
            attempt += 1


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
        with request_with_backoff(url, timeout=10) as response:
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
        LOGGER.info("Downloading preview for \"%s\"", track.display_name)
        with request_with_backoff(track.preview_url, timeout=10, stream=True) as response:
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

    def assemble_video(self, audio_path: Path, text: str, *, output_path: Path) -> Path:
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
        LOGGER.info("Rendering video to %s", output_path)
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
    ) -> Path:
        """Generate a captioned video for the provided track."""

        if translate:
            caption_text = self.translate_to_persian(caption_template.format(track=track.display_name))
        else:
            caption_text = self._normalize_persian_text(caption_template.format(track=track.display_name))

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "preview.m4a"
            self.download_preview(track, destination=audio_path)
            return self.assemble_video(audio_path=audio_path, text=caption_text, output_path=output_path)

    # ------------------------------------------------------------------
    # Serialization helpers for inspection or caching
    # ------------------------------------------------------------------
    @staticmethod
    def serialize_tracks(tracks: Iterable[TrendingTrack], *, destination: Path) -> Path:
        data = [track.__dict__ for track in tracks]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return destination

