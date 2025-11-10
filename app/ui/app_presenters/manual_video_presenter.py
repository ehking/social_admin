"""Presenter for managing manual video creation workflows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.services import create_job_with_media_and_campaign
from app.backend.services.data_access import DatabaseServiceError, JobQueryService
from app.backend.ai_workflow import TOOLS


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
    created_at: Optional[datetime]


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


@dataclass(slots=True)
class ManualVideoPresenter:
    """Prepare data for manual video creation and handle form submissions."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.manual_video")
    _ai_tools: tuple[str, ...] = tuple(sorted(tool.name for tool in TOOLS))

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

        ai_tool_value = (job.ai_tool or "").strip() if getattr(job, "ai_tool", None) else ""

        return ManualVideoJobView(
            title=job.title,
            campaign_name=campaign_name,
            ai_tool=ai_tool_value or "نامشخص",
            status_label=presentation.label,
            status_badge_class=presentation.badge_class,
            progress_percent=progress,
            progress_description=presentation.progress_description,
            created_at=job.created_at,
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
        }
        if load_error:
            context["error"] = load_error
        return self.templates.TemplateResponse("manual_video.html", context)

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
            }
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse(
                "manual_video.html", context, status_code=400
            )

        try:
            create_job_with_media_and_campaign(
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
            }
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse(
                "manual_video.html", context, status_code=400
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
