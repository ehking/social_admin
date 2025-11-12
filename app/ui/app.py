"""Application factory for the UI layer following the MVP structure."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from http import cookies
from typing import Any, Dict
from threading import Thread
from time import perf_counter

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
try:  # pragma: no cover - optional dependency in minimal test environments
    from starlette.middleware.sessions import SessionMiddleware
except ImportError:  # pragma: no cover - fallback when itsdangerous is unavailable
    class _SessionDict(dict):  # type: ignore[override]
        """Minimal session mapping that tracks modifications."""

        def __init__(self, initial: Dict[str, Any], scope: Dict[str, Any]):
            super().__init__(initial)
            self._scope = scope

        def _mark_modified(self) -> None:
            self._scope["_session_modified"] = True

        def __setitem__(self, key: str, value: Any) -> None:
            self._mark_modified()
            super().__setitem__(key, value)

        def __delitem__(self, key: str) -> None:
            if key in self:
                self._mark_modified()
            super().__delitem__(key)

        def clear(self) -> None:  # type: ignore[override]
            if self:
                self._mark_modified()
            super().clear()

        def pop(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
            if key in self:
                self._mark_modified()
            return super().pop(key, default)

        def popitem(self) -> Any:  # type: ignore[override]
            if self:
                self._mark_modified()
            return super().popitem()

        def setdefault(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
            if key not in self:
                self._mark_modified()
            return super().setdefault(key, default)

        def update(self, *args, **kwargs) -> None:  # type: ignore[override]
            if args or kwargs:
                self._mark_modified()
            super().update(*args, **kwargs)

    class SessionMiddleware:  # type: ignore[override]
        """Fallback session middleware using simple HMAC-signed cookies."""

        def __init__(
            self,
            app,
            secret_key: str,
            session_cookie: str = "session",
        ) -> None:
            self.app = app
            self._secret = secret_key.encode("utf-8")
            self._cookie_name = session_cookie

        def _load_session(self, scope: Dict[str, Any]) -> Dict[str, Any]:
            cookie_header = ""
            for name, value in scope.get("headers", []):
                if name == b"cookie":
                    cookie_header = value.decode("latin1")
                    break
            if not cookie_header:
                return {}
            jar = cookies.SimpleCookie()
            jar.load(cookie_header)
            morsel = jar.get(self._cookie_name)
            if not morsel:
                return {}
            return self._decode_cookie(morsel.value)

        def _encode_cookie(self, data: Dict[str, Any]) -> str:
            payload = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
            signature = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()
            token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
            return f"{token}.{signature}"

        def _decode_cookie(self, value: str) -> Dict[str, Any]:
            try:
                payload_b64, signature = value.split(".", 1)
                padding = "=" * (-len(payload_b64) % 4)
                payload = base64.urlsafe_b64decode((payload_b64 + padding).encode("ascii"))
                expected = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(signature, expected):
                    return {}
                return json.loads(payload.decode("utf-8"))
            except Exception:
                return {}

        def _build_cookie_header(self, value: str) -> bytes:
            cookie_value = (
                f"{self._cookie_name}={value}; Path=/; HttpOnly; SameSite=lax"
            )
            return cookie_value.encode("ascii")

        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http":
                await self.app(scope, receive, send)
                return

            initial = self._load_session(scope)
            scope["_session_modified"] = False
            scope["session"] = _SessionDict(initial, scope)

            async def send_wrapper(message):
                if message.get("type") == "http.response.start" and scope.get(
                    "_session_modified",
                ):
                    session_data = dict(scope.get("session", {}))
                    token = self._encode_cookie(session_data)
                    headers = list(message.get("headers", []))
                    headers.append((b"set-cookie", self._build_cookie_header(token)))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_wrapper)

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
from app.backend.logging_config import configure_logging
from app.backend.monitoring import configure_monitoring
from app.backend.services import JobProcessor
from app.backend.services.text_graphy import TextGraphyService
from app.backend.services.permissions import ensure_default_permissions

from .app_presenters.accounts_presenter import AccountsPresenter
from .app_presenters.ai_presenter import AIVideoWorkflowPresenter
from .app_presenters.auth_presenter import AuthPresenter
from .app_presenters.dashboard_presenter import DashboardPresenter
from .app_presenters.documentation_presenter import DocumentationPresenter
from .app_presenters.logs_presenter import LogsPresenter
from .app_presenters.helpers import is_ajax_request
from .app_presenters.manual_video_presenter import ManualVideoPresenter
from .app_presenters.media_library_presenter import MediaLibraryPresenter
from .app_presenters.text_graphy_presenter import TextGraphyPresenter
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
    media_library,
    text_graphy,
    logs,
    scheduler,
    settings,
)

configure_logging()
logger = logging.getLogger(__name__)
ajax_logger = logging.getLogger("app.ui.ajax")

REQUEST_COUNT = Counter(
    "social_admin_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "social_admin_request_latency_seconds", "HTTP request latency", ["method", "path"]
)


def _initialize_admin_security() -> None:
    db = SessionLocal()
    try:
        auth.ensure_default_admin(db)
        ensure_default_permissions(db)
        logger.info("Startup complete and default access controls ensured.")
    finally:
        db.close()


def _schedule_job_reprocessing() -> None:
    processor = JobProcessor()

    def _runner() -> None:
        processor.process_pending_jobs()

    thread = Thread(target=_runner, name="job-reprocessor", daemon=True)
    thread.start()


def create_app() -> FastAPI:
    app = FastAPI(title="Social Admin")
    app.add_middleware(SessionMiddleware, secret_key="super-secret-session-key")
    app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")

    templates = Jinja2Templates(directory="app/ui/templates")

    logger.info("Initialising Social Admin FastAPI application")

    configure_monitoring(app)

    auth_presenter = AuthPresenter(templates)
    dashboard_presenter = DashboardPresenter(templates)
    settings_presenter = SettingsPresenter(templates)
    accounts_presenter = AccountsPresenter(templates)
    scheduler_presenter = SchedulerPresenter(templates)
    documentation_presenter = DocumentationPresenter(templates)
    ai_presenter = AIVideoWorkflowPresenter()
    manual_video_presenter = ManualVideoPresenter(templates)
    media_library_presenter = MediaLibraryPresenter(templates)
    text_graphy_service = TextGraphyService()
    text_graphy_presenter = TextGraphyPresenter(templates, text_graphy_service)
    logs_presenter = LogsPresenter(templates)

    app.include_router(auth_views.create_router(auth_presenter))
    app.include_router(dashboard.create_router(dashboard_presenter))
    app.include_router(settings.create_router(settings_presenter))
    app.include_router(accounts.create_router(accounts_presenter))
    app.include_router(scheduler.create_router(scheduler_presenter))
    app.include_router(manual_video.create_router(manual_video_presenter))
    app.include_router(media_library.create_router(media_library_presenter))
    app.include_router(text_graphy.create_router(text_graphy_presenter))
    app.include_router(ai.create_router(ai_presenter))
    app.include_router(documentation.create_router(documentation_presenter))
    app.include_router(metrics.create_router())
    app.include_router(logs.create_router(logs_presenter))

    logger.info("Registered routers for application", extra={"routers": len(app.routes)})

    @app.middleware("http")
    async def ajax_logging_middleware(request: Request, call_next):
        ajax_request = is_ajax_request(request)
        start_time = perf_counter() if ajax_request else None
        response: Response = await call_next(request)
        if ajax_request:
            duration = 0.0
            if start_time is not None:
                duration = perf_counter() - start_time
            client_ip = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent")
            referer = request.headers.get("referer")
            extra = {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration": round(duration, 6),
                "client": client_ip,
                "user_agent": user_agent,
                "referer": referer,
                "outcome": "success" if response.status_code < 400 else "error",
            }
            ajax_logger.info("ajax_request", extra=extra)
        return response

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start_time = perf_counter()
        path = request.url.path
        method = request.method
        client = request.client.host if request.client else None

        logger.info(
            "Handling request",
            extra={
                "method": method,
                "path": path,
                "client": client,
            },
        )
        try:
            response: Response = await call_next(request)
        except Exception:
            elapsed = perf_counter() - start_time
            logger.exception(
                "Request raised an unhandled exception",
                extra={
                    "method": method,
                    "path": path,
                    "client": client,
                    "duration": elapsed,
                },
            )
            raise

        elapsed = perf_counter() - start_time
        status = response.status_code

        REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
        REQUEST_LATENCY.labels(method=method, path=path).observe(elapsed)
        logger.info(
            "Completed request",
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
        _initialize_admin_security()
        _schedule_job_reprocessing()

    return app
