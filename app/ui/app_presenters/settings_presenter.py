"""Presenter utilities for settings management views."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.services import permissions as permissions_service

from .helpers import build_layout_context


@dataclass(slots=True)
class SettingsPresenter:
    """Encapsulates presentation logic for service token management."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.settings")

    def render(self, request: Request, user: models.AdminUser, db: Session) -> object:
        tokens = db.query(models.ServiceToken).all()
        context = build_layout_context(
            request=request,
            user=user,
            db=db,
            active_page="settings",
            tokens=tokens,
            permission_matrix=permissions_service.get_permission_matrix(db),
            menu_definitions=permissions_service.list_menu_definitions(),
            role_definitions=permissions_service.list_role_definitions(),
        )
        return self.templates.TemplateResponse("settings.html", context)

    def save_token(
        self,
        *,
        db: Session,
        user: models.AdminUser,
        name: str,
        key: str,
        value: str,
    ) -> RedirectResponse:
        token = db.query(models.ServiceToken).filter_by(key=key).first()
        if token:
            token.name = name
            token.value = value
            self.logger.info(
                "Service token updated",
                extra={"user_id": user.id, "token_id": token.id, "key": key},
            )
        else:
            token = models.ServiceToken(name=name, key=key, value=value)
            db.add(token)
            self.logger.info(
                "Service token created",
                extra={"user_id": user.id, "key": key},
            )
        db.commit()
        return RedirectResponse(url="/settings", status_code=302)

    def delete_token(
        self,
        *,
        db: Session,
        user: models.AdminUser,
        token_id: int,
    ) -> RedirectResponse:
        token = db.get(models.ServiceToken, token_id)
        if token:
            db.delete(token)
            db.commit()
            self.logger.info(
                "Service token deleted",
                extra={"user_id": user.id, "token_id": token_id},
            )
        return RedirectResponse(url="/settings", status_code=302)

    def update_permissions(
        self,
        *,
        db: Session,
        user: models.AdminUser,
        form_data: Mapping[str, object],
    ) -> RedirectResponse:
        updates = permissions_service.parse_permission_updates(form_data)
        permissions_service.apply_permission_updates(db, updates)
        self.logger.info(
            "Menu permissions updated",
            extra={"user_id": user.id},
        )
        return RedirectResponse(url="/settings", status_code=302)
