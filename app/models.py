from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator

from .database import Base
from .security.crypto import decrypt_value, encrypt_value


class AdminRole(str, PyEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    VIEWER = "viewer"


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
