import asyncio
import json
from pathlib import Path

from contextlib import contextmanager
import typing

import pytest
import anyio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

pytest.importorskip("httpx")
import httpx


class _SyncASGIClient:
    def __init__(self, app):
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )

    def request(self, method: str, url: str, *args, **kwargs) -> httpx.Response:
        return asyncio.run(self._client.request(method, url, *args, **kwargs))

    def get(self, url: str, *args, **kwargs) -> httpx.Response:
        return self.request("GET", url, *args, **kwargs)

    def close(self) -> None:
        asyncio.run(self._client.aclose())

from app.ui.app_presenters.logs_presenter import LogsPresenter
from app.ui.views.logs import create_router


@contextmanager
def _create_client(log_dir: Path) -> typing.Iterator[_SyncASGIClient]:
    templates = Jinja2Templates(directory="app/ui/templates")
    presenter = LogsPresenter(templates, log_directory=log_dir)
    app = FastAPI()
    app.include_router(create_router(presenter))
    client = _SyncASGIClient(app)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def anyio_backend() -> str:
    """Limit anyio tests to the asyncio backend for repeatable results."""

    return "asyncio"


@pytest.mark.anyio
async def test_stream_endpoint_emits_new_entries(tmp_path: Path) -> None:
    log_path = tmp_path / "test.log"
    log_path.write_text("", encoding="utf-8")

    templates = Jinja2Templates(directory="app/ui/templates")
    presenter = LogsPresenter(templates, log_directory=tmp_path)
    router = create_router(presenter)
    stream_route = next(route for route in router.routes if route.name == "stream_log")

    response = await stream_route.endpoint(log_name="test.log")
    assert isinstance(response, StreamingResponse)
    assert response.status_code == 200
    assert response.media_type.startswith("text/event-stream")
    assert response.headers["Cache-Control"] == "no-cache"

    async def _writer() -> None:
        await anyio.sleep(0.05)
        record = {
            "level": "INFO",
            "badge_class": "info",
            "timestamp": "2024-05-01T10:00:00Z",
            "message": "job_updated",
            "details": {"job_id": "123"},
        }
        async with await anyio.open_file(log_path, "a", encoding="utf-8") as handle:
            await handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    payload = None
    async with anyio.create_task_group() as tg:
        tg.start_soon(_writer)
        with anyio.fail_after(2):
            async for chunk in response.body_iterator:
                if not chunk:
                    continue
                line = chunk.decode() if isinstance(chunk, bytes) else chunk
                if line.startswith("data: "):
                    payload = json.loads(line[len("data: "):])
                    break

    await response.body_iterator.aclose()

    assert payload is not None
    assert payload["message"] == "job_updated"


def test_stream_endpoint_requires_existing_log(tmp_path: Path) -> None:
    with _create_client(tmp_path) as client:
        response = client.get("/logs/missing.log/stream")
        assert response.status_code == 404


def test_stream_endpoint_rejects_path_traversal(tmp_path: Path) -> None:
    log_path = tmp_path / "safe.log"
    log_path.write_text("{}\n", encoding="utf-8")

    with _create_client(tmp_path) as client:
        response = client.get("/logs/../../safe.log/stream")
        assert response.status_code == 404


@pytest.fixture(autouse=True)
def _speed_up_log_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reduce the sleep interval inside the SSE generator to avoid long waits."""

    original_sleep = asyncio.sleep

    async def _fast_sleep(delay: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr("app.ui.views.logs.asyncio.sleep", _fast_sleep)
