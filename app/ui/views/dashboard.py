"""Dashboard view routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.dashboard_presenter import DashboardPresenter


def create_router(presenter: DashboardPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    async def dashboard(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.DASHBOARD,
        )
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return presenter.render(request, user, db)

    return router
