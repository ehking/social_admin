import pathlib
import sys

import pytest
from sqlalchemy import create_engine, text

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from app.backend import database


@pytest.fixture
def legacy_engine(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE admin_users ("
                "id INTEGER PRIMARY KEY,"
                "username VARCHAR(50),"
                "password_hash VARCHAR(255),"
                "created_at DATETIME"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO admin_users (username, password_hash, created_at) "
                "VALUES ('legacy', 'hash', '2024-01-01 00:00:00')"
            )
        )

        connection.execute(
            text(
                "CREATE TABLE job_media ("
                "id INTEGER PRIMARY KEY,"
                "job_name VARCHAR(150),"
                "media_type VARCHAR(50) NOT NULL,"
                "media_url VARCHAR(500),"
                "storage_key VARCHAR(255),"
                "storage_url VARCHAR(500),"
                "created_at DATETIME NOT NULL"
                ")"
            )
        )

    monkeypatch.setattr(database, "engine", engine)
    yield engine
    engine.dispose()


def test_run_startup_migrations_adds_missing_role_column(legacy_engine):
    database.run_startup_migrations()

    with legacy_engine.begin() as connection:
        columns = connection.execute(text("PRAGMA table_info(admin_users)")).fetchall()
        column_names = {column[1] for column in columns}
        assert "role" in column_names

        role_value = connection.execute(
            text("SELECT role FROM admin_users WHERE username = 'legacy'")
        ).scalar_one()
        assert role_value == "ADMIN"


def test_run_startup_migrations_adds_job_id_column(legacy_engine):
    database.run_startup_migrations()

    with legacy_engine.begin() as connection:
        columns = connection.execute(text("PRAGMA table_info(job_media)")).fetchall()
        column_names = {column[1] for column in columns}
        assert "job_id" in column_names

        job_id_column = next(column for column in columns if column[1] == "job_id")
        assert job_id_column[2].upper() == "INTEGER"
