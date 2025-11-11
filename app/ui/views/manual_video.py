"""Routes for manual video creation UI."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.manual_video_presenter import ManualVideoPresenter


logger = logging.getLogger(__name__)


def create_router(presenter: ManualVideoPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/manual-video")
    async def manual_video(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.MANUAL_VIDEO,
        )
        if not user:
            logger.info("Manual video page redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info("Rendering manual video page", extra={"user_id": user.id})
        return presenter.render(request, user, db)

    @router.post("/manual-video")
    async def create_manual_video(
        request: Request,
        title: str = Form(...),
        description: Optional[str] = Form(None),
        media_url: str = Form(...),
        media_type: Optional[str] = Form(None),
        campaign_name: str = Form(...),
        campaign_description: Optional[str] = Form(None),
        ai_tool: str = Form(...),
        db: Session = Depends(get_db),
    ):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.MANUAL_VIDEO,
        )
        if not user:
            logger.info("Manual video creation redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info(
            "Creating manual video job",
            extra={
                "user_id": user.id,
                "has_description": bool(description),
                "media_type": media_type,
                "campaign_name": campaign_name,
            },
        )
        return await presenter.create_manual_video(
            request=request,
            db=db,
            user=user,
            title=title,
            description=description,
            media_url=media_url,
            media_type=media_type,
            campaign_name=campaign_name,
            campaign_description=campaign_description,
            ai_tool=ai_tool,
        )

    return router
