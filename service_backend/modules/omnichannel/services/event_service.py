"""Conversation events (plan 27 A3, S1) - the append-only audit trail over
thread mutations. `record()` is the ONE seam every writer goes through
(inbound auto-reopen/opened, the gateway contact-create, `patch_thread`'s
status/assign branches, `lifecycle_service.move`, `MessageService._mark_agent_
message`, `add_internal_note`) - it only `db.add()`s + `db.flush()`s, NEVER
commits, so the event always rides the SAME unit of work as the mutation that
caused it (AC-IVE-02): the caller's own commit persists both, and a rollback
drops both.

`to_items()` renders rows for the read route (`GET /{id}/events`), resolving
every stored id (`actorUserId`, `actorExternalAgentId`, `fromValue`/`toValue`)
TENANT-SCOPED - the polymorphic stored-id house rule (AC-IVE-10): an
unresolvable/foreign id renders as an empty label, never another tenant's name.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.status import Status as CoreStatus
from app.models.user import User

from ..models import CloseReason, Contact, ConversationEvent, ConversationMessage
from ..models import Status as ThreadStatus
from ..schemas import ConversationEventItem

# The full event-type vocabulary (plan §Definitions) - kept here as the single
# reference list; nothing in this module branches on membership except tests.
EVENT_TYPES = (
    "opened",
    "closed",
    "reopened",
    "snoozed",
    "unsnoozed",
    "assigned",
    "unassigned",
    "first_agent_reply",
    "lifecycle_changed",
    "comment_added",
)

# The three event types that mark "an open cycle boundary" for the
# first-agent-reply-once-per-cycle rule (AC-IVE-07).
_CYCLE_MARKERS = ("opened", "reopened", "first_agent_reply")


def record(
    db: Session,
    contact: Contact,
    event_type: str,
    *,
    actor: Optional[User] = None,
    actor_id: Optional[str] = None,
    external_agent_id: Optional[str] = None,
    from_value: Optional[str] = None,
    to_value: Optional[str] = None,
    close_reason_id: Optional[str] = None,
    note: Optional[str] = None,
    payload: Optional[dict] = None,
    created_at: Optional[datetime] = None,
) -> ConversationEvent:
    """Write one event row for `contact`. Adds to `db` and flushes (so the row
    has an id + is visible to later queries in the SAME transaction) but never
    commits - the caller's own unit of work owns the transaction.

    `actor`/`actor_id` both resolve to a stored `actor_user_id` - validated
    tenant-scoped BEFORE saving (AC-IVE-10): an id that does not belong to
    `contact.tenant_id` is dropped (stored as NULL) rather than trusted, so a
    forged/foreign id can never plant a cross-tenant name behind this row.

    `created_at` (plan 33 S4, AC-MIG-42) - an explicit override for a
    BACKFILLED event, which must carry the SOURCE timestamp, never `now()`.
    Every live caller omits it and keeps getting the current instant; the
    migration writer is the one caller that passes it."""
    resolved_actor_id: Optional[str] = None
    if actor is not None:
        resolved_actor_id = str(actor.id)
    elif actor_id is not None:
        resolved_actor_id = str(actor_id)
    if resolved_actor_id is not None:
        valid = (
            db.query(User.id)
            .filter(User.id == resolved_actor_id, User.tenant_id == contact.tenant_id)
            .first()
        )
        if valid is None:
            resolved_actor_id = None

    row = ConversationEvent(
        tenant_id=contact.tenant_id,
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        event_type=event_type,
        actor_user_id=resolved_actor_id,
        actor_external_agent_id=external_agent_id,
        from_value=from_value,
        to_value=to_value,
        close_reason_id=close_reason_id,
        note=note,
        payload_json=payload,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def is_first_reply_pending(db: Session, contact: Contact) -> bool:
    """AC-IVE-07: pending iff the latest of (opened, reopened, first_agent_
    reply) for this contact is NOT already `first_agent_reply` - including the
    case where the contact has none of those three yet (no cycle marker at
    all → the very first agent reply is always "pending")."""
    latest = (
        db.query(ConversationEvent)
        .filter(
            ConversationEvent.tenant_id == contact.tenant_id,
            ConversationEvent.contact_id == contact.id,
            ConversationEvent.event_type.in_(_CYCLE_MARKERS),
        )
        .order_by(ConversationEvent.created_at.desc(), ConversationEvent.id.desc())
        .first()
    )
    if latest is None:
        return True
    return latest.event_type != "first_agent_reply"


def list_for_contact(
    db: Session,
    contact_id: str,
    tenant_id: str,
    *,
    page: int = 0,
    page_size: int = 50,
) -> Tuple[List[ConversationEvent], int]:
    """Newest-first, paginated (AC-IVE-13)."""
    q = db.query(ConversationEvent).filter(
        ConversationEvent.tenant_id == tenant_id,
        ConversationEvent.contact_id == contact_id,
    )
    total = q.count()
    rows = (
        q.order_by(ConversationEvent.created_at.desc(), ConversationEvent.id.desc())
        .offset(page * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def _label_map(db: Session, tenant_id: str, events: List[ConversationEvent]) -> Dict[str, str]:
    """One batched, tenant-scoped id → label resolution covering every kind of
    value a `from_value`/`to_value` can hold: a THREAD status id, a core
    lifecycle status id, a native user id, or an external-agent id. ids are
    UUIDs (collision-free across these concepts), so a single merged map is
    safe and far simpler than branching per `event_type`.

    B16 (round-3 codex triage) - the lifecycle branch additionally constrains
    by `entity_type` + `scope_id` (workspace), mirroring `ConversationService.
    _lifecycle_map`'s own precedent/comment: the lifecycle status machine is
    SCOPED per workspace, so a status id that happens to belong to another
    workspace of the SAME tenant (or a different scoped entity entirely) must
    not resolve and render its label here (the polymorphic stored-id rule -
    never resolve a stored id by bare tenant+id alone). All `events` passed in
    are for ONE contact (`list_for_contact`'s caller), hence one workspace."""
    from .lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY_TYPE

    ids = set()
    for e in events:
        if e.from_value:
            ids.add(e.from_value)
        if e.to_value:
            ids.add(e.to_value)
    if not ids:
        return {}
    workspace_ids = {e.workspace_id for e in events if e.workspace_id}

    labels: Dict[str, str] = {}
    for s in (
        db.query(ThreadStatus)
        .filter(ThreadStatus.tenant_id == tenant_id, ThreadStatus.id.in_(ids))
        .all()
    ):
        labels[s.id] = s.label
    remaining = ids - set(labels)

    if remaining and workspace_ids:
        for s in (
            db.query(CoreStatus)
            .filter(
                CoreStatus.tenant_id == tenant_id,
                CoreStatus.entity_type == LIFECYCLE_ENTITY_TYPE,
                CoreStatus.scope_id.in_(workspace_ids),
                CoreStatus.id.in_(remaining),
            )
            .all()
        ):
            labels[s.id] = s.label
        remaining = ids - set(labels)

    if remaining:
        for u in (
            db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(remaining)).all()
        ):
            labels[u.id] = u.name or u.email
        remaining = ids - set(labels)

    if remaining:
        from .external_agent_service import ExternalAgentService

        agents = ExternalAgentService(db).names(list(remaining), tenant_id)
        for agent_id, agent in agents.items():
            labels[agent_id] = agent.name

    return labels


