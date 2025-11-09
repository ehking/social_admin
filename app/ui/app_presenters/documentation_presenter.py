"""Presenter for serving project documentation within the UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.backend import models

from .helpers import build_layout_context


@dataclass(slots=True)
class DocumentationPresenter:
    """Prepare the documentation page view model."""

    templates: Jinja2Templates
    spec_path: Path = field(default_factory=lambda: Path("docs/project_spec.md"))

    def render(
        self,
        request: Request,
        user: models.AdminUser | None,
        db: Session | None = None,
    ) -> object:
        """Render the documentation page."""

        content = self._load_spec_text()
        if db is not None and user is not None:
            context: Dict[str, Any] = build_layout_context(
                request=request,
                user=user,
                db=db,
                active_page="documentation",
                spec_text=content,
            )
        else:
            context = {
                "request": request,
                "user": user,
                "spec_text": content,
                "active_page": "documentation",
            }
        return self.templates.TemplateResponse("documentation.html", context)

    def _load_spec_text(self) -> str:
        try:
            return self.spec_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return "مستندات پروژه یافت نشد."  # "Documentation file not found."
        except OSError as exc:
            return f"خطا در خواندن مستندات: {exc}"  # "Error reading documentation"
