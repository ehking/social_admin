"""Routes serving the internal project documentation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth
from app.backend.database import get_db

from ..app_presenters.documentation_presenter import DocumentationPresenter


def create_router(presenter: DocumentationPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/documentation")
    async def documentation(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(request, db)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        return presenter.render(request, user)

    return router
