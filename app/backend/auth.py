import logging
from typing import Iterable, Optional

from fastapi import HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models
from .services.data_access import AdminUserService
from .services import permissions as permissions_service

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

logger = logging.getLogger(__name__)


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
    if required_menu:
        if not permissions_service.has_menu_access(db, user.role, required_menu):
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
