"""Per-team assignment strategies (plan 28 S2, §5.3, D-A8-8/9/10/11).

`pick()` is the ONE algorithm `ConversationService.patch_thread` calls when a
validated `assignedTeamId` needs a member chosen by strategy (no explicit
winning `assignedUserId` in the same PATCH). It:

1. resolves the ELIGIBLE roster (a team member who is ALSO a `WorkspaceMember`
   of the contact's workspace and whose core `User.status == ACTIVE`,
   D-A8-10), sorted by user id ascending for a deterministic order (D-A8-8);
2. locks the (workspace, team) settings row `FOR UPDATE` on Postgres (a
   no-op on the sqlite test path, D-A8-9) so two concurrent picks against the
   same team never read the same cursor;
3. picks per the persisted (or overridden) strategy;
4. advances + persists the cursor in the SAME transaction as the caller's
   assignment (never commits itself - `patch_thread` owns the transaction).

An empty roster is NOT an error (D-A8-11): `pick()` returns `None` and the
caller stores the team with `assigned_user_id = NULL` (Team Unassigned).
"""
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User, UserStatus

from ..models import Contact, TeamAssignmentSetting
from ..models import Status as ThreadStatus
from ..repositories.workspace_repository import WorkspaceRepository
from . import team_directory

DEFAULT_STRATEGY = "round_robin"
STRATEGIES = ("round_robin", "least_open")


def _query_settings(db: Session, tenant_id: str, workspace_id: str, team_id: str, *, lock: bool):
    q = db.query(TeamAssignmentSetting).filter(
        TeamAssignmentSetting.tenant_id == tenant_id,
        TeamAssignmentSetting.workspace_id == workspace_id,
        TeamAssignmentSetting.team_id == team_id,
    )
    if lock and db.bind is not None and db.bind.dialect.name == "postgresql":
        q = q.with_for_update()
    return q.first()


def _get_or_create_settings(
    db: Session, tenant_id: str, workspace_id: str, team_id: str, *, lock: bool = False
) -> TeamAssignmentSetting:
    """Race-safe lock-or-create (mirrors `NumberingRepository.
    get_or_create_counter_for_update`) - `FOR UPDATE` locks nothing when no
    row exists yet, so two concurrent first-assignment callers could both
    try to create; the loser's INSERT trips the unique (workspace_id,
    team_id) constraint and is retried as a re-fetch under lock."""
    row = _query_settings(db, tenant_id, workspace_id, team_id, lock=lock)
    if row is not None:
        return row
    try:
        with db.begin_nested():
            row = TeamAssignmentSetting(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                team_id=team_id,
                strategy=DEFAULT_STRATEGY,
            )
            db.add(row)
            db.flush()
        return row
    except IntegrityError:
        row = _query_settings(db, tenant_id, workspace_id, team_id, lock=lock)
        if row is None:  # pragma: no cover - constraint guarantees a row
            raise
        return row


def list_settings(db: Session, tenant_id: str, workspace_id: str) -> List[TeamAssignmentSetting]:
    """Every configured-or-assigned-to row in this workspace (AC-TEM-28's
    list route) - NOT the team catalog (`GET /teams` is), just the rows that
    exist so far."""
    return (
        db.query(TeamAssignmentSetting)
        .filter(
            TeamAssignmentSetting.tenant_id == tenant_id,
            TeamAssignmentSetting.workspace_id == workspace_id,
        )
        .order_by(TeamAssignmentSetting.team_id.asc())
        .all()
    )


def settings_for(
    db: Session, tenant_id: str, workspace_id: str, team_id: str
) -> TeamAssignmentSetting:
    """Read accessor for the team-settings routes (AC-TEM-28) - default
    `round_robin` when no row exists yet, materializing (+ COMMITTING) one
    lazily on first read so a later PATCH-driven `pick()` has a row to lock.
    Own transaction (the router does no DB logic of its own)."""
    row = _get_or_create_settings(db, tenant_id, workspace_id, team_id)
    db.commit()
    return row


