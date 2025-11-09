from __future__ import annotations
import pathlib
import sys
import types

from fastapi import FastAPI

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.monitoring import MonitoringConfigError, configure_monitoring


def test_configure_monitoring_adds_metrics_endpoint(monkeypatch):
    app = FastAPI()

    monkeypatch.setenv("PROMETHEUS_METRICS_ENDPOINT", "/internal-metrics")
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    configure_monitoring(app)

    metric_routes = [route.path for route in app.routes if route.path == "/internal-metrics"]
    assert metric_routes == ["/internal-metrics"]
    assert getattr(app.state, "monitoring_configured") is True

    # The second call is a no-op and does not duplicate routes
    configure_monitoring(app)
    metric_routes = [route.path for route in app.routes if route.path == "/internal-metrics"]
    assert metric_routes == ["/internal-metrics"]


def test_configure_monitoring_initialises_sentry_when_dsn(monkeypatch):
    app = FastAPI()

    recorded_kwargs = {}

    def fake_sentry_init(**kwargs):
        recorded_kwargs.update(kwargs)

    monkeypatch.setitem(sys.modules, "sentry_sdk", types.SimpleNamespace(init=fake_sentry_init))
    monkeypatch.setenv("SENTRY_DSN", "https://example@ingest")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "production")
    monkeypatch.setenv("SENTRY_RELEASE", "1.2.3")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.25")

    configure_monitoring(app)

    assert recorded_kwargs == {
        "dsn": "https://example@ingest",
        "environment": "production",
        "release": "1.2.3",
        "traces_sample_rate": 0.25,
    }


def test_configure_monitoring_rejects_invalid_trace_sample_rate(monkeypatch):
    app = FastAPI()

    monkeypatch.setenv("SENTRY_DSN", "https://example@ingest")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "not-a-number")

    try:
        configure_monitoring(app)
    except MonitoringConfigError:
        pass
    else:  # pragma: no cover - safety net
        raise AssertionError("Expected MonitoringConfigError to be raised")
