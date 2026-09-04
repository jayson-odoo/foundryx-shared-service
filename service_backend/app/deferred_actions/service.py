"""Deferred-actions service - park / cancel / current / commit (AC-DLA-39..41).

No confirmation dialogs (D2): a destructive or reversible record action is
PARKED for its grace window (10s destructive / 5s reversible, tenant
configurable) and applied by the registered handler when the window lapses -
either the beat sweep (`commit_due`) or the frontend's lazy `GET current`
poll (`current`), whichever gets there first. Every read/write here is
tenant-scoped from the caller (never client input).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies import effective_permission_keys
from app.deferred_actions.registry import (
    DeferredActionWindow,
    UnknownDeferredAction,
    deferred_action_for,
)
from app.models.pending_action import (
    PENDING_ACTION_CANCELLED,
    PENDING_ACTION_COMMITTED,
    PENDING_ACTION_FAILED,
    PENDING_ACTION_PENDING,
    PendingAction,
)
from app.models.tenant_settings import (
    DEFAULT_DEFERRED_DESTRUCTIVE_SECONDS,
    DEFAULT_DEFERRED_REVERSIBLE_SECONDS,
    TenantSettings,
)
from app.models.user import User

logger = logging.getLogger("foundryx.deferred_actions")


class DeferredActionServiceError(Exception):
    """Base for deferred-action service errors."""


class UnknownActionKey(DeferredActionServiceError):
    """The `actionKey` isn't registered, or doesn't apply to `entityType`."""


class PermissionDenied(DeferredActionServiceError):
    """The actor doesn't hold the action's permission."""


class ConflictingPendingAction(DeferredActionServiceError):
    """A DIFFERENT action is already pending on this record."""


class ActionNotFound(DeferredActionServiceError):
    """Unknown id, or belongs to another tenant (uniform 404)."""


class AlreadySettled(DeferredActionServiceError):
    """Cancel arrived at/after `commit_at` - the row already committed."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PendingActionService:
    def __init__(self, db: Session):
        self.db = db

    # ---- window resolution -------------------------------------------------

    def _window_seconds(self, tenant_id: str, window: DeferredActionWindow) -> int:
        row = self.db.get(TenantSettings, tenant_id)
        if window == "destructive":
            value = row.deferred_destructive_seconds if row else None
            return value if value is not None else DEFAULT_DEFERRED_DESTRUCTIVE_SECONDS
        value = row.deferred_reversible_seconds if row else None
        return value if value is not None else DEFAULT_DEFERRED_REVERSIBLE_SECONDS

    # ---- reads ---------------------------------------------------------------

    def _pending_for(
        self, tenant_id: str, entity_type: str, entity_id: str
    ) -> Optional[PendingAction]:
        return (
            self.db.query(PendingAction)
            .filter(
                PendingAction.tenant_id == tenant_id,
                PendingAction.entity_type == entity_type,
                PendingAction.entity_id == entity_id,
                PendingAction.status == PENDING_ACTION_PENDING,
            )
            .first()
        )

    def _last_outcome(
        self, tenant_id: str, entity_type: str, entity_id: str
    ) -> Optional[PendingAction]:
        return (
            self.db.query(PendingAction)
            .filter(
                PendingAction.tenant_id == tenant_id,
                PendingAction.entity_type == entity_type,
                PendingAction.entity_id == entity_id,
                PendingAction.status != PENDING_ACTION_PENDING,
            )
            .order_by(PendingAction.ended_at.desc().nullslast(), PendingAction.created_at.desc())
            .first()
        )

    def _commit_if_due(self, row: Optional[PendingAction]) -> Optional[PendingAction]:
        """Apply a parked row whose window has already closed, before answering."""
        if row is None or row.commit_at is None:
            return row
        if row.commit_at > _now():
            return row
        return self.commit_one(row)

    def current(self, tenant_id: str, entity_type: str, entity_id: str) -> dict:
        row = self._commit_if_due(self._pending_for(tenant_id, entity_type, entity_id))
        pending = row if (row is not None and row.status == PENDING_ACTION_PENDING) else None
        return {
            "pending": pending,
            "last_outcome": self._last_outcome(tenant_id, entity_type, entity_id),
        }

    # ---- park / cancel ---------------------------------------------------

    def park(
        self,
        *,
        tenant_id: str,
        actor: User,
        requested_by_id: str,
        action_key: str,
        entity_type: str,
        entity_id: str,
        payload: Optional[dict] = None,
    ) -> PendingAction:
        """Park an action. `actor` is the EFFECTIVE user (permission check -
        matches `require_permission`'s own semantics under impersonation);
        `requested_by_id` is the REAL actor (`get_actor_user_id` - impersonation
        never attributes a parked action to the target)."""
        try:
            action_def = deferred_action_for(action_key)
        except UnknownDeferredAction as exc:
            raise UnknownActionKey(str(exc)) from exc
        if action_def.entity_type != entity_type:
            raise UnknownActionKey(
                f"Action {action_key!r} does not apply to entity type {entity_type!r}."
            )
        if action_def.permission not in effective_permission_keys(actor):
            raise PermissionDenied(f"Missing permission: {action_def.permission}")
        if action_def.platform and not (actor.tenant and actor.tenant.is_platform):
            # Same double lock as `require_platform_permission` - a plain
            # permission-key check alone isn't enough for a platform action.
            raise PermissionDenied(f"Missing permission: {action_def.permission}")

        existing = self._commit_if_due(self._pending_for(tenant_id, entity_type, entity_id))
        if existing is not None and existing.status == PENDING_ACTION_PENDING:
            if existing.action_key == action_key:
                # A double click parks one action, not two (AC-DLA-39 idempotent re-park).
                return existing
            raise ConflictingPendingAction(
                "Another action on this record is still counting down."
            )

        window_seconds = self._window_seconds(tenant_id, action_def.window)
        row = PendingAction(
            tenant_id=tenant_id,
            action_key=action_key,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_json=payload or None,
            status=PENDING_ACTION_PENDING,
            commit_at=_now() + timedelta(seconds=window_seconds),
            window_seconds=window_seconds,
            requested_by_id=str(requested_by_id),
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            # Lost the race against a concurrent park on the same record - the
            # partial unique index caught it; answer with whatever won.
            self.db.rollback()
            winner = self._pending_for(tenant_id, entity_type, entity_id)
            if winner is not None and winner.action_key == action_key:
                return winner
            raise ConflictingPendingAction(
                "Another action on this record is still counting down."
            )
        self.db.refresh(row)
        return row

    def cancel(self, tenant_id: str, action_id: str) -> PendingAction:
        row = (
            self.db.query(PendingAction)
            .filter(PendingAction.id == action_id, PendingAction.tenant_id == tenant_id)
            .first()
        )
        if row is None:
            raise ActionNotFound("Pending action not found.")
        if row.status != PENDING_ACTION_PENDING:
            raise AlreadySettled("This action already settled.")
        if row.commit_at <= _now():
            # A cancel that arrives after the window closed must lose to the
            # commit, not race it (AC-DLA-40).
            self.commit_one(row)
            raise AlreadySettled("The window already closed; the action was applied.")
        row.status = PENDING_ACTION_CANCELLED
        row.ended_at = _now()
        self.db.commit()
        self.db.refresh(row)
        return row

    # ---- commit ------------------------------------------------------------

    def commit_one(self, row: PendingAction) -> PendingAction:
        """Apply ONE pending row via its registered handler.

        Own transaction (AC-DLA-41): a handler failure rolls back whatever it
        left dirty and the row is re-marked `failed` in a FRESH commit, so a
        bad handler never poisons the session for the next row in a sweep and
        the entity itself is left untouched.
        """
        db = self.db
        row_id = row.id
        try:
            action_def = deferred_action_for(row.action_key)
        except UnknownDeferredAction as exc:
            row.status = PENDING_ACTION_FAILED
            row.error_text = str(exc)
            row.ended_at = _now()
            db.commit()
            db.refresh(row)
            return row

        try:
            action_def.execute(
                db,
                row.tenant_id,
                row.entity_id,
                row.payload_json or {},
                row.requested_by_id or "",
            )
        except Exception as exc:  # noqa: BLE001 - never propagate a handler failure
            logger.exception("Deferred action %s failed to commit", row_id)
            db.rollback()
            fresh = db.get(PendingAction, row_id)
            if fresh is None:
                return row
            fresh.status = PENDING_ACTION_FAILED
            fresh.error_text = str(exc)[:2000]
            fresh.ended_at = _now()
            db.commit()
            db.refresh(fresh)
            return fresh

        fresh = db.get(PendingAction, row_id)
        if fresh is None:
            return row
        fresh.status = PENDING_ACTION_COMMITTED
        fresh.error_text = None
        fresh.ended_at = _now()
        db.commit()
        db.refresh(fresh)
        return fresh

    def commit_due(self) -> int:
        """Beat sweep (`pending_actions.commit_due`) - every tenant's overdue
        pending rows, each in its own transaction (AC-DLA-41)."""
        rows = (
            self.db.query(PendingAction)
            .filter(
                PendingAction.status == PENDING_ACTION_PENDING,
                PendingAction.commit_at <= _now(),
            )
            .all()
        )
        for row in rows:
            self.commit_one(row)
        return len(rows)
