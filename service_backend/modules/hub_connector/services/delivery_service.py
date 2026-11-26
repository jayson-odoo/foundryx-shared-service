"""Outbound ``availability.updated`` webhooks to hubs (AC-18).

Headers::

    X-Hub-Connector-Event: availability.updated
    X-Hub-Connector-Delivery: <delivery id>
    X-Hub-Connector-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, t + "." + body)>

One delivery per hub customer whose view changed: ``items`` = what it may see
now (changed only, or everything on a resync), ``removed`` = item codes it saw
before and may no longer see. The view is decided by ``availability.view_for``
(the one shared function). The attempt itself is core
``app/services/webhook_post.py`` (same as Lead Capture / omnichannel): the
receiver URL is re-checked before EVERY attempt and the connection only opens to
an address that passed the check. Retry ladder 1 min, 5 min, 30 min, 2 h, 6 h,
24 h, then FAILED.

Ordering: every delivery carries ``sequence`` (increasing per hub customer) and
deliveries to one customer go out oldest first - a newer one waits while an
older one is still retrying, so a late retry can never overwrite newer state.
A delivery that fails for good queues that customer's FULL view once (a full
view replaces everything the hub holds for the customer), and "Send again"
also sends the customer's CURRENT full view, never a stale body.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import release_read_transactions
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository
from app.secrets import decrypt_secret, encrypt_secret
from app.services import webhook_post
from app.services.url_guard import GuardedAsyncTransport, UrlGuardError
from app.services.url_guard import assert_deliverable as core_assert_deliverable

from ..models import (
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DELIVERY_SUCCESS,
    HcDelivery,
    HcHub,
    HcHubCustomer,
    HcItem,
    HcSentView,
)
from . import availability, hub_service
from .hub_service import HubError

logger = logging.getLogger(__name__)

MODULE_NAME = "hub_connector"
EVENT_AVAILABILITY = "availability.updated"
RETRY_LADDER = [60, 300, 1800, 7200, 21600, 86400]
MAX_ATTEMPTS = len(RETRY_LADDER) + 1
DELIVERY_DEADLINE_SECONDS = 10
CLAIM_MARGIN_SECONDS = 60
DUE_RUN_BUDGET_SECONDS = 240
HIDDEN_HASH = availability.view_hash(None)


# ── signature ───────────────────────────────────────────────────────────────

def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify(secret: str, header: str, body: bytes, *, tolerance: int = 300, now: Optional[int] = None) -> bool:
    """Hub-side check (the stub hub in the tests uses it)."""
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    t, v1 = parts.get("t", ""), parts.get("v1", "")
    if not t.isdigit() or not v1:
        return False
    if abs((now if now is not None else int(time.time())) - int(t)) > tolerance:
        return False
    expected = sign(secret, t, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, v1)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ── queue (flushes, never commits - the caller owns the transaction) ────────

def tenant_lock(db: Session, tenant_id: str) -> None:
    """Serialise this tenant's pushes / policy edits until the transaction
    ends (Postgres), so two writers never diff against the same sent view."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"hub_connector:{tenant_id}"})


def _sent_map(db: Session, tenant_id: str, hub_customer_id: str, codes: Optional[Iterable[str]]) -> Dict[str, HcSentView]:
    q = db.query(HcSentView).filter(HcSentView.tenant_id == tenant_id, HcSentView.hub_customer_id == hub_customer_id)
    if codes is not None:
        code_list = list(codes)
        if not code_list:
            return {}
        q = q.filter(HcSentView.item_code.in_(code_list))
    return {row.item_code: row for row in q.all()}


