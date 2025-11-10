"""Routes for the scheduler UI."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.scheduler_presenter import SchedulerPresenter


logger = logging.getLogger(__name__)


def create_router(presenter: SchedulerPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/scheduler")
    async def scheduler(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.SCHEDULER,
        )
        if not user:
            logger.info("Scheduler access redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info("Rendering scheduler page", extra={"user_id": user.id})
        return presenter.render(request, user, db)

    @router.post("/scheduler")
    async def create_schedule(
        request: Request,
        account_id: int = Form(...),
        title: str = Form(...),
        content: Optional[str] = Form(None),
        video_url: Optional[str] = Form(None),
        scheduled_time: str = Form(...),
        db: Session = Depends(get_db),
    ):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.SCHEDULER,
        )
        if not user:
            logger.info("Schedule creation redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info(
            "Creating schedule",
            extra={
                "user_id": user.id,
                "account_id": account_id,
                "has_content": bool(content),
                "has_video_url": bool(video_url),
            },
        )
        return presenter.create_schedule(
            request=request,
            db=db,
            user=user,
            account_id=account_id,
            title=title,
            content=content,
            video_url=video_url,
            scheduled_time=scheduled_time,
        )

    @router.post("/scheduler/delete")
    async def delete_schedule(
        request: Request,
        post_id: int = Form(...),
        db: Session = Depends(get_db),
    ):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.SCHEDULER,
        )
        if not user:
            logger.info("Schedule delete redirected for unauthenticated user", extra={"post_id": post_id})
            return RedirectResponse(url="/login", status_code=302)
        logger.info(
            "Deleting schedule",
            extra={"user_id": user.id, "post_id": post_id},
        )
        return presenter.delete_schedule(db=db, user=user, post_id=post_id)

    return router
