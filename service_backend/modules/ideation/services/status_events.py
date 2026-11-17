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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.status import Status
from app.models.user import User
from modules.omnichannel.models import Contact

from ..models import Idea, IdeaStatusEvent
from .numbering import mint_idea_identity
from .crm_poke import queue_crm_poke
from .feedback_links import SUBMITTER, mint_board_link
from .followers import followers_of
from .ownership import phone_digits
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

# Who a feed row is for (lane FEEDBACK-SUBSCRIBE R7): the CRM sends the same
# update to both and may word it per role.
ROLE_REQUESTER = "requester"
ROLE_FOLLOWER = "follower"


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
    recipient_role: str = ROLE_REQUESTER,
    board_contact_id: object = SUBMITTER,
) -> None:
    """Mint the recipient's identity (idempotent), insert the row, then fill
    ``payload_json`` (needs the DB-assigned ``seq``, so a flush comes first).
    ``requester_phone`` is passed in by the caller (already resolved tenant
    scoped) so this never re-queries the Contact table.

    Review round 2 #B - ONE clock, the database's: ``created_at`` is set to a
    SQL function (``clock_timestamp()`` on Postgres - the real wall clock at
    INSERT time, unlike ``now()`` which is fixed for the whole transaction;
    ``now()`` on SQLite, which has no ``clock_timestamp()``), never a Python
    ``datetime.now()`` value - the app process's clock never enters the
    settle-window comparison on either side. ``db.refresh`` pulls the
    DB-computed value back so ``occurred_at`` reflects it exactly."""
    mint_idea_identity(db, recipient)
    track_url = mint_idea_link(db, recipient)
    # Lane PUBLIC-IDEAS-BOARD: the requester's personal feedback board link,
    # opening this idea (``None`` when the idea has no same-tenant contact).
    # ``track_url`` stays the per-idea status page, unchanged.
    # A follower's row carries THEIR OWN board link (lane FEEDBACK-SUBSCRIBE).
    board_url = mint_board_link(db, recipient, board_contact_id)

    row = IdeaStatusEvent(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        idea_id=recipient.id,
        kind=kind,
        is_test=bool(recipient.is_test),
        created_at=func.clock_timestamp() if _is_postgres(db) else func.now(),
    )
    db.add(row)
    db.flush()  # assigns row.seq (autoincrement PK)
    db.refresh(row, ["created_at"])  # pulls back the DB-computed value

    row.payload_json = {
        "event_id": row.id,
        "seq": row.seq,
        "kind": kind,
        "occurred_at": _iso_z(row.created_at),
        "idea_id": recipient.id,
        "idea_number": recipient.idea_number,
        "idea_title": _idea_title(recipient),
        "idea_type": recipient.type or "idea",
        "product_id": recipient.product_id,
        "status_label": status_label,
        "from_status_label": from_status_label,
        "track_url": track_url,
        "board_url": board_url,
        "requester_phone": requester_phone,
        "merged_into": merged_into,
        "separated_from": separated_from,
        "is_test": bool(recipient.is_test),
        # Lane FEEDBACK-SUBSCRIBE: ``requester_phone`` is the send target for
        # both roles (field name kept for the CRM contract).
        "recipient_role": recipient_role,
    }
    db.flush()
    # Owner ruling 15 Nov (CRM #2433, c): poke the tenant's CRM right after
    # this commit so the dealer's WhatsApp update goes out now (fire and
    # forget; the CRM's 15-minute safety check covers a miss). Test ideas never.
    if not recipient.is_test:
        queue_crm_poke(db, tenant_id, row.id, row.seq)


# ── 1. the CRUD event-bus subscriber (status_changed) ───────────────────────


class _Recipient:
    """One feed row to write: who gets it and for which idea row."""

    __slots__ = ("idea", "phone", "role", "contact_id")

    def __init__(self, idea: Idea, phone: str, role: str, contact_id: object):
        self.idea = idea
        self.phone = phone
        self.role = role
        self.contact_id = contact_id


def _recipients(
    db: Session, tenant_id: str, candidates: List[Idea], seen: Optional[set] = None
) -> List[_Recipient]:
    """Requesters of ``candidates`` first (in order), then their followers
    (lane FEEDBACK-SUBSCRIBE R7/R10), deduped by normalized phone so one person
    gets one message per change (R8). ``seen`` carries the dedupe set across
    calls when the caller wants it."""
    seen = seen if seen is not None else set()
    out: List[_Recipient] = []
    for candidate in candidates:
        contact = _resolve_requester_contact(db, tenant_id, candidate)
        phone = contact.phone if contact else None
        key = phone_digits(phone) or phone
        if not phone or key in seen:
            continue
        seen.add(key)
        out.append(_Recipient(candidate, phone, ROLE_REQUESTER, SUBMITTER))
    if any(not c.is_test for c in candidates):
        for idea, contact in followers_of(db, tenant_id, [c for c in candidates if not c.is_test]):
            key = phone_digits(contact.phone) or contact.phone
            if not contact.phone or key in seen:
                continue
            seen.add(key)
            out.append(_Recipient(idea, contact.phone, ROLE_FOLLOWER, contact.id))
    return out


