"""Presenter for managing manual video creation workflows."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.http_logging import (
    log_request_failure,
    log_request_start,
    log_request_success,
)
from app.backend.services import create_job_with_media_and_campaign
from app.backend.services.ai_client import (
    AIServiceConfigurationError,
    AIServiceDispatchError,
    DispatchResult,
    dispatch_manual_video_job,
)
from app.backend.services.data_access import DatabaseServiceError, JobQueryService
from app.backend.ai_workflow import TOOLS

try:  # pragma: no cover - optional dependency in minimal test environments
    import requests
except Exception:  # pragma: no cover - fallback when requests unavailable
    requests = None  # type: ignore[assignment]


@contextmanager
def _response_context(response):
    if hasattr(response, "__enter__") and hasattr(response, "__exit__"):
        with response:
            yield response
    else:
        try:
            yield response
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()


@dataclass(frozen=True, slots=True)
class StatusPresentation:
    label: str
    badge_class: str
    progress_description: str


@dataclass(slots=True)
class ManualVideoJobView:
    title: str
    campaign_name: Optional[str]
    ai_tool: str
    status_label: str
    status_badge_class: str
    progress_percent: int
    progress_description: str
    stage_label: str
    stage_hint: str
    media_preview_url: Optional[str]
    local_preview_url: Optional[str]
    local_preview_path: Optional[str]
    created_at: Optional[datetime]
    error_message: Optional[str]
    error_code: Optional[str]


@dataclass(frozen=True, slots=True)
class ManualVideoFormDefaults:
    """Default values for the manual video creation form."""

    title: str
    description: str
    media_url: str
    media_type: str
    campaign_name: str
    campaign_description: str
    ai_tool: str


@dataclass(frozen=True, slots=True)
class SampleAIVideo:
    """Static representation of an AI-generated video preview."""

    title: str
    description: str
    duration: str
    thumbnail_url: str
    video_url: str


STATUS_PRESENTATIONS: dict[str, StatusPresentation] = {
    "pending": StatusPresentation(
        label="در انتظار پردازش",
        badge_class="badge-warning",
        progress_description="وظیفه در صف پردازش قرار دارد",
    ),
    "processing": StatusPresentation(
        label="در حال پردازش",
        badge_class="badge-info",
        progress_description="سیستم در حال پردازش ویدیو است",
    ),
    "completed": StatusPresentation(
        label="تکمیل شده",
        badge_class="badge-success",
        progress_description="پردازش ویدیو با موفقیت پایان یافت",
    ),
    "failed": StatusPresentation(
        label="ناموفق",
        badge_class="badge-danger",
        progress_description="پردازش ویدیو به دلیل خطا متوقف شد",
    ),
}

DEFAULT_PRESENTATION = StatusPresentation(
    label="نامشخص",
    badge_class="badge-secondary",
    progress_description="در انتظار دریافت وضعیت از سرویس تولید ویدیو",
)


SAMPLE_AI_VIDEOS: tuple[SampleAIVideo, ...] = (
    SampleAIVideo(
        title="معرفی محصول جدید",
        description="ویدیو هوش مصنوعی درباره معرفی یک گجت پوشیدنی آینده‌نگر.",
        duration="00:28",
        thumbnail_url="https://images.unsplash.com/photo-1523475472560-d2df97ec485c?auto=format&fit=crop&w=800&q=80",
        video_url="https://cdn.openai.com/sora/videos/sora/product_demo.mp4",
    ),
    SampleAIVideo(
        title="تور مجازی شهر آینده",
        description="نمایی سینمایی از یک شهر آینده‌نگر با الهام از هوش مصنوعی.",
        duration="00:34",
        thumbnail_url="https://images.unsplash.com/photo-1526401485004-46910ecc8e51?auto=format&fit=crop&w=800&q=80",
        video_url="https://storage.googleapis.com/muxdemofiles/mux-video-intro.mp4",
    ),
    SampleAIVideo(
        title="داستان کوتاه تخیلی",
        description="داستانی کوتاه با روایت متنی که توسط مدل مولد ساخته شده است.",
        duration="00:21",
        thumbnail_url="https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=800&q=80",
        video_url="https://cdn.openai.com/sora/videos/sora/short_story.mp4",
    ),
)


DEFAULT_FORM_CAMPAIGN_NAME = "کمپین معرفی محصول آینده"
DEFAULT_FORM_CAMPAIGN_DESCRIPTION = (
    "یک کمپین نمونه برای معرفی محصولات جدید با استفاده از ابزارهای هوش مصنوعی."
)


@dataclass(slots=True)
class ManualVideoPresenter:
    """Prepare data for manual video creation and handle form submissions."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.manual_video")
    static_root: Path = Path("app/ui/static")
    preview_storage_dir: Path = Path("app/ui/static/manual_videos")
    _ai_tools: tuple[str, ...] = field(
        default_factory=lambda: tuple(tool.name for tool in TOOLS)
    )

    def _build_form_defaults(self) -> ManualVideoFormDefaults:
        """Return default values that pre-populate the manual video form."""

        default_tool = self._ai_tools[0] if self._ai_tools else ""
        sample_video = SAMPLE_AI_VIDEOS[0] if SAMPLE_AI_VIDEOS else None

        return ManualVideoFormDefaults(
            title=sample_video.title if sample_video else "ویدیوی جدید هوش مصنوعی",
            description=
                sample_video.description
                if sample_video
                else "توضیحات پیشنهادی برای ویدیوی تولید شده با هوش مصنوعی.",
            media_url=sample_video.video_url if sample_video else "",
            media_type="video/mp4",
            campaign_name=DEFAULT_FORM_CAMPAIGN_NAME,
            campaign_description=DEFAULT_FORM_CAMPAIGN_DESCRIPTION,
            ai_tool=default_tool,
        )

    def _resolve_stage(self, status: str, progress: int) -> tuple[str, str]:
        normalized_status = (status or "").strip().lower()

        if normalized_status == "completed":
            return "ویدیو آماده است", "خروجی نهایی با موفقیت ذخیره شد."
        if normalized_status == "failed":
            return "پردازش متوقف شد", "برای بررسی بیشتر لاگ‌های سیستم را بررسی کنید."

        if normalized_status == "processing":
            if progress < 30:
                return "آماده‌سازی", "در حال آماده‌سازی پیش‌نیازهای پردازش ویدیو."
            if progress < 70:
                return "رندر ویدیو", "ویدیو در حال رندر و ترکیب اجزای مختلف است."
            return "بارگذاری", "ویدیو در حال ذخیره‌سازی و بارگذاری در مقصد نهایی است."

        return "در صف انتظار", "وظیفه در صف پردازش قرار دارد."

    def _derive_media_preview_url(self, job: models.Job) -> Optional[str]:
        if not job.media:
            return None
        primary_media = job.media[0]
        for attribute in ("storage_url", "media_url"):
            value = getattr(primary_media, attribute, None)
            if value:
                trimmed = str(value).strip()
                if trimmed:
                    return trimmed
        return None

    def _find_local_preview(self, job_id: int) -> tuple[Optional[str], Optional[str]]:
        directory = self.preview_storage_dir
        if not directory.exists():
            return None, None

        try:
            candidates = sorted(directory.glob(f"job-{job_id}*"))
        except OSError:
            return None, None

        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                relative = candidate.relative_to(self.static_root)
            except ValueError:
                web_path = None
            else:
                web_path = f"/static/{relative.as_posix()}"
            return web_path, str(candidate.resolve())

        return None, None

    def _build_job_view(self, job: models.Job) -> ManualVideoJobView:
        status_raw = (job.status or "").strip().lower()
        presentation = STATUS_PRESENTATIONS.get(status_raw, DEFAULT_PRESENTATION)

        progress_value = getattr(job, "progress_percent", 0) or 0
        try:
            progress = int(progress_value)
        except (TypeError, ValueError):  # pragma: no cover - defensive guard
            progress = 0
        progress = max(0, min(100, progress))

        if status_raw == "completed":
            progress = 100
        elif status_raw == "failed" and progress < 100:
            progress = 100

        campaign_name = job.campaign.name if job.campaign else None

        stage_label, stage_hint = self._resolve_stage(status_raw, progress)

        media_preview_url = self._derive_media_preview_url(job)
        local_preview_url, local_preview_path = (None, None)
        if job.id is not None:
            local_preview_url, local_preview_path = self._find_local_preview(job.id)

        error_message: Optional[str] = None
        error_code: Optional[str] = None
        raw_error_details = getattr(job, "error_details", None)
        if raw_error_details:
            try:
                parsed = json.loads(raw_error_details)
            except (TypeError, ValueError):
                parsed = None

            if isinstance(parsed, dict):
                message_value = parsed.get("message")
                if isinstance(message_value, str):
                    error_message = message_value.strip() or None
                code_value = parsed.get("code")
                if isinstance(code_value, str):
                    error_code = code_value.strip() or None
            elif isinstance(raw_error_details, str):
                error_message = raw_error_details.strip() or None

        ai_tool_raw = getattr(job, "ai_tool", "") or ""
        ai_tool_value = str(ai_tool_raw).strip()

        if status_raw == "failed" and error_message:
            stage_hint = error_message

        return ManualVideoJobView(
            title=job.title,
            campaign_name=campaign_name,
            ai_tool=ai_tool_value or "نامشخص",
            status_label=presentation.label,
            status_badge_class=presentation.badge_class,
            progress_percent=progress,
            progress_description=presentation.progress_description,
            stage_label=stage_label,
            stage_hint=stage_hint,
            media_preview_url=media_preview_url,
            local_preview_url=local_preview_url,
            local_preview_path=local_preview_path,
            created_at=job.created_at,
            error_message=error_message,
            error_code=error_code,
        )

    def _load_recent_jobs(
        self, db: Session, *, limit: int = 10
    ) -> tuple[list[ManualVideoJobView], str | None]:
        service = JobQueryService(db)
        try:
            jobs = [
                self._build_job_view(job)
                for job in service.list_recent_jobs(limit=limit)
            ]
            return jobs, None
        except DatabaseServiceError as exc:
            self.logger.error("Failed to load recent jobs", exc_info=exc)
            return [], "بارگذاری لیست وظایف با خطا مواجه شد."

    def render(self, request: Request, user: models.AdminUser, db: Session) -> object:
        jobs, load_error = self._load_recent_jobs(db)
        context = {
            "request": request,
            "user": user,
            "jobs": jobs,
            "active_page": "manual_video",
            "ai_tools": self._ai_tools,
            "sample_ai_videos": SAMPLE_AI_VIDEOS,
            "manual_video_defaults": self._build_form_defaults(),
        }
        if load_error:
            context["error"] = load_error
        return self.templates.TemplateResponse("manual_video.html", context)

    @staticmethod
    def _should_download_media(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _download_manual_video_preview(self, url: str, *, job_id: int) -> Optional[Path]:
        if requests is None:
            self.logger.warning(
                "requests library is unavailable; cannot download manual video preview",
                extra={"url": url},
            )
            return None

        started_at = log_request_start(
            "GET",
            url,
            job_id=job_id,
            purpose="manual_video_preview",
        )
        try:
            response = requests.get(url, timeout=15, stream=True)
            response.raise_for_status()
            log_request_success(
                "GET",
                url,
                status=getattr(response, "status_code", ""),
                started_at=started_at,
                job_id=job_id,
                purpose="manual_video_preview",
            )
        except Exception as exc:  # pragma: no cover - defensive for network errors
            log_request_failure(
                "GET",
                url,
                started_at=started_at,
                error=exc,
                job_id=job_id,
                purpose="manual_video_preview",
            )
            self.logger.warning(
                "Failed to download manual video preview",
                extra={"url": url, "error": str(exc)},
            )
            return None

        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix or ".mp4"
        target_dir = self.preview_storage_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"job-{job_id}{suffix}"

        try:
            with _response_context(response):
                with target_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            handle.write(chunk)
        except Exception as exc:  # pragma: no cover - defensive for IO errors
            self.logger.error(
                "Failed to persist manual video preview",
                extra={"url": url, "destination": str(target_path), "error": str(exc)},
            )
            return None

        return target_path

    def _dispatch_manual_job_to_ai(
        self,
        *,
        job_id: int,
        user: models.AdminUser,
        title: str,
        description: Optional[str],
        media_url: str,
        media_type: str,
        campaign_name: str,
        campaign_description: Optional[str],
        ai_tool: str,
    ) -> Optional[DispatchResult]:
        payload: dict[str, object] = {
            "job_id": job_id,
            "title": title,
            "media_url": media_url,
            "media_type": media_type,
            "campaign_name": campaign_name,
            "ai_tool": ai_tool,
            "submitted_by": user.id,
        }
        if description:
            payload["description"] = description
        if campaign_description:
            payload["campaign_description"] = campaign_description

        try:
            result = dispatch_manual_video_job(job_id, payload)
        except AIServiceConfigurationError:
            self.logger.info(
                "AI service endpoint is not configured; skipping dispatch",
                extra={"job_id": job_id, "ai_tool": ai_tool},
            )
            return None
        except AIServiceDispatchError as exc:
            self.logger.error(
                "Failed to dispatch job to AI service",
                extra={"job_id": job_id, "ai_tool": ai_tool, "error": str(exc)},
            )
            return None

        self.logger.info(
            "AI service accepted manual video job",
            extra={
                "user_id": user.id,
                "job_id": job_id,
                "ai_tool": ai_tool,
                "ai_job_token": result.job_token,
            },
        )
        return result

    def create_manual_video(
        self,
        *,
        request: Request,
        db: Session,
        user: models.AdminUser,
        title: str,
        description: Optional[str],
        media_url: str,
        media_type: Optional[str],
        campaign_name: str,
        campaign_description: Optional[str],
        ai_tool: str,
    ) -> RedirectResponse | object:
        clean_title = title.strip()
        clean_media_url = media_url.strip()
        clean_campaign_name = campaign_name.strip()
        clean_media_type = (media_type or "video/mp4").strip() or "video/mp4"
        clean_description = description.strip() if description else None
        clean_campaign_description = (
            campaign_description.strip() if campaign_description else None
        )
        clean_ai_tool = ai_tool.strip()

        jobs, load_error = self._load_recent_jobs(db)
        if (
            not clean_title
            or not clean_media_url
            or not clean_campaign_name
            or not clean_ai_tool
        ):
            context = {
                "request": request,
                "user": user,
                "jobs": jobs,
                "error": "عنوان، لینک ویدیو و نام کمپین الزامی هستند.",
                "active_page": "manual_video",
                "ai_tools": self._ai_tools,
                "sample_ai_videos": SAMPLE_AI_VIDEOS,
                "manual_video_defaults": self._build_form_defaults(),
            }
            if not clean_ai_tool:
                context["error"] = (
                    "عنوان، لینک ویدیو، نام کمپین و نام ابزار هوش مصنوعی الزامی هستند."
                )
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse(
                "manual_video.html", context, status_code=400
            )

        if clean_ai_tool not in self._ai_tools:
            context = {
                "request": request,
                "user": user,
                "jobs": jobs,
                "error": "ابزار هوش مصنوعی انتخاب‌شده معتبر نیست.",
                "active_page": "manual_video",
                "ai_tools": self._ai_tools,
                "sample_ai_videos": SAMPLE_AI_VIDEOS,
                "manual_video_defaults": self._build_form_defaults(),
            }
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse(
                "manual_video.html", context, status_code=400
            )

        job = None

        try:
            job = create_job_with_media_and_campaign(
                job_payload={
                    "title": clean_title,
                    "description": clean_description,
                    "ai_tool": clean_ai_tool,
                },
                media_payloads=[
                    {
                        "media_type": clean_media_type,
                        "media_url": clean_media_url,
                        "storage_url": clean_media_url,
                    }
                ],
                campaign_payload={
                    "name": clean_campaign_name,
                    "description": clean_campaign_description,
                },
                session=db,
            )
        except ValueError as exc:
            self.logger.warning(
                "Validation error while creating manual video", extra={"error": str(exc)}
            )
            jobs, load_error = self._load_recent_jobs(db)
            context = {
                "request": request,
                "user": user,
                "jobs": jobs,
                "error": "ثبت ویدیو با خطا مواجه شد: " + str(exc),
                "active_page": "manual_video",
                "ai_tools": self._ai_tools,
                "sample_ai_videos": SAMPLE_AI_VIDEOS,
                "manual_video_defaults": self._build_form_defaults(),
            }
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse(
                "manual_video.html", context, status_code=400
            )

        if job and job.id:
            if self._should_download_media(clean_media_url):
                local_path = self._download_manual_video_preview(
                    clean_media_url, job_id=job.id
                )
                if local_path:
                    self.logger.info(
                        "Manual video preview saved locally",
                        extra={
                            "user_id": user.id,
                            "job_id": job.id,
                            "local_path": str(local_path),
                        },
                    )

            self._dispatch_manual_job_to_ai(
                job_id=job.id,
                user=user,
                title=clean_title,
                description=clean_description,
                media_url=clean_media_url,
                media_type=clean_media_type,
                campaign_name=clean_campaign_name,
                campaign_description=clean_campaign_description,
                ai_tool=clean_ai_tool,
            )

        self.logger.info(
            "Manual video job created",
            extra={
                "user_id": user.id,
                "title": clean_title,
                "campaign": clean_campaign_name,
                "ai_tool": clean_ai_tool,
            },
        )
        return RedirectResponse(url="/manual-video", status_code=302)
