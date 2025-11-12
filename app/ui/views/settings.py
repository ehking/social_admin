"""Settings and token management routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.settings_presenter import SettingsPresenter

ADMIN_ROLES = [models.AdminRole.ADMIN, models.AdminRole.SUPERADMIN]


logger = logging.getLogger(__name__)


def create_router(presenter: SettingsPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/settings")
    async def settings(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_roles=ADMIN_ROLES,
            required_menu=models.AdminMenu.SETTINGS,
        )
        if not user:
            logger.info("Settings access denied for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info("Rendering settings page", extra={"user_id": user.id})
        return presenter.render(request, user, db)

    @router.post("/settings")
    async def create_or_update_token(
        request: Request,
        name: str = Form(...),
        key: str = Form(...),
        value: str = Form(...),
        endpoint_url: str | None = Form(None),
        db: Session = Depends(get_db),
    ):
        user = auth.get_logged_in_user(
            request,
            db,
            required_roles=ADMIN_ROLES,
            required_menu=models.AdminMenu.SETTINGS,
        )
        if not user:
            logger.info("Token save denied for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        return presenter.save_token(
            request=request,
            db=db,
            user=user,
            name=name,
            key=key,
            value=value,
            endpoint_url=endpoint_url,
        )

    @router.post("/settings/delete")
    async def delete_token(
        request: Request,
        token_id: int = Form(...),
        db: Session = Depends(get_db),
    ):
        user = auth.get_logged_in_user(
            request,
            db,
            required_roles=ADMIN_ROLES,
            required_menu=models.AdminMenu.SETTINGS,
        )
        if not user:
            logger.info("Token delete denied for unauthenticated user", extra={"token_id": token_id})
            return RedirectResponse(url="/login", status_code=302)
        return presenter.delete_token(
            request=request,
            db=db,
            user=user,
            token_id=token_id,
        )

    @router.post("/settings/permissions")
    async def update_permissions(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_roles=[models.AdminRole.SUPERADMIN],
            required_menu=models.AdminMenu.SETTINGS,
        )
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        form_data = await request.form()
        return presenter.update_permissions(
            request=request,
            db=db,
            user=user,
            form_data=form_data,
        )

    return router
