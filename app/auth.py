from datetime import datetime
from typing import Optional

from fastapi import Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_logged_in_user(request: Request, db: Session) -> Optional[models.AdminUser]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(models.AdminUser, user_id)


def ensure_default_admin(db: Session) -> models.AdminUser:
    user = db.query(models.AdminUser).filter_by(username="admin").first()
    if user:
        return user
    default_user = models.AdminUser(
        username="admin",
        password_hash=hash_password("admin123"),
        created_at=datetime.utcnow(),
    )
    db.add(default_user)
    db.commit()
    db.refresh(default_user)
    return default_user
