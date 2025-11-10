"""Database configuration and helpers for the backend domain."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_startup_migrations() -> None:
    """Ensure essential schema adjustments without a full migration system."""

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "admin_users" in tables:
            from .models import AdminRole  # imported lazily to avoid circular dependency

            default_role = AdminRole.ADMIN.name
            admin_columns = {
                column["name"] for column in inspector.get_columns("admin_users")
            }

            if "role" not in admin_columns:
                connection.execute(
                    text(
                        "ALTER TABLE admin_users ADD COLUMN role VARCHAR(50) "
                        f"DEFAULT '{default_role}'"
                    )
                )

            # Ensure legacy values use the canonical enum names expected by SQLAlchemy
            for role in AdminRole:
                connection.execute(
                    text("UPDATE admin_users SET role = :canonical WHERE role = :legacy"),
                    {"canonical": role.name, "legacy": role.value},
                )

            connection.execute(
                text("UPDATE admin_users SET role = :default_role WHERE role IS NULL"),
                {"default_role": default_role},
            )

        if "jobs" in tables:
            job_columns = {column["name"] for column in inspector.get_columns("jobs")}

            if "progress_percent" not in job_columns:
                connection.execute(
                    text(
                        "ALTER TABLE jobs ADD COLUMN progress_percent INTEGER "
                        "DEFAULT 0 NOT NULL"
                    )
                )

            if "ai_tool" not in job_columns:
                connection.execute(
                    text(
                        "ALTER TABLE jobs ADD COLUMN ai_tool VARCHAR(150) "
                        "DEFAULT '' NOT NULL"
                    )
                )

        if "job_media" in tables:
            job_media_columns = {
                column["name"] for column in inspector.get_columns("job_media")
            }

            if "media_url" not in job_media_columns:
                connection.execute(
                    text("ALTER TABLE job_media ADD COLUMN media_url VARCHAR(500)")
                )

            if "job_id" not in job_media_columns:
                connection.execute(
                    text("ALTER TABLE job_media ADD COLUMN job_id INTEGER")
                )

        if "service_tokens" in tables:
            service_token_columns = {
                column["name"] for column in inspector.get_columns("service_tokens")
            }

            if "endpoint_url" not in service_token_columns:
                connection.execute(
                    text(
                        "ALTER TABLE service_tokens ADD COLUMN endpoint_url VARCHAR(500)"
                    )
                )
