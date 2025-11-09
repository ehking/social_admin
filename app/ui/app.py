"""Application factory for the UI layer following the MVP structure."""

from __future__ import annotations

import logging
from time import perf_counter

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
try:  # pragma: no cover - optional dependency in minimal test environments
    from starlette.middleware.sessions import SessionMiddleware
except ImportError:  # pragma: no cover - fallback when itsdangerous is unavailable
    class SessionMiddleware:  # type: ignore[override]
        def __init__(self, app, **_kwargs):
            self.app = app

        async def __call__(self, scope, receive, send):
            await self.app(scope, receive, send)

try:  # pragma: no cover - exercised indirectly in tests when dependency missing
    from prometheus_client import Counter, Histogram
except ImportError:  # pragma: no cover - fallback for test environments
    class _NoOpMetric:
        def labels(self, **_labels):  # type: ignore[override]
            return self

        def inc(self, *_args, **_kwargs) -> None:  # type: ignore[override]
            return None

        def observe(self, *_args, **_kwargs) -> None:  # type: ignore[override]
            return None

    def Counter(*_args, **_kwargs):  # type: ignore[misc]
        return _NoOpMetric()

    def Histogram(*_args, **_kwargs):  # type: ignore[misc]
        return _NoOpMetric()

from app.backend import auth
from app.backend.database import Base, SessionLocal, engine, run_startup_migrations
from app.backend.monitoring import configure_monitoring

from .app_presenters.accounts_presenter import AccountsPresenter
from .app_presenters.ai_presenter import AIVideoWorkflowPresenter
from .app_presenters.auth_presenter import AuthPresenter
from .app_presenters.dashboard_presenter import DashboardPresenter
from .app_presenters.documentation_presenter import DocumentationPresenter
from .app_presenters.logs_presenter import LogsPresenter
from .app_presenters.manual_video_presenter import ManualVideoPresenter
from .app_presenters.scheduler_presenter import SchedulerPresenter
from .app_presenters.settings_presenter import SettingsPresenter
from .views import (
    accounts,
    ai,
    auth as auth_views,
    dashboard,
    documentation,
    metrics,
    manual_video,
    logs,
    scheduler,
    settings,
)

logger = logging.getLogger(__name__)

REQUEST_COUNT = Counter(
    "social_admin_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "social_admin_request_latency_seconds", "HTTP request latency", ["method", "path"]
)


def _ensure_admin_user() -> None:
    db = SessionLocal()
    try:
        auth.ensure_default_admin(db)
        logger.info("Startup complete and default admin ensured.")
    finally:
        db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Social Admin")
    app.add_middleware(SessionMiddleware, secret_key="super-secret-session-key")
    app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")

    templates = Jinja2Templates(directory="app/ui/templates")

    configure_monitoring(app)

    auth_presenter = AuthPresenter(templates)
    dashboard_presenter = DashboardPresenter(templates)
    settings_presenter = SettingsPresenter(templates)
    accounts_presenter = AccountsPresenter(templates)
    scheduler_presenter = SchedulerPresenter(templates)
    documentation_presenter = DocumentationPresenter(templates)
    ai_presenter = AIVideoWorkflowPresenter()
    manual_video_presenter = ManualVideoPresenter(templates)
    logs_presenter = LogsPresenter(templates)

    app.include_router(auth_views.create_router(auth_presenter))
    app.include_router(dashboard.create_router(dashboard_presenter))
    app.include_router(settings.create_router(settings_presenter))
    app.include_router(accounts.create_router(accounts_presenter))
    app.include_router(scheduler.create_router(scheduler_presenter))
    app.include_router(manual_video.create_router(manual_video_presenter))
    app.include_router(ai.create_router(ai_presenter))
    app.include_router(documentation.create_router(documentation_presenter))
    app.include_router(metrics.create_router())
    app.include_router(logs.create_router(logs_presenter))

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start_time = perf_counter()
        response: Response = await call_next(request)
        elapsed = perf_counter() - start_time
        path = request.url.path
        method = request.method
        status = response.status_code

        REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
        REQUEST_LATENCY.labels(method=method, path=path).observe(elapsed)
        logger.debug(
            "Processed request",
            extra={
                "method": method,
                "path": path,
                "status": status,
                "duration": elapsed,
            },
        )
        return response

    @app.on_event("startup")
    def on_startup() -> None:
        Base.metadata.create_all(bind=engine)
        run_startup_migrations()
        _ensure_admin_user()

    return app
