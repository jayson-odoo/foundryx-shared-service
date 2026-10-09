"""Close reasons - per-workspace reason registry for `POST /contacts/{id}/close`
(plan 27 A3, S2 - D-A3-3). Mirrors `contact_tag_service.py`'s CRUD + case-
insensitive per-workspace uniqueness + cap shape.

Seeding (AC-IVE-27): the four respond.io-parity defaults (`SEEDED_REASONS`)
are materialized for a NEW workspace in the SAME unit of work as its create
(`WorkspaceService.create` / `bootstrap.install_tenant`'s fresh-workspace
branch), and `backfill_tenant` seeds every PRE-EXISTING workspace that has
none (called unconditionally from `update_tenant`/`install_tenant`, same
self-healing shape as `event_service.backfill_tenant`). No code ever looks a
reason up by NAME (DoD rule 3) - only by id, always workspace+tenant scoped.

Delete is blocked (409, D-A3-13) while any `ConversationEvent` still
references the reason - `is_active=false` (Deactivate) is the UI answer,
so history keeps resolving its name forever without a rewrite.
"""
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import CloseReason, ConversationEvent, Workspace

MAX_CLOSE_REASONS_PER_WORKSPACE = 100

SEEDED_REASONS = ("General Inquiry", "Sales Inquiry", "Payment Issue", "Others")


class CloseReasonNotFound(Exception):
    """No such reason in this workspace/tenant - maps to 404."""


class CloseReasonInactive(Exception):
    """The reason exists but `is_active=false` - maps to 422."""


class CloseReasonInUse(Exception):
    """Delete blocked - at least one event still references it - maps to 409."""


class CloseReasonValidationError(Exception):
    def __init__(self, message: str, field: str = "name"):
        super().__init__(message)
        self.message = message
        self.field = field


