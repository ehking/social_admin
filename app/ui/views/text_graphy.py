"""Routes for the Text Graphy interface."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.text_graphy_presenter import TextGraphyPresenter


logger = logging.getLogger(__name__)


def create_router(presenter: TextGraphyPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/text-graphy")
    async def text_graphy(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.TEXT_GRAPHY,
        )
        if not user:
            logger.info("Text Graphy page redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info("Rendering Text Graphy page", extra={"user_id": user.id})
        return presenter.render(request, user)

    @router.post("/text-graphy")
    async def create_text_graphy(
        request: Request,
        coverr_reference: str = Form(...),
        lyrics_text: str = Form(...),
        music_url: Optional[str] = Form(None),
        music_duration: Optional[str] = Form(None),
        db: Session = Depends(get_db),
    ):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.TEXT_GRAPHY,
        )
        if not user:
            logger.info("Text Graphy creation redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info(
            "Creating Text Graphy plan",
            extra={
                "user_id": user.id,
                "has_music_url": bool(music_url),
                "has_duration": bool(music_duration),
            },
        )
        return presenter.create_text_graphy(
            request=request,
            user=user,
            coverr_reference=coverr_reference,
            music_url=music_url,
            music_duration=music_duration,
            lyrics_text=lyrics_text,
        )

    return router
