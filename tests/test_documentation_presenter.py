import pathlib
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.ui.app_presenters.documentation_presenter import DocumentationPresenter


def _build_request() -> Request:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/documentation",
        "headers": [],
        "query_string": b"",
        "app": app,
        "router": app.router,
        "client": ("testclient", 5000),
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_documentation_presenter_renders_spec(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("# عنوان\n\nجزئیات مستندات", encoding="utf-8")

    templates = Jinja2Templates(directory="app/ui/templates")
    presenter = DocumentationPresenter(templates=templates, spec_path=spec)

    response = presenter.render(_build_request(), SimpleNamespace(username="admin"))
    body = response.body.decode("utf-8")

    assert "جزئیات مستندات" in body
    assert "documentation-content" in body


def test_documentation_presenter_handles_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.md"
    templates = Jinja2Templates(directory="app/ui/templates")
    presenter = DocumentationPresenter(templates=templates, spec_path=missing)

    response = presenter.render(_build_request(), None)
    body = response.body.decode("utf-8")

    assert "مستندات پروژه یافت نشد." in body
