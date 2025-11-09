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
    if "admin_users" not in inspector.get_table_names():
        return

    from .models import AdminRole  # imported lazily to avoid circular dependency

    default_role = AdminRole.ADMIN.name
    columns = {column["name"] for column in inspector.get_columns("admin_users")}

    with engine.begin() as connection:
        if "role" not in columns:
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
