"""Template repository - pure SQLAlchemy over the two-tier templates table."""

from typing import List, Optional, Tuple

from sqlalchemy import and_, case, or_, select
from sqlalchemy.orm import Session

from app.models.template import Template


class TemplateRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- visibility (two-tier, D6) ----

    def _visible_clause(self, tenant_id):
        """Tenant rows ∪ platform rows whose key the tenant has NOT forked.

        ``tenant_id is None`` = the PLATFORM TENANT's scope (D13): it sees and
        edits the NULL-tier rows themselves - maintaining the defaults every
        unforked tenant renders.
        """
        if tenant_id is None:
            return Template.tenant_id.is_(None)
        shadowed = (
            select(Template.key)
            .where(Template.tenant_id == tenant_id)
            .scalar_subquery()
        )
        return or_(
            Template.tenant_id == tenant_id,
            and_(Template.tenant_id.is_(None), Template.key.notin_(shadowed)),
        )

    # ---- reads ----

    def get_visible(self, template_id: str, tenant_id: str) -> Optional[Template]:
        return (
            self.db.query(Template)
            .filter(Template.id == template_id, self._visible_clause(tenant_id))
            .first()
        )

    def get_tenant_row(self, key: str, tenant_id: str) -> Optional[Template]:
        return (
            self.db.query(Template)
            .filter(Template.key == key, Template.tenant_id == tenant_id)
            .first()
        )

    def get_platform_row(self, key: str) -> Optional[Template]:
        return (
            self.db.query(Template)
            .filter(Template.key == key, Template.tenant_id.is_(None))
            .first()
        )

    def resolve_by_key(self, key: str, tenant_id) -> Optional[Template]:
        """Tenant fork wins; platform default otherwise (D6 read resolution)."""
        if tenant_id is None:
            return self.get_platform_row(key)
        return self.get_tenant_row(key, tenant_id) or self.get_platform_row(key)

    def paginate(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_clause=None,
    ) -> Tuple[List[Template], int]:
        query = self.db.query(Template).filter(self._visible_clause(tenant_id))
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    Template.name.ilike(like),
                    Template.key.ilike(like),
                    Template.subject.ilike(like),
                )
            )
        if filter_clause is not None:
            query = query.filter(filter_clause)

        total = query.count()

        sort_map = {
            "name": Template.name,
            "key": Template.key,
            "subject": Template.subject,
            "contextLabel": Template.context,
            "createdAt": Template.created_at,
            "updatedAt": Template.updated_at,
            # Tier sorts platform-default rows vs tenant forks.
            "tier": case((Template.tenant_id.is_(None), 0), else_=1),
        }
        column = sort_map.get(sort_by or "name", Template.name)
        query = query.order_by(column.desc() if sort_dir == "desc" else column.asc())

        rows = query.offset(page * page_size).limit(page_size).all()
        return rows, total

    # ---- writes (service owns commits) ----

    def add(self, template: Template) -> Template:
        self.db.add(template)
        return template

    def delete(self, template: Template) -> None:
        self.db.delete(template)
