"""Presenter for managing manual video creation workflows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.services import create_job_with_media_and_campaign


@dataclass(slots=True)
class ManualVideoPresenter:
    """Prepare data for manual video creation and handle form submissions."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.manual_video")

    def render(self, request: Request, user: models.AdminUser, db: Session) -> object:
        jobs = db.query(models.Job).order_by(models.Job.created_at.desc()).all()
        context = {
            "request": request,
            "user": user,
            "jobs": jobs,
            "active_page": "manual_video",
        }
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

        if not clean_title or not clean_media_url or not clean_campaign_name:
            jobs = db.query(models.Job).order_by(models.Job.created_at.desc()).all()
            context = {
                "request": request,
                "user": user,
                "jobs": jobs,
                "error": "عنوان، لینک ویدیو و نام کمپین الزامی هستند.",
                "active_page": "manual_video",
            }
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
            jobs = db.query(models.Job).order_by(models.Job.created_at.desc()).all()
            context = {
                "request": request,
                "user": user,
                "jobs": jobs,
                "error": "ثبت ویدیو با خطا مواجه شد: " + str(exc),
                "active_page": "manual_video",
            }
            return self.templates.TemplateResponse(
                "manual_video.html", context, status_code=400
            )

        self.logger.info(
            "Manual video job created",
            extra={"user_id": user.id, "title": clean_title, "campaign": clean_campaign_name},
        )
        return RedirectResponse(url="/manual-video", status_code=302)
