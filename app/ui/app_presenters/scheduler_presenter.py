"""Presenter logic for the content scheduler."""

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
from app.backend.services.data_access import (
    DatabaseServiceError,
    ScheduledPostService,
    SocialAccountService,
)

from .helpers import build_layout_context


@dataclass(slots=True)
class SchedulerPresenter:
    """Prepare view models and handle scheduled post flows."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.scheduler")

    def _load_accounts(self, db: Session) -> tuple[list[models.SocialAccount], str | None]:
        service = SocialAccountService(db)
        try:
            accounts = list(service.list_accounts_desc())
            return accounts, None
        except DatabaseServiceError as exc:
            self.logger.error("Failed to load accounts for scheduler", exc_info=exc)
            return [], "بارگذاری حساب‌ها با خطا مواجه شد."

    def _load_posts(self, db: Session) -> tuple[list[models.ScheduledPost], str | None]:
        service = ScheduledPostService(db)
        try:
            posts = list(service.list_recent_posts())
            return posts, None
        except DatabaseServiceError as exc:
            self.logger.error("Failed to load scheduled posts", exc_info=exc)
            return [], "بارگذاری پست‌های زمان‌بندی شده با خطا مواجه شد."

    def render(self, request: Request, user: models.AdminUser, db: Session) -> object:
        accounts, account_error = self._load_accounts(db)
        posts, post_error = self._load_posts(db)
        errors = [msg for msg in (account_error, post_error) if msg]
        context = {
            "request": request,
            "user": user,
            "accounts": accounts,
            "posts": posts,
            "active_page": "scheduler",
        }
        if errors:
            context["error"] = " ".join(dict.fromkeys(errors))
        return self.templates.TemplateResponse("scheduler.html", context)

    def create_schedule(
        self,
        *,
        request: Request,
        db: Session,
        user: models.AdminUser,
        account_id: int,
        title: str,
        content: Optional[str],
        video_url: Optional[str],
        scheduled_time: str,
    ) -> RedirectResponse | object:
        raw_time = scheduled_time.strip()
        if raw_time.endswith("Z"):
            raw_time = raw_time[:-1]
        try:
            schedule_dt = datetime.fromisoformat(raw_time)
        except ValueError:
            accounts, account_error = self._load_accounts(db)
            posts, post_error = self._load_posts(db)
            self.logger.warning(
                "Invalid schedule timestamp provided",
                extra={"user_id": user.id, "account_id": account_id, "value": scheduled_time},
            )
            context = {
                "request": request,
                "user": user,
                "accounts": accounts,
                "posts": posts,
                "error": "فرمت تاریخ/زمان نامعتبر است.",
                "active_page": "scheduler",
            }
            extra_errors = [msg for msg in (account_error, post_error) if msg]
            if extra_errors:
                context.setdefault("load_error", " ".join(dict.fromkeys(extra_errors)))
            return self.templates.TemplateResponse("scheduler.html", context, status_code=400)

        text_content = content.strip() or None if content else None
        video_link = video_url.strip() or None if video_url else None

        service = ScheduledPostService(db)
        try:
            post = service.create_post(
                account_id=account_id,
                title=title,
                content=text_content,
                video_url=video_link,
                scheduled_time=schedule_dt,
            )
        except DatabaseServiceError as exc:
            self.logger.error(
                "Failed to create scheduled post",
                extra={"user_id": user.id, "account_id": account_id},
                exc_info=exc,
            )
            accounts, account_error = self._load_accounts(db)
            posts, post_error = self._load_posts(db)
            context = {
                "request": request,
                "user": user,
                "accounts": accounts,
                "posts": posts,
                "error": "ثبت برنامه انتشار با خطا مواجه شد.",
                "active_page": "scheduler",
            }
            extra_errors = [msg for msg in (account_error, post_error) if msg]
            if extra_errors:
                context.setdefault("load_error", " ".join(dict.fromkeys(extra_errors)))
            return self.templates.TemplateResponse("scheduler.html", context, status_code=500)

        self.logger.info(
            "Post scheduled",
            extra={
                "user_id": user.id,
                "account_id": account_id,
                "post_id": post.id,
                "scheduled_time": schedule_dt.isoformat(),
            },
        )
        return RedirectResponse(url="/scheduler", status_code=302)

    def delete_schedule(
        self,
        *,
        request: Request,
        db: Session,
        user: models.AdminUser,
        post_id: int,
    ) -> RedirectResponse | object:
        service = ScheduledPostService(db)
        try:
            deleted = service.delete_post(post_id)
        except DatabaseServiceError as exc:
            self.logger.error(
                "Failed to delete scheduled post",
                extra={"user_id": user.id, "post_id": post_id},
                exc_info=exc,
            )
            accounts, account_error = self._load_accounts(db)
            posts, post_error = self._load_posts(db)
            context = {
                "request": request,
                "user": user,
                "accounts": accounts,
                "posts": posts,
                "error": "حذف پست زمان‌بندی شده با خطا مواجه شد.",
                "active_page": "scheduler",
            }
            extra_errors = [msg for msg in (account_error, post_error) if msg]
            if extra_errors:
                context.setdefault("load_error", " ".join(dict.fromkeys(extra_errors)))
            return self.templates.TemplateResponse("scheduler.html", context, status_code=500)

        if deleted:
            self.logger.info(
                "Scheduled post deleted",
                extra={"user_id": user.id, "post_id": post_id},
            )
        else:
            self.logger.warning(
                "Attempted to delete non-existent scheduled post",
                extra={"user_id": user.id, "post_id": post_id},
            )
        return RedirectResponse(url="/scheduler", status_code=302)