def _queue_customer(
    db: Session,
    hub: HcHub,
    customer: HcHubCustomer,
    items: Sequence[HcItem],
    *,
    full: bool,
    hide_all: bool = False,
    removed_codes: Sequence[str] = (),
) -> Optional[str]:
    """Queue ONE delivery carrying this customer's changed view, or nothing
    when nothing changed. ``full`` sends every visible item (resync);
    ``hide_all`` tells the hub to drop everything (customer removed)."""
    tenant_id = hub.tenant_id
    policy = hub_service.policy_for(hub, customer)
    sent = _sent_map(
        db, tenant_id, customer.id, None if (full or hide_all) else [i.code for i in items] + list(removed_codes)
    )
    shown: List[Dict[str, Any]] = []
    removed: List[str] = []
    seen = set()
    for item in items:
        seen.add(item.code)
        view = None if hide_all else availability.view_for(hub_service.item_facts(item), policy)
        new_hash = availability.view_hash(view)
        before = sent.get(item.code)
        was_visible = before is not None and before.view_hash != HIDDEN_HASH
        changed = before is None or before.view_hash != new_hash
        if view is not None and (changed or full):
            shown.append(view)
        elif view is None and was_visible:
            removed.append(item.code)
        if before is None:
            if view is not None:
                db.add(HcSentView(tenant_id=tenant_id, hub_customer_id=customer.id, item_code=item.code, view_hash=new_hash))
        elif before.view_hash != new_hash:
            before.view_hash = new_hash
    if full or hide_all or removed_codes:
        # Items the customer saw that no longer exist in the facts.
        for code, row in sent.items():
            if code not in seen and row.view_hash != HIDDEN_HASH:
                removed.append(code)
                row.view_hash = HIDDEN_HASH
    if not shown and not removed and not full:
        db.flush()
        return None
    seq = (
        db.query(func.max(HcDelivery.seq))
        .filter(HcDelivery.tenant_id == tenant_id, HcDelivery.hub_customer_id == customer.id)
        .scalar()
        or 0
    ) + 1
    data = {
        "hub": {"code": hub.code},
        "customer": {"code": customer.customer_code, "name": hub_service.customer_name(db, tenant_id, customer.customer_code)},
        "sequence": seq,
        "full": bool(full or hide_all),
        "items": shown,
        "removed": sorted(removed),
    }
    envelope = {"id": str(uuid.uuid4()), "type": EVENT_AVAILABILITY, "occurredAt": _iso_z(datetime.now(timezone.utc)), "data": data}
    body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
    row = HcDelivery(
        tenant_id=tenant_id,
        hub_id=hub.id,
        hub_customer_id=customer.id,
        customer_code=customer.customer_code,
        event=EVENT_AVAILABILITY,
        seq=seq,
        full=bool(full or hide_all),
        body_encrypted=encrypt_secret({"body": body}),
        item_count=len(shown) + len(removed),
        attempt=0,
        next_at=datetime.now(timezone.utc),
        status=DELIVERY_PENDING,
    )
    db.add(row)
    db.flush()
    return row.id


def _deliverable_hubs(db: Session, tenant_id: str) -> List[HcHub]:
    return (
        db.query(HcHub)
        .filter(HcHub.tenant_id == tenant_id, HcHub.active.is_(True), HcHub.callback_url.isnot(None))
        .all()
    )


def _active_customers(db: Session, tenant_id: str, hub_id: str) -> List[HcHubCustomer]:
    return (
        db.query(HcHubCustomer)
        .filter(HcHubCustomer.tenant_id == tenant_id, HcHubCustomer.hub_id == hub_id, HcHubCustomer.active.is_(True))
        .order_by(HcHubCustomer.customer_code.asc())
        .all()
    )


def queue_item_changes(
    db: Session, tenant_id: str, item_codes: Sequence[str], *, removed_codes: Sequence[str] = ()
) -> List[str]:
    """After a CRM push: one delivery per hub customer whose view of any of
    these items changed (``removed_codes`` = discontinued items)."""
    if not item_codes and not removed_codes:
        return []
    items = (
        db.query(HcItem).filter(HcItem.tenant_id == tenant_id, HcItem.code.in_(list(item_codes))).all()
        if item_codes
        else []
    )
    ids: List[str] = []
    for hub in _deliverable_hubs(db, tenant_id):
        for customer in _active_customers(db, tenant_id, hub.id):
            delivery_id = _queue_customer(db, hub, customer, items, full=False, removed_codes=removed_codes)
            if delivery_id:
                ids.append(delivery_id)
    return ids


