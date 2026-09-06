"""Saved inbox views - typed-filter server-side saved searches (plan 27 A3,
S2 - D-A3-2). NOT a rule-engine tree; `filter_json` is validated through the
typed `InboxViewFilter` (Pydantic `extra="forbid"`) both at the wire boundary
(FastAPI) and again here so a row read back from the DB is re-validated the
same way.

Visibility (AC-IVE-18/19): `list()` returns the caller's OWN views plus every
SHARED view. Any user may create/edit/delete their OWN view with only
`conversations.read` (D-A3-11); creating/editing/deleting a SHARED view - or
someone else's - additionally needs `inbox_views.manage`, enforced by the
ROUTER (it knows the caller's permission set), not here - this service only
resolves/validates/persists.

`expand()` maps a stored filter to `ContactRepository.list_threads` kwargs -
the ONE place a saved view's shape turns into repo filter kwargs, shared by
the thread-list route's `viewId` expansion.
"""
from typing import Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User

from ..models import Channel, ContactTag, InboxView
from ..schemas import InboxViewFilter

MAX_VIEWS_PER_WORKSPACE = 50


class InboxViewNotFound(Exception):
    pass


class InboxViewValidationError(Exception):
    def __init__(self, message: str, field: str = "name"):
        super().__init__(message)
        self.message = message
        self.field = field


