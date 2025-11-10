from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator

from .database import Base
from .security.crypto import decrypt_value, encrypt_value


class AdminRole(str, PyEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    VIEWER = "viewer"


class AdminMenu(str, PyEnum):
    DASHBOARD = "dashboard"
    ACCOUNTS = "accounts"
    SCHEDULER = "scheduler"
    MANUAL_VIDEO = "manual_video"
    SETTINGS = "settings"
    DOCUMENTATION = "documentation"
    LOGS = "logs"


class EncryptedText(TypeDecorator):
    """SQLAlchemy type that transparently encrypts/decrypts values."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        return encrypt_value(value)

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        return decrypt_value(value)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(AdminRole, name="admin_role"), nullable=False, default=AdminRole.ADMIN)
    created_at = Column(DateTime, default=datetime.utcnow)


class AdminMenuPermission(Base):
    __tablename__ = "admin_menu_permissions"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(Enum(AdminRole, name="admin_role"), nullable=False)
    menu = Column(Enum(AdminMenu, name="admin_menu"), nullable=False)
    is_allowed = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("role", "menu", name="uq_admin_menu_permissions_role_menu"),
    )


class ServiceToken(Base):
    __tablename__ = "service_tokens"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    key = Column(String(100), nullable=False)
    value = Column(EncryptedText(), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(30), nullable=False)
    display_name = Column(String(100), nullable=False)
    page_id = Column(String(100), nullable=True)
    oauth_token = Column(Text, nullable=True)
    youtube_channel_id = Column(String(150), nullable=True)
    telegram_chat_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    scheduled_posts = relationship(
        "ScheduledPost", back_populates="account", cascade="all, delete-orphan"
    )


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("social_accounts.id"), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=True)
    video_url = Column(String(500), nullable=True)
    scheduled_time = Column(DateTime, nullable=False)
    status = Column(String(50), default="pending")

    account = relationship("SocialAccount", back_populates="scheduled_posts")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="pending")
    scheduled_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    media = relationship("JobMedia", back_populates="job", cascade="all, delete-orphan")
    campaign = relationship(
        "Campaign", back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class JobMedia(Base):
    __tablename__ = "job_media"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    job_name = Column(String(150), nullable=True)
    media_type = Column(String(50), nullable=False, default="video/mp4")
    media_url = Column(String(500), nullable=True)
    storage_key = Column(String(255), nullable=True)
    storage_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    job = relationship("Job", back_populates="media")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    budget = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    job = relationship("Job", back_populates="campaign")
