import asyncio
import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.backend.services import ai_client


def test_dispatch_requires_endpoint(monkeypatch):
    monkeypatch.delenv("AI_SERVICE_ENDPOINT", raising=False)

    with pytest.raises(ai_client.AIServiceConfigurationError):
        asyncio.run(ai_client.dispatch_manual_video_job(1, {"title": "نمونه"}))


def test_dispatch_fails_without_httpx(monkeypatch):
    monkeypatch.setattr(ai_client, "httpx", None)

    with pytest.raises(ai_client.AIServiceDispatchError):
        asyncio.run(
            ai_client.dispatch_manual_video_job(
                2, {"title": "نمونه"}, endpoint="https://ai.example/jobs"
            )
        )


def test_dispatch_success(monkeypatch):
    calls = []

    class DummyResponse:
        status_code = 202

        def __init__(self):
            self.closed = False

        def raise_for_status(self):
            return None

        def json(self):
            return {"job_id": "ext-77"}

        async def aclose(self):
            self.closed = True

    timeout = 12.5

    class DummyAsyncClient:
        def __init__(self, timeout=15):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            calls.append((url, json, self.timeout))
            return DummyResponse()

    class DummyHttpx:
        def AsyncClient(self, timeout=15):  # pragma: no cover - test helper
            return DummyAsyncClient(timeout)

    monkeypatch.setattr(ai_client, "httpx", DummyHttpx())
    monkeypatch.setattr(ai_client, "log_request_start", lambda *args, **kwargs: 0.0)
    monkeypatch.setattr(
        ai_client,
        "log_request_failure",
        lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(AssertionError("failure logger should not be called")),
    )

    successes = []

    def fake_success(*args, **kwargs):
        successes.append((args, kwargs))

    monkeypatch.setattr(ai_client, "log_request_success", fake_success)

    result = asyncio.run(
        ai_client.dispatch_manual_video_job(
            7,
            {"title": "نمونه", "ai_tool": "sora"},
            endpoint="https://ai.example/jobs",
            timeout=timeout,
        )
    )

    assert calls == [
        ("https://ai.example/jobs", {"title": "نمونه", "ai_tool": "sora"}, timeout)
    ]
    assert successes
    assert result.job_token == "ext-77"
    assert result.response_payload == {"job_id": "ext-77"}
