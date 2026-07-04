"""Workspace repository — tenant-scoped queries + membership. Pure SQLAlchemy."""
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from app.models.user import User
from ..models import Channel, Workspace, WorkspaceMember

_SORT = {"name": Workspace.name, "created": Workspace.created_at}


class WorkspaceRepository:
    def __init__(self, db: Session):
        self.db = db

    def paginate(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        trashed: bool = False,
    ) -> Tuple[List[Workspace], int]:
        q = self.db.query(Workspace).filter(
            Workspace.tenant_id == tenant_id, Workspace.is_trashed.is_(trashed)
        )
        if search and search.strip():
            q = q.filter(Workspace.name.ilike(f"%{search.strip()}%"))
        total = q.count()
        col = _SORT.get(sort_by or "", Workspace.created_at)
        q = q.order_by(col.desc() if sort_dir == "desc" else col.asc(), Workspace.id.asc())
        rows = q.offset(page * page_size).limit(page_size).all()
        return rows, total

    def all_scoped(self, tenant_id: str, *, trashed: bool = False) -> List[Workspace]:
        return (
            self.db.query(Workspace)
            .filter(Workspace.tenant_id == tenant_id, Workspace.is_trashed.is_(trashed))
            .order_by(Workspace.created_at.desc(), Workspace.id.asc())
            .all()
        )

    def get_by_id(self, ws_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> Optional[Workspace]:
        return (
            self.db.query(Workspace)
            .filter(Workspace.tenant_id == tenant_id, Workspace.id == ws_id)
            .first()
        )

    def get_many(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> List[Workspace]:
        if not ids:
            return []
        return (
            self.db.query(Workspace)
            .filter(Workspace.tenant_id == tenant_id, Workspace.id.in_(ids))
            .all()
        )

    def channel_counts(self, ws_ids: List[str]) -> Dict[str, int]:
        if not ws_ids:
            return {}
        rows = (
            self.db.query(Channel.workspace_id, func.count())
            .filter(Channel.workspace_id.in_(ws_ids), Channel.is_trashed.is_(False))
            .group_by(Channel.workspace_id)
            .all()
        )
        return {wid: c for wid, c in rows}

    def member_counts(self, ws_ids: List[str]) -> Dict[str, int]:
        if not ws_ids:
            return {}
        rows = (
            self.db.query(WorkspaceMember.workspace_id, func.count())
            .filter(WorkspaceMember.workspace_id.in_(ws_ids))
            .group_by(WorkspaceMember.workspace_id)
            .all()
        )
        return {wid: c for wid, c in rows}

    # ---- members ----
    def members(
        self, workspace_id: str, tenant_id: str, search: Optional[str] = None
    ) -> List[Tuple[WorkspaceMember, User]]:
        q = (
            self.db.query(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.tenant_id == tenant_id,
                User.is_trashed.is_(False),
            )
        )
        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(or_(User.name.ilike(term), User.email.ilike(term)))
        return q.order_by(WorkspaceMember.created_at.desc()).all()

    def list_assignable(
        self, workspace_id: str, tenant_id: str, search: Optional[str] = None
    ) -> List[User]:
        taken = select(WorkspaceMember.user_id).where(
            WorkspaceMember.workspace_id == workspace_id
        )
        q = self.db.query(User).filter(
            User.tenant_id == tenant_id,
            User.is_trashed.is_(False),
            User.id.notin_(taken),
        )
        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(or_(User.name.ilike(term), User.email.ilike(term)))
        return q.order_by(User.name.asc()).all()

    def member_exists(self, workspace_id: str, user_id: str) -> bool:
        return (
            self.db.query(WorkspaceMember.id)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .first()
            is not None
        )

    def add_member(self, workspace_id: str, tenant_id: str, user_id: str) -> None:
        self.db.add(
            WorkspaceMember(tenant_id=tenant_id, workspace_id=workspace_id, user_id=user_id)
        )

    def remove_member(self, workspace_id: str, user_id: str) -> None:
        self.db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        ).delete()

    def get_member_assigned_at(self, workspace_id: str, user_id: str) -> Optional[datetime]:
        row = (
            self.db.query(WorkspaceMember.created_at)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .first()
        )
        return row[0] if row else None
