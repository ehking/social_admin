"""Presenter for displaying stored media assets in the admin UI."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.services.data_access import DatabaseServiceError, JobQueryService

from .helpers import build_layout_context


@dataclass(slots=True)
class MediaAssetView:
    """Lightweight representation of a media row for template rendering."""

    id: int
    title: str
    media_type: str
    category: str
    preview_url: Optional[str]
    created_at: Optional[datetime]
    created_display: str
    job_id: Optional[int]
    job_title: Optional[str]
    job_status: Optional[str]
    campaign_name: Optional[str]
    source_label: str


@dataclass(slots=True)
class MediaSummary:
    """Aggregate counters for the media library header."""

    total: int
    video: int
    image: int
    audio: int
    other: int


@dataclass(slots=True)
class MediaLibraryPresenter:
    """Prepare data required to render the media library page."""

    templates: Jinja2Templates
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("app.ui.media_library")
    )
    default_limit: int = 60

    def render(self, request: Request, user: models.AdminUser, db: Session) -> object:
        items, error = self._load_media(db)
        summary = self._summarise(items)
        context = build_layout_context(
            request=request,
            user=user,
            db=db,
            active_page="media_library",
            media_items=items,
            media_summary=summary,
        )
        if error:
            context["error"] = error
        elif not items:
            context["info"] = "هنوز رسانه‌ای در سیستم ثبت نشده است."
        return self.templates.TemplateResponse("media_library.html", context)

    def _load_media(self, db: Session) -> tuple[list[MediaAssetView], Optional[str]]:
        service = JobQueryService(db)
        try:
            records: Sequence[models.JobMedia] = service.list_recent_media(
                limit=self.default_limit
            )
        except DatabaseServiceError as exc:
            self.logger.error("Failed to load media assets", exc_info=exc)
            return [], "بارگذاری رسانه‌ها با خطا مواجه شد."

        items = [self._build_media_view(record) for record in records]
        return items, None

    def _build_media_view(self, media: models.JobMedia) -> MediaAssetView:
        preview_url = self._select_preview_url(media)
        category = self._infer_category(media.media_type, preview_url)
        title = self._derive_title(media)
        created_at = getattr(media, "created_at", None)
        created_display = (
            created_at.strftime("%Y-%m-%d %H:%M") if isinstance(created_at, datetime) else ""
        )
        job = getattr(media, "job", None)
        job_id = getattr(job, "id", None)
        job_title = self._clean(getattr(job, "title", None))
        job_status = self._clean(getattr(job, "status", None))
        campaign_name = None
        if job and getattr(job, "campaign", None):
            campaign_name = self._clean(getattr(job.campaign, "name", None))
        source_label = self._source_label(media)

        return MediaAssetView(
            id=getattr(media, "id", 0) or 0,
            title=title,
            media_type=self._clean(media.media_type) or "",
            category=category,
            preview_url=preview_url,
            created_at=created_at,
            created_display=created_display,
            job_id=job_id,
            job_title=job_title,
            job_status=job_status,
            campaign_name=campaign_name,
            source_label=source_label,
        )

    def _select_preview_url(self, media: models.JobMedia) -> Optional[str]:
        for attribute in ("storage_url", "media_url"):
            value = self._clean(getattr(media, attribute, None))
            if value:
                return value
        return None

    def _infer_category(
        self, media_type: Optional[str], preview_url: Optional[str]
    ) -> str:
        media_type_value = (media_type or "").strip().lower()
        if media_type_value.startswith("video"):
            return "video"
        if media_type_value.startswith("image"):
            return "image"
        if media_type_value.startswith("audio"):
            return "audio"

        if preview_url:
            lowered = preview_url.lower()
            if lowered.endswith((".mp4", ".mov", ".mkv", ".webm")):
                return "video"
            if lowered.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                return "image"
            if lowered.endswith((".mp3", ".wav", ".ogg", ".m4a")):
                return "audio"
        return "other"

    def _derive_title(self, media: models.JobMedia) -> str:
        for candidate in (
            self._clean(getattr(media, "job_name", None)),
            self._clean(getattr(media, "storage_key", None)),
        ):
            if candidate:
                return candidate
        job = getattr(media, "job", None)
        title = self._clean(getattr(job, "title", None)) if job else None
        if title:
            return title
        media_id = getattr(media, "id", None)
        return f"رسانه شماره {media_id}" if media_id else "رسانه ثبت‌شده"

    def _source_label(self, media: models.JobMedia) -> str:
        if self._clean(getattr(media, "storage_url", None)):
            return "ذخیره شده در فضای داخلی"
        if self._clean(getattr(media, "media_url", None)):
            return "لینک خارجی ثبت‌شده"
        return "بدون لینک ثبت‌شده"

    def _summarise(self, items: Sequence[MediaAssetView]) -> MediaSummary:
        summary = MediaSummary(total=len(items), video=0, image=0, audio=0, other=0)
        for item in items:
            if item.category == "video":
                summary.video += 1
            elif item.category == "image":
                summary.image += 1
            elif item.category == "audio":
                summary.audio += 1
            else:
                summary.other += 1
        return summary

    @staticmethod
    def _clean(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None
