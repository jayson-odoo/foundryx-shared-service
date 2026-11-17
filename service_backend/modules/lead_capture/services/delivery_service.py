"""Consumer webhook endpoints + signed delivery (plan 64 D7, AC-64-60/62/63/64).

Headers per AC-64-62::

    X-Lead-Capture-Event: lead.created
    X-Lead-Capture-Delivery: <delivery id>
    X-Lead-Capture-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, t + "." + body)>

Retry ladder per AC-64-63: a non-2xx or a timeout (10 s total per attempt) is
retried at 1 min, 5 min, 30 min, 2 h, 6 h, 24 h, then the delivery is FAILED.
The callback URL is re-checked before EVERY attempt (AC-64-64) and the
connection only opens to an address that passed the check (core guarded
transport). The attempt itself is core ``app/services/webhook_post.py`` - the
same function omnichannel's consumer webhooks use (R5).

The body is personal data, so it is stored Fernet-encrypted and decrypted only
to sign and send it. Nothing here logs a body, a secret or a URL.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets as pysecrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.database import release_read_transactions
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository
from app.secrets import decrypt_secret, encrypt_secret
from app.services import webhook_post
from app.services.url_guard import GuardedAsyncTransport, UrlGuardError
from app.services.url_guard import assert_deliverable as core_assert_deliverable
from app.services.url_guard import validate_public_https_url

from ..models import (
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DELIVERY_SUCCESS,
    LcDelivery,
    LcLead,
    LcWebhookEndpoint,
)

logger = logging.getLogger(__name__)

MODULE_NAME = "lead_capture"
EVENT_LEAD_CREATED = "lead.created"
EVENT_TYPES = ("lead.created", "lead.updated", "source.updated")
MAX_ENDPOINTS = 5
# Delay before the NEXT attempt, indexed by attempts already made (AC-64-63).
RETRY_LADDER = [60, 300, 1800, 7200, 21600, 86400]
MAX_ATTEMPTS = len(RETRY_LADDER) + 1
DELIVERY_DEADLINE_SECONDS = 10
CLAIM_MARGIN_SECONDS = 60
DUE_RUN_BUDGET_SECONDS = 240
SECRET_SCHEME = "whsec_"


class DeliveryError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


# ── Signature ───────────────────────────────────────────────────────────────

def sign(secret: str, timestamp: str, body: bytes) -> str:
    """``t=<unix>,v1=<hex HMAC-SHA256(secret, t + "." + body)>``."""
    mac = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify(secret: str, header: str, body: bytes, *, tolerance: int = 300, now: Optional[int] = None) -> bool:
    """Consumer-side check (documented in the guide; used by the tests)."""
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    t, v1 = parts.get("t", ""), parts.get("v1", "")
    if not t.isdigit() or not v1:
        return False
    if abs((now if now is not None else int(time.time())) - int(t)) > tolerance:
        return False
    expected = sign(secret, t, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, v1)


# ── Endpoints (AC-64-60) ────────────────────────────────────────────────────

def _validate_events(events: List[str]) -> List[str]:
    clean = list(dict.fromkeys(e for e in events or [] if isinstance(e, str)))
    if not clean:
        raise DeliveryError(422, "invalid_events", "Choose at least one event.")
    unknown = [e for e in clean if e not in EVENT_TYPES]
    if unknown:
        raise DeliveryError(422, "invalid_events", f"Unknown event: {unknown[0]}.")
    return clean


def create_endpoint(db: Session, tenant_id: str, url: str, events: List[str]) -> Tuple[LcWebhookEndpoint, str]:
    """Returns ``(row, secret)``; the secret is shown ONCE."""
    try:
        clean_url = validate_public_https_url(url, strict_dns=False, subject="Callback URL")
    except UrlGuardError as exc:
        raise DeliveryError(422, "invalid_url", str(exc)) from None
    clean_events = _validate_events(events)
    count = (
        db.query(LcWebhookEndpoint)
        .filter(LcWebhookEndpoint.tenant_id == tenant_id, LcWebhookEndpoint.active.is_(True))
        .count()
    )
    if count >= MAX_ENDPOINTS:
        raise DeliveryError(409, "endpoint_limit", f"At most {MAX_ENDPOINTS} receivers.")
    secret = SECRET_SCHEME + pysecrets.token_urlsafe(32)
    row = LcWebhookEndpoint(
        tenant_id=tenant_id,
        url=clean_url,
        events_json=clean_events,
        secret_encrypted=encrypt_secret({"secret": secret}),
        active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, secret


def list_endpoints(db: Session, tenant_id: str) -> List[LcWebhookEndpoint]:
    return (
        db.query(LcWebhookEndpoint)
        .filter(LcWebhookEndpoint.tenant_id == tenant_id, LcWebhookEndpoint.active.is_(True))
        .order_by(LcWebhookEndpoint.created_at.asc(), LcWebhookEndpoint.id.asc())
        .all()
    )


def delete_endpoint(db: Session, tenant_id: str, endpoint_id: str) -> None:
    row = (
        db.query(LcWebhookEndpoint)
        .filter(LcWebhookEndpoint.id == endpoint_id, LcWebhookEndpoint.tenant_id == tenant_id)
        .first()
    )
    if row is None or not row.active:
        raise DeliveryError(404, "endpoint_not_found", "Endpoint not found.")
    row.active = False
    # Pending deliveries to it stop here (never sent to a removed endpoint).
    db.query(LcDelivery).filter(
        LcDelivery.endpoint_id == row.id,
        LcDelivery.tenant_id == tenant_id,
        LcDelivery.status == DELIVERY_PENDING,
    ).update({"status": DELIVERY_FAILED, "next_at": None, "last_error": "Endpoint removed."})
    db.commit()


# ── Queue (no commit - the caller owns the lead transaction) ───────────────

def envelope(event: str, data: Dict[str, Any]) -> Dict[str, Any]:
    from ..mapping import iso_z

    return {
        "id": str(uuid.uuid4()),
        "type": event,
        "occurredAt": iso_z(datetime.now(timezone.utc)),
        "data": data,
    }


def queue_event(db: Session, tenant_id: str, event: str, data: Dict[str, Any], lead_id: Optional[str] = None) -> List[str]:
    """One PENDING delivery per active endpoint subscribed to ``event``. Flushes,
    never commits. Returns the new delivery ids."""
    endpoints = [e for e in list_endpoints(db, tenant_id) if event in (e.events_json or [])]
    return _queue_to(db, tenant_id, endpoints, event, data, lead_id)


def _queue_to(
    db: Session,
    tenant_id: str,
    endpoints: List[LcWebhookEndpoint],
    event: str,
    data: Dict[str, Any],
    lead_id: Optional[str],
) -> List[str]:
    """One PENDING delivery per given endpoint. Flushes, never commits."""
    if not endpoints:
        return []
    body = json.dumps(envelope(event, data), separators=(",", ":"), ensure_ascii=False)
    ids: List[str] = []
    for ep in endpoints:
        row = LcDelivery(
            tenant_id=tenant_id,
            endpoint_id=ep.id,
            lead_id=lead_id,
            event=event,
            body_encrypted=encrypt_secret({"body": body}),
            attempt=0,
            next_at=datetime.now(timezone.utc),
            status=DELIVERY_PENDING,
        )
        db.add(row)
        db.flush()
        ids.append(row.id)
    return ids


# Fake values per field TYPE for a test push (never real personal data).
_TEST_VALUES = {
    "name": "Test Lead",
    "phone": "+60000000000",
    "email": "test.lead@example.com",
    "notes": "Test push from Lead Capture.",
    "text": "Test",
}


def get_endpoint(db: Session, tenant_id: str, endpoint_id: str) -> LcWebhookEndpoint:
    """An ACTIVE endpoint of this tenant, else ``endpoint_not_found``."""
    row = (
        db.query(LcWebhookEndpoint)
        .filter(LcWebhookEndpoint.id == endpoint_id, LcWebhookEndpoint.tenant_id == tenant_id)
        .first()
    )
    if row is None or not row.active:
        raise DeliveryError(404, "endpoint_not_found", "Endpoint not found.")
    return row


def send_test_push(db: Session, tenant_id: str, endpoint_id: str) -> LcDelivery:
    """Queue ONE signed delivery of a sample lead (``isTest: true``) to this
    endpoint only, through the same queue + dispatch as a real lead (AC-64-57).
    The event is ``lead.created`` when subscribed, else the endpoint's first."""
    from ..mapping import lead_body
    from .field_service import targets

    endpoint = get_endpoint(db, tenant_id, endpoint_id)
    events = list(endpoint.events_json or [])
    event = EVENT_LEAD_CREATED if EVENT_LEAD_CREATED in events or not events else events[0]
    now = datetime.now(timezone.utc)
    fields = {key: _TEST_VALUES.get(typ, "Test") for key, typ in targets(db, tenant_id)}
    data = lead_body(
        lead_id=f"test_{uuid.uuid4().hex[:12]}",
        source_id="test",
        source_name="Test push",
        platform="test",
        platform_lead_id="test",
        page_id=None,
        form_id=None,
        form_name=None,
        received_at=now,
        platform_created_at=now,
        is_test=True,
        duplicate_of=None,
        fields=fields,
        answers=[],
        attribution={},
    )
    [delivery_id] = _queue_to(db, tenant_id, [endpoint], event, data, None)
    db.commit()
    enqueue([delivery_id])
    row = db.query(LcDelivery).filter(LcDelivery.id == delivery_id, LcDelivery.tenant_id == tenant_id).first()
    db.refresh(row)
    return row