def _fan_out_recipients(db: Session, tenant_id: str, moved_idea: Idea) -> List[_Recipient]:
    """The moved idea plus, when it is a survivor, each merged child (plan
    7.1) - their requesters and then their followers, deduped by phone, the
    SURVIVOR's own requester winning a collision (moved idea is candidate 0,
    so it is always seen first)."""
    candidates: List[Idea] = [moved_idea]
    candidates.extend(
        db.query(Idea)
        .filter(Idea.tenant_id == tenant_id, Idea.merged_into_id == moved_idea.id)
        .all()
    )
    return _recipients(db, tenant_id, candidates)


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

    for r in recipients:
        _write_event(
            db,
            tenant_id=tenant_id,
            kind=KIND_STATUS_CHANGED,
            recipient=r.idea,
            requester_phone=r.phone,
            status_label=to_status_label or "",
            from_status_label=from_status.label,
            merged_into=_merged_into_dict(idea) if r.idea.id != idea.id else None,
            recipient_role=r.role,
            board_contact_id=r.contact_id,
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
        # The member's requester, then its followers (lane FEEDBACK-SUBSCRIBE).
        for r in _recipients(db, tenant_id, [member]):
            _write_event(
                db,
                tenant_id=tenant_id,
                kind=KIND_MERGED,
                recipient=member,
                requester_phone=r.phone,
                status_label=status_label,
                merged_into=_merged_into_dict(survivor),
                recipient_role=r.role,
                board_contact_id=r.contact_id,
            )


def record_flatten_events(
    db: Session,
    *,
    tenant_id: str,
    survivor: Idea,
    children: List[Idea],
) -> None:
    """Review round 1 NIT #10 - a grandchild re-pointed straight onto a NEW
    survivor during flatten (``IdeaMergeService.merge``, D2) gets its OWN
    ``kind="merged"`` row: its requester was already told (at ITS OWN
    original merge) that it was combined into the OLD (intermediate)
    survivor, and now needs telling it tracks the NEW one instead. No row
    for the intermediate member itself - it is never a requester recipient,
    only a now-frozen pointer hop."""
    survivor_status = db.query(Status).filter(Status.id == survivor.status_id).first()
    status_label = survivor_status.label if survivor_status else ""
    for child in children:
        for r in _recipients(db, tenant_id, [child]):
            _write_event(
                db,
                tenant_id=tenant_id,
                kind=KIND_MERGED,
                recipient=child,
                requester_phone=r.phone,
                status_label=status_label,
                merged_into=_merged_into_dict(survivor),
                recipient_role=r.role,
                board_contact_id=r.contact_id,
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
    seen_phones: set = set()
    for child in restored:
        recipients = _recipients(db, tenant_id, [child], seen_phones)
        if not recipients:
            continue

        former_survivor_id = former_survivor_ids.get(child.id)
        former_survivor = (
            db.query(Idea)
            .filter(Idea.id == former_survivor_id, Idea.tenant_id == tenant_id)
            .first()
            if former_survivor_id
            else None
        )
        status = db.query(Status).filter(Status.id == child.status_id).first()
        for r in recipients:
            _write_event(
                db,
                tenant_id=tenant_id,
                kind=KIND_UNMERGED,
                recipient=child,
                requester_phone=r.phone,
                status_label=status.label if status else "",
                separated_from=_merged_into_dict(former_survivor),
                recipient_role=r.role,
                board_contact_id=r.contact_id,
            )


# ── 3. the feed (CRM workspace-key read) ─────────────────────────────────────


def _is_postgres(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind is not None and bind.dialect.name == "postgresql")


def _settle_window_cutoff_expr(db: Session):
    """Review round 1 #6 - the settle-window cutoff computed ENTIRELY IN SQL
    from the DATABASE's own clock, never the app process's (`datetime.now()`
    in Python is vulnerable to app/DB clock skew, which could silently widen
    or shrink the window). Postgres: ``clock_timestamp()`` (the real wall
    clock, unlike ``now()`` which is fixed for the whole transaction) minus
    the window. SQLite (tests): ``datetime('now', ...)`` is also the
    engine's own clock, never the app's."""
    if _is_postgres(db):
        return text(f"clock_timestamp() - interval '{SETTLE_WINDOW_SECONDS} seconds'")
    return text(f"datetime('now', '-{SETTLE_WINDOW_SECONDS} seconds')")


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
    (AC-94-68, computed in SQL from the DB's own clock - review round 1 #6)
    and, by default, ``is_test`` rows (AC-94-67). ONE query - the row's own
    ``payload_json`` (built at write time) is already the exact wire shape,
    so there is no per-row fan-out here."""
    limit = max(1, min(limit, MAX_FEED_LIMIT))

    query = db.query(IdeaStatusEvent).filter(
        IdeaStatusEvent.tenant_id == tenant_id,
        IdeaStatusEvent.seq > after,
        IdeaStatusEvent.created_at <= _settle_window_cutoff_expr(db),
    )
    if not include_test:
        query = query.filter(IdeaStatusEvent.is_test.is_(False))
    rows = query.order_by(IdeaStatusEvent.seq.asc()).limit(limit).all()

    events = [row.payload_json for row in rows]
    next_after = rows[-1].seq if rows else after
    return {"events": events, "next_after": next_after}
