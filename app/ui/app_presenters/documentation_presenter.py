"""Presenter for serving project documentation within the UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.backend import models


@dataclass(slots=True)
class DocumentationPresenter:
    """Prepare the documentation page view model."""

    templates: Jinja2Templates
    spec_path: Path = field(default_factory=lambda: Path("docs/project_spec.md"))

    def render(self, request: Request, user: models.AdminUser | None) -> object:
        """Render the documentation page."""

        content = self._load_spec_text()
        context: Dict[str, Any] = {
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
