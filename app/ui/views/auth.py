"""Authentication related routes for the UI layer."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.backend.database import get_db

from ..app_presenters.auth_presenter import AuthPresenter


logger = logging.getLogger(__name__)


def create_router(presenter: AuthPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/login")
    async def login_form(request: Request):
        logger.info("Rendering login form")
        return presenter.login_form(request)

    @router.post("/login")
    async def login(request: Request, db: Session = Depends(get_db)):
        logger.info(
            "Login attempt received",
            extra={"ip": request.client.host if request.client else None},
        )
        return await presenter.login(request, db)

    @router.post("/logout")
    async def logout(request: Request):
        logger.info("Logout requested")
        return presenter.logout(request)

    return router
