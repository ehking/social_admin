"""Routes for the media library section of the admin UI."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.media_library_presenter import MediaLibraryPresenter


logger = logging.getLogger(__name__)


def create_router(presenter: MediaLibraryPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/media-library")
    async def media_library(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.MEDIA_LIBRARY,
        )
        if not user:
            logger.info("Media library access redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info("Rendering media library", extra={"user_id": user.id})
        return presenter.render(request, user, db)

    return router