def enqueue(delivery_ids: List[str]) -> None:
    """Hand each delivery to the worker (eager dev runs it inline). Never raises."""
    for delivery_id in delivery_ids:
        try:
            from app.workflow_engine.worker import lead_capture_deliver

            lead_capture_deliver.delay(delivery_id)
        except Exception:  # noqa: BLE001 - the due tick is the backstop
            logger.exception("lead delivery enqueue failed for %s", delivery_id)


# ── One attempt ─────────────────────────────────────────────────────────────

def _service_enabled(db: Session, tenant_id: str) -> bool:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.signin_allowed:
        return False
    return ModuleRepository(db).is_active(tenant_id, MODULE_NAME)


def _assert_deliverable(url: str) -> None:
    core_assert_deliverable(url, subject="Callback URL")


def _check_address(url: str, budget: float) -> float:
    return webhook_post.check_address_within(url, budget, lambda u: _assert_deliverable(u))


def _post(url: str, *, content: bytes, headers: Dict[str, str], timeout: float) -> webhook_post.PostReply:
    """Module-level so a test can replace the outbound call."""
    return webhook_post.run_under_deadline(
        lambda: webhook_post.post_async(
            url, content, headers, timeout, lambda: GuardedAsyncTransport(subject="Callback URL")
        ),
        timeout,
    )