def _all_items(db: Session, tenant_id: str) -> List[HcItem]:
    return db.query(HcItem).filter(HcItem.tenant_id == tenant_id).order_by(HcItem.code.asc()).all()


def resync_customer(db: Session, hub: HcHub, customer: HcHubCustomer) -> Optional[str]:
    """The customer's FULL view (policy change / Resync / new customer)."""
    if not hub.active or not hub.callback_url or not customer.active:
        return None
    tenant_lock(db, hub.tenant_id)
    return _queue_customer(db, hub, customer, _all_items(db, hub.tenant_id), full=True)


def hide_customer(db: Session, hub: HcHub, customer: HcHubCustomer) -> Optional[str]:
    """Tell the hub to drop everything this customer saw (removed / paused)."""
    if not hub.active or not hub.callback_url:
        return None
    tenant_lock(db, hub.tenant_id)
    return _queue_customer(db, hub, customer, _all_items(db, hub.tenant_id), full=False, hide_all=True)


def resync_hub(db: Session, tenant_id: str, hub_id: str) -> List[str]:
    hub = hub_service.get_hub(db, tenant_id, hub_id)
    if not hub.active:
        raise HubError(409, "hub_inactive", "This hub is switched off.")
    if not hub.callback_url:
        raise HubError(409, "no_receiver", "Add a receiver URL first.")
    tenant_lock(db, tenant_id)
    items = _all_items(db, tenant_id)
    ids = [d for d in (_queue_customer(db, hub, c, items, full=True) for c in _active_customers(db, tenant_id, hub.id)) if d]
    return ids


def enqueue(delivery_ids: Sequence[str]) -> None:
    """Hand each delivery to the worker (eager dev runs it inline). Never raises."""
    for delivery_id in delivery_ids:
        try:
            from app.workflow_engine.worker import hub_connector_deliver

            hub_connector_deliver.delay(delivery_id)
        except Exception:  # noqa: BLE001 - the due tick is the backstop
            logger.exception("hub delivery enqueue failed for %s", delivery_id)


# ── one attempt ─────────────────────────────────────────────────────────────

def _service_enabled(db: Session, tenant_id: str) -> bool:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.signin_allowed:
        return False
    return ModuleRepository(db).is_active(tenant_id, MODULE_NAME)


def _assert_deliverable(url: str) -> None:
    core_assert_deliverable(url, subject="The receiver URL")


def _check_address(url: str, budget: float) -> float:
    return webhook_post.check_address_within(url, budget, lambda u: _assert_deliverable(u))


def _post(url: str, *, content: bytes, headers: Dict[str, str], timeout: float) -> webhook_post.PostReply:
    """Module-level so a test can replace the outbound call."""
    return webhook_post.run_under_deadline(
        lambda: webhook_post.post_async(
            url, content, headers, timeout, lambda: GuardedAsyncTransport(subject="The receiver URL")
        ),
        timeout,
    )


def _fail(db: Session, delivery: HcDelivery, message: str) -> None:
    delivery.status, delivery.next_at, delivery.last_error = DELIVERY_FAILED, None, message
    db.commit()


def _older_pending(db: Session, delivery: HcDelivery) -> Optional[HcDelivery]:
    if not delivery.hub_customer_id:
        return None
    return (
        db.query(HcDelivery)
        .filter(
            HcDelivery.tenant_id == delivery.tenant_id,
            HcDelivery.hub_customer_id == delivery.hub_customer_id,
            HcDelivery.status == DELIVERY_PENDING,
            HcDelivery.seq < delivery.seq,
        )
        .order_by(HcDelivery.seq.asc())
        .first()
    )


def _recover_after_dead(db: Session, delivery: HcDelivery) -> Optional[str]:
    """A change the hub never got: queue the customer's full view ONCE (not
    after a failed full view, so a hub that stays down is not re-queued
    forever - the admin's "Send again" takes over)."""
    if delivery.full or not delivery.hub_customer_id:
        return None
    hub = db.query(HcHub).filter(HcHub.id == delivery.hub_id, HcHub.tenant_id == delivery.tenant_id).first()
    customer = (
        db.query(HcHubCustomer)
        .filter(HcHubCustomer.id == delivery.hub_customer_id, HcHubCustomer.tenant_id == delivery.tenant_id)
        .first()
    )
    if hub is None or customer is None:
        return None
    return resync_customer(db, hub, customer)


