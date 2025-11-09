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


@dataclass(slots=True)
class AccountsPresenter:
    """Prepare view models and orchestrate CRUD flows for accounts."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.accounts")

    def list_accounts(self, request: Request, user: models.AdminUser, db: Session) -> object:
        accounts = (
            db.query(models.SocialAccount)
            .order_by(models.SocialAccount.created_at.desc())
            .all()
        )
        context = {
            "request": request,
            "user": user,
            "accounts": accounts,
            "active_page": "accounts",
        }
        return self.templates.TemplateResponse("accounts.html", context)

    def account_form(
        self,
        request: Request,
        user: models.AdminUser,
        *,
        db: Session,
        account_id: Optional[int] = None,
    ) -> object:
        account = db.get(models.SocialAccount, account_id) if account_id else None
        context = {
            "request": request,
            "user": user,
            "account": account,
            "active_page": "accounts",
        }
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
    ) -> RedirectResponse:
        if account_id:
            account = db.get(models.SocialAccount, int(account_id))
            if not account:
                self.logger.warning(
                    "Attempted to update non-existent account",
                    extra={"user_id": user.id, "account_id": account_id},
                )
                return RedirectResponse(url="/accounts", status_code=302)
        else:
            account = models.SocialAccount(platform=platform, display_name=display_name)
            db.add(account)
            self.logger.info(
                "Creating new account",
                extra={"user_id": user.id, "platform": platform},
            )

        def _clean(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            value = value.strip()
            return value or None

        account.platform = platform
        account.display_name = display_name.strip()
        account.page_id = _clean(page_id)
        account.oauth_token = _clean(oauth_token)
        account.youtube_channel_id = _clean(youtube_channel_id)
        account.telegram_chat_id = _clean(telegram_chat_id)

        db.commit()
        self.logger.info(
            "Account saved",
            extra={"user_id": user.id, "account_id": account.id, "platform": account.platform},
        )
        return RedirectResponse(url="/accounts", status_code=302)

    def delete_account(
        self,
        *,
        db: Session,
        user: models.AdminUser,
        account_id: int,
    ) -> RedirectResponse:
        account = db.get(models.SocialAccount, account_id)
        if account:
            db.delete(account)
            db.commit()
            self.logger.info(
                "Account deleted",
                extra={"user_id": user.id, "account_id": account_id, "platform": account.platform},
            )
        return RedirectResponse(url="/accounts", status_code=302)