def to_items(
    db: Session, events: List[ConversationEvent], tenant_id: str
) -> List[ConversationEventItem]:
    """Map rows → the wire shape, resolving actor + from/to labels tenant-
    scoped in ONE batched pass (AC-IVE-10, AC-IVE-13). `closeReasonName`
    resolves the same way - a `close_reason_id` of another tenant/workspace
    (should never happen, defense-in-depth) renders empty, never a foreign
    reason's name (plan 27 A3, S2)."""
    actor_user_ids = {e.actor_user_id for e in events if e.actor_user_id}
    actor_names: Dict[str, str] = {}
    if actor_user_ids:
        for u in (
            db.query(User)
            .filter(User.tenant_id == tenant_id, User.id.in_(actor_user_ids))
            .all()
        ):
            actor_names[u.id] = u.name or u.email

    external_ids = {e.actor_external_agent_id for e in events if e.actor_external_agent_id}
    agent_names: Dict[str, str] = {}
    if external_ids:
        from .external_agent_service import ExternalAgentService

        for agent_id, agent in ExternalAgentService(db).names(list(external_ids), tenant_id).items():
            agent_names[agent_id] = agent.name

    value_labels = _label_map(db, tenant_id, events)

    # B16 - close reasons are per-workspace (never a two-tier NULL-tenant
    # row like statuses); scope by workspace too, not bare tenant+id, for the
    # same reason as the lifecycle branch above.
    workspace_ids = {e.workspace_id for e in events if e.workspace_id}
    reason_ids = {e.close_reason_id for e in events if e.close_reason_id}
    reason_names: Dict[str, str] = {}
    if reason_ids and workspace_ids:
        for r in (
            db.query(CloseReason)
            .filter(
                CloseReason.tenant_id == tenant_id,
                CloseReason.workspace_id.in_(workspace_ids),
                CloseReason.id.in_(reason_ids),
            )
            .all()
        ):
            reason_names[r.id] = r.name

    items: List[ConversationEventItem] = []
    for e in events:
        if e.actor_external_agent_id:
            actor_name = agent_names.get(e.actor_external_agent_id)
        elif e.actor_user_id:
            actor_name = actor_names.get(e.actor_user_id)
        else:
            actor_name = None
        items.append(
            ConversationEventItem(
                id=e.id,
                eventType=e.event_type,
                actorName=actor_name,
                actorUserId=e.actor_user_id,
                fromValue=e.from_value,
                fromLabel=value_labels.get(e.from_value) if e.from_value else None,
                toValue=e.to_value,
                toLabel=value_labels.get(e.to_value) if e.to_value else None,
                closeReasonId=e.close_reason_id,
                closeReasonName=reason_names.get(e.close_reason_id) if e.close_reason_id else None,
                note=e.note,
                payload=e.payload_json,
                createdAt=e.created_at,
            )
        )
    return items


