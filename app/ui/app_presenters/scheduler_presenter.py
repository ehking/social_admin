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

from .helpers import build_layout_context


@dataclass(slots=True)
class SchedulerPresenter:
    """Prepare view models and handle scheduled post flows."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.scheduler")

    def render(self, request: Request, user: models.AdminUser, db: Session) -> object:
        accounts = db.query(models.SocialAccount).all()
        posts = (
            db.query(models.ScheduledPost)
            .order_by(models.ScheduledPost.scheduled_time.desc())
            .all()
        )
        context = build_layout_context(
            request=request,
            user=user,
            db=db,
            active_page="scheduler",
            accounts=accounts,
            posts=posts,
        )
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
            accounts = db.query(models.SocialAccount).all()
            posts = (
                db.query(models.ScheduledPost)
                .order_by(models.ScheduledPost.scheduled_time.desc())
                .all()
            )
            self.logger.warning(
                "Invalid schedule timestamp provided",
                extra={"user_id": user.id, "account_id": account_id, "value": scheduled_time},
            )
            context = build_layout_context(
                request=request,
                user=user,
                db=db,
                active_page="scheduler",
                accounts=accounts,
                posts=posts,
                error="فرمت تاریخ/زمان نامعتبر است.",
            )
            return self.templates.TemplateResponse("scheduler.html", context, status_code=400)

        text_content = content.strip() or None if content else None
        video_link = video_url.strip() or None if video_url else None

        post = models.ScheduledPost(
            account_id=account_id,
            title=title,
            content=text_content,
            video_url=video_link,
            scheduled_time=schedule_dt,
        )
        db.add(post)
        db.commit()
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
        db: Session,
        user: models.AdminUser,
        post_id: int,
    ) -> RedirectResponse:
        post = db.get(models.ScheduledPost, post_id)
        if post:
            db.delete(post)
            db.commit()
            self.logger.info(
                "Scheduled post deleted",
                extra={"user_id": user.id, "post_id": post_id, "account_id": post.account_id},
            )
        return RedirectResponse(url="/scheduler", status_code=302)
