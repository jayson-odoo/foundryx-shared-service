"""Status repository (sprint-2/01) - pure SQLAlchemy, two-tier resolution.

Two-tier (D7): reads for an entity_type return the TENANT's rows when any
exist for that entity_type, else the platform defaults (``tenant_id NULL``).
Platform-owned entities (registry flag) only ever have the NULL tier.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.status import Status


class StatusRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- tier resolution (D7) ----

    def tenant_has_fork(self, entity_type: str, tenant_id: Optional[str]) -> bool:
        if tenant_id is None:
            return False
        return (
            self.db.query(Status.id)
            .filter(Status.entity_type == entity_type, Status.tenant_id == tenant_id)
            .first()
            is not None
        )

    def resolve_tier(self, entity_type: str, tenant_id: Optional[str]) -> Optional[str]:
        """The owning tenant_id of the visible set - tenant fork or None (platform)."""
        return tenant_id if self.tenant_has_fork(entity_type, tenant_id) else None

    def list_for_entity(
        self,
        entity_type: str,
        tenant_id: Optional[str],
        include_inactive: bool = True,
        scope_id: Optional[str] = None,
    ) -> List[Status]:
        """``scope_id`` (sprint-3/01 D4): a scoped entity's rows live per
        owning record. None filters IS NULL - unscoped reads never see
        scoped rows and vice versa."""
        tier = self.resolve_tier(entity_type, tenant_id)
        q = self.db.query(Status).filter(
            Status.entity_type == entity_type,
            Status.tenant_id.is_(None) if tier is None else Status.tenant_id == tier,
            Status.scope_id.is_(None) if scope_id is None else Status.scope_id == scope_id,
        )
        if not include_inactive:
            q = q.filter(Status.is_active.is_(True))
        return q.order_by(Status.sort_order.asc(), Status.created_at.asc()).all()

    # ---- single rows ----

    def get_by_id(self, status_id: str) -> Optional[Status]:
        return self.db.query(Status).filter(Status.id == status_id).first()

    def get_by_key(
        self,
        entity_type: str,
        key: str,
        tenant_id: Optional[str],
        scope_id: Optional[str] = None,
    ) -> Optional[Status]:
        tier = self.resolve_tier(entity_type, tenant_id)
        return (
            self.db.query(Status)
            .filter(
                Status.entity_type == entity_type,
                Status.key == key,
                Status.tenant_id.is_(None) if tier is None else Status.tenant_id == tier,
                Status.scope_id.is_(None) if scope_id is None else Status.scope_id == scope_id,
            )
            .first()
        )

    # ---- writes ----

    def add(self, status: Status) -> Status:
        self.db.add(status)
        self.db.flush()
        return status

    def delete(self, status: Status) -> None:
        self.db.delete(status)
        self.db.flush()
