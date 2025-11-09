import base64
import os
import pathlib
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.backend import auth, models
from app.backend.database import Base
from app.backend.security import crypto


@pytest.fixture(autouse=True)
def configure_fernet_key(monkeypatch, request):
    if request.node.get_closest_marker("no_fernet_autoconfig"):
        crypto.reset_cipher_cache()
        yield
        crypto.reset_cipher_cache()
        return

    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("FERNET_KEY", key)
    crypto.reset_cipher_cache()
    yield
    crypto.reset_cipher_cache()


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)


def test_service_token_value_encrypted_in_database(session_factory):
    session = session_factory()
    try:
        token = models.ServiceToken(name="Test Token", key="api", value="super-secret")
        session.add(token)
        session.commit()
        session.refresh(token)

        raw_value = session.execute(
            text("SELECT value FROM service_tokens WHERE id = :id"),
            {"id": token.id},
        ).scalar_one()

        assert raw_value != "super-secret"
        assert crypto.decrypt_value(raw_value) == "super-secret"
    finally:
        session.close()


def test_viewer_role_cannot_access_admin_only_section(session_factory):
    session = session_factory()
    try:
        viewer = models.AdminUser(
            username="viewer",
            password_hash="dummy-hash",
            role=models.AdminRole.VIEWER,
        )
        session.add(viewer)
        session.commit()

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/settings",
            "headers": [],
            "session": {"user_id": viewer.id},
        }

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(scope, receive=receive)

        with pytest.raises(HTTPException) as exc_info:
            auth.get_logged_in_user(
                request,
                session,
                required_roles=[models.AdminRole.ADMIN, models.AdminRole.SUPERADMIN],
            )

        assert exc_info.value.status_code == 403
    finally:
        session.close()


@pytest.mark.no_fernet_autoconfig
def test_missing_key_file_is_created(tmp_path, monkeypatch):
    monkeypatch.delenv("FERNET_KEY", raising=False)
    key_path = tmp_path / "config" / "fernet.key"
    monkeypatch.setenv("FERNET_KEY_PATH", str(key_path))

    encrypted = crypto.encrypt_value("hello-world")

    assert key_path.exists()
    stored_key = key_path.read_bytes().strip()
    assert stored_key
    assert crypto.decrypt_value(encrypted) == "hello-world"