def backfill_tenant(db: Session, tenant_id: str) -> Dict[str, int]:
    """`install_tenant` (self-healing) + `update_tenant` backfill (AC-IVE-12):
    every contact of this tenant that has NO events yet gets `opened` (at its
    `created_at`), plus `closed`/`assigned` (at its `updated_at`) when its
    CURRENT state already carries that fact - each carrying
    `payload_json.backfilled = true`. Also fills `last_agent_message_at`
    (AC-IVE-11) from each contact's own AGENT-message history. Idempotent: a
    contact that already has an event, or already carries a non-null
    `last_agent_message_at`, is left untouched - safe to call on every
    install/update, including a tenant already fully backfilled.

    Mirrors the Alembic migration's set-based SQL twin (§5.4) - this Python
    function is what pytest actually exercises (module Alembic is a
    Postgres-only no-op under the test suite); the migration is verified
    separately on live Postgres.

    Review round 1 (finding 4): batched to TWO queries over the whole
    contact set (which contacts already have an event; the latest AGENT
    message per contact missing `last_agent_message_at`) instead of one of
    each per contact - a tenant with thousands of contacts was doing
    thousands of round trips.
    """
    contacts = db.query(Contact).filter(Contact.tenant_id == tenant_id).all()
    if not contacts:
        return {"contactsBackfilled": 0, "eventsWritten": 0}

    contact_ids = [c.id for c in contacts]

    status_keys = {
        s.id: s.key
        for s in db.query(ThreadStatus)
        .filter(ThreadStatus.tenant_id == tenant_id, ThreadStatus.scope == "THREAD")
        .all()
    }

    # Batch 1: which contacts already have at least one event.
    has_event_ids = {
        r[0]
        for r in db.query(ConversationEvent.contact_id)
        .filter(
            ConversationEvent.tenant_id == tenant_id,
            ConversationEvent.contact_id.in_(contact_ids),
        )
        .distinct()
        .all()
    }

    # Batch 2: latest AGENT message per contact, only for contacts that still
    # need `last_agent_message_at` filled.
    needs_last_agent_ids = [c.id for c in contacts if c.last_agent_message_at is None]
    latest_agent_at: Dict[str, datetime] = {}
    if needs_last_agent_ids:
        latest_agent_at = {
            r[0]: r[1]
            for r in db.query(
                ConversationMessage.contact_id, func.max(ConversationMessage.created_at)
            )
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.contact_id.in_(needs_last_agent_ids),
                ConversationMessage.sender_type == "AGENT",
            )
            .group_by(ConversationMessage.contact_id)
            .all()
        }

    events_written = 0
    contacts_touched = 0
    for c in contacts:
        if c.id not in has_event_ids:
            db.add(
                ConversationEvent(
                    tenant_id=tenant_id,
                    workspace_id=c.workspace_id,
                    contact_id=c.id,
                    event_type="opened",
                    to_value=c.status_id,
                    payload_json={"backfilled": True},
                    created_at=c.created_at,
                )
            )
            events_written += 1
            if status_keys.get(c.status_id) == "CLOSED":
                db.add(
                    ConversationEvent(
                        tenant_id=tenant_id,
                        workspace_id=c.workspace_id,
                        contact_id=c.id,
                        event_type="closed",
                        to_value=c.status_id,
                        payload_json={"backfilled": True},
                        created_at=c.updated_at,
                    )
                )
                events_written += 1
            assignee = c.assigned_user_id or c.assigned_external_agent_id
            if assignee:
                kind = "user" if c.assigned_user_id else "external_agent"
                db.add(
                    ConversationEvent(
                        tenant_id=tenant_id,
                        workspace_id=c.workspace_id,
                        contact_id=c.id,
                        event_type="assigned",
                        to_value=assignee,
                        payload_json={"backfilled": True, "assigneeKind": kind},
                        created_at=c.updated_at,
                    )
                )
                events_written += 1
            contacts_touched += 1

        if c.last_agent_message_at is None:
            at = latest_agent_at.get(c.id)
            if at is not None:
                c.last_agent_message_at = at

    db.flush()
    return {"contactsBackfilled": contacts_touched, "eventsWritten": events_written}
