"""Services for generating Text Graphy overlays using Coverr videos."""

from __future__ import annotations

import inspect
import json
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

try:  # pragma: no cover - optional dependency guard
    import requests
except Exception:  # pragma: no cover - fallback when requests missing
    requests = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency guard
    import urllib3
except Exception:  # pragma: no cover - fallback when urllib3 missing
    urllib3 = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency in lightweight environments
    from deep_translator import GoogleTranslator
except Exception:  # pragma: no cover - graceful degradation if translator missing
    GoogleTranslator = None  # type: ignore[assignment]


LOGGER = logging.getLogger(__name__)


class TextGraphyServiceError(RuntimeError):
    """Base class for Text Graphy related failures."""

    def __init__(self, message: str = "", *, diagnostics=None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class CoverrAPIError(TextGraphyServiceError):
    """Raised when retrieving data from the Coverr API fails."""


class LyricsProcessingError(TextGraphyServiceError):
    """Raised when submitted lyrics cannot be processed."""


@dataclass(frozen=True, slots=True)
class CoverrVideoSource:
    """Single rendition of a Coverr video."""

    quality: str
    format: str
    url: str


@dataclass(frozen=True, slots=True)
class CoverrVideoMetadata:
    """Minimal metadata required to play a Coverr video."""

    identifier: str
    title: str
    thumbnail_url: str
    preview_url: Optional[str]
    sources: tuple[CoverrVideoSource, ...]

    def primary_source(self) -> Optional[CoverrVideoSource]:
        return self.sources[0] if self.sources else None


@dataclass(frozen=True, slots=True)
class TextGraphyLine:
    """Lyric line decorated with translated content and timing."""

    index: int
    original: str
    translated: str
    start: float
    end: float

    def to_json(self) -> dict[str, object]:
        return {
            "index": self.index,
            "original": self.original,
            "translated": self.translated,
            "start": self.start,
            "end": self.end,
        }

    def start_timestamp(self) -> str:
        return _format_timestamp(self.start)

    def end_timestamp(self) -> str:
        return _format_timestamp(self.end)


@dataclass(frozen=True, slots=True)
class TextGraphyPlan:
    """Container describing how to build a Text Graphy experience."""

    video: CoverrVideoMetadata
    lines: tuple[TextGraphyLine, ...]
    audio_url: Optional[str]
    total_duration: float

    def as_webvtt(self) -> str:
        """Render the translated lyrics as a WEBVTT caption file."""

        blocks: list[str] = ["WEBVTT"]
        for line in self.lines:
            blocks.append("")
            blocks.append(str(line.index + 1))
            blocks.append(f"{line.start_timestamp()} --> {line.end_timestamp()}")
            blocks.append(line.translated)
        return "\n".join(blocks)

    def lines_json(self) -> str:
        """Return a JSON serialisation usable by the front-end."""

        return json.dumps([line.to_json() for line in self.lines], ensure_ascii=False)


@dataclass(slots=True)
class TextGraphyProcessingStage:
    """Represents a single step of the plan generation pipeline."""

    key: str
    title: str
    status: str = "pending"
    detail: Optional[str] = None


@dataclass(slots=True)
class TextGraphyDiagnostics:
    """Container for exposing diagnostic information to the UI."""

    stages: Tuple[TextGraphyProcessingStage, ...]
    token_label: str
    token_hint: Optional[str] = None


DEFAULT_COVERR_BASE_URL = "https://api.coverr.co"
DEFAULT_LINE_DURATION = 4.0


class TextGraphyService:
    """High level facade for interacting with Coverr and translating lyrics."""

    def __init__(
        self,
        *,
        http_client=None,
        translator: Optional[GoogleTranslator] = None,
        coverr_base_url: str = DEFAULT_COVERR_BASE_URL,
        default_line_duration: float = DEFAULT_LINE_DURATION,
        request_timeout: int = 10,
        request_retries: int = 2,
        retry_backoff: float = 0.5,
    ) -> None:
        if http_client is None:
            if requests is None:  # pragma: no cover - handled in environments without requests
                raise RuntimeError("requests library is required for TextGraphyService")
            http_client = requests
        self._http = http_client
        self._translator = translator or self._build_translator()
        self._coverr_base_url = coverr_base_url.rstrip("/")
        self._default_line_duration = max(0.5, float(default_line_duration))
        self._request_timeout = request_timeout
        self._request_retries = max(0, int(request_retries))
        self._retry_backoff = max(0.0, float(retry_backoff))
        self._token_label = self._infer_translator_label(self._translator)
        self._token_hint = self._build_token_hint(self._translator)

    @staticmethod
    def _build_translator() -> GoogleTranslator:
        if GoogleTranslator is None:  # pragma: no cover - optional dependency guard
            raise RuntimeError("deep-translator is required for TextGraphyService")
        return GoogleTranslator(source="auto", target="fa")

    def fetch_coverr_video(self, reference: str) -> CoverrVideoMetadata:
        """Retrieve metadata for the requested Coverr video."""

        video_id = self._extract_video_id(reference)
        url = f"{self._coverr_base_url}/videos/{video_id}"
        LOGGER.debug("Fetching Coverr video metadata", extra={"video_id": video_id, "url": url})

        try:
            response = self._perform_coverr_get(url)
        except Exception as exc:  # pragma: no cover - network dependent
            self._log_service_event(
                logging.ERROR,
                "Failed to call Coverr API",
                extra=self._exception_metadata(exc),
                exc_info=True,
            )
            raise CoverrAPIError("عدم دسترسی به سرویس Coverr. لطفاً دوباره تلاش کنید.") from exc

        if getattr(response, "status_code", 200) >= 400:
            self._log_service_event(
                logging.ERROR,
                "Coverr API returned error",
                extra={
                    "status": getattr(response, "status_code", None),
                    "video_id": video_id,
                    "request": {
                        "method": "GET",
                        "url": url,
                        "params": None,
                        "timeout": self._request_timeout,
                    },
                    "response_text": self._summarize_response_text(response),
                },
            )
            raise CoverrAPIError("شناسه ویدیو Coverr معتبر نیست یا قابل بازیابی نمی‌باشد.")

        try:
            payload = response.json()
        except Exception as exc:  # pragma: no cover - network dependent
            self._log_service_event(
                logging.ERROR,
                "Invalid JSON from Coverr API",
                extra=self._exception_metadata(exc),
                exc_info=True,
            )
            raise CoverrAPIError("پاسخ نامعتبر از سرویس Coverr دریافت شد.") from exc

        sources = self._extract_sources(payload)
        if not sources:
            self._log_service_event(
                logging.WARNING,
                "Coverr response missing video sources",
                extra={"video_id": video_id},
            )

        metadata = CoverrVideoMetadata(
            identifier=str(
                payload.get("id")
                or payload.get("videoId")
                or payload.get("slug")
                or video_id
            ),
            title=(payload.get("title") or payload.get("name") or "ویدیوی Coverr"),
            thumbnail_url=(
                payload.get("poster")
                or payload.get("thumbnail")
                or payload.get("thumb")
                or payload.get("image")
                or ""
            ),
            preview_url=payload.get("preview")
            or payload.get("previewUrl")
            or payload.get("preview_url")
            or (payload.get("video") or {}).get("preview"),
            sources=tuple(sources),
        )
        return metadata

    def _perform_coverr_get(self, url: str):
        attempt = 0
        while True:
            try:
                return self._http.get(url, timeout=self._request_timeout)
            except Exception as exc:  # pragma: no cover - network dependent
                should_retry = attempt < self._request_retries and self._is_retryable_exception(exc)
                if not should_retry:
                    raise
                attempt += 1
                delay = min(self._retry_backoff * attempt, 5.0)
                extra = {
                    "attempt": attempt,
                    "max_retries": self._request_retries,
                    "video_url": url,
                }
                extra.update(self._exception_metadata(exc))
                self._log_service_event(
                    logging.WARNING,
                    "Coverr API call failed, retrying",
                    extra=extra,
                )
                if delay > 0:
                    time.sleep(delay)

    def _is_retryable_exception(self, exc: Exception) -> bool:
        current: Optional[Exception] = exc
        while current is not None:
            if self._matches_retryable_type(current):
                return True
            current = current.__cause__ if current.__cause__ is not current else None
        return False

    def _matches_retryable_type(self, exc: Exception) -> bool:
        if requests is not None:
            try:
                from requests import exceptions as req_exc
            except Exception:  # pragma: no cover - defensive import guard
                req_exc = None  # type: ignore[assignment]
            else:
                if isinstance(exc, (req_exc.ConnectionError, req_exc.Timeout)):  # type: ignore[arg-type]
                    return True
        if urllib3 is not None:
            try:
                from urllib3 import exceptions as urllib3_exc
            except Exception:  # pragma: no cover - defensive import guard
                urllib3_exc = None  # type: ignore[assignment]
            else:
                if isinstance(exc, urllib3_exc.ProtocolError):  # type: ignore[arg-type]
                    return True
        return isinstance(exc, (ConnectionError, TimeoutError, OSError))

    @staticmethod
    def _summarize_response_text(response: Any, limit: int = 500) -> Optional[str]:
        """Safely extract a short preview of the response text for logging."""

        text = getattr(response, "text", None)
        if not text:
            return None
        preview = str(text)
        if len(preview) > limit:
            preview = f"{preview[:limit]}…"
        return preview

    @staticmethod
    def _extract_video_id(reference: str) -> str:
        if not reference:
            raise CoverrAPIError("لطفاً شناسه یا لینک ویدیو را وارد کنید.")

        reference = reference.strip()
        if "/" in reference:
            parsed = urlparse(reference)
            if parsed.path:
                candidate = parsed.path.rstrip("/").split("/")[-1]
                if candidate:
                    return candidate
        return reference

    @staticmethod
    def _extract_sources(payload: dict) -> List[CoverrVideoSource]:
        def iter_sources(data: dict) -> Iterable[CoverrVideoSource]:
            for quality, sources in data.items():
                if not isinstance(sources, dict):
                    continue
                for fmt, url in sources.items():
                    if isinstance(url, str) and url:
                        yield CoverrVideoSource(quality=str(quality), format=str(fmt), url=url)

        video_section = payload.get("video") or payload.get("urls") or payload.get("videoUrls") or {}
        sources = list(iter_sources(video_section))
        if not sources and isinstance(payload.get("source"), dict):
            sources = list(iter_sources(payload["source"]))
        return sources

    def build_plan(
        self,
        *,
        coverr_reference: str,
        lyrics_text: str,
        audio_url: Optional[str],
        audio_duration: Optional[float] = None,
    ) -> TextGraphyPlan:
        plan, _ = self.build_plan_with_diagnostics(
            coverr_reference=coverr_reference,
            lyrics_text=lyrics_text,
            audio_url=audio_url,
            audio_duration=audio_duration,
        )
        return plan

    def build_plan_with_diagnostics(
        self,
        *,
        coverr_reference: str,
        lyrics_text: str,
        audio_url: Optional[str],
        audio_duration: Optional[float] = None,
    ) -> Tuple[TextGraphyPlan, TextGraphyDiagnostics]:
        stages: List[TextGraphyProcessingStage] = [
            TextGraphyProcessingStage(
                key="coverr_fetch",
                title="دریافت ویدیو از Coverr",
            ),
            TextGraphyProcessingStage(
                key="lyrics_processing",
                title="پردازش و ترجمه متن ترانه",
            ),
            TextGraphyProcessingStage(
                key="timeline_assembly",
                title="مونتاژ زیرنویس و آماده‌سازی پیش‌نمایش",
            ),
        ]

        video: Optional[CoverrVideoMetadata] = None
        lines: List[TextGraphyLine] = []

        try:
            stages[0].status = "processing"
            video = self.fetch_coverr_video(coverr_reference)
            stages[0].status = "completed"
            stages[0].detail = video.title
        except TextGraphyServiceError as exc:
            stages[0].status = "error"
            stages[0].detail = str(exc)
            diagnostics = self._finalise_diagnostics(stages)
            exc.diagnostics = diagnostics
            raise
        except Exception as exc:  # pragma: no cover - defensive branch
            stages[0].status = "error"
            stages[0].detail = "خطای غیرمنتظره هنگام دریافت ویدیو"
            diagnostics = self._finalise_diagnostics(stages)
            raise TextGraphyServiceError(
                "خطای غیرمنتظره هنگام دریافت ویدیو Coverr.", diagnostics=diagnostics
            ) from exc

        try:
            stages[1].status = "processing"
            lines = self._build_lines(lyrics_text, audio_duration)
            stages[1].status = "completed"
            stages[1].detail = f"{len(lines)} خط پردازش شد"
        except TextGraphyServiceError as exc:
            stages[1].status = "error"
            stages[1].detail = str(exc)
            diagnostics = self._finalise_diagnostics(stages)
            exc.diagnostics = diagnostics
            raise
        except Exception as exc:  # pragma: no cover - defensive branch
            stages[1].status = "error"
            stages[1].detail = "خطای غیرمنتظره هنگام پردازش متن"
            diagnostics = self._finalise_diagnostics(stages)
            raise TextGraphyServiceError(
                "خطای غیرمنتظره هنگام پردازش متن ترانه.", diagnostics=diagnostics
            ) from exc

        stages[2].status = "processing"
        total_duration = lines[-1].end if lines else 0.0
        plan = TextGraphyPlan(
            video=video,
            lines=tuple(lines),
            audio_url=audio_url,
            total_duration=total_duration,
        )
        stages[2].status = "completed"
        stages[2].detail = f"مدت کل: {total_duration:.1f} ثانیه"

        diagnostics = self._finalise_diagnostics(stages)
        return plan, diagnostics

    def _build_lines(
        self,
        lyrics_text: str,
        audio_duration: Optional[float],
    ) -> List[TextGraphyLine]:
        lines = [line.strip() for line in lyrics_text.splitlines() if line.strip()]
        if not lines:
            raise LyricsProcessingError("متن موزیک خالی است. لطفاً متن را وارد نمایید.")

        normalized_duration = None
        if audio_duration is not None:
            try:
                normalized_duration = max(1.0, float(audio_duration))
            except (TypeError, ValueError) as exc:
                raise LyricsProcessingError("مدت زمان موزیک معتبر نیست.") from exc

        line_duration = (
            normalized_duration / len(lines)
            if normalized_duration is not None
            else self._default_line_duration
        )

        computed_lines: List[TextGraphyLine] = []
        current_start = 0.0
        for index, original in enumerate(lines):
            translated = self._translate(original)
            start = round(current_start, 3)
            end = round(current_start + line_duration, 3)
            if normalized_duration is not None and index == len(lines) - 1:
                end = round(normalized_duration, 3)
            computed_lines.append(
                TextGraphyLine(
                    index=index,
                    original=original,
                    translated=translated,
                    start=start,
                    end=end,
                )
            )
            current_start += line_duration
        return computed_lines

    def _translate(self, text: str) -> str:
        if not self._translator:
            return text
        try:
            translated = self._translator.translate(text)
        except Exception as exc:  # pragma: no cover - depends on external service
            self._log_service_event(
                logging.ERROR,
                "Translation failed",
                extra=self._exception_metadata(exc),
                exc_info=True,
            )
            raise LyricsProcessingError("ترجمه متن با خطا مواجه شد. لطفاً دوباره تلاش کنید.") from exc
        return translated

    @staticmethod
    def _exception_metadata(exc: Exception) -> dict[str, object]:
        metadata: dict[str, object] = {
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
        }
        tb = exc.__traceback__
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

    def _log_service_event(
        self,
        level: int,
        message: str,
        *,
        extra: Optional[dict[str, object]] = None,
        exc_info=None,
    ) -> None:
        payload: dict[str, object] = dict(extra) if extra else {}
        frame = inspect.currentframe()
        try:
            caller = frame.f_back if frame is not None else None
            if caller is not None:
                module = caller.f_globals.get("__name__", caller.f_code.co_filename)
                function = caller.f_code.co_name
                line = caller.f_lineno
                payload.setdefault("service_module", module)
                payload.setdefault("service_function", function)
                payload.setdefault("service_line", line)
                payload.setdefault("service_location", f"{module}:{function}:{line}")
        finally:
            del frame
            if "caller" in locals():
                del caller
        context_segments: list[str] = []
        location = payload.get("service_location")
        if location:
            context_segments.append(f"service_location={location}")
        error_origin = payload.get("error_origin")
        if error_origin:
            context_segments.append(f"error_origin={error_origin}")
        if context_segments:
            message = f"{message} [{' '.join(context_segments)}]"
        LOGGER.log(level, message, extra=payload, exc_info=exc_info)

    def _infer_translator_label(self, translator) -> str:
        if translator is None:
            return "مترجم خودکار فعال نیست"
        provider = getattr(translator, "provider", None) or getattr(translator, "source", None)
        provider_label = f" – {provider}" if provider else ""
        return f"{translator.__class__.__name__}{provider_label}"

    def _build_token_hint(self, translator) -> Optional[str]:
        if translator is None:
            return None
        token = getattr(translator, "api_key", None) or getattr(translator, "token", None)
        if token:
            masked = self._mask_token(str(token))
            return f"توکن مترجم: {masked}"
        return "بدون نیاز به توکن اختصاصی (Deep Translator)"

    @staticmethod
    def _mask_token(token: str) -> str:
        if len(token) <= 6:
            return "*" * len(token)
        return f"{token[:3]}***{token[-3:]}"

    def _finalise_diagnostics(
        self, stages: List[TextGraphyProcessingStage]
    ) -> TextGraphyDiagnostics:
        frozen = tuple(
            TextGraphyProcessingStage(
                key=stage.key,
                title=stage.title,
                status=stage.status,
                detail=stage.detail,
            )
            for stage in stages
        )
        return TextGraphyDiagnostics(
            stages=frozen,
            token_label=self._token_label,
            token_hint=self._token_hint,
        )


def _format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_milliseconds = int(round(seconds * 1000))
    td = timedelta(milliseconds=total_milliseconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    hours += td.days * 24
    milliseconds = total_milliseconds % 1000
    return f"{hours:02}:{minutes:02}:{seconds_part:02}.{milliseconds:03}"
