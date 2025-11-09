"""Dashboard view routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth
from app.backend.database import get_db

from ..app_presenters.dashboard_presenter import DashboardPresenter


logger = logging.getLogger(__name__)


def create_router(presenter: DashboardPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    async def dashboard(request: Request, db: Session = Depends(get_db)):
        logger.info("Dashboard requested")
        user = auth.get_logged_in_user(request, db)
        if not user:
            logger.info("Unauthenticated dashboard access redirected")
            return RedirectResponse(url="/login", status_code=302)
        logger.info("Rendering dashboard", extra={"user_id": user.id})
        return presenter.render(request, user, db)

    return router
