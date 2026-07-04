"""Role repository — tenant-scoped role queries, grants, and user assignment.

Pure SQLAlchemy; no business rules. Every query is bounded by `tenant_id`.
"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models.permission import Permission
from app.models.role import Role, user_roles
from app.models.tenant import DEFAULT_TENANT_ID
from app.models.user import User

# Sortable list columns (frontend column id -> Role column). Count columns
# (users/permissions) gracefully fall back to created order.
_SORT_COLUMNS = {
    "role": Role.name,
    "name": Role.name,
    "description": Role.description,
    "created": Role.created_at,
}


class RoleRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- reads ----

    def list(self, tenant_id: str = DEFAULT_TENANT_ID) -> List[Role]:
        return (
            self.db.query(Role)
            .filter(Role.tenant_id == tenant_id)
            .order_by(Role.name.asc())
            .all()
        )

    def get_many(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> List[Role]:
        if not ids:
            return []
        return (
            self.db.query(Role)
            .filter(Role.tenant_id == tenant_id, Role.id.in_(ids))
            .all()
        )

    def get_by_id(self, role_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> Optional[Role]:
        return (
            self.db.query(Role)
            .filter(Role.tenant_id == tenant_id, Role.id == role_id)
            .first()
        )

    def paginate(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_clause=None,
    ) -> Tuple[List[Role], int]:
        q = self.db.query(Role).filter(Role.tenant_id == tenant_id)

        if search and search.strip():
            term = f"%{search.strip()}%"
            # Search the role itself, its assigned users, and its permission keys.
            users_subq = (
                select(user_roles.c.role_id)
                .join(User, User.id == user_roles.c.user_id)
                .where(
                    User.tenant_id == tenant_id,
                    or_(User.name.ilike(term), User.email.ilike(term)),
                )
            )
            q = q.filter(
                or_(
                    Role.name.ilike(term),
                    Role.description.ilike(term),
                    Role.permissions.any(Permission.key.ilike(term)),
                    Role.id.in_(users_subq),
                )
            )

        if filter_clause is not None:
            q = q.filter(filter_clause)

        total = q.count()

        column = _SORT_COLUMNS.get(sort_by or "", Role.created_at)
        q = q.order_by(column.desc() if sort_dir == "desc" else column.asc())
        q = q.order_by(Role.id.asc())  # stable tiebreak

        rows = q.offset(page * page_size).limit(page_size).all()
        return rows, total

    def user_counts(self, role_ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> Dict[str, int]:
        if not role_ids:
            return {}
        # role_id already scopes to this tenant's roles; join users to exclude
        # trashed members (and to avoid trusting the association's tenant_id).
        rows = (
            self.db.query(user_roles.c.role_id, func.count())
            .join(User, User.id == user_roles.c.user_id)
            .filter(user_roles.c.role_id.in_(role_ids), User.is_trashed.is_(False))
            .group_by(user_roles.c.role_id)
            .all()
        )
        return {role_id: count for role_id, count in rows}

    def get_assigned_users(
        self, role_id: str, tenant_id: str = DEFAULT_TENANT_ID, search: Optional[str] = None
    ) -> List[Tuple[User, datetime]]:
        q = (
            self.db.query(User, user_roles.c.assigned_at)
            .join(user_roles, user_roles.c.user_id == User.id)
            .filter(
                user_roles.c.role_id == role_id,
                User.tenant_id == tenant_id,
                User.is_trashed.is_(False),
            )
        )
        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(or_(User.name.ilike(term), User.email.ilike(term)))
        return q.order_by(user_roles.c.assigned_at.desc()).all()

    def list_assignable(
        self, role_id: str, tenant_id: str = DEFAULT_TENANT_ID, search: Optional[str] = None
    ) -> List[User]:
        assigned_subq = select(user_roles.c.user_id).where(user_roles.c.role_id == role_id)
        q = self.db.query(User).filter(
            User.tenant_id == tenant_id,
            User.is_trashed.is_(False),
            User.id.notin_(assigned_subq),
        )
        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(or_(User.name.ilike(term), User.email.ilike(term)))
        return q.order_by(User.name.asc()).all()

    # ---- writes ----

    def add(self, role: Role) -> Role:
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role

    def save(self, role: Role) -> Role:
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role

    def delete(self, role: Role) -> None:
        self.db.delete(role)
        self.db.commit()

    def assign_users(self, role: Role, user_ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> None:
        if not user_ids:
            return
        users = (
            self.db.query(User)
            .filter(User.tenant_id == tenant_id, User.id.in_(user_ids))
            .all()
        )
        for user in users:
            if role not in user.roles:
                user.roles.append(role)
        self.db.commit()

    def remove_user(self, role: Role, user_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        user = (
            self.db.query(User)
            .filter(User.tenant_id == tenant_id, User.id == user_id)
            .first()
        )
        if user and role in user.roles:
            user.roles.remove(role)
            self.db.commit()
