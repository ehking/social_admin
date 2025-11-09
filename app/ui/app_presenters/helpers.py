"""Shared presenter utilities for building template contexts."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import Request
from sqlalchemy.orm import Session

from app.backend import models
from app.backend.services import permissions as permissions_service


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
