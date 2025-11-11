"""Presenter for the Text Graphy experience."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.backend.services.text_graphy import (
    CoverrAPIError,
    LyricsProcessingError,
    TextGraphyPlan,
    TextGraphyService,
    TextGraphyServiceError,
)

LOGGER = logging.getLogger(__name__)


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
    ):
        state = form_state or self._default_state()
        result_payload = self._plan_to_payload(state.plan) if state.plan else None
        context = {
            "request": request,
            "user": user,
            "active_page": "text_graphy",
            "form_state": state,
            "result": result_payload,
            "info": state.info,
            "error": state.error,
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
    ):
        duration_seconds: Optional[float] = None
        error: Optional[str] = None
        info: Optional[str] = None
        plan: Optional[TextGraphyPlan] = None

        try:
            duration_seconds = self._parse_duration(music_duration)
        except ValueError:
            error = "فرمت مدت زمان موزیک معتبر نیست. از قالب mm:ss یا ثانیه استفاده کنید."

        if error is None:
            try:
                plan = self.service.build_plan(
                    coverr_reference=coverr_reference,
                    lyrics_text=lyrics_text,
                    audio_url=music_url if music_url else None,
                    audio_duration=duration_seconds,
                )
                info = "پیش‌نمایش تکس گرافی با موفقیت ساخته شد."
            except CoverrAPIError as exc:
                error = str(exc)
            except LyricsProcessingError as exc:
                error = str(exc)
            except TextGraphyServiceError as exc:
                error = str(exc)
            except Exception:  # pragma: no cover - defensive branch
                self.logger.exception("Unexpected error while building Text Graphy plan")
                error = "خطای غیرمنتظره هنگام ساخت تکس گرافی رخ داد."

        state = TextGraphyFormState(
            coverr_reference=coverr_reference,
            music_url=music_url or "",
            music_duration=music_duration or "",
            lyrics_text=lyrics_text,
            info=info,
            error=error,
            plan=plan,
        )
        return self.render(request, user, state)

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
