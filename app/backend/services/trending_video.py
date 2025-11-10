"""Tools for assembling short vertical videos with trending audio and Persian captions."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

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

from .. import models
from ..config import AppSettings, get_settings
from ..http_logging import log_request_failure, log_request_start, log_request_success
from ..logging_utils import job_context

from .storage import StorageResult, StorageService, StorageError, get_storage_service
from .worker import Worker


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
    started_at = log_request_start("GET", track.preview_url, resource="trending_preview")
    try:
        response = requests.get(track.preview_url, timeout=10, stream=True)
        response.raise_for_status()
    except Exception as exc:
        log_request_failure("GET", track.preview_url, started_at=started_at, error=exc)
        raise

    log_request_success(
        "GET",
        track.preview_url,
        status=response.status_code,
        started_at=started_at,
        resource="trending_preview",
    )

    with response:
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
class GeneratedMedia:
    """Details about a generated media artifact and its storage metadata."""

    storage_key: str
    storage_url: str | None
    job_media_id: int | None
    local_path: Path | None = None
    log_path: Path | None = None


@contextmanager
def _log_stage(
    logger: logging.Logger | logging.LoggerAdapter,
    stage: str,
    **extra: Any,
) -> Iterator[Dict[str, Any]]:
    """Log the lifecycle of a workflow stage with structured metadata."""

    payload: Dict[str, Any] = {"stage": stage, **extra}
    logger.info("stage_started", extra=payload)
    try:
        yield payload
    except Exception:
        logger.exception("stage_failed", extra=payload)
        raise
    else:
        logger.info("stage_completed", extra=payload)


@dataclass(slots=True)
class TrendingTrack:
    """Metadata for a trending music track."""

    title: str
    artist: str
    preview_url: str

    @property
    def display_name(self) -> str:
        """Return a human-friendly name for the track."""

        title = (self.title or "").strip()
        artist = (self.artist or "").strip()

        if title and artist:
            return f"{title} — {artist}"
        if title:
            return title
        if artist:
            return artist

        preview = (self.preview_url or "").strip()
        if preview:
            return preview

        return "Unknown Track"


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
        started_at = log_request_start(
            method_name,
            url,
            attempt=attempt,
            max_attempts=attempts_limit,
        )
        try:
            response = method(url, **request_kwargs)
            response.raise_for_status()
            log_request_success(
                method_name,
                url,
                status=response.status_code,
                started_at=started_at,
                attempt=attempt,
                max_attempts=attempts_limit,
            )
            return response
        except requests.exceptions.RequestException as exc:
            log_request_failure(
                method_name,
                url,
                started_at=started_at,
                error=exc,
                attempt=attempt,
                max_attempts=attempts_limit,
                status=getattr(getattr(exc, "response", None), "status_code", None),
            )
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
        """Build a deterministic job name for generated media."""

        display_name = (track.display_name or "").strip()
        if not display_name:
            for candidate in (track.title, track.artist, track.preview_url):
                candidate = (candidate or "").strip()
                if candidate:
                    display_name = candidate
                    break

        sanitized = TrendingVideoCreator._sanitize_filename(display_name)
        return f"trend-video:{sanitized}"

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

        resolved_job_name = job_name or self._default_job_name(track)
        output_name = self._derive_output_name(output_path, track)

        upload_result: StorageResult | None = None
        job_media_id: int | None = None
        local_result_path: Path | None = None
        generated_media: GeneratedMedia | None = None

        extra_context = {
            "job_name": resolved_job_name,
            "track_display_name": track.display_name,
            "track_title": track.title,
            "track_artist": track.artist,
            "track_preview_url": track.preview_url,
            "output_name": output_name,
            "translate": translate,
        }

        with job_context(extra_context=extra_context) as log_ctx:
            job_logger = log_ctx.logger

            job_logger.info(
                "caption_resolved",
                extra={
                    "stage": "prepare_caption",
                    "caption_template": caption_template,
                    "caption_value": caption_value,
                },
            )

            with self.worker.temporary_directory(prefix="trend-video-") as temp_dir:
                temp_dir = Path(temp_dir)
                job_logger.info(
                    "worker_directory_ready",
                    extra={"stage": "prepare_workspace", "path": str(temp_dir)},
                )

                audio_path = temp_dir / "preview.m4a"
                with _log_stage(
                    job_logger,
                    "download_preview",
                    preview_url=track.preview_url,
                    destination=str(audio_path),
                ):
                    self.download_preview_sync(track, destination=audio_path)

                render_path = temp_dir / output_name
                with _log_stage(
                    job_logger,
                    "render_video",
                    destination=str(render_path),
                ):
                    self.assemble_video(
                        audio_path=audio_path,
                        text=caption_text,
                        output_path=render_path,
                    )

                with _log_stage(
                    job_logger,
                    "upload_video",
                    destination_name=output_name,
                ) as upload_payload:
                    upload_result = self.storage_service.upload_file(
                        render_path,
                        destination_name=output_name,
                        content_type="video/mp4",
                    )
                    upload_payload["storage_key"] = upload_result.key
                    upload_payload["storage_url"] = upload_result.url

                if self.db_session:
                    with _log_stage(
                        job_logger,
                        "record_job_media",
                        job_name=resolved_job_name,
                    ) as media_payload:
                        job_media = self._record_job_media(
                            job_name=resolved_job_name,
                            upload_result=upload_result,
                        )
                        self.db_session.flush()
                        self.db_session.commit()
                        job_media_id = job_media.id
                        media_payload["job_media_id"] = job_media_id
                        log_ctx.logger.extra["job_media_id"] = job_media_id  # type: ignore[attr-defined]
                        log_ctx.media_id = job_media_id

                if output_path is not None:
                    with _log_stage(
                        job_logger,
                        "persist_local_copy",
                        destination=str(output_path),
                    ) as copy_payload:
                        final_path = Path(output_path).expanduser()
                        if not final_path.is_absolute():
                            final_path = (Path.cwd() / final_path).resolve()
                        else:
                            final_path = final_path.resolve()
                        final_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(render_path, final_path)
                        local_result_path = final_path
                        copy_payload["local_path"] = str(final_path)

            if upload_result is None:
                job_logger.error(
                    "missing_upload_result",
                    extra={"stage": "complete", "reason": "storage_service_returned_none"},
                )
                raise StorageError("Failed to upload generated video")

            job_logger.info(
                "job_succeeded",
                extra={
                    "stage": "complete",
                    "storage_key": upload_result.key,
                    "storage_url": upload_result.url,
                    "job_media_id": job_media_id,
                    "local_path": str(local_result_path) if local_result_path else None,
                    "log_path": str(log_ctx.log_path),
                },
            )

            generated_media = GeneratedMedia(
                storage_key=upload_result.key,
                storage_url=upload_result.url,
                job_media_id=job_media_id,
                local_path=local_result_path,
                log_path=log_ctx.log_path,
            )

        if generated_media is None:  # pragma: no cover - defensive
            raise StorageError("Trend video generation did not produce a result")

        return generated_media

    # ------------------------------------------------------------------
    # Serialization helpers for inspection or caching
    # ------------------------------------------------------------------
    @staticmethod
    def serialize_tracks(tracks: Iterable[TrendingTrack], *, destination: Path) -> Path:
        data = [track.__dict__ for track in tracks]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return destination

