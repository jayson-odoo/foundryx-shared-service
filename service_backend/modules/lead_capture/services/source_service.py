"""A connected source's lifecycle after connect (plan 64 lane L-B).

- Forms (AC-64-23): read the Page's Instant Forms; choose "all" (new forms
  included) or "pick" (only the ticked ids, at least one). The ingest and the
  backfill ask ``accepts_form`` before storing a lead.
- Token health (AC-64-29): a Graph answer classified by core
  ``app/integrations/meta/errors.is_token_error`` moves a routing source to
  ``NEEDS_RECONNECT`` - ONE guarded update, so exactly one ``source.updated``
  event and one email to the tenant's ``lead_capture.manage`` holders, however
  many workers hit the dead token at once.
- Disconnect (AC-64-09/37): ``DISCONNECTED``, token wiped, leads kept; the
  Page's ``leadgen`` field is dropped (core ``unsubscribe_page_fields``) only
  when no other source, of any tenant, still receives that Page's leads.
- History (AC-64-38): one ``lc_source_event`` row per tracked change, with who
  (user, gateway key or the system), on behalf of whom, when, old -> new.

Every lookup takes the tenant (AC-64-70) except the token-health flip, which
runs inside the ingest on a source it already resolved. No token reaches a log
line, an event, an email or an answer (AC-64-71).
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.integrations.meta.pages import unsubscribe_page_fields
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.secrets import decrypt_secret

from .. import schemas
from ..meta_leads import MetaLeadClient, MetaLeadError
from ..models import (
    PLATFORM_FACEBOOK,
    SOURCE_DISCONNECTED,
    SOURCE_LIVE,
    SOURCE_NEEDS_RECONNECT,
    SOURCE_ROUTING_STATES,
    LcApiKey,
    LcSource,
    LcSourceEvent,
)
from . import delivery_service

logger = logging.getLogger(__name__)

LEADGEN_FIELD = "leadgen"
MANAGE_PERMISSION = "lead_capture.manage"
EVENT_SOURCE_UPDATED = "source.updated"
FORMS_ALL = "all"
FORMS_PICK = "pick"
FORMS_MODES = (FORMS_ALL, FORMS_PICK)
MAX_PICKED_FORMS = 200
_FORM_ID_RE = re.compile(r"^[0-9]{1,32}$")
# config_json key remembering the routing state a source had before it left
# routing, so a reconnect restores LIVE only for a source that passed its test.
LAST_ROUTING_KEY = "lastRoutingStatus"

ACTION_CONNECTED = "connected"
ACTION_RECONNECTED = "reconnected"
ACTION_FORMS_CHANGED = "forms_changed"
ACTION_NEEDS_RECONNECT = "needs_reconnect"
ACTION_DISCONNECTED = "disconnected"


class SourceError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Actor:
    """Who made a change: a signed-in user (``on_behalf_of`` = the user they
    are impersonating), a gateway key, or the system (token health)."""

    type: str
    id: Optional[str] = None
    on_behalf_of: Optional[str] = None

    @classmethod
    def user(cls, actor_id: Optional[str], effective_id: Optional[str] = None) -> "Actor":
        behalf = effective_id if effective_id and effective_id != actor_id else None
        return cls("user", actor_id, behalf)

    @classmethod
    def key(cls, key_id: str) -> "Actor":
        return cls("key", key_id)

    @classmethod
    def system(cls) -> "Actor":
        return cls("system")


# ── lookups ─────────────────────────────────────────────────────────────────

def get_source(db: Session, tenant_id: str, source_id: str) -> LcSource:
    row = (
        db.query(LcSource)
        .filter(LcSource.id == source_id, LcSource.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        raise SourceError(404, "source_not_found", "Source not found.")
    return row


def page_credentials(source: LcSource) -> Optional[Dict[str, Any]]:
    """``{"pageToken", "dev"}`` or None (no token, undecryptable)."""
    if not source.credentials_encrypted:
        return None
    try:
        creds = decrypt_secret(source.credentials_encrypted)
    except Exception:  # noqa: BLE001 - undecryptable: treated as no token
        logger.warning("lead source %s credentials could not be decrypted", source.id)
        return None
    return creds if isinstance(creds, dict) and creds.get("pageToken") else None


def _usable_credentials(source: LcSource, meta: MetaLeadClient) -> Dict[str, Any]:
    creds = page_credentials(source)
    if source.platform != PLATFORM_FACEBOOK or creds is None or (meta.configured and creds.get("dev")):
        raise SourceError(400, "token_invalid", "This source has no usable Page token. Reconnect the Page.")
    return creds


# ── forms (AC-64-23) ────────────────────────────────────────────────────────

def forms_mode(source: LcSource) -> str:
    mode = (source.config_json or {}).get("formsMode")
    return mode if mode in FORMS_MODES else FORMS_ALL


def picked_forms(source: LcSource) -> List[str]:
    ids = (source.config_json or {}).get("formIds")
    return [i for i in ids if isinstance(i, str)] if forms_mode(source) == FORMS_PICK and isinstance(ids, list) else []


def accepts_form(source: LcSource, form_id: Optional[str]) -> bool:
    """The forms filter: only "pick" mode filters. An unknown form id (the
    webhook did not say) is accepted here and checked again on the lead's own
    form id once it is read."""
    if forms_mode(source) != FORMS_PICK or not form_id:
        return True
    return form_id in picked_forms(source)


def _meta_error(exc: MetaLeadError) -> SourceError:
    if exc.unreachable:
        return SourceError(502, "meta_unreachable", "Meta could not be reached. Try again.")
    if exc.token_invalid:
        return SourceError(400, "token_invalid", "Meta no longer accepts this Page's token. Reconnect the Page.")
    return SourceError(400, "meta_refused", exc.message)


def list_forms(
    db: Session, tenant_id: str, source_id: str, *, client: Optional[MetaLeadClient] = None
) -> schemas.FormList:
    source = get_source(db, tenant_id, source_id)
    meta = client or MetaLeadClient()
    creds = _usable_credentials(source, meta)
    dev = bool(creds.get("dev")) or not meta.configured
    try:
        forms = meta.leadgen_forms(creds["pageToken"], source.account_ref or "", dev=dev)
    except MetaLeadError as exc:
        logger.info("form list read refused (code %s)", exc.code)
        handle_meta_error(db, source, exc)
        raise _meta_error(exc) from None
    tos = meta.leadgen_tos_accepted(creds["pageToken"], source.account_ref or "", dev=dev)
    from ..mapping import parse_meta_time

    return schemas.FormList(
        formsMode=forms_mode(source),
        formIds=picked_forms(source),
        tosAccepted=tos,
        data=[
            schemas.FormItem(
                id=f["id"], name=f.get("name"), status=f.get("status"), createdAt=parse_meta_time(f.get("createdTime"))
            )
            for f in forms
        ],
    )


def _forms_label(source: LcSource, mode: str, ids: List[str]) -> str:
    if mode != FORMS_PICK:
        return "All forms"
    names = (source.config_json or {}).get("formNames") or {}
    return ("Only " + ", ".join(names.get(i) or i for i in ids))[:500]


def set_forms(
    db: Session, tenant_id: str, source_id: str, mode: str, form_ids: Optional[List[str]], actor: Actor
) -> LcSource:
    if mode not in FORMS_MODES:
        raise SourceError(422, "invalid_forms_mode", 'formsMode must be "all" or "pick".')
    clean: List[str] = []
    if mode == FORMS_PICK:
        for form_id in form_ids or []:
            if not isinstance(form_id, str) or not _FORM_ID_RE.fullmatch(form_id.strip()):
                raise SourceError(422, "invalid_form_id", "Form ids are digits only.")
            if form_id.strip() not in clean:
                clean.append(form_id.strip())
        if not clean:
            raise SourceError(422, "forms_required", "Tick at least one form.")
        if len(clean) > MAX_PICKED_FORMS:
            raise SourceError(422, "invalid_form_id", f"Tick at most {MAX_PICKED_FORMS} forms.")
    source = get_source(db, tenant_id, source_id)
    before = _forms_label(source, forms_mode(source), picked_forms(source))
    config = dict(source.config_json or {})
    config["formsMode"] = mode
    if mode == FORMS_PICK:
        config["formIds"] = clean
    else:
        config.pop("formIds", None)
    source.config_json = config  # fresh dict: in-place JSON edits are not tracked
    after = _forms_label(source, mode, clean)
    ids: List[str] = []
    if before != after:
        record_event(db, source, ACTION_FORMS_CHANGED, actor, before, after)
        ids = emit_source_updated(db, source, ACTION_FORMS_CHANGED)
    db.commit()
    delivery_service.enqueue(ids)
    db.refresh(source)
    return source


# ── history (AC-64-38) ──────────────────────────────────────────────────────

def record_event(
    db: Session,
    source: LcSource,
    action: str,
    actor: Actor,
    from_value: Optional[str] = None,
    to_value: Optional[str] = None,
) -> None:
    """Add one History row. No commit: the change it records owns the txn."""
    db.add(
        LcSourceEvent(
            tenant_id=source.tenant_id,
            source_id=source.id,
            action=action,
            actor_type=actor.type,
            actor_id=actor.id,
            on_behalf_of_id=actor.on_behalf_of,
            from_value=(from_value or None) and from_value[:500],
            to_value=(to_value or None) and to_value[:500],
            created_at=datetime.now(timezone.utc),
        )
    )


def history(db: Session, tenant_id: str, source_id: str, limit: int = 200) -> schemas.SourceEventList:
    source = get_source(db, tenant_id, source_id)
    rows = (
        db.query(LcSourceEvent)
        .filter(LcSourceEvent.tenant_id == tenant_id, LcSourceEvent.source_id == source.id)
        .order_by(LcSourceEvent.created_at.desc(), LcSourceEvent.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    user_ids = {r.actor_id for r in rows if r.actor_type == "user" and r.actor_id}
    user_ids |= {r.on_behalf_of_id for r in rows if r.on_behalf_of_id}
    key_ids = {r.actor_id for r in rows if r.actor_type == "key" and r.actor_id}
    # Stored ids resolve WITH the tenant (AC-64-70): a planted id names nobody.
    users = {
        u.id: (u.name or u.email or "")
        for u in db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(user_ids)).all()
    } if user_ids else {}
    keys = {
        k.id: (k.name or "API key")
        for k in db.query(LcApiKey).filter(LcApiKey.tenant_id == tenant_id, LcApiKey.id.in_(key_ids)).all()
    } if key_ids else {}

    def actor_name(row: LcSourceEvent) -> str:
        if row.actor_type == "user":
            return users.get(row.actor_id or "", "") or "Removed user"
        if row.actor_type == "key":
            return keys.get(row.actor_id or "", "") or "Removed API key"
        return "System"

    return schemas.SourceEventList(
        data=[
            schemas.SourceEventItem(
                id=r.id,
                action=r.action,
                actor=schemas.EventActor(type=r.actor_type, name=actor_name(r)),
                onBehalfOf=users.get(r.on_behalf_of_id) if r.on_behalf_of_id else None,
                **{"from": r.from_value, "to": r.to_value},
                createdAt=r.created_at,
            )
            for r in rows
        ]
    )


# ── consumer event (AC-64-29/35) ────────────────────────────────────────────

def emit_source_updated(db: Session, source: LcSource, change: str) -> List[str]:
    """Queue ``source.updated`` (the source as ``GET /sources`` shows it plus
    ``change``). Flushes, never commits; returns the delivery ids."""
    from .read_service import source_item

    db.flush()
    data = source_item(source).model_dump(mode="json")
    data["change"] = change
    return delivery_service.queue_event(db, source.tenant_id, EVENT_SOURCE_UPDATED, data)


# ── token health (AC-64-29) ─────────────────────────────────────────────────

def handle_meta_error(db: Session, source: LcSource, exc: MetaLeadError) -> bool:
    """Flip the source when ``exc`` means the token is gone. Returns True when
    this call moved it. Rolls back the caller's open work first: only call it
    where nothing unsaved is pending."""
    if not exc.token_invalid:
        return False
    return mark_needs_reconnect(db, source.id)


def mark_needs_reconnect(db: Session, source_id: str) -> bool:
    """Routing -> NEEDS_RECONNECT, once. The guarded UPDATE is the gate: only
    the caller whose update matched records History, queues the event and
    sends the email."""
    db.rollback()
    source = db.get(LcSource, source_id)
    if source is None or source.status not in SOURCE_ROUTING_STATES:
        return False
    before = source.status
    moved = (
        db.query(LcSource)
        .filter(LcSource.id == source_id, LcSource.status == before)
        .update({"status": SOURCE_NEEDS_RECONNECT}, synchronize_session=False)
    )
    if moved != 1:
        db.rollback()
        return False
    db.refresh(source)
    source.config_json = {**(source.config_json or {}), LAST_ROUTING_KEY: before}
    record_event(db, source, ACTION_NEEDS_RECONNECT, Actor.system(), before, SOURCE_NEEDS_RECONNECT)
    ids = emit_source_updated(db, source, ACTION_NEEDS_RECONNECT)
    db.commit()
    logger.info("lead source %s needs reconnecting", source_id)
    delivery_service.enqueue(ids)
    _notify_needs_reconnect(db, source)
    return True


def _notify_needs_reconnect(db: Session, source: LcSource) -> None:
    """One email per manager of the source's own tenant. Runs after the
    status commit; mail trouble never undoes it (ids only in the log)."""
    from app.services.email_service import OutboxEmailService

    try:
        recipients: Dict[str, str] = {}
        for user in UserRepository(db).users_with_permission(source.tenant_id, MANAGE_PERMISSION):
            if user.email:
                recipients.setdefault(user.email.strip().lower(), user.email.strip())
        page = (source.account_name or source.name or "your Facebook Page").strip()
        subject = f"Reconnect the Facebook Page {page}"[:200]
        text = (
            f"Facebook no longer accepts the access for the Page {page}, so new leads from it "
            "cannot be read. Open Lead Capture and connect the Page again. Leads sent in the "
            "meantime are picked up after you reconnect."
        )
        body = f"<p>{html.escape(text)}</p>"
    except Exception:  # noqa: BLE001
        logger.exception("reconnect email could not be composed for source %s", source.id)
        db.rollback()
        return
    for address in recipients.values():
        try:
            OutboxEmailService().enqueue_raw(
                db, source.tenant_id, address, subject, body, text, template_key="lead_capture.source_needs_reconnect"
            )
        except Exception:  # noqa: BLE001
            logger.exception("reconnect email failed for source %s", source.id)
            db.rollback()


# ── disconnect (AC-64-09/37) ────────────────────────────────────────────────

def _page_still_held(db: Session, source: LcSource) -> bool:
    """Another source, of ANY tenant, still receiving this Page's leads."""
    return (
        db.query(LcSource.id)
        .filter(
            LcSource.platform == source.platform,
            LcSource.account_ref == source.account_ref,
            LcSource.status.in_(SOURCE_ROUTING_STATES),
            LcSource.id != source.id,
        )
        .first()
        is not None
    )


