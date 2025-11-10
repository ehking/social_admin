import json
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

pytest.importorskip("httpx")
from starlette.testclient import TestClient

from app.ui.app_presenters.logs_presenter import LogsPresenter
from app.ui.views.logs import create_router


def _create_client(log_dir: Path) -> TestClient:
    templates = Jinja2Templates(directory="app/ui/templates")
    presenter = LogsPresenter(templates, log_directory=log_dir)
    app = FastAPI()
    app.include_router(create_router(presenter))
    return TestClient(app)


def test_stream_endpoint_emits_new_entries(tmp_path: Path) -> None:
    log_path = tmp_path / "test.log"
    log_path.write_text("", encoding="utf-8")

    with _create_client(tmp_path) as client:
        def _writer() -> None:
            time.sleep(0.3)
            record = {
                "level": "INFO",
                "badge_class": "info",
                "timestamp": "2024-05-01T10:00:00Z",
                "message": "job_updated",
                "details": {"job_id": "123"},
            }
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        threading.Thread(target=_writer, daemon=True).start()

        with client.stream("GET", "/logs/test.log/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")

            payload = None
            start = time.time()

            for chunk in response.iter_lines():
                if chunk:
                    line = chunk.decode() if isinstance(chunk, bytes) else chunk
                    if line.startswith("data: "):
                        payload = json.loads(line[len("data: "):])
                        break
                if time.time() - start > 5:
                    pytest.fail("Timed out waiting for streamed log entry")

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
