"""Role-based menu permission utilities for the admin UI."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Dict, Iterable as TypingIterable, List, Mapping, Tuple

from sqlalchemy.orm import Session

from app.backend import models


# Type aliases used for clarity within this module.
PermissionKey = Tuple[models.AdminRole, models.AdminMenu]
PermissionMatrix = Dict[str, Dict[str, bool]]


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
    """Return a shallow copy of available menu definitions."""

    # Returning a new list prevents callers from mutating the module-level
    # constant.  We do not deep-copy the dataclasses because they are frozen
    # and therefore immutable by design.
    return list(MENU_DEFINITIONS)


def list_role_definitions() -> List[Dict[str, object]]:
    """Provide metadata about roles for rendering permission matrices."""

    # Roles are enumerations with deterministic ordering, so iterating once and
    # building dictionaries keeps the function readable and inexpensive.
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


def _load_permission_records(db: Session) -> Dict[PermissionKey, models.AdminMenuPermission]:
    """Return a mapping of ``(role, menu)`` pairs to permission objects."""

    permissions = db.query(models.AdminMenuPermission).all()
    return {(permission.role, permission.menu): permission for permission in permissions}


def _iter_assignable_roles() -> TypingIterable[models.AdminRole]:
    """Yield roles that can have explicit permission records."""

    for role in models.AdminRole:
        if role is not models.AdminRole.SUPERADMIN:
            yield role


def ensure_default_permissions(db: Session) -> None:
    """Create default menu permissions for roles if they do not yet exist."""

    # Fetch all existing permissions in a single query to avoid redundant
    # lookups when iterating through the role/menu combinations below.
    existing_records = _load_permission_records(db)
    to_create: List[models.AdminMenuPermission] = []

    for role in _iter_assignable_roles():
        for menu_definition in MENU_DEFINITIONS:
            key: PermissionKey = (role, menu_definition.key)
            if key not in existing_records:
                to_create.append(
                    models.AdminMenuPermission(
                        role=role,
                        menu=menu_definition.key,
                        is_allowed=True,
                    )
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

    if role is models.AdminRole.SUPERADMIN:
        # Superadmins automatically receive all navigation options.
        return [
            {"key": definition.key.value, "label": definition.label, "url": definition.url}
            for definition in MENU_DEFINITIONS
        ]

    # Materialise the permission set for the role in a single query to prevent
    # issuing additional queries for each menu definition.
    allowed_menus = {
        permission.menu
        for permission in db.query(models.AdminMenuPermission)
        .filter_by(role=role)
        .all()
        if permission.is_allowed
    }

    items: List[Dict[str, str]] = []
    for definition in MENU_DEFINITIONS:
        if definition.key in allowed_menus:
            items.append(
                {
                    "key": definition.key.value,
                    "label": definition.label,
                    "url": definition.url,
                }
            )
    return items


def get_permission_matrix(db: Session) -> PermissionMatrix:
    """Build a matrix of permissions keyed by role and menu for templates."""

    matrix: PermissionMatrix = {
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


def parse_permission_updates(form_data: Mapping[str, object]) -> PermissionMatrix:
    """Interpret submitted form data into a permission update mapping."""

    def coerce_to_bool(value: object) -> bool:
        """Convert raw form values (including lists) to a boolean flag."""

        if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            return any(bool(item) for item in value)
        return bool(value)

    updates: PermissionMatrix = {}
    for role in models.AdminRole:
        role_key = role.value
        updates[role_key] = {}

        if role is models.AdminRole.SUPERADMIN:
            for definition in MENU_DEFINITIONS:
                updates[role_key][definition.key.value] = True
            continue

        for definition in MENU_DEFINITIONS:
            field_name = f"perm-{role_key}-{definition.key.value}"
            raw_value = form_data.get(field_name)
            updates[role_key][definition.key.value] = coerce_to_bool(raw_value)

    return updates


def apply_permission_updates(db: Session, updates: Mapping[str, Mapping[str, bool]]) -> None:
    """Persist permission updates to the database."""

    existing = _load_permission_records(db)

    for role_key, menus in updates.items():
        role = models.AdminRole(role_key)
        if role is models.AdminRole.SUPERADMIN:
            # Superadmin permissions are implicit and never stored.
            continue

        for menu_key, allowed in menus.items():
            menu = models.AdminMenu(menu_key)
            key: PermissionKey = (role, menu)
            record = existing.get(key)
            if record is None:
                record = models.AdminMenuPermission(
                    role=role,
                    menu=menu,
                    is_allowed=bool(allowed),
                )
                db.add(record)
                existing[key] = record
            else:
                record.is_allowed = bool(allowed)

    db.commit()
