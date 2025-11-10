"""Routes for managing social media accounts."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.accounts_presenter import AccountsPresenter


logger = logging.getLogger(__name__)


def create_router(presenter: AccountsPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/accounts")
    async def list_accounts(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.ACCOUNTS,
        )
        if not user:
            logger.info("Unauthenticated accounts list access redirected")
            return RedirectResponse(url="/login", status_code=302)
        logger.info("Rendering accounts list", extra={"user_id": user.id})
        return presenter.list_accounts(request, user, db)

    @router.get("/accounts/new")
    async def new_account(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.ACCOUNTS,
        )
        if not user:
            logger.info("Unauthenticated new account access redirected")
            return RedirectResponse(url="/login", status_code=302)
        logger.info("Rendering new account form", extra={"user_id": user.id})
        return presenter.account_form(request, user, db=db)

    @router.get("/accounts/{account_id}")
    async def edit_account(account_id: int, request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.ACCOUNTS,
        )
        if not user:
            logger.info("Unauthenticated account edit redirected", extra={"account_id": account_id})
            return RedirectResponse(url="/login", status_code=302)
        logger.info(
            "Rendering account edit form",
            extra={"user_id": user.id, "account_id": account_id},
        )
        return presenter.account_form(request, user, db=db, account_id=account_id)

    @router.post("/accounts")
    async def save_account(
        request: Request,
        platform: str = Form(...),
        display_name: str = Form(...),
        page_id: Optional[str] = Form(None),
        oauth_token: Optional[str] = Form(None),
        youtube_channel_id: Optional[str] = Form(None),
        telegram_chat_id: Optional[str] = Form(None),
        account_id: Optional[int] = Form(None),
        db: Session = Depends(get_db),
    ):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.ACCOUNTS,
        )
        if not user:
            logger.info("Unauthenticated account save redirected")
            return RedirectResponse(url="/login", status_code=302)
        logger.info(
            "Saving account",
            extra={
                "user_id": user.id,
                "platform": platform,
                "account_id": account_id,
                "has_oauth_token": bool(oauth_token),
            },
        )
        return presenter.save_account(
            request=request,
            db=db,
            user=user,
            platform=platform,
            display_name=display_name,
            page_id=page_id,
            oauth_token=oauth_token,
            youtube_channel_id=youtube_channel_id,
            telegram_chat_id=telegram_chat_id,
            account_id=account_id,
        )

    @router.post("/accounts/delete")
    async def delete_account(
        request: Request,
        account_id: int = Form(...),
        db: Session = Depends(get_db),
    ):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.ACCOUNTS,
        )
        if not user:
            logger.info(
                "Unauthenticated account delete redirected",
                extra={"account_id": account_id},
            )
            return RedirectResponse(url="/login", status_code=302)
        logger.info(
            "Deleting account",
            extra={"user_id": user.id, "account_id": account_id},
        )
        return presenter.delete_account(db=db, user=user, account_id=account_id)

    return router
