"""Routes for the Text Graphy interface."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db
from app.backend.services.data_access import ServiceTokenService

from ..app_presenters.text_graphy_presenter import TextGraphyPresenter, TextGraphyTokenUsage


logger = logging.getLogger(__name__)


def _load_text_graphy_tokens(db: Session) -> list[TextGraphyTokenUsage]:
    service = ServiceTokenService(db)
    tokens: list[TextGraphyTokenUsage] = []
    try:
        stored_tokens = list(service.list_tokens())
    except Exception:  # pragma: no cover - database/IO defensive branch
        logger.exception("Failed to load service tokens for Text Graphy page")
        stored_tokens = []

    def is_relevant(token) -> bool:
        identifier = f"{getattr(token, 'name', '')} {getattr(token, 'key', '')}".lower()
        keywords = ("graphy", "coverr", "translate", "lyrics", "openai")
        return any(keyword in identifier for keyword in keywords)

    filtered = [token for token in stored_tokens if is_relevant(token)]
    if not filtered:
        filtered = stored_tokens[:2]

    for index, token in enumerate(filtered):
        tokens.append(
            TextGraphyTokenUsage(
                name=getattr(token, "name", ""),
                key=getattr(token, "key", ""),
                endpoint_url=getattr(token, "endpoint_url", None),
                is_active=index == 0,
            )
        )
    return tokens


def create_router(presenter: TextGraphyPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/text-graphy")
    async def text_graphy(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.TEXT_GRAPHY,
        )
        if not user:
            logger.info("Text Graphy page redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info("Rendering Text Graphy page", extra={"user_id": user.id})
        token_usage = _load_text_graphy_tokens(db)
        return presenter.render(request, user, token_usage=token_usage)

    @router.post("/text-graphy")
    async def create_text_graphy(
        request: Request,
        coverr_reference: str = Form(...),
        lyrics_text: str = Form(...),
        music_url: Optional[str] = Form(None),
        music_duration: Optional[str] = Form(None),
        db: Session = Depends(get_db),
    ):
        user = auth.get_logged_in_user(
            request,
            db,
            required_menu=models.AdminMenu.TEXT_GRAPHY,
        )
        if not user:
            logger.info("Text Graphy creation redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        logger.info(
            "Creating Text Graphy plan",
            extra={
                "user_id": user.id,
                "has_music_url": bool(music_url),
                "has_duration": bool(music_duration),
            },
        )
        return presenter.create_text_graphy(
            request=request,
            user=user,
            coverr_reference=coverr_reference,
            music_url=music_url,
            music_duration=music_duration,
            lyrics_text=lyrics_text,
            token_usage=_load_text_graphy_tokens(db),
        )

    return router