class CloseReasonService:
    def __init__(self, db: Session):
        self.db = db

    # ── registry CRUD ────────────────────────────────────────────────────────
    def list(self, workspace_id: str, tenant_id: str) -> List[CloseReason]:
        return (
            self.db.query(CloseReason)
            .filter(CloseReason.tenant_id == tenant_id, CloseReason.workspace_id == workspace_id)
            .order_by(CloseReason.sort_order.asc(), func.lower(CloseReason.name).asc())
            .all()
        )

    def get(self, reason_id: str, workspace_id: str, tenant_id: str) -> CloseReason:
        row = (
            self.db.query(CloseReason)
            .filter(
                CloseReason.id == reason_id,
                CloseReason.workspace_id == workspace_id,
                CloseReason.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise CloseReasonNotFound()
        return row

    def get_active(self, reason_id: str, workspace_id: str, tenant_id: str) -> CloseReason:
        """Resolve a reason for use in `close_thread` (AC-IVE-29): missing /
        foreign-workspace / foreign-tenant -> `CloseReasonNotFound` (404);
        inactive -> `CloseReasonInactive` (422). Nothing is written on either."""
        row = self.get(reason_id, workspace_id, tenant_id)
        if not row.is_active:
            raise CloseReasonInactive()
        return row

    def uses_counts(self, workspace_id: str, tenant_id: str) -> Dict[str, int]:
        """Batched `reason_id -> referencing-event count` (AC-IVE-31's Uses
        column + the Delete-vs-Deactivate row-menu gate)."""
        rows = (
            self.db.query(ConversationEvent.close_reason_id, func.count(ConversationEvent.id))
            .join(CloseReason, CloseReason.id == ConversationEvent.close_reason_id)
            .filter(
                CloseReason.workspace_id == workspace_id,
                ConversationEvent.tenant_id == tenant_id,
                ConversationEvent.close_reason_id.isnot(None),
            )
            .group_by(ConversationEvent.close_reason_id)
            .all()
        )
        return {reason_id: count for reason_id, count in rows if reason_id}

    def _find_by_name(
        self, workspace_id: str, tenant_id: str, name: str
    ) -> Optional[CloseReason]:
        return (
            self.db.query(CloseReason)
            .filter(
                CloseReason.tenant_id == tenant_id,
                CloseReason.workspace_id == workspace_id,
                func.lower(CloseReason.name) == name.strip().lower(),
            )
            .first()
        )

    def create(self, workspace_id: str, tenant_id: str, payload) -> CloseReason:
        name = (payload.name or "").strip()
        if not name:
            raise CloseReasonValidationError("Name is required.")
        if self._find_by_name(workspace_id, tenant_id, name) is not None:
            raise CloseReasonValidationError("A close reason with this name already exists.")
        count = (
            self.db.query(CloseReason.id)
            .filter(CloseReason.tenant_id == tenant_id, CloseReason.workspace_id == workspace_id)
            .count()
        )
        if count >= MAX_CLOSE_REASONS_PER_WORKSPACE:
            raise CloseReasonValidationError(
                f"This workspace already has {MAX_CLOSE_REASONS_PER_WORKSPACE} close "
                "reasons (the maximum)."
            )
        row = CloseReason(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=name,
            sort_order=payload.sortOrder if payload.sortOrder is not None else count,
            is_active=payload.isActive if payload.isActive is not None else True,
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            # Concurrent create landed first (Postgres functional unique
            # index backstop) - same recovery as `contact_tag_service`.
            self.db.rollback()
            raise CloseReasonValidationError("A close reason with this name already exists.")
        self.db.refresh(row)
        return row

    def update(self, reason_id: str, workspace_id: str, tenant_id: str, payload) -> CloseReason:
        row = self.get(reason_id, workspace_id, tenant_id)
        sent = payload.model_fields_set
        if "name" in sent:
            name = (payload.name or "").strip()
            if not name:
                raise CloseReasonValidationError("Name is required.")
            existing = self._find_by_name(workspace_id, tenant_id, name)
            if existing is not None and existing.id != row.id:
                raise CloseReasonValidationError("A close reason with this name already exists.")
            row.name = name
        if "sortOrder" in sent and payload.sortOrder is not None:
            row.sort_order = payload.sortOrder
        if "isActive" in sent and payload.isActive is not None:
            row.is_active = payload.isActive
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise CloseReasonValidationError("A close reason with this name already exists.")
        self.db.refresh(row)
        return row

    def delete(self, reason_id: str, workspace_id: str, tenant_id: str) -> None:
        row = self.get(reason_id, workspace_id, tenant_id)
        in_use = (
            self.db.query(ConversationEvent.id)
            .filter(
                ConversationEvent.tenant_id == tenant_id,
                ConversationEvent.close_reason_id == row.id,
            )
            .first()
        )
        if in_use is not None:
            raise CloseReasonInUse()
        self.db.delete(row)
        try:
            self.db.commit()
        except IntegrityError:
            # B14 (round-3 codex triage) - a concurrent close-with-this-reason
            # can land BETWEEN the `in_use` check above and this commit (the
            # FK `fk_conv_events_close_reason` then rejects the delete).
            # Translate to the same typed 409 the pre-commit check raises,
            # never an opaque 500.
            self.db.rollback()
            raise CloseReasonInUse()

    # ── seeding (AC-IVE-27) ──────────────────────────────────────────────────
    def seed_for_workspace(self, workspace_id: str, tenant_id: str) -> None:
        """Materialize the four default reasons for a NEW workspace, same
        unit of work as workspace creation - flushes, caller commits. A no-op
        if the workspace already carries any reason (idempotent, so a caller
        that later becomes self-healing can call this unconditionally)."""
        existing = (
            self.db.query(CloseReason.id)
            .filter(CloseReason.tenant_id == tenant_id, CloseReason.workspace_id == workspace_id)
            .first()
        )
        if existing is not None:
            return
        for i, name in enumerate(SEEDED_REASONS):
            self.db.add(
                CloseReason(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    name=name,
                    sort_order=i,
                    is_active=True,
                )
            )
        self.db.flush()

    def backfill_tenant(self, tenant_id: str) -> int:
        """Seed the default reasons for every workspace of this tenant that
        has none yet (`update_tenant` + self-healing `install_tenant`).
        Idempotent (a workspace that already has any reason is skipped) -
        returns the count of workspaces seeded."""
        seeded = 0
        for ws in self.db.query(Workspace).filter(Workspace.tenant_id == tenant_id).all():
            existing = (
                self.db.query(CloseReason.id)
                .filter(CloseReason.tenant_id == tenant_id, CloseReason.workspace_id == ws.id)
                .first()
            )
            if existing is None:
                self.seed_for_workspace(ws.id, tenant_id)
                seeded += 1
        self.db.flush()
        return seeded