def dispatch(db: Session, delivery_id: str) -> str:
    """Run ONE attempt. Returns 'success' | 'retry' | 'dead' | 'skip'."""
    delivery = db.query(LcDelivery).filter(LcDelivery.id == delivery_id).first()
    if delivery is None or delivery.status != DELIVERY_PENDING:
        return "skip"
    tenant_id = delivery.tenant_id
    endpoint = (
        db.query(LcWebhookEndpoint)
        .filter(LcWebhookEndpoint.id == delivery.endpoint_id, LcWebhookEndpoint.tenant_id == tenant_id)
        .first()
    )
    if endpoint is None or not endpoint.active:
        delivery.status, delivery.next_at, delivery.last_error = DELIVERY_FAILED, None, "Endpoint removed."
        db.commit()
        return "skip"
    if not _service_enabled(db, tenant_id):
        delivery.status, delivery.next_at = DELIVERY_FAILED, None
        delivery.last_error = "Lead Capture is not enabled for this tenant."
        db.commit()
        return "skip"
    try:
        body = decrypt_secret(delivery.body_encrypted)["body"].encode("utf-8")
        secret = decrypt_secret(endpoint.secret_encrypted)["secret"]
    except Exception:  # noqa: BLE001 - undecryptable: dead-letter cleanly
        delivery.status, delivery.next_at = DELIVERY_FAILED, None
        delivery.last_error = "Stored delivery could not be decrypted."
        db.commit()
        return "dead"

    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Foundryx-LeadCapture/1.0",
        "X-Lead-Capture-Event": delivery.event,
        "X-Lead-Capture-Delivery": delivery.id,
        "X-Lead-Capture-Signature": sign(secret, timestamp, body),
    }
    url = endpoint.url
    # Atomic claim: the task's own reschedule and the due tick can reach the
    # same row together; only the one whose UPDATE matches sends. The claim
    # parks next_at past this attempt's deadline, so a crash mid-POST is
    # re-driven by the tick afterwards.
    now = datetime.now(timezone.utc)
    claimed = (
        db.query(LcDelivery)
        .filter(
            LcDelivery.id == delivery_id,
            LcDelivery.status == DELIVERY_PENDING,
            LcDelivery.attempt == delivery.attempt,
            LcDelivery.next_at <= now,
        )
        .update(
            {
                "attempt": LcDelivery.attempt + 1,
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
    delivery = db.query(LcDelivery).filter(LcDelivery.id == delivery_id).first()
    if delivery is None or delivery.status != DELIVERY_PENDING:
        return "skip"  # removed / failed by staff while the POST ran
    delivery.last_code = outcome.status_code
    delivery.last_error = outcome.error
    if outcome.ok:
        delivery.status, delivery.next_at = DELIVERY_SUCCESS, None
        endpoint = (
            db.query(LcWebhookEndpoint)
            .filter(LcWebhookEndpoint.id == delivery.endpoint_id, LcWebhookEndpoint.tenant_id == tenant_id)
            .first()
        )
        if endpoint is not None:
            endpoint.last_success_at = datetime.now(timezone.utc)
        db.commit()
        return "success"
    if attempt < MAX_ATTEMPTS:
        delivery.next_at = datetime.now(timezone.utc) + timedelta(seconds=RETRY_LADDER[attempt - 1])
        db.commit()
        return "retry"
    delivery.status, delivery.next_at = DELIVERY_FAILED, None
    db.commit()
    return "dead"


def redeliver(db: Session, tenant_id: str, delivery_id: str) -> LcDelivery:
    """Resend the SAME body (a new signature at send time), ladder restarted."""
    row = (
        db.query(LcDelivery)
        .filter(LcDelivery.id == delivery_id, LcDelivery.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        raise DeliveryError(404, "delivery_not_found", "Delivery not found.")
    if row.lead_id:
        lead = db.query(LcLead).filter(LcLead.id == row.lead_id, LcLead.tenant_id == tenant_id).first()
        if lead is not None and lead.purged_at is not None:
            raise DeliveryError(409, "lead_purged", "This lead's personal data was deleted; it cannot be resent.")
    row.status, row.attempt, row.next_at = DELIVERY_PENDING, 0, datetime.now(timezone.utc)
    row.last_error = None
    db.commit()
    enqueue([row.id])
    db.refresh(row)
    return row


def run_due(db: Session, limit: int = 100) -> int:
    """Re-drive PENDING deliveries whose time has come (beat tick)."""
    now = datetime.now(timezone.utc)
    due = [
        r for (r,) in db.query(LcDelivery.id)
        .filter(LcDelivery.status == DELIVERY_PENDING, LcDelivery.next_at <= now)
        .order_by(LcDelivery.next_at.asc())
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
            logger.exception("lead delivery %s failed in the due run", delivery_id)
            db.rollback()
    return attempted
