"""Shared presenter utilities for building template contexts."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.services import permissions as permissions_service


def is_ajax_request(request: Request) -> bool:
    """Return ``True`` when the incoming request originated from AJAX."""

    requested_with = request.headers.get("x-requested-with", "").lower()
    if requested_with == "xmlhttprequest":
        return True
    accept_header = request.headers.get("accept", "")
    return "application/json" in accept_header.lower()


def json_success(message: str | None = None, *, status_code: int = 200, **payload: Any) -> JSONResponse:
    """Construct a JSON success response with a consistent schema."""

    body: Dict[str, Any] = {"success": True}
    if message:
        body["message"] = message
    body.update(payload)
    return JSONResponse(body, status_code=status_code)


def json_error(message: str, *, status_code: int = 400, **payload: Any) -> JSONResponse:
    """Construct a JSON error response with a consistent schema."""

    body: Dict[str, Any] = {"success": False, "error": message}
    body.update(payload)
    return JSONResponse(body, status_code=status_code)


def build_layout_context(
    *,
    request: Request,
    user: models.AdminUser,
    db: Session,
    active_page: str,
    **extra: Any,
) -> Dict[str, Any]:
    """Compose the base context for templates that extend the main layout."""

    context: Dict[str, Any] = {
        "request": request,
        "user": user,
        "active_page": active_page,
        "menu_items": permissions_service.get_accessible_menu_items(db, user.role),
    }
    context.update(extra)
    return context
