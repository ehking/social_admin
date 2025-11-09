"""Monitoring helpers for the FastAPI application.

This module wires together error reporting via Sentry and exposes a lightweight
Prometheus-compatible metrics endpoint.  The configuration is intentionally
minimal so the application can run without any of the optional services
enabled.  When the appropriate environment variables are provided, the helpers
boot the integrations and make sure they are only attached once per application
instance.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Tuple

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse


class MonitoringConfigError(RuntimeError):
    """Raised when monitoring configuration cannot be applied."""


_MONITORING_STATE_FLAG = "monitoring_configured"


RequestLabel = Tuple[str, str, int]


@dataclass(slots=True)
class RequestMetrics:
    """Aggregate counters for HTTP request monitoring."""

    counts: Dict[RequestLabel, int] = field(default_factory=lambda: defaultdict(int))
    latency_totals: Dict[RequestLabel, float] = field(default_factory=lambda: defaultdict(float))
    latency_counts: Dict[RequestLabel, int] = field(default_factory=lambda: defaultdict(int))

    def record(self, method: str, path: str, status_code: int, duration: float) -> None:
        label = (method, path, status_code)
        self.counts[label] += 1
        self.latency_totals[label] += duration
        self.latency_counts[label] += 1

    def render(self) -> str:
        """Render the metrics using the Prometheus text exposition format."""

        lines = [
            "# HELP http_requests_total Total number of HTTP requests.",
            "# TYPE http_requests_total counter",
        ]
        for (method, path, status), count in sorted(self.counts.items()):
            lines.append(
                f'http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
            )

        lines.extend(
            [
                "# HELP http_request_duration_seconds Average time spent processing requests.",
                "# TYPE http_request_duration_seconds gauge",
            ]
        )
        for label, total_duration in sorted(self.latency_totals.items()):
            count = self.latency_counts[label]
            average = total_duration / count if count else 0.0
            method, path, status = label
            lines.append(
                "http_request_duration_seconds{method=\"%s\",path=\"%s\",status=\"%s\"} %.6f"
                % (method, path, status, average)
            )

        return "\n".join(lines) + "\n"


def _init_sentry(env: Dict[str, str]) -> None:
    """Initialise Sentry only when a DSN is configured."""

    dsn = env.get("SENTRY_DSN", "").strip()
    if not dsn:
        return

    try:
        import importlib

        sentry_sdk = importlib.import_module("sentry_sdk")
    except ImportError as exc:
        raise MonitoringConfigError(
            "SENTRY_DSN is configured but the sentry-sdk package is not installed.",
        ) from exc

    traces_sample_rate_raw = env.get("SENTRY_TRACES_SAMPLE_RATE", "").strip() or "0.1"
    try:
        traces_sample_rate = float(traces_sample_rate_raw)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise MonitoringConfigError(
            "Invalid SENTRY_TRACES_SAMPLE_RATE value; expected a float",
        ) from exc

    sentry_sdk.init(
        dsn=dsn,
        environment=env.get("SENTRY_ENVIRONMENT"),
        release=env.get("SENTRY_RELEASE"),
        traces_sample_rate=traces_sample_rate,
    )


def _expose_metrics(app: FastAPI, env: Dict[str, str]) -> None:
    """Expose a Prometheus metrics endpoint and middleware."""

    endpoint = env.get("PROMETHEUS_METRICS_ENDPOINT", "/metrics").strip() or "/metrics"

    metrics = RequestMetrics()
    app.state.request_metrics = metrics

    @app.middleware("http")
    async def _metrics_middleware(request, call_next):  # type: ignore[no-untyped-def]
        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time
        metrics.record(request.method, request.url.path, response.status_code, duration)
        return response

    if not any(route.path == endpoint for route in app.routes):
        async def _metrics_endpoint():
            return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

        app.add_api_route(
            endpoint,
            _metrics_endpoint,
            include_in_schema=False,
            response_class=PlainTextResponse,
        )


def configure_monitoring(app: FastAPI, *, env: Dict[str, str] | None = None) -> None:
    """Attach Sentry and Prometheus monitoring integrations to *app*.

    The function is safe to call multiple times; the monitoring hooks are only
    initialised once and subsequent calls are ignored.  The environment values
    are read from *env* when provided (making the function easier to test) or
    from :data:`os.environ` by default.
    """

    if getattr(app.state, _MONITORING_STATE_FLAG, False):
        return

    env_mapping: Dict[str, str]
    if env is not None:
        env_mapping = dict(env)
    else:
        env_mapping = dict(os.environ)

    _init_sentry(env_mapping)
    _expose_metrics(app, env_mapping)

    setattr(app.state, _MONITORING_STATE_FLAG, True)

