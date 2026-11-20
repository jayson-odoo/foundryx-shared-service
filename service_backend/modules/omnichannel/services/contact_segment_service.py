"""Contact segments (plan 26 S1, D-A2-3) - saved, named `FilterGroup` trees per
workspace. CRUD + case-insensitive per-workspace uniqueness + cap (100) +
save-time `validate_filter_tree` (the SAME whitelisted column map the list
query applies) - mirrors `ContactTagService`'s shape (rename/create/update all
go through the same DB-backstop-on-IntegrityError pattern, since two
concurrent requests could both pass the app-level uniqueness check)."""
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.schemas.filters import FilterGroup
from app.services.filter_translator import FilterError

from ..models import ContactSegment
from .contact_filters import validate_filter_tree

MAX_SEGMENTS_PER_WORKSPACE = 100


class SegmentNotFound(Exception):
    pass


class SegmentValidationError(Exception):
    """Carries a `{field: message}` map - the router turns this into a 422
    `{fieldErrors}` body."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Contact segment validation failed")
        self.errors = errors


class ContactSegmentService:
    def __init__(self, db: Session):
        self.db = db

    # ── reads ────────────────────────────────────────────────────────────────
    def list(self, workspace_id: str, tenant_id: str) -> List[ContactSegment]:
        return (
            self.db.query(ContactSegment)
            .filter(ContactSegment.tenant_id == tenant_id, ContactSegment.workspace_id == workspace_id)
            .order_by(func.lower(ContactSegment.name).asc())
            .all()
        )

    def get(self, segment_id: str, workspace_id: str, tenant_id: str) -> ContactSegment:
        row = (
            self.db.query(ContactSegment)
            .filter(
                ContactSegment.id == segment_id,
                ContactSegment.workspace_id == workspace_id,
                ContactSegment.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise SegmentNotFound()
        return row

    def tree_for(self, segment_id: str, workspace_id: str, tenant_id: str) -> Optional[FilterGroup]:
        """The stored tree for a segment (A3/A4 consume this directly, per the
        plan's `tree_for` seam) - raises `SegmentNotFound` like `get`."""
        row = self.get(segment_id, workspace_id, tenant_id)
        return FilterGroup.model_validate(row.filter_json) if row.filter_json else None

    def _find_by_name(self, workspace_id: str, tenant_id: str, name: str) -> Optional[ContactSegment]:
        return (
            self.db.query(ContactSegment)
            .filter(
                ContactSegment.tenant_id == tenant_id,
                ContactSegment.workspace_id == workspace_id,
                func.lower(ContactSegment.name) == name.strip().lower(),
            )
            .first()
        )

    def _validate_tree(
        self, workspace_id: str, tenant_id: str, tree: Optional[FilterGroup], errors: Dict[str, str]
    ) -> None:
        if tree is None:
            return
        try:
            validate_filter_tree(self.db, tenant_id, workspace_id, tree)
        except FilterError as exc:
            errors["filter"] = str(exc)

    # ── writes ───────────────────────────────────────────────────────────────
    def create(self, workspace_id: str, tenant_id: str, payload, *, actor_user_id: Optional[str]) -> ContactSegment:
        errors: Dict[str, str] = {}
        name = (payload.name or "").strip()
        if not name:
            errors["name"] = "Name is required."
        elif self._find_by_name(workspace_id, tenant_id, name) is not None:
            errors["name"] = "A segment with this name already exists."

        self._validate_tree(workspace_id, tenant_id, payload.filter, errors)
        if errors:
            raise SegmentValidationError(errors)

        count = (
            self.db.query(ContactSegment.id)
            .filter(ContactSegment.tenant_id == tenant_id, ContactSegment.workspace_id == workspace_id)
            .count()
        )
        if count >= MAX_SEGMENTS_PER_WORKSPACE:
            raise SegmentValidationError(
                {"name": f"This workspace already has {MAX_SEGMENTS_PER_WORKSPACE} segments (the maximum)."}
            )

        row = ContactSegment(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=name,
            description=(payload.description or None),
            filter_json=payload.filter.model_dump() if payload.filter else None,
            created_by_user_id=actor_user_id,
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            # The app-level uniqueness check above passed, then a concurrent
            # request's row landed first - the DB backstop
            # (`uq_contact_segments_workspace_name`) raises here. Surface the
            # SAME 422 a same-request duplicate gets, never an unhandled 500.
            self.db.rollback()
            raise SegmentValidationError({"name": "A segment with this name already exists."})
        self.db.refresh(row)
        return row

    def update(self, segment_id: str, workspace_id: str, tenant_id: str, payload) -> ContactSegment:
        row = self.get(segment_id, workspace_id, tenant_id)
        sent = payload.model_fields_set
        errors: Dict[str, str] = {}

        if "name" in sent:
            name = (payload.name or "").strip()
            if not name:
                errors["name"] = "Name is required."
            else:
                existing = self._find_by_name(workspace_id, tenant_id, name)
                if existing is not None and existing.id != row.id:
                    errors["name"] = "A segment with this name already exists."

        if "filter" in sent:
            self._validate_tree(workspace_id, tenant_id, payload.filter, errors)

        if errors:
            raise SegmentValidationError(errors)

        if "name" in sent:
            row.name = payload.name.strip()
        if "description" in sent:
            row.description = payload.description or None
        if "filter" in sent:
            row.filter_json = payload.filter.model_dump() if payload.filter else None

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise SegmentValidationError({"name": "A segment with this name already exists."})
        self.db.refresh(row)
        return row

    def delete(self, segment_id: str, workspace_id: str, tenant_id: str) -> None:
        row = self.get(segment_id, workspace_id, tenant_id)
        self.db.delete(row)
        self.db.commit()
