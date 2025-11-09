"""Routes for manual video creation UI."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth
from app.backend.database import get_db

from ..app_presenters.manual_video_presenter import ManualVideoPresenter


def create_router(presenter: ManualVideoPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/manual-video")
    async def manual_video(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(request, db)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
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
        db: Session = Depends(get_db),
    ):
        user = auth.get_logged_in_user(request, db)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return presenter.create_manual_video(
            request=request,
            db=db,
            user=user,
            title=title,
            description=description,
            media_url=media_url,
            media_type=media_type,
            campaign_name=campaign_name,
            campaign_description=campaign_description,
        )

    return router
