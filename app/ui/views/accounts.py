"""Routes for managing social media accounts."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth
from app.backend.database import get_db

from ..app_presenters.accounts_presenter import AccountsPresenter


def create_router(presenter: AccountsPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/accounts")
    async def list_accounts(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(request, db)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return presenter.list_accounts(request, user, db)

    @router.get("/accounts/new")
    async def new_account(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(request, db)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return presenter.account_form(request, user, db=db)

    @router.get("/accounts/{account_id}")
    async def edit_account(account_id: int, request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(request, db)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
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
        user = auth.get_logged_in_user(request, db)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
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
        user = auth.get_logged_in_user(request, db)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return presenter.delete_account(db=db, user=user, account_id=account_id)

    return router