def set_strategy(
    db: Session, tenant_id: str, workspace_id: str, team_id: str, strategy: str
) -> TeamAssignmentSetting:
    """Own transaction (the router does no DB logic of its own)."""
    row = _get_or_create_settings(db, tenant_id, workspace_id, team_id)
    row.strategy = strategy
    db.commit()
    return row


def eligible_members(db: Session, tenant_id: str, workspace_id: str, team_id: str) -> List[str]:
    """AC-TEM-23 / D-A8-10 - team member AND `WorkspaceMember` of THIS
    workspace AND core `User.status == ACTIVE`; sorted by user id ascending
    (D-A8-8's deterministic order)."""
    roster = team_directory.members(db, tenant_id, team_id)
    if not roster:
        return []
    user_ids = [m["userId"] for m in roster]
    ws_repo = WorkspaceRepository(db)
    ws_member_ids = {uid for uid in user_ids if ws_repo.member_exists(workspace_id, uid)}
    if not ws_member_ids:
        return []
    active_ids = {
        row[0]
        for row in db.query(User.id)
        .filter(
            User.tenant_id == tenant_id,
            User.id.in_(ws_member_ids),
            User.status == UserStatus.ACTIVE.value,
        )
        .all()
    }
    return sorted(active_ids)


def _open_counts(db: Session, tenant_id: str, workspace_id: str, user_ids: List[str]) -> dict:
    """AC-TEM-22 - OPEN threads per candidate, THIS workspace, THIS tenant
    only (SNOOZED/CLOSED and other workspaces/tenants excluded)."""
    if not user_ids:
        return {}
    rows = (
        db.query(Contact.assigned_user_id, func.count(Contact.id))
        .join(ThreadStatus, Contact.status_id == ThreadStatus.id)
        .filter(
            Contact.tenant_id == tenant_id,
            Contact.workspace_id == workspace_id,
            ThreadStatus.scope == "THREAD",
            ThreadStatus.key == "OPEN",
            Contact.assigned_user_id.in_(user_ids),
        )
        .group_by(Contact.assigned_user_id)
        .all()
    )
    return dict(rows)


def pick(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    team_id: str,
    strategy: Optional[str] = None,
) -> Optional[str]:
    """Resolve + persist the next assignee for `team_id` in `workspace_id`
    (§5.3). Returns `None` when the roster has no eligible member (D-A8-11 -
    a success, not a failure; the caller stores team + NULL user)."""
    eligible = eligible_members(db, tenant_id, workspace_id, team_id)
    if not eligible:
        return None

    setting = _get_or_create_settings(db, tenant_id, workspace_id, team_id, lock=True)
    effective_strategy = strategy or setting.strategy or DEFAULT_STRATEGY

    if effective_strategy == "least_open":
        counts = _open_counts(db, tenant_id, workspace_id, eligible)
        order_index = {uid: i for i, uid in enumerate(eligible)}
        chosen = min(eligible, key=lambda uid: (counts.get(uid, 0), order_index[uid]))
    else:  # round_robin (default + fallback for an unknown persisted value)
        cursor = setting.last_assigned_user_id
        i = eligible.index(cursor) if cursor in eligible else -1
        chosen = eligible[(i + 1) % len(eligible)]

    # Both strategies advance + persist the cursor (§5.3 "both:") - same
    # transaction as the caller's assignment write, no commit here.
    setting.last_assigned_user_id = chosen
    db.flush()
    return chosen


def assign(
    db: Session,
    contact: Contact,
    team_id: str,
    *,
    strategy_override: Optional[str] = None,
) -> Optional[str]:
    """Contact-shaped convenience over `pick()` - resolves the workspace from
    the contact so callers (the manual PATCH path, and the S3 workflow
    action) never have to thread `workspace_id` through separately. Does NOT
    touch `contact` itself - the caller (`patch_thread`) owns setting
    `assigned_team_id`/`assigned_user_id` so the write stays inside its own
    transaction."""
    return pick(db, contact.tenant_id, contact.workspace_id, team_id, strategy_override)