def disconnect(db: Session, tenant_id: str, source_id: str, *, actor: Actor) -> LcSource:
    """``DISCONNECTED``: stops routing, wipes the token, keeps every lead.
    Calling it again is a no-op."""
    from .connect_service import lock_page

    source = get_source(db, tenant_id, source_id)
    if source.status == SOURCE_DISCONNECTED:
        return source
    lock_page(db, source.platform, source.account_ref or "")
    db.refresh(source)
    if source.status == SOURCE_DISCONNECTED:
        db.commit()
        return source
    before = source.status
    creds = page_credentials(source)
    last_holder = source.account_ref and not _page_still_held(db, source)
    config = dict(source.config_json or {})
    if before in SOURCE_ROUTING_STATES:
        config[LAST_ROUTING_KEY] = before
    config.pop("testLeadRequests", None)
    source.config_json = config
    source.status = SOURCE_DISCONNECTED
    source.credentials_encrypted = None
    record_event(db, source, ACTION_DISCONNECTED, actor, before, SOURCE_DISCONNECTED)
    ids = emit_source_updated(db, source, ACTION_DISCONNECTED)
    db.commit()
    delivery_service.enqueue(ids)
    if last_holder and creds is not None and source.platform == PLATFORM_FACEBOOK:
        _unsubscribe(source.account_ref, creds)
    db.refresh(source)
    return source


