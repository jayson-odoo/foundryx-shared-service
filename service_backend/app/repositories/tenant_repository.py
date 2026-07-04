"""Tenant repository — platform-console tenant queries (plan 07 §9).

Pure SQLAlchemy; no business rules. These queries are CROSS-tenant by design —
they exist only behind ``require_platform_permission`` (the platform console).
Every query joins the lifecycle status so list/filter/sort see the category.
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models.status import Status
from app.models.tenant import Tenant
from app.models.user import User

# Sortable list columns (frontend column id -> column).
_SORT_COLUMNS = {
    "tenant": Tenant.name,
    "name": Tenant.name,
    "slug": Tenant.slug,
    "status": Status.category,
    "contact": Tenant.contact_email,
    "contactEmail": Tenant.contact_email,
    "created": Tenant.created_at,
}


class TenantRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, tenant_id: str) -> Optional[Tenant]:
        return self.db.query(Tenant).filter(Tenant.id == tenant_id).first()

    def get_by_slug(self, slug: str) -> Optional[Tenant]:
        return self.db.query(Tenant).filter(Tenant.slug == slug).first()

    def paginate(
        self,
        *,
        page: int = 0,
        page_size: int = 25,
        status_view: str = "active",
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_clause=None,
    ) -> Tuple[List[Tenant], int]:
        q = self.db.query(Tenant).join(Status, Status.id == Tenant.status_id)

        # Status views: 'trashed' = archived tenants, 'active' = the rest.
        # Behavior reads the is_archived TRAIT FLAG (sprint-2/01 D2), never a
        # category enum — custom archived-like statuses hide correctly too.
        if status_view == "trashed":
            q = q.filter(Status.is_archived.is_(True))
        else:
            q = q.filter(Status.is_archived.is_(False))

        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(
                or_(
                    Tenant.name.ilike(term),
                    Tenant.slug.ilike(term),
                    Tenant.contact_name.ilike(term),
                    Tenant.contact_email.ilike(term),
                    Tenant.custom_domain.ilike(term),
                )
            )

        if filter_clause is not None:
            q = q.filter(filter_clause)

        total = q.count()

        column = _SORT_COLUMNS.get(sort_by or "", Tenant.created_at)
        q = q.order_by(column.desc() if sort_dir == "desc" else column.asc())
        q = q.order_by(Tenant.id.asc())  # stable tiebreak

        rows = q.offset(page * page_size).limit(page_size).all()
        return rows, total

    def user_counts(self, tenant_ids: List[str]) -> Dict[str, int]:
        if not tenant_ids:
            return {}
        rows = (
            self.db.query(User.tenant_id, func.count())
            .filter(User.tenant_id.in_(tenant_ids), User.is_trashed.is_(False))
            .group_by(User.tenant_id)
            .all()
        )
        return {tenant_id: count for tenant_id, count in rows}

    # ---- writes ----

    def add(self, tenant: Tenant) -> Tenant:
        self.db.add(tenant)
        self.db.flush()
        return tenant

    def save(self, tenant: Tenant) -> Tenant:
        self.db.add(tenant)
        self.db.commit()
        self.db.refresh(tenant)
        return tenant