class InboxViewService:
    def __init__(self, db: Session):
        self.db = db

    # ── reads ────────────────────────────────────────────────────────────────
    def list(self, workspace_id: str, tenant_id: str, user_id: Optional[str]) -> List[InboxView]:
        q = self.db.query(InboxView).filter(
            InboxView.tenant_id == tenant_id, InboxView.workspace_id == workspace_id
        )
        if user_id:
            q = q.filter(or_(InboxView.owner_user_id == user_id, InboxView.is_shared.is_(True)))
        else:
            q = q.filter(InboxView.is_shared.is_(True))
        return q.order_by(InboxView.sort_order.asc(), func.lower(InboxView.name).asc()).all()

    def owner_names(self, rows: List[InboxView], tenant_id: str) -> Dict[str, str]:
        """Tenant-scoped display-name lookup for a batch of views' owners -
        the ONE place that runs a `User` query for this resource (the router
        stays HTTP/Pydantic only)."""
        ids = {r.owner_user_id for r in rows if r.owner_user_id}
        if not ids:
            return {}
        users = (
            self.db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(ids)).all()
        )
        return {u.id: (u.name or u.email) for u in users}

    def get(self, view_id: str, workspace_id: str, tenant_id: str) -> InboxView:
        row = (
            self.db.query(InboxView)
            .filter(
                InboxView.id == view_id,
                InboxView.workspace_id == workspace_id,
                InboxView.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise InboxViewNotFound()
        return row

    def get_visible(
        self, view_id: str, tenant_id: str, user_id: Optional[str]
    ) -> InboxView:
        """Tenant-scoped lookup for the thread-list `viewId` expansion
        (AC-IVE-17), gated on VISIBILITY only (own or shared) - a private
        view id can never be borrowed by guessing it. The ROUTER separately
        enforces that the view's `workspace_id` matches the caller's
        resolved workspace (review round 1, finding 7 - no cross-workspace
        portability: a viewId from another workspace 404s even if the
        caller sent no explicit `workspaceId` at all)."""
        row = self.db.query(InboxView).filter(
            InboxView.id == view_id, InboxView.tenant_id == tenant_id
        ).first()
        if row is None:
            raise InboxViewNotFound()
        if row.is_shared:
            return row
        if user_id and row.owner_user_id == user_id:
            return row
        raise InboxViewNotFound()

    # ── writes ───────────────────────────────────────────────────────────────
    def _find_by_name(self, workspace_id: str, tenant_id: str, name: str) -> Optional[InboxView]:
        return (
            self.db.query(InboxView)
            .filter(
                InboxView.tenant_id == tenant_id,
                InboxView.workspace_id == workspace_id,
                func.lower(InboxView.name) == name.strip().lower(),
            )
            .first()
        )

    def _validate_filter_ids(
        self, workspace_id: str, tenant_id: str, filt: InboxViewFilter
    ) -> None:
        """Every id embedded in the filter must belong to THIS workspace/
        tenant (the polymorphic stored-id rule, validated at save time) -
        422s otherwise, nothing is written (AC-IVE-18)."""
        # B18 (round-3 codex triage) - `segmentId` is a reserved seam for A2
        # (D-A3-17); the thread-list route already 422s a query-param
        # `segmentId` with this exact message. A saved view must reject it
        # the SAME way at save time (not silently accept + discard it on
        # `expand()`, which would let a view LOOK like it filters by segment
        # while quietly doing nothing).
        if filt.segmentId is not None:
            raise InboxViewValidationError(
                "Contact segments are not available yet.", "filter"
            )
        if filt.lifecycleStageIds:
            from .lifecycle_service import stages_for_workspace

            valid = {s.id for s in stages_for_workspace(self.db, tenant_id, workspace_id)}
            if not set(filt.lifecycleStageIds) <= valid:
                raise InboxViewValidationError(
                    "One or more lifecycle stages do not belong to this workspace.", "filter"
                )
        if filt.tagIds:
            found = {
                r[0]
                for r in self.db.query(ContactTag.id)
                .filter(
                    ContactTag.tenant_id == tenant_id,
                    ContactTag.workspace_id == workspace_id,
                    ContactTag.id.in_(filt.tagIds),
                )
                .all()
            }
            if not set(filt.tagIds) <= found:
                raise InboxViewValidationError(
                    "One or more tags do not belong to this workspace.", "filter"
                )
        if filt.channelIds:
            found = {
                r[0]
                for r in self.db.query(Channel.id)
                .filter(
                    Channel.tenant_id == tenant_id,
                    Channel.workspace_id == workspace_id,
                    Channel.id.in_(filt.channelIds),
                )
                .all()
            }
            if not set(filt.channelIds) <= found:
                raise InboxViewValidationError(
                    "One or more channels do not belong to this workspace.", "filter"
                )
        if filt.assigneeUserIds:
            from app.models.user import User

            found = {
                r[0]
                for r in self.db.query(User.id)
                .filter(User.tenant_id == tenant_id, User.id.in_(filt.assigneeUserIds))
                .all()
            }
            if not set(filt.assigneeUserIds) <= found:
                raise InboxViewValidationError(
                    "One or more assignees do not belong to this tenant.", "filter"
                )

    def create(
        self, workspace_id: str, tenant_id: str, owner_user_id: str, payload
    ) -> InboxView:
        name = (payload.name or "").strip()
        if not name:
            raise InboxViewValidationError("Name is required.")
        if self._find_by_name(workspace_id, tenant_id, name) is not None:
            raise InboxViewValidationError("A view with this name already exists.")
        count = (
            self.db.query(InboxView.id)
            .filter(InboxView.tenant_id == tenant_id, InboxView.workspace_id == workspace_id)
            .count()
        )
        if count >= MAX_VIEWS_PER_WORKSPACE:
            raise InboxViewValidationError(
                f"This workspace already has {MAX_VIEWS_PER_WORKSPACE} saved views (the maximum)."
            )
        filt = payload.filter or InboxViewFilter()
        self._validate_filter_ids(workspace_id, tenant_id, filt)
        row = InboxView(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=name,
            owner_user_id=owner_user_id,
            is_shared=bool(payload.isShared),
            filter_json=filt.model_dump(exclude_none=True),
            sort_order=count,
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            # B17 (round-3 codex triage) - a concurrent create with the same
            # (workspace, name) can land BETWEEN `_find_by_name` and this
            # commit (`uq_inbox_views_workspace_name` then rejects it).
            # Translate to the same typed validation error the pre-check
            # raises (A1 tags precedent), never a 500.
            self.db.rollback()
            raise InboxViewValidationError("A view with this name already exists.")
        self.db.refresh(row)
        return row

    def update(self, view_id: str, workspace_id: str, tenant_id: str, payload) -> InboxView:
        row = self.get(view_id, workspace_id, tenant_id)
        sent = payload.model_fields_set
        if "name" in sent:
            name = (payload.name or "").strip()
            if not name:
                raise InboxViewValidationError("Name is required.")
            existing = self._find_by_name(workspace_id, tenant_id, name)
            if existing is not None and existing.id != row.id:
                raise InboxViewValidationError("A view with this name already exists.")
            row.name = name
        if "isShared" in sent and payload.isShared is not None:
            row.is_shared = payload.isShared
        if "filter" in sent and payload.filter is not None:
            self._validate_filter_ids(workspace_id, tenant_id, payload.filter)
            row.filter_json = payload.filter.model_dump(exclude_none=True)
        if "sortOrder" in sent and payload.sortOrder is not None:
            row.sort_order = payload.sortOrder
        try:
            self.db.commit()
        except IntegrityError:
            # B17 - same race as `create`, for a RENAME landing on a name a
            # concurrent request just took.
            self.db.rollback()
            raise InboxViewValidationError("A view with this name already exists.")
        self.db.refresh(row)
        return row

    def delete(self, view_id: str, workspace_id: str, tenant_id: str) -> None:
        row = self.get(view_id, workspace_id, tenant_id)
        self.db.delete(row)
        self.db.commit()

    # ── expansion (AC-IVE-17) ────────────────────────────────────────────────
    def expand(self, view: InboxView) -> Dict:
        """Map a saved view's stored filter to `ContactRepository.list_
        threads` kwargs. Only keys the filter actually set are returned -
        the caller layers explicit query-param overrides on top.

        B18 - defense-in-depth mirror of the save-time `segmentId` rejection
        above: a row planted/left over from before that guard existed must
        not silently expand into "no filter" (looking like it scopes by
        segment while doing nothing) - raises the same
        `InboxViewValidationError` the router maps to the identical 422."""
        filt = InboxViewFilter(**(view.filter_json or {}))
        if filt.segmentId is not None:
            raise InboxViewValidationError(
                "Contact segments are not available yet.", "filter"
            )
        out: Dict = {}
        if filt.statuses:
            out["status_keys"] = list(filt.statuses)
        if filt.assignee is not None:
            out["assignee"] = filt.assignee
        if filt.assigneeUserIds:
            out["assignee_user_ids"] = list(filt.assigneeUserIds)
        if filt.lifecycleStageIds:
            out["lifecycle_stage_ids"] = list(filt.lifecycleStageIds)
        if filt.tagIds:
            out["tag_ids"] = list(filt.tagIds)
        if filt.channelIds:
            out["channel_ids"] = list(filt.channelIds)
        if filt.priority is not None:
            out["priority"] = None if filt.priority == "ALL" else filt.priority
        if filt.unreplied is not None:
            out["unreplied"] = filt.unreplied
        if filt.sort is not None:
            out["sort"] = filt.sort
        return out
