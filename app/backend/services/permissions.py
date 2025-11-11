"""Role-based menu permission utilities for the admin UI."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Dict, List, Mapping

from sqlalchemy.orm import Session

from app.backend import models


@dataclass(frozen=True)
class MenuDefinition:
    """Describe a navigational menu item available in the UI."""

    key: models.AdminMenu
    label: str
    url: str


MENU_DEFINITIONS: List[MenuDefinition] = [
    MenuDefinition(models.AdminMenu.DASHBOARD, "داشبورد", "/"),
    MenuDefinition(models.AdminMenu.ACCOUNTS, "حساب‌ها", "/accounts"),
    MenuDefinition(models.AdminMenu.SCHEDULER, "زمان‌بندی محتوا", "/scheduler"),
    MenuDefinition(models.AdminMenu.TEXT_GRAPHY, "تکس گرافی", "/text-graphy"),
    MenuDefinition(models.AdminMenu.MANUAL_VIDEO, "ویدیو دستی", "/manual-video"),
    MenuDefinition(models.AdminMenu.MEDIA_LIBRARY, "کتابخانه مدیا", "/media-library"),
    MenuDefinition(models.AdminMenu.SETTINGS, "تنظیمات", "/settings"),
    MenuDefinition(models.AdminMenu.DOCUMENTATION, "مستندات", "/documentation"),
    MenuDefinition(models.AdminMenu.LOGS, "لاگ‌ها", "/logs"),
]

ROLE_LABELS: Dict[models.AdminRole, str] = {
    models.AdminRole.SUPERADMIN: "سوپر ادمین",
    models.AdminRole.ADMIN: "مدیر",
    models.AdminRole.VIEWER: "مشاهده‌گر",
}


def list_menu_definitions() -> List[MenuDefinition]:
    """Return a copy of available menu definitions."""

    return list(MENU_DEFINITIONS)


def list_role_definitions() -> List[Dict[str, object]]:
    """Provide metadata about roles for rendering permission matrices."""

    definitions: List[Dict[str, object]] = []
    for role in models.AdminRole:
        definitions.append(
            {
                "value": role.value,
                "label": ROLE_LABELS.get(role, role.value),
                "editable": role is not models.AdminRole.SUPERADMIN,
            }
        )
    return definitions


def ensure_default_permissions(db: Session) -> None:
    """Create default menu permissions for roles if they do not yet exist."""

    existing_pairs = {
        (permission.role, permission.menu)
        for permission in db.query(models.AdminMenuPermission).all()
    }
    to_create: List[models.AdminMenuPermission] = []
    for role in models.AdminRole:
        if role is models.AdminRole.SUPERADMIN:
            # Superadmins always have full access without stored records.
            continue
        for menu in (definition.key for definition in MENU_DEFINITIONS):
            if (role, menu) not in existing_pairs:
                to_create.append(
                    models.AdminMenuPermission(role=role, menu=menu, is_allowed=True)
                )
    if to_create:
        db.add_all(to_create)
        db.commit()


def has_menu_access(db: Session, role: models.AdminRole, menu: models.AdminMenu) -> bool:
    """Return True if the provided role may access the requested menu."""

    if role is models.AdminRole.SUPERADMIN:
        return True
    permission = (
        db.query(models.AdminMenuPermission)
            .filter_by(role=role, menu=menu)
            .first()
    )
    if permission is None:
        return False
    return bool(permission.is_allowed)


def get_accessible_menu_items(db: Session, role: models.AdminRole) -> List[Dict[str, str]]:
    """Return menu items accessible to a given role for navigation rendering."""

    items: List[Dict[str, str]] = []
    for definition in MENU_DEFINITIONS:
        if has_menu_access(db, role, definition.key):
            items.append(
                {
                    "key": definition.key.value,
                    "label": definition.label,
                    "url": definition.url,
                }
            )
    return items


def get_permission_matrix(db: Session) -> Dict[str, Dict[str, bool]]:
    """Build a matrix of permissions keyed by role and menu for templates."""

    matrix: Dict[str, Dict[str, bool]] = {
        role.value: {definition.key.value: False for definition in MENU_DEFINITIONS}
        for role in models.AdminRole
    }

    for permission in db.query(models.AdminMenuPermission).all():
        matrix[permission.role.value][permission.menu.value] = bool(permission.is_allowed)

    # Superadmins always have full access regardless of stored records.
    matrix[models.AdminRole.SUPERADMIN.value] = {
        definition.key.value: True for definition in MENU_DEFINITIONS
    }
    return matrix


def parse_permission_updates(
    form_data: Mapping[str, object]
) -> Dict[str, Dict[str, bool]]:
    """Interpret submitted form data into a permission update mapping."""

    updates: Dict[str, Dict[str, bool]] = {}
    for role in models.AdminRole:
        role_key = role.value
        updates[role_key] = {}
        if role is models.AdminRole.SUPERADMIN:
            for definition in MENU_DEFINITIONS:
                updates[role_key][definition.key.value] = True
            continue
        for definition in MENU_DEFINITIONS:
            field_name = f"perm-{role_key}-{definition.key.value}"
            value = form_data.get(field_name)
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
                allowed = any(bool(item) for item in value)
            else:
                allowed = bool(value)
            updates[role_key][definition.key.value] = allowed
    return updates


def apply_permission_updates(
    db: Session, updates: Mapping[str, Mapping[str, bool]]
) -> None:
    """Persist permission updates to the database."""

    existing = {
        (permission.role.value, permission.menu.value): permission
        for permission in db.query(models.AdminMenuPermission).all()
    }

    for role_key, menus in updates.items():
        role = models.AdminRole(role_key)
        if role is models.AdminRole.SUPERADMIN:
            continue
        for menu_key, allowed in menus.items():
            menu = models.AdminMenu(menu_key)
            record = existing.get((role_key, menu_key))
            if record is None:
                record = models.AdminMenuPermission(role=role, menu=menu, is_allowed=bool(allowed))
                db.add(record)
            else:
                record.is_allowed = bool(allowed)
    db.commit()
