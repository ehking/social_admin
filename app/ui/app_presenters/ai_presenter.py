"""Presenter for AI workflow related responses."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.responses import JSONResponse

from app.backend.ai_workflow import get_ai_video_workflow


@dataclass(slots=True)
class AIVideoWorkflowPresenter:
    """Return structured data for the AI workflow API."""

    def as_response(self) -> JSONResponse:
        return JSONResponse(get_ai_video_workflow())