def dispatch(db: Session, delivery_id: str) -> str:
    """Run ONE attempt. Returns 'success' | 'retry' | 'waiting' | 'dead' | 'skip'."""
    delivery = db.query(HcDelivery).filter(HcDelivery.id == delivery_id).first()
    if delivery is None or delivery.status != DELIVERY_PENDING:
        return "skip"
    tenant_id = delivery.tenant_id
    hub = db.query(HcHub).filter(HcHub.id == delivery.hub_id, HcHub.tenant_id == tenant_id).first()
    if hub is None or not hub.active or not hub.callback_url:
        _fail(db, delivery, "The hub is switched off or has no receiver URL.")
        return "skip"
    if not _service_enabled(db, tenant_id):
        _fail(db, delivery, "Hub Connector is not enabled for this tenant.")
        return "skip"
    older = _older_pending(db, delivery)
    if older is not None:
        # Oldest first per customer: wait just past the older one's next try.
        delivery.next_at = max(older.next_at or datetime.now(timezone.utc), datetime.now(timezone.utc)) + timedelta(seconds=1)
        db.commit()
        return "waiting"
    try:
        body = decrypt_secret(delivery.body_encrypted)["body"].encode("utf-8")
        secret = decrypt_secret(hub.secret_encrypted)["secret"]
    except Exception:  # noqa: BLE001 - undecryptable: dead-letter cleanly
        _fail(db, delivery, "Stored delivery could not be decrypted.")
        return "dead"

    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Foundryx-HubConnector/1.0",
        "X-Hub-Connector-Event": delivery.event,
        "X-Hub-Connector-Delivery": delivery.id,
        "X-Hub-Connector-Signature": sign(secret, timestamp, body),
    }
    url = hub.callback_url
    now = datetime.now(timezone.utc)
    # Atomic claim (task reschedule and the due tick can race on one row).
    claimed = (
        db.query(HcDelivery)
        .filter(
            HcDelivery.id == delivery_id,
            HcDelivery.status == DELIVERY_PENDING,
            HcDelivery.attempt == delivery.attempt,
            HcDelivery.next_at <= now,
        )
        .update(
            {
                "attempt": HcDelivery.attempt + 1,
                "last_attempt_at": now,
                "next_at": now + timedelta(seconds=DELIVERY_DEADLINE_SECONDS + CLAIM_MARGIN_SECONDS),
            },
            synchronize_session=False,
        )
    )
    attempt = delivery.attempt + 1
    db.commit()
    if claimed != 1:
        return "skip"
    release_read_transactions()

    outcome = webhook_post.attempt_post(
        url,
        body,
        headers,
        deadline_seconds=DELIVERY_DEADLINE_SECONDS,
        check=lambda u, budget: _check_address(u, budget),
        post=lambda u, **kw: _post(u, **kw),
        refused=(UrlGuardError,),
        log_ref=delivery_id,
    )

    db.expire_all()
    delivery = db.query(HcDelivery).filter(HcDelivery.id == delivery_id).first()
    if delivery is None or delivery.status != DELIVERY_PENDING:
        return "skip"
    delivery.last_code = outcome.status_code
    delivery.last_error = outcome.error
    if outcome.ok:
        delivery.status, delivery.next_at = DELIVERY_SUCCESS, None
        hub = db.query(HcHub).filter(HcHub.id == delivery.hub_id, HcHub.tenant_id == tenant_id).first()
        if hub is not None:
            hub.last_success_at = datetime.now(timezone.utc)
        db.commit()
        return "success"
    if attempt < MAX_ATTEMPTS:
        delivery.next_at = datetime.now(timezone.utc) + timedelta(seconds=RETRY_LADDER[attempt - 1])
        db.commit()
        return "retry"
    delivery.status, delivery.next_at = DELIVERY_FAILED, None
    recovery = _recover_after_dead(db, delivery)
    db.commit()
    if recovery:
        enqueue([recovery])
    return "dead"


