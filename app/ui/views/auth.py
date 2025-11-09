"""Authentication related routes for the UI layer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.backend.database import get_db

from ..app_presenters.auth_presenter import AuthPresenter


def create_router(presenter: AuthPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/login")
    async def login_form(request: Request):
        return presenter.login_form(request)

    @router.post("/login")
    async def login(request: Request, db: Session = Depends(get_db)):
        return await presenter.login(request, db)

    @router.post("/logout")
    async def logout(request: Request):
        return presenter.logout(request)

    return router
