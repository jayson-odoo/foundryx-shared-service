"""Requester status-update event feed (issue #94, plan section 7).

Two producers write ``idea_status_events`` rows, one reader (the CRM's
workspace-key feed, ``routers/intake_reads.py``) consumes them:

1. ``on_domain_event`` - the ideation module's subscriber on the CORE CRUD
   event bus (``app.workflow_engine.entity_events.register_event_subscriber``,
   wired from ``bootstrap.register_engine_entities``). Every idea move already
   emits ``entity.status_changed`` inside ``status_machine.transition`` - this
   catches all 7 transition call sites (and any future one) with no per-call-
   site code. Runs on a FRESH post-commit session the bus owns; a raise here
   is caught and rolled back by the bus itself (``_notify_subscribers``), so a
   failing write here can never break the triggering request (AC-94-69).

2. ``record_merge_events`` / ``record_unmerge_events`` - called by
   ``IdeaMergeService`` (``services/merge.py``) from INSIDE its own merge/
   unmerge transaction (S3 seam), because a merge/unmerge is not itself a
   ``status_changed`` event on the child (its ``status_id`` never moves).

Recipients are always resolved to a Contact TENANT SCOPED off the idea's own
``tenant_id`` (never an unscoped lookup on a stored id - the polymorphic
stored-id rule, AC-94-70). A recipient with no contact / no phone never gets
a row. ``track_url`` mints the recipient's own idea_number/status_token first
(idempotent, same as the intake sink does) so a requester's link always
resolves, even on an idea that never went through the conversational sink.

3. ``list_feed_events`` - the CRM's workspace-key read (``GET /ideation/
   intake/status-events``, ``routers/intake_reads.py``). ONE query, no per-row
   fan-out (the row's own ``payload_json`` is already the wire shape).
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.status import Status
from app.models.user import User
from modules.omnichannel.models import Contact

from ..models import Idea, IdeaStatusEvent
from .numbering import mint_idea_identity
from .sinks import mint_idea_link
from .statuses import IDEA_ENTITY

# The feed withholds rows younger than this (AC-94-68) - a lower ``seq`` that
# commits late (a slow subscriber/transaction) must never be skipped past by
# a cursor that already moved beyond it.
SETTLE_WINDOW_SECONDS = 5
DEFAULT_FEED_LIMIT = 100
MAX_FEED_LIMIT = 200

KIND_STATUS_CHANGED = "status_changed"
KIND_MERGED = "merged"
KIND_UNMERGED = "unmerged"


def _iso_z(dt: datetime) -> str:
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return aware.isoformat().replace("+00:00", "Z")


def _idea_title(idea: Idea) -> str:
    return (idea.title or idea.problem or "").strip()


def _resolve_requester_contact(db: Session, tenant_id: str, idea: Idea) -> Optional[Contact]:
    """Tenant-scoped resolution of the idea's stored ``submitter_contact_id``
    (AC-94-70) - never resolved unscoped, even defensively when the stored id
    points at another tenant's row."""
    if not idea.submitter_contact_id:
        return None
    return (
        db.query(Contact)
        .filter(Contact.id == idea.submitter_contact_id, Contact.tenant_id == tenant_id)
        .first()
    )


def _merged_into_dict(idea: Idea) -> Optional[Dict[str, Optional[str]]]:
    if idea is None:
        return None
    return {"idea_number": idea.idea_number, "title": _idea_title(idea)}


