"""Routes for viewing structured job logs in the admin UI."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.logs_presenter import LogsPresenter

ADMIN_ROLES = [models.AdminRole.ADMIN, models.AdminRole.SUPERADMIN]


logger = logging.getLogger(__name__)


def create_router(presenter: LogsPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/logs")
    async def view_logs(request: Request, db: Session = Depends(get_db)):
        logger.info("Logs page requested")
        user = auth.get_logged_in_user(request, db, required_roles=ADMIN_ROLES)
        if not user:
            logger.info("Logs access redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info("Rendering logs page", extra={"user_id": user.id})
        return presenter.render(request, user)

    return router
