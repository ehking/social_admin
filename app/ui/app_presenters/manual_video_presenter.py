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


@dataclass(frozen=True, slots=True)
class StatusPresentation:
    label: str
    badge_class: str
    progress_description: str


@dataclass(slots=True)
class ManualVideoJobView:
    title: str
    campaign_name: Optional[str]
    status_label: str
    status_badge_class: str
    progress_percent: int
    progress_description: str
    created_at: Optional[datetime]


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


@dataclass(slots=True)
class ManualVideoPresenter:
    """Prepare data for manual video creation and handle form submissions."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.manual_video")

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

        return ManualVideoJobView(
            title=job.title,
            campaign_name=campaign_name,
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
    ) -> RedirectResponse | object:
        clean_title = title.strip()
        clean_media_url = media_url.strip()
        clean_campaign_name = campaign_name.strip()
        clean_media_type = (media_type or "video/mp4").strip() or "video/mp4"
        clean_description = description.strip() if description else None
        clean_campaign_description = (
            campaign_description.strip() if campaign_description else None
        )

        jobs, load_error = self._load_recent_jobs(db)
        if not clean_title or not clean_media_url or not clean_campaign_name:
            context = {
                "request": request,
                "user": user,
                "jobs": jobs,
                "error": "عنوان، لینک ویدیو و نام کمپین الزامی هستند.",
                "active_page": "manual_video",
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
            }
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse(
                "manual_video.html", context, status_code=400
            )

        self.logger.info(
            "Manual video job created",
            extra={"user_id": user.id, "title": clean_title, "campaign": clean_campaign_name},
        )
        return RedirectResponse(url="/manual-video", status_code=302)