def _write_event(
    db: Session,
    *,
    tenant_id: str,
    kind: str,
    recipient: Idea,
    requester_phone: str,
    status_label: str,
    from_status_label: Optional[str] = None,
    merged_into: Optional[Dict[str, Optional[str]]] = None,
    separated_from: Optional[Dict[str, Optional[str]]] = None,
) -> None:
    """Mint the recipient's identity (idempotent), insert the row, then fill
    ``payload_json`` (needs the DB-assigned ``seq``, so a flush comes first).
    ``requester_phone`` is passed in by the caller (already resolved tenant
    scoped) so this never re-queries the Contact table."""
    mint_idea_identity(db, recipient)
    track_url = mint_idea_link(db, recipient)

    row = IdeaStatusEvent(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        idea_id=recipient.id,
        kind=kind,
        is_test=bool(recipient.is_test),
    )
    db.add(row)
    db.flush()  # assigns row.seq (autoincrement PK) + row.created_at (server_default)

    row.payload_json = {
        "event_id": row.id,
        "seq": row.seq,
        "kind": kind,
        "occurred_at": _iso_z(row.created_at),
        "idea_id": recipient.id,
        "idea_number": recipient.idea_number,
        "idea_title": _idea_title(recipient),
        "product_id": recipient.product_id,
        "status_label": status_label,
        "from_status_label": from_status_label,
        "track_url": track_url,
        "requester_phone": requester_phone,
        "merged_into": merged_into,
        "separated_from": separated_from,
        "is_test": bool(recipient.is_test),
    }
    db.flush()


# ── 1. the CRUD event-bus subscriber (status_changed) ───────────────────────


def _fan_out_recipients(db: Session, tenant_id: str, moved_idea: Idea) -> List[Tuple[Idea, str]]:
    """The moved idea plus, when it is a survivor, each merged child (plan
    7.1) - deduped by phone, the SURVIVOR's own row winning a collision
    (moved idea is candidate 0, so it is always seen first)."""
    candidates: List[Idea] = [moved_idea]
    candidates.extend(
        db.query(Idea)
        .filter(Idea.tenant_id == tenant_id, Idea.merged_into_id == moved_idea.id)
        .all()
    )
    seen_phones = set()
    recipients: List[Tuple[Idea, str]] = []
    for candidate in candidates:
        contact = _resolve_requester_contact(db, tenant_id, candidate)
        phone = contact.phone if contact else None
        if not phone or phone in seen_phones:
            continue
        seen_phones.add(phone)
        recipients.append((candidate, phone))
    return recipients


def on_domain_event(db: Session, ev: Dict[str, Any]) -> None:
    """Bus subscriber (registered via ``register_event_subscriber``). Only
    ``idea``/``status_changed`` events are relevant; every other entity/action
    is a silent no-op (AC-94-61)."""
    if ev.get("entity_type") != IDEA_ENTITY or ev.get("action") != "status_changed":
        return

    tenant_id = ev.get("tenant_id")
    idea_id = ev.get("record_id")
    extra = ev.get("extra") or {}
    from_status_id = extra.get("from_status_id")
    to_status_label = extra.get("to_status_label")
    if not tenant_id or not idea_id or not from_status_id:
        return

    from_status = db.query(Status).filter(Status.id == from_status_id).first()
    if from_status is None or from_status.is_initial:
        # Draft -> captured / rejected / duplicate: the live chat already
        # replied (owner Q3, AC-94-62).
        return

    idea = db.query(Idea).filter(Idea.id == idea_id, Idea.tenant_id == tenant_id).first()
    if idea is None:
        return

    recipients = _fan_out_recipients(db, tenant_id, idea)
    if not recipients:
        return  # no requester anywhere in this fan-out (AC-94-62)

    for recipient, phone in recipients:
        _write_event(
            db,
            tenant_id=tenant_id,
            kind=KIND_STATUS_CHANGED,
            recipient=recipient,
            requester_phone=phone,
            status_label=to_status_label or "",
            from_status_label=from_status.label,
            merged_into=_merged_into_dict(idea) if recipient.id != idea.id else None,
        )


def bus_subscriber(db: Session, ev: Dict[str, Any]) -> None:
    """The function actually handed to ``register_event_subscriber``
    (``bootstrap.register_engine_entities``) - a thin, STABLE-identity proxy
    over ``on_domain_event``. Registration is idempotent by function-object
    identity, so the registered callable's identity must never change; going
    through a module-global name lookup here (rather than registering
    ``on_domain_event`` directly) also means a test can monkeypatch
    ``status_events.on_domain_event`` and have the bus pick it up (a
    directly-registered function reference would already be frozen in the
    bus's subscriber list by the time a test patches the module attribute)."""
    on_domain_event(db, ev)


