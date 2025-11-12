"""Presenter logic for the content scheduler."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.services.data_access import (
    DatabaseServiceError,
    ScheduledPostService,
    SocialAccountService,
)

from .helpers import is_ajax_request

@dataclass(slots=True)
class SchedulerPresenter:
    """Prepare view models and handle scheduled post flows."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.scheduler")

    @staticmethod
    def _is_ajax(request: Request) -> bool:
        """Return True when the request originates from an AJAX call."""

        return is_ajax_request(request)

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

    @staticmethod
    def _serialize_posts(posts: list[models.ScheduledPost]) -> list[dict[str, object]]:
        """Convert post models into JSON serialisable dictionaries."""

        serialised: list[dict[str, object]] = []
        for post in posts:
            account_name = "-"
            account_platform = ""
            if post.account:
                account_name = post.account.display_name
                account_platform = post.account.platform
            serialised.append(
                {
                    "id": post.id,
                    "title": post.title,
                    "account": account_name,
                    "account_platform": account_platform,
                    "scheduled_time": post.scheduled_time.isoformat() if post.scheduled_time else "",
                    "scheduled_time_display": post.scheduled_time.strftime("%Y-%m-%d %H:%M")
                    if post.scheduled_time
                    else "",
                    "status": post.status or "pending",
                    "video_url": post.video_url or "",
                    "content": post.content or "",
                }
            )
        return serialised

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
        return self.templates.TemplateResponse(request, "scheduler.html", context)

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
            if self._is_ajax(request):
                payload = {
                    "success": False,
                    "error": "فرمت تاریخ/زمان نامعتبر است.",
                    "posts": self._serialize_posts(posts),
                }
                if extra_errors:
                    payload["warning"] = " ".join(dict.fromkeys(extra_errors))
                return JSONResponse(payload, status_code=400)
            return self.templates.TemplateResponse(
                request, "scheduler.html", context, status_code=400
            )

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
            if self._is_ajax(request):
                payload = {
                    "success": False,
                    "error": "ثبت برنامه انتشار با خطا مواجه شد.",
                    "posts": self._serialize_posts(posts),
                }
                if extra_errors:
                    payload["warning"] = " ".join(dict.fromkeys(extra_errors))
                return JSONResponse(payload, status_code=500)
            return self.templates.TemplateResponse(
                request, "scheduler.html", context, status_code=500
            )

        self.logger.info(
            "Post scheduled",
            extra={
                "user_id": user.id,
                "account_id": account_id,
                "post_id": post.id,
                "scheduled_time": schedule_dt.isoformat(),
            },
        )
        posts, post_error = self._load_posts(db)
        if self._is_ajax(request):
            payload: dict[str, object] = {
                "success": True,
                "message": "زمان‌بندی با موفقیت ثبت شد.",
                "posts": self._serialize_posts(posts),
            }
            if post_error:
                payload["warning"] = post_error
            return JSONResponse(payload, status_code=201)
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
            if self._is_ajax(request):
                payload = {
                    "success": False,
                    "error": "حذف پست زمان‌بندی شده با خطا مواجه شد.",
                    "posts": self._serialize_posts(posts),
                }
                if extra_errors:
                    payload["warning"] = " ".join(dict.fromkeys(extra_errors))
                return JSONResponse(payload, status_code=500)
            return self.templates.TemplateResponse(
                request, "scheduler.html", context, status_code=500
            )

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
        posts, post_error = self._load_posts(db)
        if self._is_ajax(request):
            payload: dict[str, object] = {
                "success": True,
                "message": "پست زمان‌بندی شده حذف شد.",
                "posts": self._serialize_posts(posts),
            }
            if post_error:
                payload["warning"] = post_error
            return JSONResponse(payload, status_code=200)
        return RedirectResponse(url="/scheduler", status_code=302)
