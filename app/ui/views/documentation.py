"""Routes serving the internal project documentation."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.documentation_presenter import DocumentationPresenter


logger = logging.getLogger(__name__)


def create_router(presenter: DocumentationPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/documentation")
    async def documentation(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.DOCUMENTATION,
        )
        if not user:
            logger.info("Documentation access redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        return presenter.render(request, user, db)

    return router
