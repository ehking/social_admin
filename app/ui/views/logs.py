"""Routes for viewing structured job logs in the admin UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.logs_presenter import LogsPresenter

ADMIN_ROLES = [models.AdminRole.ADMIN, models.AdminRole.SUPERADMIN]


def create_router(presenter: LogsPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/logs")
    async def view_logs(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_roles=ADMIN_ROLES,
            required_menu=models.AdminMenu.LOGS,
        )
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return presenter.render(request, user, db)

    return router
