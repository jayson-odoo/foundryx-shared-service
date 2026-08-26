"""Channel repository - tenant-scoped channel queries. Pure SQLAlchemy."""
from typing import List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from ..models import Channel

_SORT = {
    "name": Channel.name,
    "created": Channel.created_at,
    "displayPhoneNumber": Channel.display_phone_number,
}


class ChannelRepository:
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
    ) -> Tuple[List[Channel], int]:
        q = self.db.query(Channel).filter(
            Channel.tenant_id == tenant_id, Channel.is_trashed.is_(trashed)
        )
        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(or_(Channel.name.ilike(term), Channel.display_phone_number.ilike(term)))
        total = q.count()
        col = _SORT.get(sort_by or "", Channel.created_at)
        q = q.order_by(col.desc() if sort_dir == "desc" else col.asc(), Channel.id.asc())
        rows = q.offset(page * page_size).limit(page_size).all()
        return rows, total

    def all_scoped(self, tenant_id: str, *, trashed: bool = False) -> List[Channel]:
        return (
            self.db.query(Channel)
            .filter(Channel.tenant_id == tenant_id, Channel.is_trashed.is_(trashed))
            .order_by(Channel.created_at.desc(), Channel.id.asc())
            .all()
        )

    def active_scoped(self, tenant_id: str) -> List[Channel]:
        """Live channel candidates. Credential suitability stays in service
        logic because repositories never decrypt secrets."""
        return (
            self.db.query(Channel)
            .filter(
                Channel.tenant_id == tenant_id,
                Channel.is_active.is_(True),
                Channel.is_trashed.is_(False),
            )
            .order_by(Channel.name.asc(), Channel.id.asc())
            .all()
        )

    def get_active_by_id(self, channel_id: str, tenant_id: str) -> Optional[Channel]:
        return (
            self.db.query(Channel)
            .filter(
                Channel.id == channel_id,
                Channel.tenant_id == tenant_id,
                Channel.is_active.is_(True),
                Channel.is_trashed.is_(False),
            )
            .first()
        )

    def list_by_workspace(self, workspace_id: str, tenant_id: str) -> List[Channel]:
        return (
            self.db.query(Channel)
            .filter(
                Channel.tenant_id == tenant_id,
                Channel.workspace_id == workspace_id,
                Channel.is_trashed.is_(False),
            )
            .order_by(Channel.created_at.desc(), Channel.id.asc())
            .all()
        )

    def get_by_id(self, channel_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> Optional[Channel]:
        return (
            self.db.query(Channel)
            .filter(Channel.tenant_id == tenant_id, Channel.id == channel_id)
            .first()
        )

    def get_many(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> List[Channel]:
        if not ids:
            return []
        return (
            self.db.query(Channel)
            .filter(Channel.tenant_id == tenant_id, Channel.id.in_(ids))
            .all()
        )
