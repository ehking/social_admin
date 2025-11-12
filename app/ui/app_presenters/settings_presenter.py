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
from app.backend.services.data_access import DatabaseServiceError, ServiceTokenService

from .helpers import is_ajax_request, json_error, json_success

@dataclass(slots=True)
class SettingsPresenter:
    """Encapsulates presentation logic for service token management."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.settings")

    def _load_tokens(self, db: Session) -> tuple[list[models.ServiceToken], str | None]:
        service = ServiceTokenService(db)
        try:
            tokens = list(service.list_tokens())
            return tokens, None
        except DatabaseServiceError as exc:
            self.logger.error("Failed to load service tokens", exc_info=exc)
            return [], "بارگذاری توکن‌ها با خطا مواجه شد."

    def render(self, request: Request, user: models.AdminUser, db: Session) -> object:
        tokens, load_error = self._load_tokens(db)
        context = {
            "request": request,
            "user": user,
            "tokens": tokens,
            "active_page": "settings",
        }
        if load_error:
            context["error"] = load_error
        return self.templates.TemplateResponse("settings.html", context)

    def save_token(
        self,
        *,
        request: Request,
        db: Session,
        user: models.AdminUser,
        name: str,
        key: str,
        value: str,
        endpoint_url: str | None,
    ) -> RedirectResponse | object:
        service = ServiceTokenService(db)
        try:
            token, created = service.upsert_token(
                name=name,
                key=key,
                value=value,
                endpoint_url=endpoint_url,
            )
        except DatabaseServiceError as exc:
            self.logger.error(
                "Failed to save service token",
                extra={"user_id": user.id, "key": key},
                exc_info=exc,
            )
            tokens, load_error = self._load_tokens(db)
            error_message = "ذخیره توکن با خطا مواجه شد."
            if is_ajax_request(request):
                payload: dict[str, object] = {}
                if load_error:
                    payload["warning"] = load_error
                return json_error(error_message, status_code=500, **payload)
            context = {
                "request": request,
                "user": user,
                "tokens": tokens,
                "error": error_message,
                "active_page": "settings",
            }
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse("settings.html", context, status_code=500)

        action = "created" if created else "updated"
        self.logger.info(
            "Service token %s",
            action,
            extra={"user_id": user.id, "token_id": token.id, "key": key},
        )
        if is_ajax_request(request):
            message = "توکن با موفقیت ایجاد شد." if created else "توکن با موفقیت به‌روزرسانی شد."
            return json_success(message, redirect="/settings")
        return RedirectResponse(url="/settings", status_code=302)

    def delete_token(
        self,
        *,
        request: Request,
        db: Session,
        user: models.AdminUser,
        token_id: int,
    ) -> RedirectResponse | object:
        service = ServiceTokenService(db)
        try:
            deleted = service.delete_token(token_id)
        except DatabaseServiceError as exc:
            self.logger.error(
                "Failed to delete service token",
                extra={"user_id": user.id, "token_id": token_id},
                exc_info=exc,
            )
            tokens, load_error = self._load_tokens(db)
            error_message = "حذف توکن با خطا مواجه شد."
            if is_ajax_request(request):
                payload: dict[str, object] = {}
                if load_error:
                    payload["warning"] = load_error
                return json_error(error_message, status_code=500, **payload)
            context = {
                "request": request,
                "user": user,
                "tokens": tokens,
                "error": error_message,
                "active_page": "settings",
            }
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse("settings.html", context, status_code=500)

        if deleted:
            self.logger.info(
                "Service token deleted",
                extra={"user_id": user.id, "token_id": token_id},
            )
        else:
            self.logger.warning(
                "Attempted to delete non-existent service token",
                extra={"user_id": user.id, "token_id": token_id},
            )
        if is_ajax_request(request):
            if deleted:
                return json_success("توکن با موفقیت حذف شد.", redirect="/settings")
            return json_error("توکن مورد نظر یافت نشد.", status_code=404)
        return RedirectResponse(url="/settings", status_code=302)

    def update_permissions(
        self,
        *,
        request: Request,
        db: Session,
        user: models.AdminUser,
        form_data: Mapping[str, object],
    ) -> RedirectResponse | object:
        updates = permissions_service.parse_permission_updates(form_data)
        permissions_service.apply_permission_updates(db, updates)
        self.logger.info(
            "Menu permissions updated",
            extra={"user_id": user.id},
        )
        if is_ajax_request(request):
            return json_success("مجوزهای دسترسی با موفقیت به‌روزرسانی شد.")
        return RedirectResponse(url="/settings", status_code=302)
