"""Presenter for the Text Graphy experience."""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
class TextGraphyFormState:
    """Represents the submitted values of the Text Graphy form."""

    coverr_reference: str
    music_url: str
    music_duration: str
    lyrics_text: str
    info: Optional[str] = None
    error: Optional[str] = None
    plan: Optional[TextGraphyPlan] = None
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
        result_payload = self._plan_to_payload(state.plan) if state.plan else None
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
        diagnostics: Optional[TextGraphyDiagnostics] = None

        try:
            duration_seconds = self._parse_duration(music_duration)
        except ValueError:
            error = "فرمت مدت زمان موزیک معتبر نیست. از قالب mm:ss یا ثانیه استفاده کنید."

        if error is None:
            try:
                plan, diagnostics = self.service.build_plan_with_diagnostics(
                    coverr_reference=coverr_reference,
                    lyrics_text=lyrics_text,
                    audio_url=music_url if music_url else None,
                    audio_duration=duration_seconds,
                )
                info = "پیش‌نمایش تکس گرافی با موفقیت ساخته شد."
            except CoverrAPIError as exc:
                diagnostics = getattr(exc, "diagnostics", diagnostics)
                self.logger.warning(
                    "Coverr video lookup failed",
                    extra={
                        "error": str(exc),
                        "coverr_reference": coverr_reference,
                        "stage": "menu",
                    },
                )
                error = str(exc)
            except LyricsProcessingError as exc:
                diagnostics = getattr(exc, "diagnostics", diagnostics)
                error = str(exc)
            except TextGraphyServiceError as exc:
                diagnostics = getattr(exc, "diagnostics", diagnostics)
                error = str(exc)
            except Exception:  # pragma: no cover - defensive branch
                self.logger.exception("Unexpected error while building Text Graphy plan")
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

    def _plan_to_payload(self, plan: TextGraphyPlan):
        return {
            "video": plan.video,
            "audio_url": plan.audio_url,
            "lines": plan.lines,
            "lines_json": plan.lines_json(),
            "webvtt": plan.as_webvtt(),
            "total_duration": plan.total_duration,
        }

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
