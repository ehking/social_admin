"""Presenter utilities for managing social accounts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.services.data_access import (
    DatabaseServiceError,
    EntityNotFoundError,
    SocialAccountService,
)

from .helpers import build_layout_context, is_ajax_request, json_error, json_success


@dataclass(slots=True)
class AccountsPresenter:
    """Prepare view models and orchestrate CRUD flows for accounts."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.accounts")

    def _load_accounts(self, db: Session) -> tuple[list[models.SocialAccount], str | None]:
        service = SocialAccountService(db)
        try:
            accounts = list(service.list_accounts_desc())
            return accounts, None
        except DatabaseServiceError as exc:
            self.logger.error("Failed to load social accounts", exc_info=exc)
            return [], "بارگذاری حساب‌ها با خطا مواجه شد."

    def list_accounts(self, request: Request, user: models.AdminUser, db: Session) -> object:
        accounts, load_error = self._load_accounts(db)
        context = {
            "request": request,
            "user": user,
            "accounts": accounts,
            "active_page": "accounts",
        }
        if load_error:
            context["error"] = load_error
        return self.templates.TemplateResponse("accounts.html", context)

    def account_form(
        self,
        request: Request,
        user: models.AdminUser,
        *,
        db: Session,
        account_id: Optional[int] = None,
    ) -> object:
        account = None
        error_message: Optional[str] = None
        if account_id:
            service = SocialAccountService(db)
            try:
                account = service.get_account(account_id)
            except DatabaseServiceError as exc:
                self.logger.error(
                    "Failed to load account form data",
                    extra={"account_id": account_id},
                    exc_info=exc,
                )
                error_message = "بارگذاری حساب انتخاب‌شده با خطا مواجه شد."
            if account is None and error_message is None:
                error_message = "حساب مورد نظر یافت نشد."
        context = {
            "request": request,
            "user": user,
            "account": account,
            "active_page": "accounts",
        }
        if error_message:
            context["error"] = error_message
        return self.templates.TemplateResponse("account_form.html", context)

    def save_account(
        self,
        *,
        request: Request,
        db: Session,
        user: models.AdminUser,
        platform: str,
        display_name: str,
        page_id: Optional[str],
        oauth_token: Optional[str],
        youtube_channel_id: Optional[str],
        telegram_chat_id: Optional[str],
        account_id: Optional[int],
    ) -> RedirectResponse | object:
        service = SocialAccountService(db)

        def _clean(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            value = value.strip()
            return value or None

        cleaned_data = {
            "platform": platform,
            "display_name": display_name.strip(),
            "page_id": _clean(page_id),
            "oauth_token": _clean(oauth_token),
            "youtube_channel_id": _clean(youtube_channel_id),
            "telegram_chat_id": _clean(telegram_chat_id),
        }

        try:
            account, created = service.save_account(
                account_id=int(account_id) if account_id else None,
                data=cleaned_data,
            )
        except EntityNotFoundError as exc:
            self.logger.warning(
                "Attempted to update non-existent account",
                extra={"user_id": user.id, "account_id": account_id},
            )
            accounts, load_error = self._load_accounts(db)
            error_message = str(exc)
            if is_ajax_request(request):
                payload: dict[str, object] = {}
                if load_error:
                    payload["warning"] = load_error
                return json_error(error_message, status_code=404, **payload)
            context = {
                "request": request,
                "user": user,
                "accounts": accounts,
                "error": error_message,
                "active_page": "accounts",
            }
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse("accounts.html", context, status_code=404)
        except DatabaseServiceError as exc:
            self.logger.error(
                "Failed to save account",
                extra={"user_id": user.id, "account_id": account_id},
                exc_info=exc,
            )
            accounts, load_error = self._load_accounts(db)
            error_message = "ذخیره حساب با خطا مواجه شد."
            if is_ajax_request(request):
                payload: dict[str, object] = {}
                if load_error:
                    payload["warning"] = load_error
                return json_error(error_message, status_code=500, **payload)
            context = {
                "request": request,
                "user": user,
                "accounts": accounts,
                "error": error_message,
                "active_page": "accounts",
            }
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse("accounts.html", context, status_code=500)

        action = "created" if created else "updated"
        self.logger.info(
            "Account %s",
            action,
            extra={"user_id": user.id, "account_id": account.id, "platform": account.platform},
        )
        if is_ajax_request(request):
            message = "حساب جدید با موفقیت ایجاد شد." if created else "اطلاعات حساب با موفقیت به‌روزرسانی شد."
            return json_success(message, redirect="/accounts")
        return RedirectResponse(url="/accounts", status_code=302)

    def delete_account(
        self,
        *,
        request: Request,
        db: Session,
        user: models.AdminUser,
        account_id: int,
    ) -> RedirectResponse | object:
        service = SocialAccountService(db)
        try:
            deleted = service.delete_account(account_id)
        except DatabaseServiceError as exc:
            self.logger.error(
                "Failed to delete account",
                extra={"user_id": user.id, "account_id": account_id},
                exc_info=exc,
            )
            accounts, load_error = self._load_accounts(db)
            error_message = "حذف حساب با خطا مواجه شد."
            if is_ajax_request(request):
                payload: dict[str, object] = {}
                if load_error:
                    payload["warning"] = load_error
                return json_error(error_message, status_code=500, **payload)
            context = {
                "request": request,
                "user": user,
                "accounts": accounts,
                "error": error_message,
                "active_page": "accounts",
            }
            if load_error:
                context.setdefault("load_error", load_error)
            return self.templates.TemplateResponse("accounts.html", context, status_code=500)

        if deleted:
            self.logger.info(
                "Account deleted",
                extra={"user_id": user.id, "account_id": account_id},
            )
        else:
            self.logger.warning(
                "Attempted to delete non-existent account",
                extra={"user_id": user.id, "account_id": account_id},
            )
        if is_ajax_request(request):
            if deleted:
                return json_success("حساب با موفقیت حذف شد.", redirect="/accounts")
            return json_error("حساب مورد نظر یافت نشد.", status_code=404)
        return RedirectResponse(url="/accounts", status_code=302)
