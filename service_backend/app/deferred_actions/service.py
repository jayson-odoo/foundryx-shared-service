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
    DeferredActionDef,
    DeferredActionWindow,
    UnknownDeferredAction,
    deferred_action_for,
)
from app.models.pending_action import (
    PENDING_ACTION_CANCELLED,
    PENDING_ACTION_COMMITTED,
    PENDING_ACTION_COMMITTING,
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
from app.repositories.user_repository import UserRepository

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


class TargetNotFound(DeferredActionServiceError):
    """Park was asked to act on a record that doesn't exist (or isn't in
    this tenant) - fix round 1 item 7. 404, never silently parked."""


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
        # Fix round 2, B1: only a TERMINAL row (committed/cancelled/failed)
        # is a settled outcome - `committing` is mid-flight (the beat sweep
        # claimed it and the handler may still be running, or may still
        # fail). A `committing` row must never surface here: the frontend
        # treats anything but cancelled/failed as success and would toast +
        # navigate away before the handler even finishes.
        return (
            self.db.query(PendingAction)
            .filter(
                PendingAction.tenant_id == tenant_id,
                PendingAction.entity_type == entity_type,
                PendingAction.entity_id == entity_id,
                PendingAction.status.notin_(
                    [PENDING_ACTION_PENDING, PENDING_ACTION_COMMITTING]
                ),
            )
            .order_by(PendingAction.ended_at.desc().nullslast(), PendingAction.created_at.desc())
            .first()
        )

    def _committing_for(
        self, tenant_id: str, entity_type: str, entity_id: str
    ) -> Optional[PendingAction]:
        """A row another caller (beat sweep, or a racing `current` poll) has
        already CLAIMED but not yet settled - fix round 2, B1."""
        return (
            self.db.query(PendingAction)
            .filter(
                PendingAction.tenant_id == tenant_id,
                PendingAction.entity_type == entity_type,
                PendingAction.entity_id == entity_id,
                PendingAction.status == PENDING_ACTION_COMMITTING,
            )
            .order_by(PendingAction.created_at.desc())
            .first()
        )

    def _commit_if_due(self, row: Optional[PendingAction]) -> Optional[PendingAction]:
        """Apply a parked row whose window has already closed, before answering."""
        if row is None or row.commit_at is None:
            return row
        if row.commit_at > _now():
            return row
        return self.commit_one(row)

    def _module_active(self, tenant_id: str, action_def: DeferredActionDef) -> bool:
        # Fix round 2, S4: mirrors every other catalog's `active_modules`/
        # `is_visible` check (workflow triggers/actions, rule facts, status
        # entities, importer, terminology, ...) - a tenant with the module
        # INACTIVE can't park (or keep observing/committing) a countdown
        # against one of its actions, even if a stale role grant still holds
        # the permission key.
        from app.module_platform.active import active_modules, is_visible

        return is_visible(action_def.module, active_modules(self.db, tenant_id))

    def _may_act_on(self, actor: User, action_key: str, tenant_id: Optional[str] = None) -> bool:
        try:
            action_def = deferred_action_for(action_key)
        except UnknownDeferredAction:
            return False
        if action_def.permission not in effective_permission_keys(actor):
            return False
        if action_def.platform and not (actor.tenant and actor.tenant.is_platform):
            return False
        if tenant_id is not None and not self._module_active(tenant_id, action_def):
            return False
        return True

    def requester_name(self, row: PendingAction) -> Optional[str]:
        """Display name for `row.requested_by_id` - fix round 2, N1: moved
        out of the router (`app/api/v1/pending_actions.py` used to run this
        query itself, which is DB access in a layer that must stay HTTP/
        Pydantic only). Tenant-scoped resolution of a stored user id at USE
        time (the polymorphic-target_id rule) - `row.tenant_id` is the
        acting tenant the park happened under, which is where
        `requested_by_id` lives."""
        if not row.requested_by_id:
            return None
        user = UserRepository(self.db).get_by_id(
            row.requested_by_id, row.tenant_id, include_trashed=True
        )
        return user.name if user else "a teammate"

    def current(self, tenant_id: str, entity_type: str, entity_id: str, actor: User) -> dict:
        # Fix round 2, S5: resolve the row WITHOUT committing it, gate on
        # permission (+ module, fix round 2 S4) FIRST, and only lazy-commit
        # an overdue row once the caller is confirmed allowed to observe it.
        # `_commit_if_due` on line one (the old order) ran the handler for
        # ANY caller who happened to poll an overdue row before the
        # permission check ever ran - a teammate without the permission
        # could trigger the commit just by asking.
        raw_pending = self._pending_for(tenant_id, entity_type, entity_id)
        committing_before = (
            self._committing_for(tenant_id, entity_type, entity_id) if raw_pending is None else None
        )
        last_outcome_before = (
            None
            if committing_before is not None
            else self._last_outcome(tenant_id, entity_type, entity_id)
        )

        # Fix round 1 item 1: `current` is gated by the SAME permission the
        # parked action itself requires (resolved fresh from the actor's
        # roles, exactly like `park`) - a teammate who cannot fire the action
        # cannot observe its countdown either. Uniform empty response (never
        # a distinct error shape) so a caller lacking the permission cannot
        # distinguish "nothing pending" from "pending, but not yours to see".
        relevant_key = (
            raw_pending.action_key
            if raw_pending
            else committing_before.action_key
            if committing_before
            else (last_outcome_before.action_key if last_outcome_before else None)
        )
        if relevant_key is not None and not self._may_act_on(actor, relevant_key, tenant_id):
            raise ActionNotFound("Pending action not found.")

        row = self._commit_if_due(raw_pending)
        pending = row if (row is not None and row.status == PENDING_ACTION_PENDING) else None
        # Fix round 2, B1: a row another caller (beat sweep, or a racing
        # `current` poll from another tab) already claimed is mid-commit -
        # surfaced via the SAME `pending` slot (distinguished by
        # `status='committing'`, the smaller wire change vs a new field) so
        # the client keeps polling instead of reading a bogus settled
        # outcome. Never both `pending` and a committing row at once (the
        # partial unique index only covers `status='pending'`, but a park
        # can't happen while one is already committing on this record).
        committing = self._committing_for(tenant_id, entity_type, entity_id) if pending is None else None
        last_outcome = None if committing is not None else self._last_outcome(tenant_id, entity_type, entity_id)

        return {
            "pending": pending if pending is not None else committing,
            "last_outcome": last_outcome,
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
        if not self._module_active(tenant_id, action_def):
            # Fix round 2, S4: a module action key stays REGISTERED globally
            # (the registry has no tenant concept) - a tenant with the
            # module INACTIVE must not be able to park (or keep observing/
            # committing) a countdown against one of its actions, even
            # holding the stale permission from before deactivation.
            raise PermissionDenied(f"Missing permission: {action_def.permission}")
        if action_def.permission not in effective_permission_keys(actor):
            raise PermissionDenied(f"Missing permission: {action_def.permission}")
        if action_def.platform and not (actor.tenant and actor.tenant.is_platform):
            # Same double lock as `require_platform_permission` - a plain
            # permission-key check alone isn't enough for a platform action.
            raise PermissionDenied(f"Missing permission: {action_def.permission}")
        if not action_def.exists(self.db, tenant_id, entity_id):
            # Fix round 1 item 7: never park a countdown against a record
            # that's already gone (or never existed in this tenant).
            raise TargetNotFound(f"{entity_type} {entity_id!r} not found.")

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

    def cancel(self, tenant_id: str, action_id: str, actor: User) -> PendingAction:
        row = (
            self.db.query(PendingAction)
            .filter(PendingAction.id == action_id, PendingAction.tenant_id == tenant_id)
            .first()
        )
        if row is None:
            raise ActionNotFound("Pending action not found.")
        # Fix round 1 item 1: cancel is gated by the parked action's OWN
        # permission (resolved fresh, same as `park`) - ANY teammate holding
        # it may veto (a second admin can cancel a colleague's park); anyone
        # without it is refused. The id itself is already tenant-scoped
        # above, so this is a plain 403 (not a 404 - there's nothing to
        # enumerate that a 404 would hide beyond what the 200-path already
        # would have revealed by the row's existence).
        if not self._may_act_on(actor, row.action_key, tenant_id):
            raise PermissionDenied(f"Missing permission for {row.action_key!r}.")
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

        Fix round 1 item 4: an atomic claim (`UPDATE ... WHERE id=:id AND
        status='pending'`) precedes the handler call - the beat sweep and the
        frontend's lazy `current` poll can both race to commit the same
        overdue row, and without the claim both would run the handler. A
        rowcount of 0 means another caller already claimed (or settled) it -
        this call is a no-op and returns whatever the row now is.
        """
        db = self.db
        row_id = row.id
        claim = (
            db.query(PendingAction)
            .filter(PendingAction.id == row_id, PendingAction.status == PENDING_ACTION_PENDING)
            .update({PendingAction.status: PENDING_ACTION_COMMITTING}, synchronize_session=False)
        )
        db.commit()
        if claim == 0:
            fresh = db.get(PendingAction, row_id)
            return fresh if fresh is not None else row
        row = db.get(PendingAction, row_id)
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

    # A `committing` row that crashed mid-execute (process killed between the
    # claim and the terminal status write) never resolves itself - the next
    # sweep marks it `failed` once it's sat well past its own window.
    _STUCK_COMMITTING_GRACE = timedelta(seconds=60)

    def _reap_stuck_committing(self) -> None:
        stuck = (
            self.db.query(PendingAction)
            .filter(
                PendingAction.status == PENDING_ACTION_COMMITTING,
                PendingAction.commit_at <= _now() - self._STUCK_COMMITTING_GRACE,
            )
            .all()
        )
        for row in stuck:
            row.status = PENDING_ACTION_FAILED
            row.error_text = "Commit did not complete (worker crashed or was interrupted)."
            row.ended_at = _now()
        if stuck:
            self.db.commit()

    def commit_due(self) -> int:
        """Beat sweep (`pending_actions.commit_due`) - every tenant's overdue
        pending rows, each in its own transaction (AC-DLA-41)."""
        self._reap_stuck_committing()
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
