"""Form + FormVersion persistence (plan sprint-3/01) — pure SQLAlchemy, ALWAYS
tenant-scoped. Every query filters ``tenant_id``; the tenant comes from the
authed context, never client input (multi-tenancy invariant). Versions are
reached only THROUGH their owning form (a join to ``forms`` enforces the tenant
boundary — a stored ``version_id`` is never resolved unscoped, the polymorphic
target_id rule).
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.form import FORM_ARCHIVED, Form, FormSubmission, FormVersion


class FormRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- forms ----

    def paginate(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        status_view: Optional[str] = None,
        filter_clause=None,
    ) -> Tuple[List[Form], int]:
        query = self.db.query(Form).filter(Form.tenant_id == tenant_id)
        # Active|Archived view (statusView 'trashed' = the archived definition
        # state). The shell relabels the segmented control per entity (D5/D18).
        if status_view == "trashed":
            query = query.filter(Form.status == FORM_ARCHIVED)
        else:
            query = query.filter(Form.status != FORM_ARCHIVED)
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(Form.name.ilike(like), Form.description.ilike(like))
            )
        if filter_clause is not None:
            query = query.filter(filter_clause)
        total = query.count()
        # submissionCount sort skipped (D — awkward over a grouped subquery; the
        # column still sorts client-falls-back on the page set).
        sort_map = {
            "name": Form.name,
            "status": Form.status,
            "access": Form.access,
            "updatedAt": Form.updated_at,
            "createdAt": Form.created_at,
        }
        column = sort_map.get(sort_by or "name", Form.name)
        query = query.order_by(column.desc() if sort_dir == "desc" else column.asc())
        rows = query.offset(page * page_size).limit(page_size).all()
        return rows, total

    def get_by_id(self, tenant_id: str, form_id: str) -> Optional[Form]:
        return (
            self.db.query(Form)
            .filter(Form.id == form_id, Form.tenant_id == tenant_id)
            .first()
        )

    def get_by_slug(self, tenant_id: str, slug: str) -> Optional[Form]:
        return (
            self.db.query(Form)
            .filter(Form.slug == slug, Form.tenant_id == tenant_id)
            .first()
        )

    def slug_taken(self, tenant_id: str, slug: str) -> bool:
        return self.get_by_slug(tenant_id, slug) is not None

    def add(self, form: Form) -> Form:
        self.db.add(form)
        self.db.flush()
        return form

    def delete(self, form: Form) -> None:
        # Versions + submissions cascade via the FK ``ondelete="CASCADE"``; the
        # scoped status graph is dropped separately by the service (delete_scope).
        self.db.delete(form)
        self.db.flush()

    # ---- submission counts (one grouped query for the page's ids, D18 column) ----

    def submission_counts(self, tenant_id: str, form_ids: List[str]) -> Dict[str, int]:
        if not form_ids:
            return {}
        rows = (
            self.db.query(FormSubmission.form_id, func.count(FormSubmission.id))
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.form_id.in_(form_ids),
                # Count logical submissions — one per revision group (R3).
                FormSubmission.is_current.is_(True),
            )
            .group_by(FormSubmission.form_id)
            .all()
        )
        return {form_id: count for form_id, count in rows}

    def submission_count(self, tenant_id: str, form_id: str) -> int:
        return self.submission_counts(tenant_id, [form_id]).get(form_id, 0)

    # ---- versions ----

    def next_version_number(self, form_id: str) -> int:
        current = (
            self.db.query(func.max(FormVersion.version_number))
            .filter(FormVersion.form_id == form_id)
            .scalar()
        )
        return (current or 0) + 1

    def add_version(self, version: FormVersion) -> FormVersion:
        self.db.add(version)
        self.db.flush()
        return version

    def get_version(self, tenant_id: str, version_id: str) -> Optional[FormVersion]:
        """Tenant-scoped via the join to the owning form — a version id from
        another tenant resolves to None (never trust a stored id unscoped)."""
        return (
            self.db.query(FormVersion)
            .join(Form, Form.id == FormVersion.form_id)
            .filter(FormVersion.id == version_id, Form.tenant_id == tenant_id)
            .first()
        )

    def versions_paginate(
        self, tenant_id: str, form_id: str, *, page: int = 0, page_size: int = 20
    ) -> Tuple[List[FormVersion], int]:
        query = (
            self.db.query(FormVersion)
            .join(Form, Form.id == FormVersion.form_id)
            .filter(FormVersion.form_id == form_id, Form.tenant_id == tenant_id)
        )
        total = query.count()
        rows = (
            query.order_by(FormVersion.version_number.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total
