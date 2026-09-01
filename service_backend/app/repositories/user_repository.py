"""User repository - pure SQLAlchemy queries, all tenant-scoped.

No business logic here; no HTTP concerns. Every lookup is bounded by `tenant_id`
so one tenant can never read another's rows (multi-tenancy groundwork, BL-004).
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from app.models.user import User

# Sortable list columns (frontend column id -> User column).
_SORT_COLUMNS = {
    "user": User.name,
    "name": User.name,
    "email": User.email,
    "status": User.status,
    "joined": User.created_at,
    "lastSignIn": User.last_sign_in_at,
}


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_email(
        self, email: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> Optional[User]:
        return (
            self.db.query(User)
            .filter(
                User.tenant_id == tenant_id,
                User.email == email,
                User.is_trashed.is_(False),
            )
            .first()
        )

    def get_by_id(
        self,
        user_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        include_trashed: bool = False,
    ) -> Optional[User]:
        q = self.db.query(User).filter(
            User.tenant_id == tenant_id,
            User.id == user_id,
        )
        if not include_trashed:
            q = q.filter(User.is_trashed.is_(False))
        return q.first()

    def exists_by_email(
        self,
        email: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        include_trashed: bool = False,
    ) -> bool:
        """`include_trashed=True` mirrors uq_users_tenant_email, which covers
        trashed rows too - uniqueness guards must check the constraint's full
        scope or the flush 500s where a clean 409 was intended."""
        if not include_trashed:
            return self.get_by_email(email, tenant_id) is not None
        return (
            self.db.query(User.id)
            .filter(User.tenant_id == tenant_id, User.email == email)
            .first()
            is not None
        )

    def list(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_clause=None,
        status_view: str = "active",
    ) -> Tuple[List[User], int]:
        """Server-side list: search + filter + sort + paginate. Returns (rows, total)."""
        q = self.db.query(User).filter(User.tenant_id == tenant_id)
        q = q.filter(User.is_trashed.is_(status_view == "trashed"))

        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(or_(User.name.ilike(term), User.email.ilike(term)))

        if filter_clause is not None:
            q = q.filter(filter_clause)

        total = q.count()

        column = _SORT_COLUMNS.get(sort_by or "", User.created_at)
        q = q.order_by(column.desc() if sort_dir == "desc" else column.asc())
        # Stable tiebreak so pagination + record-nav are deterministic.
        q = q.order_by(User.id.asc())

        rows = q.offset(page * page_size).limit(page_size).all()
        return rows, total

    def add(self, user: User) -> User:
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def save(self, user: User) -> User:
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def set_trashed(self, ids: List[str], tenant_id: str, trashed: bool) -> None:
        if not ids:
            return
        self.db.query(User).filter(
            User.tenant_id == tenant_id, User.id.in_(ids)
        ).update({User.is_trashed: trashed}, synchronize_session=False)
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()

    def touch_last_sign_in(self, user: User) -> None:
        user.last_sign_in_at = datetime.now(timezone.utc)
        self.db.add(user)
        self.db.commit()
