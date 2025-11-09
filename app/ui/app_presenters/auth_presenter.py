"""Presenters responsible for authentication views."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import auth, models


@dataclass(slots=True)
class AuthPresenter:
    """Encapsulates the presentation logic for authentication related views."""

    templates: Jinja2Templates
    logger: logging.Logger = logging.getLogger("app.ui.auth")

    def login_form(self, request: Request) -> RedirectResponse | object:
        """Render the login form or redirect authenticated users."""

        user_id = request.session.get("user_id")
        if user_id:
            self.logger.debug(
                "Authenticated user attempted to access login form",
                extra={"user_id": user_id},
            )
            return RedirectResponse(url="/", status_code=302)
        return self.templates.TemplateResponse("login.html", {"request": request})

    async def login(self, request: Request, db: Session) -> RedirectResponse | object:
        """Handle login submissions and redirect appropriately."""

        form = await request.form()
        username = form.get("username", "").strip()
        password = form.get("password", "")

        user = db.query(models.AdminUser).filter_by(username=username).first()
        if not user or not auth.verify_password(password, user.password_hash):
            self.logger.warning(
                "Failed login attempt",
                extra={"username": username, "ip": request.client.host if request.client else None},
            )
            return self.templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "نام کاربری یا رمز عبور نادرست است."},
                status_code=400,
            )

        request.session["user_id"] = user.id
        self.logger.info(
            "User logged in",
            extra={"user_id": user.id, "username": username, "ip": request.client.host if request.client else None},
        )
        return RedirectResponse(url="/", status_code=302)

    def logout(self, request: Request) -> RedirectResponse:
        """Clear the session for the current user."""

        user_id: Optional[int] = request.session.get("user_id")
        request.session.clear()
        if user_id:
            self.logger.info("User logged out", extra={"user_id": user_id})
        return RedirectResponse(url="/login", status_code=302)
