import asyncio
import pathlib
import sys
from datetime import datetime, timedelta

import pytest

pytest.importorskip("httpx")

import httpx


class _SyncASGIClient:
    def __init__(self, app):
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )

    def request(self, method: str, *args, **kwargs) -> httpx.Response:
        return asyncio.run(self._client.request(method, *args, **kwargs))

    def post(self, url: str, *args, **kwargs) -> httpx.Response:
        return self.request("POST", url, *args, **kwargs)

    def get(self, url: str, *args, **kwargs) -> httpx.Response:
        return self.request("GET", url, *args, **kwargs)

    @property
    def cookies(self) -> httpx.Cookies:
        return self._client.cookies

    def close(self) -> None:
        asyncio.run(self._client.aclose())

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.backend import auth, models
from app.backend.database import Base, get_db
from app.main import app


@pytest.fixture(name="test_session")
def fixture_test_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield TestingSessionLocal

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(name="client")
def fixture_client(test_session):
    with test_session() as db:
        auth.ensure_default_admin(db)
        account = models.SocialAccount(
            platform="instagram",
            display_name="اکانت آزمایشی",
            page_id="123",
        )
        db.add(account)
        db.commit()
        db.refresh(account)
    client = _SyncASGIClient(app)
    try:
        yield client
    finally:
        client.close()


def test_full_job_workflow(client, test_session):
    login_response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    schedule_time = (datetime.utcnow() + timedelta(hours=1)).replace(second=0, microsecond=0)

    with test_session() as db:
        account = db.query(models.SocialAccount).first()
        account_id = account.id

    create_response = client.post(
        "/scheduler",
        data={
            "account_id": str(account_id),
            "title": "پست تستی",
            "content": "این یک سناریوی کامل برای تست است.",
            "video_url": "https://videos.example.com/test.mp4",
            "scheduled_time": schedule_time.isoformat(timespec="minutes"),
        },
        follow_redirects=False,
    )

    assert create_response.status_code == 302

    with test_session() as db:
        post = db.query(models.ScheduledPost).one()
        assert post.title == "پست تستی"
        assert post.video_url == "https://videos.example.com/test.mp4"
        assert post.content.startswith("این یک سناریو")
        assert post.account_id == account_id

    page_response = client.get("/scheduler")
    assert page_response.status_code == 200
    page_html = page_response.text
    assert "پست تستی" in page_html
    assert "اکانت آزمایشی" in page_html
    assert schedule_time.strftime("%Y-%m-%d %H:%M") in page_html
