"""Role business logic (RBAC, plan 03).

Owns the rules: blanket implied-read normalization on save (any granted action on
a resource forces `<resource>.read`), the system-role delete guard, and user
assignment. Routers translate outcomes to HTTP; the repository does the SQL.
"""
import csv
import io
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.role import Role
from app.models.tenant import DEFAULT_TENANT_ID
from app.models.user import User
from app.repositories.permission_repository import PermissionRepository
from app.repositories.role_repository import RoleRepository
from app.schemas.filters import FilterGroup
from app.services.filter_translator import translate_filter
from app.workflow_engine.entity_events import emit_entity_event, notify_entity_event

# Whitelisted filter columns for the roles list (field -> column).
_ROLE_FILTER_COLUMNS = {
    "role": Role.name,
    "name": Role.name,
    "description": Role.description,
    "system": Role.is_system,
    "created": Role.created_at,
}


class RoleServiceError(Exception):
    """Base class for role domain errors."""


class RoleNotFound(RoleServiceError):
    pass


class RoleNameExists(RoleServiceError):
    pass


class SystemRoleProtected(RoleServiceError):
    """Attempted to delete a system (protected) role."""


def apply_implied_read(keys: List[str]) -> List[str]:
    """Any granted non-read action on a resource implies `<resource>.read`."""
    result = set(keys)
    for key in keys:
        resource, _, action = key.partition(".")
        if action and action != "read":
            result.add(f"{resource}.read")
    return list(result)


class RoleService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = RoleRepository(db)
        self.permissions = PermissionRepository(db)

    # ---- reads ----

    def list(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[List[Role], int]:
        clause = translate_filter(filter_group, _ROLE_FILTER_COLUMNS)
        return self.repo.paginate(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=clause,
        )

    def user_counts(self, role_ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> Dict[str, int]:
        return self.repo.user_counts(role_ids, tenant_id)

    def user_count(self, role_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> int:
        return self.repo.user_counts([role_id], tenant_id).get(role_id, 0)

    def get(self, role_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> Role:
        role = self.repo.get_by_id(role_id, tenant_id)
        if role is None:
            raise RoleNotFound()
        return role

    def get_at(
        self,
        index: int,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[Optional[Role], int]:
        rows, total = self.list(
            tenant_id,
            page=max(index, 0),
            page_size=1,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=filter_group,
        )
        return (rows[0] if rows else None), total

    def get_assigned_users(
        self, role_id: str, tenant_id: str = DEFAULT_TENANT_ID, search: Optional[str] = None
    ) -> List[Tuple[User, datetime]]:
        self.get(role_id, tenant_id)  # 404 if missing
        return self.repo.get_assigned_users(role_id, tenant_id, search)

    def list_assignable(
        self, role_id: str, tenant_id: str = DEFAULT_TENANT_ID, search: Optional[str] = None
    ) -> List[User]:
        self.get(role_id, tenant_id)
        return self.repo.list_assignable(role_id, tenant_id, search)

    # ---- writes ----

    def _grantable(self, keys: List[str], tenant_id: str):
        """Resolve keys → permission rows a TENANT role may hold (plan 08 §6):
        platform keys never; module keys only while the module is installed for
        the tenant. Platform-tenant roles are exempt (operator catalog)."""
        from app.models.tenant import PLATFORM_TENANT_ID
        from app.repositories.module_repository import ModuleRepository
        from app.services.permission_service import CORE_MODULE, PLATFORM_MODULE

        perms = self.permissions.get_by_keys(keys)
        if tenant_id == PLATFORM_TENANT_ID:
            return perms
        installed = ModuleRepository(self.db).installed_module_names(tenant_id)
        return [
            p
            for p in perms
            if p.module != PLATFORM_MODULE
            and (p.module == CORE_MODULE or p.module in installed)
        ]

    def create(
        self,
        name: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        description: Optional[str] = None,
        permission_keys: Optional[List[str]] = None,
        is_system: bool = False,
    ) -> Role:
        role = Role(tenant_id=tenant_id, name=name, description=description, is_system=is_system)
        keys = apply_implied_read(permission_keys or [])
        role.permissions = self._grantable(keys, tenant_id)
        try:
            saved = self.repo.add(role)
        except IntegrityError:
            self.db.rollback()
            raise RoleNameExists()
        notify_entity_event(self.db, "role", "created", saved, tenant_id=tenant_id)
        return saved

    def update(
        self,
        role_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        permission_keys: Optional[List[str]] = None,
        is_system: Optional[bool] = None,
        description_set: bool = False,
    ) -> Role:
        role = self.get(role_id, tenant_id)
        changes: dict = {}
        if name is not None and role.name != name:
            changes["name"] = {"from": role.name, "to": name}
            role.name = name
        if description_set and role.description != description:
            changes["description"] = {"from": role.description, "to": description}
            role.description = description
        if is_system is not None:
            role.is_system = is_system
        if permission_keys is not None:
            keys = apply_implied_read(permission_keys)
            role.permissions = self._grantable(keys, tenant_id)
        try:
            saved = self.repo.save(role)
        except IntegrityError:
            self.db.rollback()
            raise RoleNameExists()
        notify_entity_event(self.db, "role", "updated", saved, tenant_id=tenant_id, changes=changes or None)
        return saved

    def delete(self, role_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        role = self.get(role_id, tenant_id)
        if role.is_system:
            raise SystemRoleProtected()
        # Emit BEFORE the delete commits - record facts captured while live; the
        # delete's own commit drains the buffer (rolled-back delete discards it).
        emit_entity_event(self.db, "role", "deleted", role, tenant_id=tenant_id)
        self.repo.delete(role)

    def assign_users(
        self, role_id: str, user_ids: List[str], tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        role = self.get(role_id, tenant_id)
        self.repo.assign_users(role, user_ids, tenant_id)

    def remove_user(self, role_id: str, user_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        role = self.get(role_id, tenant_id)
        self.repo.remove_user(role, user_id, tenant_id)

    # ---- export ----

    def export_csv(
        self,
        columns: List[str],
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        ids: Optional[List[str]] = None,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> str:
        rows, _ = self.list(
            tenant_id,
            page=0,
            page_size=100_000,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=filter_group,
        )
        if ids:
            id_set = set(ids)
            rows = [r for r in rows if r.id in id_set]
        counts = self.user_counts([r.id for r in rows], tenant_id)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        for role in rows:
            writer.writerow([_column_value(role, c, counts.get(role.id, 0)) for c in columns])
        return buffer.getvalue()


def _column_value(role: Role, column: str, user_count: int) -> str:
    if column in ("role", "name"):
        return role.name
    if column == "description":
        return role.description or ""
    if column == "users":
        return str(user_count)
    if column == "permissions":
        return str(len(role.permissions))
    if column == "created":
        return role.created_at.isoformat() if role.created_at else ""
    return ""
