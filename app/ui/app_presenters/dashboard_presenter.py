"""Presenter for the administrative dashboard view."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.services.data_access import (
    DatabaseServiceError,
    ScheduledPostService,
    ServiceTokenService,
    SocialAccountService,
)


@dataclass(slots=True)
class DashboardPresenter:
    """Prepare the dashboard view model."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.dashboard")

    def render(self, request: Request, user: models.AdminUser, db: Session) -> object:
        account_service = SocialAccountService(db)
        post_service = ScheduledPostService(db)
        token_service = ServiceTokenService(db)

        error_messages: list[str] = []

        try:
            accounts = list(account_service.list_accounts_desc())
        except DatabaseServiceError as exc:
            accounts = []
            error_messages.append("بارگذاری حساب‌ها با خطا مواجه شد.")
            self.logger.error("Failed to load social accounts", exc_info=exc)

        try:
            scheduled_posts = list(post_service.list_recent_posts(limit=10))
        except DatabaseServiceError as exc:
            scheduled_posts = []
            error_messages.append("بارگذاری پست‌های زمان‌بندی شده با خطا مواجه شد.")
            self.logger.error("Failed to load scheduled posts", exc_info=exc)

        try:
            tokens = list(token_service.list_tokens())
        except DatabaseServiceError as exc:
            tokens = []
            error_messages.append("بارگذاری توکن‌ها با خطا مواجه شد.")
            self.logger.error("Failed to load service tokens", exc_info=exc)

        context: Dict[str, Any] = {
            "request": request,
            "user": user,
            "accounts": accounts,
            "scheduled_posts": scheduled_posts,
            "tokens": tokens,
            "active_page": "dashboard",
        }
        if error_messages:
            # Preserve insertion order while removing duplicates
            unique_messages = list(dict.fromkeys(error_messages))
            context["error"] = " ".join(unique_messages)
        return self.templates.TemplateResponse("dashboard.html", context)