def _unsubscribe(page_id: str, creds: Dict[str, Any]) -> None:
    """Drop ``leadgen`` from the app's Page subscription, keeping every other
    field (omnichannel's). Best effort: a dead token or Meta refusal only
    means Meta keeps sending webhooks nobody claims (dropped at resolve)."""
    meta = MetaLeadClient()
    dev = bool(creds.get("dev")) or not meta.configured
    try:
        unsubscribe_page_fields(creds["pageToken"], page_id, [LEADGEN_FIELD], dev=dev)
    except Exception as exc:  # noqa: BLE001 - never fails the disconnect
        logger.warning("leadgen unsubscribe for a Page failed: %s", type(exc).__name__)


def status_after_reconnect(source: LcSource) -> str:
    """The routing state a reconnected source returns to: LIVE when it had
    passed its test before leaving routing, else WAITING_FOR_TEST."""
    from ..models import SOURCE_WAITING_FOR_TEST

    if source.status in SOURCE_ROUTING_STATES:
        return source.status
    last = (source.config_json or {}).get(LAST_ROUTING_KEY)
    if last == SOURCE_LIVE or (last is None and source.status == SOURCE_NEEDS_RECONNECT):
        return SOURCE_LIVE
    return SOURCE_WAITING_FOR_TEST
