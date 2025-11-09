import logging
from datetime import datetime
from typing import Iterable, Optional

from fastapi import HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models


logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _ensure_role(user: models.AdminUser, required_roles: Optional[Iterable[models.AdminRole]]) -> None:
    if not required_roles:
        return
    if user.role not in set(required_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: insufficient role.",
        )


def get_logged_in_user(
    request: Request,
    db: Session,
    required_roles: Optional[Iterable[models.AdminRole]] = None,
) -> Optional[models.AdminUser]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(models.AdminUser, user_id)
    if not user:
        logger.warning(
            "Session referenced missing user",
            extra={"user_id": user_id},
        )
        return None
    _ensure_role(user, required_roles)
    logger.debug(
        "Resolved logged-in user",
        extra={"user_id": user_id, "roles": user.role.name if user.role else None},
    )
    return user


def require_user(
    request: Request,
    db: Session,
    required_roles: Optional[Iterable[models.AdminRole]] = None,
) -> models.AdminUser:
    user = get_logged_in_user(request, db, required_roles=required_roles)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    logger.debug("Authenticated request", extra={"user_id": user.id})
    return user


def ensure_default_admin(db: Session) -> models.AdminUser:
    user = db.query(models.AdminUser).filter_by(username="admin").first()
    if user:
        logger.debug("Default admin already present", extra={"user_id": user.id})
        return user
    default_user = models.AdminUser(
        username="admin",
        password_hash=hash_password("admin123"),
        role=models.AdminRole.SUPERADMIN,
        created_at=datetime.utcnow(),
    )
    db.add(default_user)
    db.commit()
    db.refresh(default_user)
    logger.info("Created default admin user", extra={"user_id": default_user.id})
    return default_user
