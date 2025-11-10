"""Presenter for the administrative dashboard view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import models

from .helpers import build_layout_context


@dataclass(slots=True)
class DashboardPresenter:
    """Prepare the dashboard view model."""

    templates: Jinja2Templates

    def render(self, request: Request, user: models.AdminUser, db: Session) -> object:
        accounts = (
            db.query(models.SocialAccount)
            .order_by(models.SocialAccount.created_at.desc())
            .all()
        )
        scheduled_posts = (
            db.query(models.ScheduledPost)
            .order_by(models.ScheduledPost.scheduled_time.asc())
            .limit(10)
            .all()
        )
        tokens = (
            db.query(models.ServiceToken)
            .order_by(models.ServiceToken.created_at.desc())
            .all()
        )

        context: Dict[str, Any] = build_layout_context(
            request=request,
            user=user,
            db=db,
            active_page="dashboard",
            accounts=accounts,
            scheduled_posts=scheduled_posts,
            tokens=tokens,
        )
        return self.templates.TemplateResponse("dashboard.html", context)