def redeliver(db: Session, tenant_id: str, delivery_id: str) -> Optional[str]:
    """"Send again": the customer's CURRENT full view (never the old body, which
    may be older than what the hub already holds). Returns the new delivery id."""
    row = db.query(HcDelivery).filter(HcDelivery.id == delivery_id, HcDelivery.tenant_id == tenant_id).first()
    if row is None:
        raise HubError(404, "delivery_not_found", "Delivery not found.")
    if row.status == DELIVERY_PENDING:
        raise HubError(409, "delivery_pending", "This delivery is still being sent.")
    hub = hub_service.get_hub(db, tenant_id, row.hub_id)
    customer = (
        db.query(HcHubCustomer)
        .filter(HcHubCustomer.id == row.hub_customer_id, HcHubCustomer.tenant_id == tenant_id)
        .first()
        if row.hub_customer_id
        else None
    )
    if customer is None:
        raise HubError(409, "customer_removed", "This customer is no longer on the hub.")
    if not hub.active or not hub.callback_url or not customer.active:
        raise HubError(409, "hub_inactive", "Switch the hub and the customer on, and add a receiver URL first.")
    new_id = resync_customer(db, hub, customer)
    db.commit()
    enqueue([new_id] if new_id else [])
    return new_id


def run_due(db: Session, limit: int = 100) -> int:
    """Re-drive PENDING deliveries whose time has come (beat tick)."""
    now = datetime.now(timezone.utc)
    due = [
        r
        for (r,) in db.query(HcDelivery.id)
        .filter(HcDelivery.status == DELIVERY_PENDING, HcDelivery.next_at <= now)
        .order_by(HcDelivery.next_at.asc())
        .limit(limit)
        .all()
    ]
    deadline = time.monotonic() + DUE_RUN_BUDGET_SECONDS
    attempted = 0
    for delivery_id in due:
        if time.monotonic() >= deadline:
            break
        attempted += 1
        try:
            dispatch(db, delivery_id)
        except Exception:  # noqa: BLE001 - one bad row never stops the rest
            logger.exception("hub delivery %s failed in the due run", delivery_id)
            db.rollback()
    return attempted


_DELIVERY_SORT = {
    "createdAt": HcDelivery.created_at,
    "customerCode": HcDelivery.customer_code,
    "event": HcDelivery.event,
    "status": HcDelivery.status,
    "attempt": HcDelivery.attempt,
}


def list_deliveries(
    db: Session,
    tenant_id: str,
    hub_id: str,
    *,
    statuses: Optional[Sequence[str]] = None,
    search: Optional[str] = None,
    sort: Optional[str] = None,
    order: str = "desc",
    page: int = 0,
    page_size: int = 25,
):
    from sqlalchemy import func, or_

    from ..models import HcCustomer

    hub_service.get_hub(db, tenant_id, hub_id)
    q = (
        db.query(HcDelivery, HcCustomer.name)
        .outerjoin(HcCustomer, (HcCustomer.code == HcDelivery.customer_code) & (HcCustomer.tenant_id == tenant_id))
        .filter(HcDelivery.tenant_id == tenant_id, HcDelivery.hub_id == hub_id)
    )
    status_list = [s for s in statuses or [] if s in (DELIVERY_PENDING, DELIVERY_SUCCESS, DELIVERY_FAILED)]
    if status_list:
        q = q.filter(HcDelivery.status.in_(status_list))
    if search and search.strip():
        pattern = hub_service._like(search.strip())
        q = q.filter(
            or_(
                func.lower(func.coalesce(HcDelivery.customer_code, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(HcCustomer.name, "")).like(pattern, escape="\\"),
            )
        )
    total = q.count()
    offset, size = hub_service._page(page, page_size)
    column = HcCustomer.name if sort == "customerName" else _DELIVERY_SORT.get(sort or "", HcDelivery.created_at)
    primary = column.asc() if order == "asc" else column.desc()
    rows = q.order_by(primary, HcDelivery.id.asc()).offset(offset).limit(size).all()
    return rows, total
