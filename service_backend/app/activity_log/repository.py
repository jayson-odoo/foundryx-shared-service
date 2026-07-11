"""Integration-activity repository (sprint-4/12) — pure SQLAlchemy, tenant-scoped.

Every query filters by ``tenant_id`` (the tenant comes from the authenticated
context, never client input). The read side backs the Developers → Logs console;
the whitelisted filter map lives in the service (the translator never touches
arbitrary columns).
"""
from typing import List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.integration_activity import IntegrationActivity


class IntegrationActivityRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, row: IntegrationActivity) -> IntegrationActivity:
        self.db.add(row)
        self.db.flush()
        return row

    def get(self, tenant_id: str, row_id: str) -> Optional[IntegrationActivity]:
        return (
            self.db.query(IntegrationActivity)
            .filter(
                IntegrationActivity.tenant_id == tenant_id,
                IntegrationActivity.id == row_id,
            )
            .first()
        )

    def list(
        self,
        tenant_id: str,
        *,
        clause=None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_desc: bool = True,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[IntegrationActivity], int]:
        q = self.db.query(IntegrationActivity).filter(
            IntegrationActivity.tenant_id == tenant_id
        )
        if clause is not None:
            q = q.filter(clause)
        if search:
            like = f"%{search}%"
            q = q.filter(
                or_(
                    IntegrationActivity.operation.ilike(like),
                    IntegrationActivity.trace_id.ilike(like),
                    IntegrationActivity.external_ref.ilike(like),
                )
            )
        total = q.count()

        sort_col = getattr(IntegrationActivity, sort_by, IntegrationActivity.created_at)
        order = sort_col.desc() if sort_desc else sort_col.asc()
        rows = (
            q.order_by(order, IntegrationActivity.id.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total
