"""Tools for assembling short vertical videos with trending audio and Persian captions."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
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

LOGGER = logging.getLogger(__name__)

_CONCURRENCY_ENV_VAR = "TRENDING_PREVIEW_MAX_CONCURRENCY"
_DEFAULT_MAX_CONCURRENCY = 3


def _resolve_max_concurrency() -> int:
    """Read the preview download concurrency from the environment."""

    raw_value = os.getenv(_CONCURRENCY_ENV_VAR)
    if raw_value is None:
        return _DEFAULT_MAX_CONCURRENCY

    try:
        value = int(raw_value)
    except ValueError:
        LOGGER.warning(
            "Invalid value for %s=%s. Falling back to default of %s.",
            _CONCURRENCY_ENV_VAR,
            raw_value,
            _DEFAULT_MAX_CONCURRENCY,
        )
        return _DEFAULT_MAX_CONCURRENCY

    if value < 1:
        LOGGER.warning(
            "Configured %s=%s is less than 1. Falling back to default of %s.",
            _CONCURRENCY_ENV_VAR,
            raw_value,
            _DEFAULT_MAX_CONCURRENCY,
        )
        return _DEFAULT_MAX_CONCURRENCY

    return value


def _download_preview_to_path(track: "TrendingTrack", destination: Path) -> Path:
    """Synchronous helper that streams a preview file to ``destination``."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Downloading preview for \"%s\"", track.display_name)
    with requests.get(track.preview_url, timeout=10, stream=True) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
    return destination


class PreviewDownloadManager:
    """Coordinate preview downloads with a configurable concurrency limit."""

    def __init__(self, *, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    async def download(self, track: "TrendingTrack", *, destination: Path) -> Path:
        """Download ``track``'s preview to ``destination`` respecting the limit."""

        async with self._semaphore:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                _download_preview_to_path,
                track,
                destination,
            )

    def download_sync(self, track: "TrendingTrack", *, destination: Path) -> Path:
        """Synchronous wrapper that executes :meth:`download` on an event loop."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop in this thread – safe to create a temporary one.
            return asyncio.run(self.download(track, destination=destination))

        raise RuntimeError(
            "download_sync() cannot be used while the current event loop is running. "
            "Use the async download() API instead."
        )


_preview_download_manager: Optional[PreviewDownloadManager] = None


def get_preview_download_manager() -> PreviewDownloadManager:
    """Return a module-level :class:`PreviewDownloadManager` singleton."""

    global _preview_download_manager
    if _preview_download_manager is None:
        _preview_download_manager = PreviewDownloadManager(
            max_concurrency=_resolve_max_concurrency()
        )
    return _preview_download_manager


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
    async def download_preview(track: TrendingTrack, *, destination: Path) -> Path:
        """Download the audio preview for a track using the shared manager."""

        manager = get_preview_download_manager()
        return await manager.download(track, destination=destination)

    @staticmethod
    def download_preview_sync(track: TrendingTrack, *, destination: Path) -> Path:
        """Synchronous helper that leverages the shared download manager."""

        manager = get_preview_download_manager()
        return manager.download_sync(track, destination=destination)

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
            self.download_preview_sync(track, destination=audio_path)
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

