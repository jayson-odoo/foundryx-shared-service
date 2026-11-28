"""Dashboard store queries. EVERY query is scoped by tenant_id AND product; a recipient is
resolved through ``dash_share`` and never by a bare id."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session

from ..models import DashDashboard, DashIdempotency, DashShare, DashVersion


class DashboardRepository:
    def __init__(self, db: Session, tenant_id: str, product: str):
        self.db = db
        self.tenant_id = tenant_id
        self.product = product

    def _scoped(self, model):
        return and_(model.tenant_id == self.tenant_id, model.product == self.product)

    # -- dashboards ----------------------------------------------------------------------------------
    def get(self, dashboard_id: str) -> Optional[DashDashboard]:
        return (
            self.db.query(DashDashboard)
            .filter(DashDashboard.id == dashboard_id, self._scoped(DashDashboard))
            .first()
        )

    def add(self, row: DashDashboard) -> DashDashboard:
        row.tenant_id, row.product = self.tenant_id, self.product
        self.db.add(row)
        self.db.flush()
        return row

    def delete(self, row: DashDashboard) -> None:
        self.db.query(DashShare).filter(DashShare.dashboard_id == row.id, self._scoped(DashShare)).delete()
        self.db.query(DashVersion).filter(DashVersion.dashboard_id == row.id, self._scoped(DashVersion)).delete()
        self.db.delete(row)
        self.db.flush()

    def _shared_with(self, actor_ref: str):
        return exists().where(
            DashShare.dashboard_id == DashDashboard.id,
            self._scoped(DashShare),
            DashShare.user_ref == actor_ref,
        )

    def is_recipient(self, dashboard_id: str, actor_ref: str) -> bool:
        return (
            self.db.query(DashShare.id)
            .filter(DashShare.dashboard_id == dashboard_id, self._scoped(DashShare), DashShare.user_ref == actor_ref)
            .first()
            is not None
        )

    def list(self, actor_ref: str, scope: str, q: Optional[str], sort: str, direction: str,
             page: int, limit: int) -> Tuple[List[DashDashboard], int]:
        mine = DashDashboard.owner_ref == actor_ref
        shared = self._shared_with(actor_ref)
        cond = {"mine": mine, "shared": and_(~mine, shared)}.get(scope, or_(mine, shared))
        query = self.db.query(DashDashboard).filter(self._scoped(DashDashboard), cond)
        if q and q.strip():
            esc = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.filter(DashDashboard.name.ilike(f"%{esc}%", escape="\\"))
        total = query.count()
        col = {"name": func.lower(DashDashboard.name), "updated_at": DashDashboard.updated_at,
               "owner_ref": DashDashboard.owner_ref}[sort]
        query = query.order_by(col.desc() if direction == "desc" else col.asc(), DashDashboard.id.asc())
        return query.offset((page - 1) * limit).limit(limit).all(), total

    # -- shares --------------------------------------------------------------------------------------
    def share_refs(self, dashboard_id: str) -> List[str]:
        rows = (
            self.db.query(DashShare.user_ref)
            .filter(DashShare.dashboard_id == dashboard_id, self._scoped(DashShare))
            .order_by(DashShare.position.asc(), DashShare.user_ref.asc())
            .all()
        )
        return [r[0] for r in rows]

    def share_counts(self, dashboard_ids: List[str]) -> Dict[str, int]:
        if not dashboard_ids:
            return {}
        rows = (
            self.db.query(DashShare.dashboard_id, func.count(DashShare.id))
            .filter(DashShare.dashboard_id.in_(dashboard_ids), self._scoped(DashShare))
            .group_by(DashShare.dashboard_id)
            .all()
        )
        return {d: n for d, n in rows}

    def replace_shares(self, dashboard_id: str, refs: List[str]) -> None:
        self.db.query(DashShare).filter(DashShare.dashboard_id == dashboard_id, self._scoped(DashShare)).delete()
        self.db.flush()
        for i, ref in enumerate(refs):
            self.db.add(DashShare(dashboard_id=dashboard_id, tenant_id=self.tenant_id, product=self.product,
                                  user_ref=ref, position=i))
        self.db.flush()

    # -- versions ------------------------------------------------------------------------------------
    def add_version(self, row: DashVersion) -> DashVersion:
        row.tenant_id, row.product = self.tenant_id, self.product
        self.db.add(row)
        self.db.flush()
        return row

    def versions(self, dashboard_id: str, page: int, limit: int) -> Tuple[List[DashVersion], int]:
        query = self.db.query(DashVersion).filter(DashVersion.dashboard_id == dashboard_id, self._scoped(DashVersion))
        total = query.count()
        rows = query.order_by(DashVersion.version.desc()).offset((page - 1) * limit).limit(limit).all()
        return rows, total

    # -- idempotency ---------------------------------------------------------------------------------
    def get_idempotent(self, key_id: str, actor_ref: str, idem: str, since: datetime) -> Optional[DashIdempotency]:
        row = (
            self.db.query(DashIdempotency)
            .filter(DashIdempotency.key_id == key_id, DashIdempotency.actor_ref == actor_ref,
                    DashIdempotency.idem_ref == idem, self._scoped(DashIdempotency))
            .first()
        )
        if row is not None and row.created_at < since:
            self.db.delete(row)  # expired: the key may be used again
            self.db.flush()
            return None
        return row

    def add_idempotent(self, row: DashIdempotency) -> None:
        row.tenant_id, row.product = self.tenant_id, self.product
        self.db.add(row)
        self.db.flush()
