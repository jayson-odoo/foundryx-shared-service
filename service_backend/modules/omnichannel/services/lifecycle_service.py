"""Contact lifecycle (plan 25 S2) - the `omnichannel_contact_lifecycle` SCOPED
status entity, one graph per workspace (`scope_id = workspace_id`).

Registers into the CORE status engine (`app.status_engine.registry`) exactly
like the platform's first scoped adopter (`form_submission`) - no engine code
is forked, no `module == "omnichannel"` special case anywhere in `app/`. The
seed graph (AC-CDM-13/14, plan §5.3) is materialized once per workspace, at
workspace creation AND at `install_tenant`; `update_tenant` backfills any
workspace that predates this slice (AC-CDM-15). Moves + fireable-edge listing
delegate to the ONE `status_machine` executor (AC-CDM-17/18) - this module
never re-implements edge/role/notification logic.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.status import Status
from app.models.status_transition import StatusTransition
from app.models.user import User
from app.services import status_machine
from app.status_engine.registry import StatusEntity, register_status_entity
from app.status_engine.scoped import (
    ScopeSeedEdge,
    ScopeSeedStatus,
    get_scope_status,
    initial_scope_status,
    materialize_scope,
    scope_status_ids,
)

from ..models import Contact, Workspace

ENTITY_TYPE = "omnichannel_contact_lifecycle"
MODULE_NAME = "omnichannel"


class LifecycleStageNotFound(Exception):
    """`toStatusId` does not exist, or belongs to another workspace/tenant
    (AC-CDM-17: this is a uniform 404, distinct from `TransitionNotAllowed`
    - the machine's "no edge" 409 - which is only reachable once the target
    is confirmed to belong to this contact's own workspace graph)."""

# ── Seed graph (plan §5.3, locked - keys are a code contract, never a display
# label match) ────────────────────────────────────────────────────────────────
_NEW_LEAD = "new_lead"
_HOT_LEAD = "hot_lead"
_PAYMENT = "payment"
_CUSTOMER = "customer"
_COLD_LEAD = "cold_lead"

_LABELS = {
    _NEW_LEAD: "🆕 New Lead",
    _HOT_LEAD: "🔥 Hot Lead",
    _PAYMENT: "💵 Payment",
    _CUSTOMER: "🤩 Customer",
    _COLD_LEAD: "🧊 Cold Lead",
}

# The three "active" stages a contact cycles through before winning/losing.
_ACTIVE_KEYS = (_NEW_LEAD, _HOT_LEAD, _PAYMENT)

SEED_STATUSES: List[ScopeSeedStatus] = [
    ScopeSeedStatus(
        key=_NEW_LEAD, label=_LABELS[_NEW_LEAD], color="blue", sort_order=0,
        flags={"is_initial": True, "is_default": True},
    ),
    ScopeSeedStatus(key=_HOT_LEAD, label=_LABELS[_HOT_LEAD], color="orange", sort_order=1),
    ScopeSeedStatus(key=_PAYMENT, label=_LABELS[_PAYMENT], color="amber", sort_order=2),
    ScopeSeedStatus(
        key=_CUSTOMER, label=_LABELS[_CUSTOMER], color="green", sort_order=3,
        flags={"is_terminal": True},
    ),
    ScopeSeedStatus(
        key=_COLD_LEAD, label=_LABELS[_COLD_LEAD], color="slate", sort_order=4,
        flags={"is_archived": True},
    ),
]


def _seed_edges() -> List[ScopeSeedEdge]:
    """Mesh among the active stages; each active stage -> Customer (won) and
    -> Cold Lead (lost); Cold Lead -> New Lead (re-engagement). Labels are
    "Move to <stage>" (plan §5.3); `trigger_mode` stays the default "manual"."""
    edges: List[ScopeSeedEdge] = []
    order = 0
    for a in _ACTIVE_KEYS:
        for b in _ACTIVE_KEYS:
            if a == b:
                continue
            edges.append(
                ScopeSeedEdge(from_key=a, to_key=b, label=f"Move to {_LABELS[b]}", sort_order=order)
            )
            order += 1
    for a in _ACTIVE_KEYS:
        edges.append(
            ScopeSeedEdge(
                from_key=a, to_key=_CUSTOMER, label=f"Move to {_LABELS[_CUSTOMER]}", sort_order=order
            )
        )
        order += 1
    for a in _ACTIVE_KEYS:
        edges.append(
            ScopeSeedEdge(
                from_key=a, to_key=_COLD_LEAD, label=f"Move to {_LABELS[_COLD_LEAD]}", sort_order=order
            )
        )
        order += 1
    edges.append(
        ScopeSeedEdge(
            from_key=_COLD_LEAD, to_key=_NEW_LEAD, label=f"Move to {_LABELS[_NEW_LEAD]}",
            sort_order=order,
        )
    )
    return edges


# ── status-entity registration (AC-CDM-13) ──────────────────────────────────


def _workspace_exists(db: Session, tenant_id: str, scope_id: str) -> bool:
    """`scope_exists` - the polymorphic guard class: a canvas write must never
    target a workspace outside the caller's tenant."""
    return (
        db.query(Workspace.id)
        .filter(Workspace.id == scope_id, Workspace.tenant_id == tenant_id)
        .first()
        is not None
    )


def _count_records(db: Session, status_id: str, tenant_id: Optional[str]) -> int:
    q = db.query(Contact).filter(Contact.lifecycle_status_id == status_id)
    if tenant_id is not None:
        q = q.filter(Contact.tenant_id == tenant_id)
    return q.count()


def _migrate_records(
    db: Session, from_status_id: str, to_status_id: str, tenant_id: Optional[str]
) -> int:
    q = db.query(Contact).filter(Contact.lifecycle_status_id == from_status_id)
    if tenant_id is not None:
        q = q.filter(Contact.tenant_id == tenant_id)
    count = q.update({Contact.lifecycle_status_id: to_status_id}, synchronize_session=False)
    db.flush()
    return count


def register_lifecycle_entity() -> None:
    """Idempotent (module boot re-registers on every bootstrap, like the rest
    of `register_engine_entities`)."""
    register_status_entity(
        StatusEntity(
            entity_type=ENTITY_TYPE,
            label="Contact Lifecycle",
            module=MODULE_NAME,
            count_records=_count_records,
            migrate_records=_migrate_records,
            status_attr="lifecycle_status_id",
            record_label_attr="phone",
            scoped=True,
            scope_attr="workspace_id",
            scope_label="Workspace",
            scope_exists=_workspace_exists,
            required_flags=["is_initial", "is_terminal", "is_archived"],
            # This entity_type names the per-workspace MACHINE, not the record
            # it moves - `entity.status_changed` triggers are authored against
            # the Contact record (`omnichannel_contact`, registered in S1).
            workflow_entity_type="omnichannel_contact",
        )
    )


# ── materialization (AC-CDM-14/15) ──────────────────────────────────────────


def materialize_for_workspace(db: Session, workspace: Workspace) -> bool:
    """Seed the graph for `workspace` if it doesn't already have one. Flushes,
    does NOT commit - rides the caller's unit of work (workspace creation /
    `install_tenant` / the `update_tenant` backfill). Returns True when a
    graph was created (False = already existed, idempotent no-op)."""
    if scope_status_ids(db, ENTITY_TYPE, workspace.tenant_id, workspace.id):
        return False
    materialize_scope(
        db, ENTITY_TYPE, workspace.tenant_id, workspace.id, SEED_STATUSES, _seed_edges()
    )
    return True


def initial_status_id(db: Session, tenant_id: str, workspace_id: str) -> Optional[str]:
    """The workspace's `is_initial` stage id, or None when the workspace has
    no graph yet (should not happen post-backfill; callers must tolerate it -
    AC-CDM-16 leaves `lifecycle_status_id` NULL rather than crash creation)."""
    row = initial_scope_status(db, ENTITY_TYPE, tenant_id, workspace_id)
    return row.id if row else None


def backfill_tenant(db: Session, tenant_id: str) -> None:
    """`update_tenant` 0.1.0 -> 0.2.0 backfill (AC-CDM-15, D13): materialize
    every workspace missing a graph, then set every contact whose
    `lifecycle_status_id IS NULL` to its own workspace's initial stage.
    Idempotent - a graph that already exists is skipped (`materialize_for_
    workspace`), and a contact already carrying a stage is left untouched."""
    workspaces = db.query(Workspace).filter(Workspace.tenant_id == tenant_id).all()
    for ws in workspaces:
        materialize_for_workspace(db, ws)
    for ws in workspaces:
        initial_id = initial_status_id(db, tenant_id, ws.id)
        if initial_id is None:
            continue
        db.query(Contact).filter(
            Contact.tenant_id == tenant_id,
            Contact.workspace_id == ws.id,
            Contact.lifecycle_status_id.is_(None),
        ).update({Contact.lifecycle_status_id: initial_id}, synchronize_session=False)
    db.flush()


# ── stages + moves (AC-CDM-17/18/19) ────────────────────────────────────────


def stages_for_workspace(db: Session, tenant_id: str, workspace_id: str) -> List[Status]:
    return (
        db.query(Status)
        .filter(
            Status.entity_type == ENTITY_TYPE,
            Status.tenant_id == tenant_id,
            Status.scope_id == workspace_id,
        )
        .order_by(Status.sort_order.asc())
        .all()
    )


def find_stage_by_key_or_label(
    db: Session, tenant_id: str, workspace_id: str, value: str
) -> Optional[Status]:
    """Resolve the gateway PATCH `lifecycle: <key or label>` value to a stage
    of THIS workspace's own graph (AC-CDM-26). `key` match is exact (keys are
    a locked lowercase system contract, D6-style); `label` match is
    case-insensitive exact (labels carry free display text + the emoji, D3).
    Returns None when nothing matches in this workspace - the caller renders a
    422 `fieldErrors.lifecycle`, never a 404 (the value came from the request
    body, not a path segment, and a foreign-workspace label must not leak
    which stages exist elsewhere)."""
    value = (value or "").strip()
    if not value:
        return None
    rows = stages_for_workspace(db, tenant_id, workspace_id)
    for s in rows:
        if s.key == value:
            return s
    lowered = value.lower()
    for s in rows:
        if s.label.strip().lower() == lowered:
            return s
    return None


def move(
    db: Session, contact: Contact, to_status_id: str, actor: Optional[User] = None
) -> StatusTransition:
    """Move `contact` along a defined edge - delegates entirely to the shared
    executor (edge graph, role auth, notifications, the generic
    `entity.status_changed` emission). `commit=False`: the caller's own unit of
    work owns the transaction (matches every other lifecycle write in this
    module).

    Raises `LifecycleStageNotFound` (-> 404) when `to_status_id` isn't a stage
    of THIS contact's own workspace graph, BEFORE the machine ever runs - so a
    genuinely missing edge (-> 409, `status_machine.TransitionNotAllowed`)
    stays distinguishable from a bad/foreign target id (AC-CDM-17)."""
    if get_scope_status(db, ENTITY_TYPE, contact.tenant_id, contact.workspace_id, to_status_id) is None:
        raise LifecycleStageNotFound()
    return status_machine.transition(
        db, ENTITY_TYPE, contact, to_status_id, actor=actor,
        tenant_id=contact.tenant_id, commit=False,
    )


def fireable_moves(
    db: Session, contact: Contact, actor: Optional[User] = None
) -> List[StatusTransition]:
    """Outgoing edges the contact may fire right now (AC-CDM-18) - empty on a
    won (`is_terminal`) stage, since a terminal status has no outgoing edges
    in the seed graph."""
    return status_machine.available_transitions(
        db, ENTITY_TYPE, contact, actor=actor, tenant_id=contact.tenant_id
    )
