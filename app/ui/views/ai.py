"""AI related API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..app_presenters.ai_presenter import AIVideoWorkflowPresenter


logger = logging.getLogger(__name__)


def create_router(presenter: AIVideoWorkflowPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/ai/video-workflow")
    async def ai_video_workflow():
        logger.info("AI video workflow requested")
        return presenter.as_response()

    return router
