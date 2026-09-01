"""Document-sharing persistence (plan sprint-3/05) - pure SQLAlchemy, ALWAYS
tenant-scoped (the multi-tenancy invariant). The PUBLIC resolve path looks a
share up by its globally-unique ``token`` (the bearer capability self-identifies
the tenant - D9), then every downstream query re-scopes by the resolved
``share.tenant_id``. The service owns the transaction (flush, not commit)."""
from typing import List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.document import FileLink, FileShare, FileShareUser


class ShareRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- shares ----

    def get_by_token(self, token: str) -> Optional[FileShare]:
        """The ONE non-tenant-scoped lookup - the token is the global capability."""
        return self.db.query(FileShare).filter(FileShare.token == token).first()

    def get(self, tenant_id: str, share_id: str) -> Optional[FileShare]:
        return (
            self.db.query(FileShare)
            .filter(FileShare.id == share_id, FileShare.tenant_id == tenant_id)
            .first()
        )

    def for_target(
        self, tenant_id: str, target_kind: str, target_id: str
    ) -> List[FileShare]:
        return (
            self.db.query(FileShare)
            .filter(
                FileShare.tenant_id == tenant_id,
                FileShare.target_kind == target_kind,
                FileShare.target_id == target_id,
            )
            .order_by(FileShare.created_at.desc())
            .all()
        )

    def active_in_tenant(self, tenant_id: str) -> List[FileShare]:
        """All non-disabled shares in a tenant - for the 'Shared with me' filter
        (authorization is applied in the service per-user)."""
        return (
            self.db.query(FileShare)
            .filter(
                FileShare.tenant_id == tenant_id,
                FileShare.is_disabled.is_(False),
            )
            .order_by(FileShare.created_at.desc())
            .all()
        )

    def add(self, share: FileShare) -> FileShare:
        self.db.add(share)
        self.db.flush()
        return share

    def add_share_user(self, row: FileShareUser) -> FileShareUser:
        self.db.add(row)
        self.db.flush()
        return row

    def share_users(self, share_id: str) -> List[FileShareUser]:
        return (
            self.db.query(FileShareUser)
            .filter(FileShareUser.share_id == share_id)
            .all()
        )

    def paginate(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        disabled: bool = False,
    ) -> Tuple[List[FileShare], int]:
        query = self.db.query(FileShare).filter(
            FileShare.tenant_id == tenant_id,
            FileShare.is_disabled.is_(disabled),
        )
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    FileShare.general_access.ilike(like),
                    FileShare.general_capability.ilike(like),
                )
            )
        total = query.count()
        sort_map = {
            "access": FileShare.general_access,
            "capability": FileShare.general_capability,
            "createdAt": FileShare.created_at,
            "expiresAt": FileShare.expires_at,
        }
        col = sort_map.get(sort_by or "createdAt", FileShare.created_at)
        query = query.order_by(col.desc() if sort_dir == "desc" else col.asc())
        rows = query.offset(page * page_size).limit(page_size).all()
        return rows, total

    # ---- file_links seam ----

    def add_link(self, row: FileLink) -> FileLink:
        self.db.add(row)
        self.db.flush()
        return row

    def get_link(self, tenant_id: str, link_id: str) -> Optional[FileLink]:
        return (
            self.db.query(FileLink)
            .filter(FileLink.id == link_id, FileLink.tenant_id == tenant_id)
            .first()
        )

    def links_for_entity(
        self, tenant_id: str, entity_type: str, entity_id: str
    ) -> List[FileLink]:
        return (
            self.db.query(FileLink)
            .filter(
                FileLink.tenant_id == tenant_id,
                FileLink.entity_type == entity_type,
                FileLink.entity_id == entity_id,
            )
            .order_by(FileLink.created_at.desc())
            .all()
        )

    def delete_link(self, link: FileLink) -> None:
        self.db.delete(link)
        self.db.flush()
