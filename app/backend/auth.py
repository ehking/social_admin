import logging
from typing import Iterable, Optional

import bcrypt
from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from . import models
from .services import permissions as permissions_service
from .services.data_access import AdminUserService

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""

    password_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str | bytes) -> bool:
    """Verify a password against a bcrypt hash."""

    if isinstance(hashed_password, bytes):
        hashed_bytes = hashed_password
    elif isinstance(hashed_password, str):
        hashed_bytes = hashed_password.encode("utf-8")
    else:
        logger.error("Stored password hash has unexpected type", extra={"type": type(hashed_password).__name__})
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_bytes)


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
    required_menu: Optional[models.AdminMenu] = None,
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
    if required_menu and not permissions_service.has_menu_access(
        db, user.role, required_menu
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: menu access is restricted.",
        )
    return user


def require_user(
    request: Request,
    db: Session,
    required_roles: Optional[Iterable[models.AdminRole]] = None,
    required_menu: Optional[models.AdminMenu] = None,
) -> models.AdminUser:
    user = get_logged_in_user(
        request,
        db,
        required_roles=required_roles,
        required_menu=required_menu,
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    logger.debug("Authenticated request", extra={"user_id": user.id})
    return user


def ensure_default_admin(db: Session) -> models.AdminUser:
    service = AdminUserService(db)
    return service.ensure_default_admin(
        username="admin",
        password_hash=hash_password("admin123"),
        role=models.AdminRole.SUPERADMIN,
    )
