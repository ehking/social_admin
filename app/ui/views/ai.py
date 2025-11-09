"""AI related API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..app_presenters.ai_presenter import AIVideoWorkflowPresenter


def create_router(presenter: AIVideoWorkflowPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/ai/video-workflow")
    async def ai_video_workflow():
        return presenter.as_response()

    return router
