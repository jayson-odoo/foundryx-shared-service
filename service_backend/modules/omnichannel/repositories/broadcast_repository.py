"""Broadcast repository - tenant + workspace scoped, pure SQLAlchemy (plan 29,
roadmap A4). No business logic here (Router -> Service -> Repository).

The list whitelist (AC-BRD-20) is `name, status, channel, scheduledAt,
createdAt, createdBy` - anything else is a 422. `channel` and `createdBy` are
TEXT search fields on the frontend (channel NAME / created-by display name),
not the raw ids stored on the row, so both resolve via a tenant-scoped
subquery into `Channel`/`User` (never a bare id match on free text) - the
same "special resolver" shape `contact_filters.py` uses for `assignee`.
"""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import false as sa_false, func, or_, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.filters import FilterCondition
from app.services.filter_translator import ColumnMap, FilterError, SpecialResolver, translate_filter

from ..models import Broadcast, BroadcastRecipient, Channel, Contact, Status

# The plain-column half of the whitelist (AC-BRD-20).
BROADCAST_FILTER_COLUMNS: ColumnMap = {
    "name": Broadcast.name,
    "scheduledAt": Broadcast.scheduled_at,
    "createdAt": Broadcast.created_at,
}


def build_special(tenant_id: str, status_key_to_id: Dict[str, str]) -> SpecialResolver:
    """`status`/`channel`/`createdBy` all need more than a bare column
    comparison - resolved against THIS tenant, never a raw id/string from the
    client matched blind."""

    def _special(cond: FilterCondition):
        if cond.field == "status":
            if cond.operator not in ("in", "eq"):
                raise FilterError(f"unsupported operator for status: {cond.operator}")
            values = cond.value if isinstance(cond.value, list) else [cond.value]
            ids = [status_key_to_id[v] for v in values if v in status_key_to_id]
            return Broadcast.status_id.in_(ids) if ids else sa_false()

        if cond.field == "channel":
            if cond.operator not in ("contains", "eq", "neq"):
                raise FilterError(f"unsupported operator for channel: {cond.operator}")
            subq = select(Channel.id).where(Channel.tenant_id == tenant_id)
            if cond.operator == "contains":
                subq = subq.where(Channel.name.ilike(f"%{cond.value}%"))
            else:
                subq = subq.where(Channel.name == cond.value)
            clause = Broadcast.channel_id.in_(subq)
            return clause if cond.operator != "neq" else ~clause

        if cond.field == "createdBy":
            if cond.operator not in ("contains", "eq", "neq"):
                raise FilterError(f"unsupported operator for createdBy: {cond.operator}")
            subq = select(User.id).where(User.tenant_id == tenant_id)
            if cond.operator == "contains":
                subq = subq.where(or_(User.name.ilike(f"%{cond.value}%"), User.email.ilike(f"%{cond.value}%")))
            else:
                subq = subq.where(or_(User.name == cond.value, User.email == cond.value))
            clause = Broadcast.created_by_user_id.in_(subq)
            return clause if cond.operator != "neq" else ~clause

        return None

    return _special


def _sort_columns(tenant_id: str) -> Dict[str, Any]:
    """Built per-request (not a module-level constant) so the `channel`/
    `createdBy`/`status` orderings can be tenant-scoped subqueries, matching
    `contact_filters.py`'s `_LIFECYCLE_SORT_ORDER` correlated-subquery
    pattern (sort by the REFERENCED row's own value, never a raw id)."""
    status_order = (
        select(Status.sort_order)
        .where(Status.id == Broadcast.status_id)
        .correlate(Broadcast)
        .scalar_subquery()
    )
    channel_name = (
        select(Channel.name)
        .where(Channel.id == Broadcast.channel_id, Channel.tenant_id == tenant_id)
        .correlate(Broadcast)
        .scalar_subquery()
    )
    created_by_name = (
        select(func.coalesce(User.name, User.email))
        .where(User.id == Broadcast.created_by_user_id, User.tenant_id == tenant_id)
        .correlate(Broadcast)
        .scalar_subquery()
    )
    return {
        "name": Broadcast.name,
        "status": status_order,
        "channel": channel_name,
        "scheduledAt": Broadcast.scheduled_at,
        "createdAt": Broadcast.created_at,
        "createdBy": created_by_name,
    }


class BroadcastRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, broadcast_id: str, tenant_id: str, workspace_id: str) -> Optional[Broadcast]:
        return (
            self.db.query(Broadcast)
            .filter(
                Broadcast.id == broadcast_id,
                Broadcast.tenant_id == tenant_id,
                Broadcast.workspace_id == workspace_id,
            )
            .first()
        )

    def list(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        search: Optional[str] = None,
        filter_group=None,
        status_key_to_id: Optional[Dict[str, str]] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[Broadcast], int]:
        q = self.db.query(Broadcast).filter(
            Broadcast.tenant_id == tenant_id, Broadcast.workspace_id == workspace_id
        )
        if search and search.strip():
            q = q.filter(Broadcast.name.ilike(f"%{search.strip()}%"))
        if filter_group is not None:
            clause = translate_filter(
                filter_group, BROADCAST_FILTER_COLUMNS, build_special(tenant_id, status_key_to_id or {})
            )
            if clause is not None:
                q = q.filter(clause)
        sort_columns = _sort_columns(tenant_id)
        if sort_by is not None and sort_by not in sort_columns:
            raise FilterError(f"field not sortable: {sort_by}")
        total = q.count()
        col = sort_columns[sort_by] if sort_by else Broadcast.created_at
        q = q.order_by(col.desc() if sort_dir == "desc" else col.asc(), Broadcast.id.asc())
        rows = q.offset(page * page_size).limit(page_size).all()
        return rows, total

    def add(self, broadcast: Broadcast) -> None:
        self.db.add(broadcast)

    def delete(self, broadcast: Broadcast) -> None:
        self.db.delete(broadcast)

    def recipients_page(
        self,
        tenant_id: str,
        broadcast_id: str,
        *,
        state: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[Tuple[BroadcastRecipient, Contact]], int]:
        q = (
            self.db.query(BroadcastRecipient, Contact)
            .join(Contact, Contact.id == BroadcastRecipient.contact_id)
            .filter(
                BroadcastRecipient.tenant_id == tenant_id,
                BroadcastRecipient.broadcast_id == broadcast_id,
            )
        )
        if state:
            q = q.filter(BroadcastRecipient.state == state)
        if search and search.strip():
            term = f"%{search.strip()}%"
            full_name = func.coalesce(Contact.first_name, "") + " " + func.coalesce(Contact.last_name, "")
            q = q.filter(or_(full_name.ilike(term), Contact.phone.ilike(term)))
        total = q.count()
        q = q.order_by(BroadcastRecipient.created_at.asc(), BroadcastRecipient.id.asc())
        rows = q.offset(page * page_size).limit(page_size).all()
        return rows, total
