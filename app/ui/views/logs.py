"""Routes for viewing structured job logs in the admin UI."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.backend import auth, models
from app.backend.database import get_db

from ..app_presenters.logs_presenter import LogsPresenter

ADMIN_ROLES = [models.AdminRole.ADMIN, models.AdminRole.SUPERADMIN]


logger = logging.getLogger(__name__)


def create_router(presenter: LogsPresenter) -> APIRouter:
    router = APIRouter()

    @router.get("/logs")
    async def view_logs(request: Request, db: Session = Depends(get_db)):
        user = auth.get_logged_in_user(
            request,
            db,
            required_roles=ADMIN_ROLES,
            required_menu=models.AdminMenu.LOGS,
        )
        if not user:
            logger.info("Logs access redirected for unauthenticated user")
            return RedirectResponse(url="/login", status_code=302)
        return presenter.render(request, user, db)

    @router.get("/logs/{log_name}/stream")
    async def stream_log(log_name: str):
        sanitized = Path(log_name).name
        if sanitized != log_name or not sanitized.endswith(".log"):
            raise HTTPException(status_code=404, detail="Log file not found")

        log_path = presenter.log_directory / sanitized
        if not log_path.exists() or not log_path.is_file():
            raise HTTPException(status_code=404, detail="Log file not found")

        async def event_generator():
            try:
                last_position = log_path.stat().st_size
            except OSError:
                last_position = 0

            heartbeat_counter = 0

            try:
                while True:
                    await asyncio.sleep(1)
                    heartbeat_counter += 1

                    try:
                        current_size = log_path.stat().st_size
                    except OSError as exc:  # pragma: no cover - rare filesystem error
                        payload = json.dumps(
                            {
                                "level": "ERROR",
                                "badge_class": "danger",
                                "timestamp": "",
                                "message": "خطا در دسترسی به فایل لاگ",
                                "details": str(exc),
                            },
                            ensure_ascii=False,
                        )
                        yield f"event: error\ndata: {payload}\n\n"
                        break

                    if current_size < last_position:
                        last_position = 0

                    if current_size > last_position:
                        try:
                            with log_path.open("r", encoding="utf-8") as handle:
                                handle.seek(last_position)
                                new_data = handle.read()
                                last_position = handle.tell()
                        except OSError as exc:  # pragma: no cover - rare filesystem error
                            payload = json.dumps(
                                {
                                    "level": "ERROR",
                                    "badge_class": "danger",
                                    "timestamp": "",
                                    "message": "خطا در خواندن فایل لاگ",
                                    "details": str(exc),
                                },
                                ensure_ascii=False,
                            )
                            yield f"event: error\ndata: {payload}\n\n"
                            break

                        lines = [line.strip() for line in new_data.splitlines() if line.strip()]
                        if lines:
                            heartbeat_counter = 0
                            for line in lines:
                                entry = presenter.parse_log_line(line)
                                payload = json.dumps(entry, ensure_ascii=False)
                                yield f"data: {payload}\n\n"
                            continue

                    if heartbeat_counter >= 15:
                        heartbeat_counter = 0
                        yield ": keep-alive\n\n"
            except asyncio.CancelledError:  # pragma: no cover - cancellation by client
                raise

        headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)

    return router
