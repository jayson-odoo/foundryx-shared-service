"""Workspace business logic — tenant-scoped. Routers stay thin; this owns rules
(default-workspace protection, status resolution, membership)."""
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from app.models.user import User
from ..models import Workspace
from ..repositories.workspace_repository import WorkspaceRepository
from ..schemas import (
    MemberCandidateItem,
    WorkspaceCreate,
    WorkspaceItem,
    WorkspaceMemberItem,
    WorkspaceUpdate,
)
from . import statuses


class WorkspaceNotFound(Exception):
    pass


class DefaultWorkspaceProtected(Exception):
    pass


class WorkspaceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = WorkspaceRepository(db)

    # ---- helpers ----
    def _item(self, ws: Workspace, status_map, channel_counts, member_counts) -> WorkspaceItem:
        return WorkspaceItem(
            id=ws.id,
            tenantId=ws.tenant_id,
            name=ws.name,
            status=status_map.get(ws.status_id, "ACTIVE"),
            channelCount=channel_counts.get(ws.id, 0),
            memberCount=member_counts.get(ws.id, 0),
            isDefault=ws.is_default,
            isTrashed=ws.is_trashed,
            createdAt=ws.created_at,
            updatedAt=ws.updated_at,
        )

    def _items(self, rows: List[Workspace], tenant_id: str) -> List[WorkspaceItem]:
        ids = [w.id for w in rows]
        smap = statuses.id_to_key_map(self.db, tenant_id)
        cc = self.repo.channel_counts(ids)
        mc = self.repo.member_counts(ids)
        return [self._item(w, smap, cc, mc) for w in rows]

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
        status_view: str = "active",
    ) -> Tuple[List[WorkspaceItem], int]:
        rows, total = self.repo.paginate(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            trashed=status_view == "trashed",
        )
        return self._items(rows, tenant_id), total

    def get(self, ws_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> WorkspaceItem:
        ws = self.repo.get_by_id(ws_id, tenant_id)
        if ws is None:
            raise WorkspaceNotFound()
        return self._items([ws], tenant_id)[0]

    def get_at(
        self, index: int, tenant_id: str = DEFAULT_TENANT_ID, *, status_view: str = "active",
        search: Optional[str] = None, sort_by: Optional[str] = None, sort_dir: str = "asc",
    ) -> Tuple[Optional[WorkspaceItem], int]:
        rows, total = self.repo.paginate(
            tenant_id, page=0, page_size=10_000, search=search, sort_by=sort_by,
            sort_dir=sort_dir, trashed=status_view == "trashed",
        )
        if index < 0 or index >= len(rows):
            return None, total
        return self._items([rows[index]], tenant_id)[0], total

    # ---- writes ----
    def create(self, payload: WorkspaceCreate, tenant_id: str = DEFAULT_TENANT_ID) -> WorkspaceItem:
        statuses.ensure_statuses(self.db, tenant_id)
        ws = Workspace(
            tenant_id=tenant_id,
            name=payload.name.strip(),
            status_id=statuses.status_id_for(self.db, tenant_id, "WORKSPACE", payload.status),
            is_default=False,
            is_trashed=False,
        )
        self.db.add(ws)
        self.db.commit()
        self.db.refresh(ws)
        return self._items([ws], tenant_id)[0]

    def update(
        self, ws_id: str, payload: WorkspaceUpdate, tenant_id: str = DEFAULT_TENANT_ID
    ) -> WorkspaceItem:
        ws = self.repo.get_by_id(ws_id, tenant_id)
        if ws is None:
            raise WorkspaceNotFound()
        if payload.name is not None:
            ws.name = payload.name.strip()
        if payload.status is not None:
            ws.status_id = statuses.status_id_for(self.db, tenant_id, "WORKSPACE", payload.status)
        self.db.commit()
        self.db.refresh(ws)
        return self._items([ws], tenant_id)[0]

    def trash(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> None:
        for ws in self.repo.get_many(ids, tenant_id):
            if ws.is_default:
                raise DefaultWorkspaceProtected()
            ws.is_trashed = True
        self.db.commit()

    def restore(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> None:
        for ws in self.repo.get_many(ids, tenant_id):
            ws.is_trashed = False
        self.db.commit()

    # ---- members ----
    def members(
        self, ws_id: str, tenant_id: str = DEFAULT_TENANT_ID, search: Optional[str] = None
    ) -> List[WorkspaceMemberItem]:
        if self.repo.get_by_id(ws_id, tenant_id) is None:
            raise WorkspaceNotFound()
        out: List[WorkspaceMemberItem] = []
        for member, user in self.repo.members(ws_id, tenant_id, search):
            out.append(
                WorkspaceMemberItem(
                    id=member.id,
                    userId=user.id,
                    name=user.name,
                    email=user.email,
                    status=user.status,
                    assignedAt=member.created_at,
                )
            )
        return out

    def list_assignable(
        self, ws_id: str, tenant_id: str = DEFAULT_TENANT_ID, search: Optional[str] = None
    ) -> List[MemberCandidateItem]:
        if self.repo.get_by_id(ws_id, tenant_id) is None:
            raise WorkspaceNotFound()
        users: List[User] = self.repo.list_assignable(ws_id, tenant_id, search)
        return [
            MemberCandidateItem(userId=u.id, name=u.name, email=u.email, status=u.status)
            for u in users
        ]

    def assign_members(
        self, ws_id: str, user_ids: List[str], tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        if self.repo.get_by_id(ws_id, tenant_id) is None:
            raise WorkspaceNotFound()
        for uid in user_ids:
            if not self.repo.member_exists(ws_id, uid):
                self.repo.add_member(ws_id, tenant_id, uid)
        self.db.commit()

    def remove_member(self, ws_id: str, user_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        if self.repo.get_by_id(ws_id, tenant_id) is None:
            raise WorkspaceNotFound()
        self.repo.remove_member(ws_id, user_id)
        self.db.commit()