# ── 2. merge / unmerge (called inside IdeaMergeService's own transaction) ───


def record_merge_events(
    db: Session,
    *,
    tenant_id: str,
    survivor: Idea,
    members: List[Idea],
    actor: Optional[User] = None,
) -> None:
    """Write one ``kind="merged"`` row per member that resolves to a
    requester (AC-94-64); no row for the survivor itself."""
    survivor_status = db.query(Status).filter(Status.id == survivor.status_id).first()
    status_label = survivor_status.label if survivor_status else ""
    for member in members:
        contact = _resolve_requester_contact(db, tenant_id, member)
        if contact is None or not contact.phone:
            continue
        _write_event(
            db,
            tenant_id=tenant_id,
            kind=KIND_MERGED,
            recipient=member,
            requester_phone=contact.phone,
            status_label=status_label,
            merged_into=_merged_into_dict(survivor),
        )


def record_unmerge_events(
    db: Session,
    *,
    tenant_id: str,
    restored: List[Idea],
    former_survivor_ids: Dict[str, str],
    actor: Optional[User] = None,
) -> None:
    """Write one ``kind="unmerged"`` row per restored child that resolves to
    a requester (AC-94-64), ``separated_from`` = the FORMER survivor (never
    the restored idea's own new/blank pointer - the caller must capture
    ``former_survivor_ids`` BEFORE clearing ``merged_into_id``). Deduped by
    phone within this one unmerge call (plan 7.1); no event for the former
    survivor."""
    seen_phones = set()
    for child in restored:
        contact = _resolve_requester_contact(db, tenant_id, child)
        if contact is None or not contact.phone:
            continue
        if contact.phone in seen_phones:
            continue
        seen_phones.add(contact.phone)

        former_survivor_id = former_survivor_ids.get(child.id)
        former_survivor = (
            db.query(Idea)
            .filter(Idea.id == former_survivor_id, Idea.tenant_id == tenant_id)
            .first()
            if former_survivor_id
            else None
        )
        status = db.query(Status).filter(Status.id == child.status_id).first()
        _write_event(
            db,
            tenant_id=tenant_id,
            kind=KIND_UNMERGED,
            recipient=child,
            requester_phone=contact.phone,
            status_label=status.label if status else "",
            separated_from=_merged_into_dict(former_survivor),
        )


# ── 3. the feed (CRM workspace-key read) ─────────────────────────────────────


def list_feed_events(
    db: Session,
    tenant_id: str,
    *,
    after: int = 0,
    limit: int = DEFAULT_FEED_LIMIT,
    include_test: bool = False,
) -> Dict[str, Any]:
    """``GET /ideation/intake/status-events`` (AC-94-66): tenant T's rows with
    ``seq > after``, ascending, at most ``limit`` (clamped to
    ``MAX_FEED_LIMIT``). Withholds anything younger than the settle window
    (AC-94-68) and, by default, ``is_test`` rows (AC-94-67). ONE query - the
    row's own ``payload_json`` (built at write time) is already the exact
    wire shape, so there is no per-row fan-out here."""
    limit = max(1, min(limit, MAX_FEED_LIMIT))
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=SETTLE_WINDOW_SECONDS)

    query = db.query(IdeaStatusEvent).filter(
        IdeaStatusEvent.tenant_id == tenant_id,
        IdeaStatusEvent.seq > after,
        IdeaStatusEvent.created_at <= cutoff,
    )
    if not include_test:
        query = query.filter(IdeaStatusEvent.is_test.is_(False))
    rows = query.order_by(IdeaStatusEvent.seq.asc()).limit(limit).all()

    events = [row.payload_json for row in rows]
    next_after = rows[-1].seq if rows else after
    return {"events": events, "next_after": next_after}
