from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

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

    columns = {column["name"] for column in inspector.get_columns("admin_users")}
    if "role" not in columns:
        default_role = "admin"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE admin_users ADD COLUMN role VARCHAR(50) "
                    "DEFAULT :default_role"
                ),
                {"default_role": default_role},
            )
            connection.execute(
                text(
                    "UPDATE admin_users SET role = :default_role WHERE role IS NULL"
                ),
                {"default_role": default_role},
            )
