"""Presenter for the Text Graphy experience."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.backend.services.text_graphy import (
    CoverrAPIError,
    LyricsProcessingError,
    TextGraphyPlan,
    TextGraphyDiagnostics,
    TextGraphyProcessingStage,
    TextGraphyService,
    TextGraphyServiceError,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TextGraphyTokenUsage:
    """Represents a relevant service token for the Text Graphy flow."""

    name: str
    key: str
    endpoint_url: Optional[str] = None
    is_active: bool = False


@dataclass(slots=True)
class TextGraphyDownloads:
    """Represents downloadable artifacts generated from a Text Graphy plan."""

    webvtt_path: Path
    lines_json_path: Path
    webvtt_url: str
    lines_json_url: str


@dataclass(slots=True)
class TextGraphyFormState:
    """Represents the submitted values of the Text Graphy form."""

    coverr_reference: str
    music_url: str
    music_duration: str
    lyrics_text: str
    info: Optional[str] = None
    error: Optional[str] = None
    plan: Optional[TextGraphyPlan] = None
    downloads: Optional[TextGraphyDownloads] = None
    stages: Optional[tuple[TextGraphyProcessingStage, ...]] = None
    token_label: Optional[str] = None
    token_hint: Optional[str] = None
    token_usage: Optional[tuple[TextGraphyTokenUsage, ...]] = None


DEFAULT_LYRICS = (
    "In moonlit nights we wander far\n"
    "Chasing echoes of who we are\n"
    "Hearts awake in silent gleam\n"
    "Writing dreams on silver stream"
)
DEFAULT_COVERR_REFERENCE = "sunset-over-the-lake"
DEFAULT_MUSIC_URL = "https://cdn.coverr.co/audio/coverr-ambient-rising.mp3"
DEFAULT_MUSIC_DURATION = "02:00"


class TextGraphyPresenter:
    """Prepare the template data for the Text Graphy page."""

    def __init__(
        self,
        templates: Jinja2Templates,
        service: TextGraphyService,
    ) -> None:
        self.templates = templates
        self.service = service
        self.logger = logging.getLogger("app.ui.text_graphy")
        self.download_storage_dir = Path("app/ui/static/text_graphy")
        self.download_url_prefix = "/static/text_graphy"

    def render(
        self,
        request: Request,
        user,
        form_state: Optional[TextGraphyFormState] = None,
        token_usage: Optional[Sequence[TextGraphyTokenUsage]] = None,
    ):
        state = form_state or self._default_state()
        if token_usage is not None:
            state.token_usage = tuple(token_usage)
            if state.token_hint is None and token_usage:
                state.token_hint = "توکن‌های فعال از بخش تنظیمات بارگذاری شده‌اند."
        result_payload = (
            self._plan_to_payload(state.plan, state.downloads)
            if state.plan
            else None
        )
        context = {
            "request": request,
            "user": user,
            "active_page": "text_graphy",
            "form_state": state,
            "result": result_payload,
            "info": state.info,
            "error": state.error,
            "stages": state.stages,
            "token_label": state.token_label,
            "token_hint": state.token_hint,
            "token_usage": state.token_usage,
        }
        return self.templates.TemplateResponse("text_graphy.html", context)

    def create_text_graphy(
        self,
        request: Request,
        user,
        *,
        coverr_reference: str,
        music_url: Optional[str],
        music_duration: Optional[str],
        lyrics_text: str,
        token_usage: Optional[Sequence[TextGraphyTokenUsage]] = None,
    ):
        duration_seconds: Optional[float] = None
        error: Optional[str] = None
        info: Optional[str] = None
        plan: Optional[TextGraphyPlan] = None
        downloads: Optional[TextGraphyDownloads] = None
        diagnostics: Optional[TextGraphyDiagnostics] = None

        try:
            duration_seconds = self._parse_duration(music_duration)
        except ValueError as exc:
            error = "فرمت مدت زمان موزیک معتبر نیست. از قالب mm:ss یا ثانیه استفاده کنید."
            self._log_text_graphy_error(
                "Invalid audio duration provided for Text Graphy submission",
                error=exc,
                coverr_reference=coverr_reference,
                level=logging.WARNING,
            )

        if error is None:
            try:
                plan, diagnostics = self.service.build_plan_with_diagnostics(
                    coverr_reference=coverr_reference,
                    lyrics_text=lyrics_text,
                    audio_url=music_url if music_url else None,
                    audio_duration=duration_seconds,
                )
                info = "پیش‌نمایش تکس گرافی با موفقیت ساخته شد."
                try:
                    downloads = self._persist_plan_artifacts(plan)
                except Exception as exc:  # pragma: no cover - defensive for IO errors
                    self._log_text_graphy_error(
                        "Failed to persist Text Graphy artifacts",
                        error=exc,
                        coverr_reference=coverr_reference,
                        diagnostics=diagnostics,
                        level=logging.ERROR,
                    )
            except CoverrAPIError as exc:
                diagnostics = getattr(exc, "diagnostics", diagnostics)
                cause = exc.__cause__ or exc.__context__
                extra: dict[str, object] = {}
                if cause:
                    extra["service_cause"] = f"{cause.__class__.__name__}: {cause}"
                self._log_text_graphy_error(
                    "Coverr video lookup failed",
                    error=exc,
                    coverr_reference=coverr_reference,
                    diagnostics=diagnostics,
                    source_stage="menu",
                    level=logging.ERROR,
                    **extra,
                )
                error = str(exc)
            except LyricsProcessingError as exc:
                diagnostics = getattr(exc, "diagnostics", diagnostics)
                self._log_text_graphy_error(
                    "Lyrics processing failed",
                    error=exc,
                    coverr_reference=coverr_reference,
                    diagnostics=diagnostics,
                    level=logging.ERROR,
                )
                error = str(exc)
            except TextGraphyServiceError as exc:
                diagnostics = getattr(exc, "diagnostics", diagnostics)
                self._log_text_graphy_error(
                    "Text Graphy service failed",
                    error=exc,
                    coverr_reference=coverr_reference,
                    diagnostics=diagnostics,
                    level=logging.ERROR,
                )
                error = str(exc)
            except Exception as exc:  # pragma: no cover - defensive branch
                self._log_text_graphy_error(
                    "Unexpected error while building Text Graphy plan",
                    error=exc,
                    coverr_reference=coverr_reference,
                    diagnostics=diagnostics,
                    level=logging.ERROR,
                )
                self.logger.exception(
                    "Unexpected error while building Text Graphy plan",
                    extra={"stage": "logs"},
                )
                error = "خطای غیرمنتظره هنگام ساخت تکس گرافی رخ داد."

        token_label = diagnostics.token_label if diagnostics else None
        token_hint = diagnostics.token_hint if diagnostics else None
        if token_hint is None and token_usage:
            token_hint = "توکن‌های فعال از بخش تنظیمات بارگذاری شده‌اند."

        state = TextGraphyFormState(
            coverr_reference=coverr_reference,
            music_url=music_url or "",
            music_duration=music_duration or "",
            lyrics_text=lyrics_text,
            info=info,
            error=error,
            plan=plan,
            downloads=downloads,
            stages=diagnostics.stages if diagnostics else None,
            token_label=token_label,
            token_hint=token_hint,
            token_usage=tuple(token_usage) if token_usage else None,
        )
        return self.render(request, user, state, token_usage=token_usage)

    def _default_state(self) -> TextGraphyFormState:
        return TextGraphyFormState(
            coverr_reference=DEFAULT_COVERR_REFERENCE,
            music_url=DEFAULT_MUSIC_URL,
            music_duration=DEFAULT_MUSIC_DURATION,
            lyrics_text=DEFAULT_LYRICS,
        )

    def _plan_to_payload(
        self, plan: TextGraphyPlan, downloads: Optional[TextGraphyDownloads]
    ):
        payload = {
            "video": plan.video,
            "audio_url": plan.audio_url,
            "lines": plan.lines,
            "lines_json": plan.lines_json(),
            "webvtt": plan.as_webvtt(),
            "total_duration": plan.total_duration,
        }
        if downloads:
            payload["downloads"] = {
                "webvtt_url": downloads.webvtt_url,
                "lines_json_url": downloads.lines_json_url,
                "webvtt_path": str(downloads.webvtt_path),
                "lines_json_path": str(downloads.lines_json_path),
            }
        return payload

    def _persist_plan_artifacts(self, plan: TextGraphyPlan) -> TextGraphyDownloads:
        base_name = self._sanitize_identifier(plan.video.identifier)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        directory = self.download_storage_dir
        directory.mkdir(parents=True, exist_ok=True)

        def _unique_path(suffix: str) -> Path:
            candidate = directory / f"{base_name}-{timestamp}{suffix}"
            counter = 1
            while candidate.exists():
                candidate = directory / f"{base_name}-{timestamp}-{counter}{suffix}"
                counter += 1
            return candidate

        webvtt_path = _unique_path(".vtt")
        lines_json_path = _unique_path(".json")

        webvtt_path.write_text(plan.as_webvtt(), encoding="utf-8")
        lines_json_path.write_text(plan.lines_json(), encoding="utf-8")

        return TextGraphyDownloads(
            webvtt_path=webvtt_path,
            lines_json_path=lines_json_path,
            webvtt_url=f"{self.download_url_prefix}/{webvtt_path.name}",
            lines_json_url=f"{self.download_url_prefix}/{lines_json_path.name}",
        )

    @staticmethod
    def _sanitize_identifier(identifier: Optional[str]) -> str:
        clean = (identifier or "text-graphy").strip()
        clean = clean or "text-graphy"
        clean = re.sub(r"[^\w-]+", "-", clean, flags=re.UNICODE)
        clean = clean.strip("-") or "text-graphy"
        return clean.lower()

    def _log_text_graphy_error(
        self,
        message: str,
        *,
        error: Exception,
        coverr_reference: Optional[str] = None,
        diagnostics: Optional[TextGraphyDiagnostics] = None,
        level: int = logging.WARNING,
        **extra: object,
    ) -> None:
        extra_payload: dict[str, object] = {"stage": "logs"}
        if extra:
            extra_payload.update(extra)
        extra_payload["error"] = str(error)
        extra_payload["error_type"] = error.__class__.__name__
        extra_payload.update(self._exception_metadata(error))
        if coverr_reference:
            extra_payload["coverr_reference"] = coverr_reference
        if diagnostics and diagnostics.stages:
            extra_payload["diagnostics"] = [
                {
                    "key": stage.key,
                    "status": stage.status,
                    "detail": stage.detail,
                }
                for stage in diagnostics.stages
            ]
        context_segments: list[str] = []
        location = extra_payload.get("error_origin")
        if location:
            context_segments.append(f"error_origin={location}")
        coverr_ref = extra_payload.get("coverr_reference")
        if coverr_ref:
            context_segments.append(f"coverr_reference={coverr_ref}")
        if context_segments:
            message = f"{message} [{' '.join(context_segments)}]"
        self.logger.log(level, message, extra=extra_payload)

    @staticmethod
    def _exception_metadata(error: Exception) -> dict[str, object]:
        metadata: dict[str, object] = {}
        tb = error.__traceback__
        last_tb = None
        while tb:
            last_tb = tb
            tb = tb.tb_next
        if last_tb is not None:
            frame = last_tb.tb_frame
            try:
                module = frame.f_globals.get("__name__", frame.f_code.co_filename)
                function = frame.f_code.co_name
                line = last_tb.tb_lineno
            finally:
                del frame
            metadata.update(
                {
                    "error_origin_module": module,
                    "error_origin_function": function,
                    "error_origin_line": line,
                    "error_origin": f"{module}:{function}:{line}",
                }
            )
        return metadata

    def _parse_duration(self, raw: Optional[str]) -> Optional[float]:
        if raw is None:
            return None
        value = raw.strip()
        if not value:
            return None

        normalized = value.replace(",", ".")
        if ":" in normalized:
            parts = normalized.split(":")
            if len(parts) == 2:
                minutes, seconds = parts
                return float(minutes) * 60 + float(seconds)
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
            raise ValueError("invalid duration format")

        return float(normalized)
