"""Planner 3D webhook receivers + signed event delivery (contract 5).

Headers (contract 5.2)::

    X-Planner3d-Event: model.candidates_ready
    X-Planner3d-Delivery: <delivery id>
    X-Planner3d-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, t + "." + body)>

Retry ladder (contract 5.4): a non-2xx or a timeout (10 s per attempt) is retried at
1 min, 5 min, 30 min, 2 h, 6 h, 24 h, then the delivery is FAILED. The receiver URL is
re-checked before EVERY attempt and the connection only opens to an address that
passed the check (core guarded transport, ``app/services/webhook_post.py``). Repeats
``modules/lead_capture/services/delivery_service.py`` (cross-module imports are
forbidden, BL-SS-210). Bodies are Fernet-encrypted at rest; nothing here logs a
body, a secret or a URL.
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
from app.secrets import decrypt_secret, encrypt_secret
from app.services import webhook_post
from app.services.url_guard import GuardedAsyncTransport, UnparseableUrlError, UrlGuardError
from app.services.url_guard import assert_deliverable as core_assert_deliverable
from app.services.url_guard import validate_public_https_url

from ..models import (
    DELIVERY_FAILED,
    DELIVERY_PENDING,
    DELIVERY_SUCCESS,
    KIND_CONVERT,
    KIND_MODEL,
    P3Delivery,
    P3Job,
    P3Receiver,
)
from .errors import P3Error

logger = logging.getLogger(__name__)

EVENT_CANDIDATES_READY = "model.candidates_ready"
EVENT_MODEL_READY = "model.ready"
EVENT_TYPES = (EVENT_CANDIDATES_READY, EVENT_MODEL_READY)
EVENT_FOR_KIND = {KIND_MODEL: EVENT_CANDIDATES_READY, KIND_CONVERT: EVENT_MODEL_READY}
MAX_RECEIVERS = 5
RETRY_LADDER = [60, 300, 1800, 7200, 21600, 86400]
MAX_ATTEMPTS = len(RETRY_LADDER) + 1
DELIVERY_DEADLINE_SECONDS = 10
CLAIM_MARGIN_SECONDS = 60
DUE_RUN_BUDGET_SECONDS = 240
SECRET_SCHEME = "whsec_"
USER_AGENT = "Foundryx-Planner3d/1.0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── signature ───────────────────────────────────────────────────────────────

def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify(secret: str, header: str, body: bytes, *, tolerance: int = 300, now: Optional[int] = None) -> bool:
    """Receiver-side check (the CRM has its own; used by the tests)."""
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    t, v1 = parts.get("t", ""), parts.get("v1", "")
    if not t.isdigit() or not v1:
        return False
    if abs((now if now is not None else int(time.time())) - int(t)) > tolerance:
        return False
    expected = sign(secret, t, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, v1)


# ── receivers ───────────────────────────────────────────────────────────────

def _clean_events(events: List[str]) -> List[str]:
    clean = list(dict.fromkeys(e for e in events or [] if isinstance(e, str)))
    if not clean:
        raise P3Error(422, "invalid_events", "Choose at least one event.")
    unknown = [e for e in clean if e not in EVENT_TYPES]
    if unknown:
        raise P3Error(422, "invalid_events", f"Unknown event: {unknown[0]}.")
    return clean


def create_receiver(db: Session, tenant_id: str, url: str, events: List[str]) -> Tuple[P3Receiver, str]:
    """``(row, secret)``; the secret is shown ONCE."""
    try:
        clean_url = validate_public_https_url(url, strict_dns=False, subject="The URL")
    except UnparseableUrlError:
        raise P3Error(422, "invalid_url", "Enter a valid URL.") from None
    except UrlGuardError as exc:
        raise P3Error(422, "invalid_url", str(exc)) from None
    clean_events = _clean_events(events)
    if len(list_receivers(db, tenant_id)) >= MAX_RECEIVERS:
        raise P3Error(409, "receiver_limit", f"At most {MAX_RECEIVERS} receivers.")
    secret = SECRET_SCHEME + pysecrets.token_urlsafe(32)
    row = P3Receiver(
        tenant_id=tenant_id,
        url=clean_url,
        events_json=clean_events,
        secret_encrypted=encrypt_secret({"secret": secret}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, secret


def list_receivers(db: Session, tenant_id: str) -> List[P3Receiver]:
    return (
        db.query(P3Receiver)
        .filter(P3Receiver.tenant_id == tenant_id, P3Receiver.active.is_(True))
        .order_by(P3Receiver.created_at.asc(), P3Receiver.id.asc())
        .all()
    )


def delete_receiver(db: Session, tenant_id: str, receiver_id: str) -> None:
    """Soft remove (deliveries keep their history); pending deliveries stop."""
    row = (
        db.query(P3Receiver)
        .filter(P3Receiver.id == receiver_id, P3Receiver.tenant_id == tenant_id, P3Receiver.active.is_(True))
        .first()
    )
    if row is None:
        raise P3Error(404, "receiver_not_found", "This receiver does not exist.")
    row.active = False
    db.query(P3Delivery).filter(
        P3Delivery.tenant_id == tenant_id,
        P3Delivery.receiver_id == receiver_id,
        P3Delivery.status == DELIVERY_PENDING,
    ).update(
        {"status": DELIVERY_FAILED, "next_at": None, "last_error": "Receiver removed."},
        synchronize_session=False,
    )
    db.commit()


# ── queueing ────────────────────────────────────────────────────────────────

def envelope(event: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": event,
        "occurredAt": _now().isoformat().replace("+00:00", "Z"),
        "data": data,
    }


def event_data(db: Session, job: P3Job) -> Dict[str, Any]:
    from . import gateway_service

    params = job.params_json or {}
    data: Dict[str, Any] = {
        "jobId": job.id,
        "productCode": params.get("productCode"),
        "company": params.get("company"),
        "status": job.status,
        "engine": job.engine or "gpu",
        "dimensionsMm": params.get("dimensionsMm"),
        "files": gateway_service.result_files(db, job),
        "error": gateway_service.error_out(job),
    }
    if job.kind == KIND_CONVERT:
        source = (
            db.query(P3Job).filter(P3Job.tenant_id == job.tenant_id, P3Job.id == job.source_job_id).first()
            if job.source_job_id
            else None
        )
        sparams = (source.params_json or {}) if source is not None else {}
        data.update(
            sourceJobId=job.source_job_id,
            approvedCandidate=(job.params_json or {}).get("candidate"),
            productCode=sparams.get("productCode"),
            company=sparams.get("company"),
            dimensionsMm=sparams.get("dimensionsMm"),
        )
    return data


def queue_job_event(db: Session, job: P3Job) -> List[str]:
    """Queue the final-state event of a model or convert job to every receiver of its
    tenant that asked for it, then hand the deliveries to the worker. Never raises:
    a delivery problem must not undo the job's own final state."""
    event = EVENT_FOR_KIND.get(job.kind)
    if event is None:
        return []
    try:
        receivers = [r for r in list_receivers(db, job.tenant_id) if event in (r.events_json or [])]
        if not receivers:
            return []
        body = json.dumps(envelope(event, event_data(db, job)), separators=(",", ":"))
        env_id = json.loads(body)["id"]
        ids = []
        for receiver in receivers:
            row = P3Delivery(
                tenant_id=job.tenant_id,
                receiver_id=receiver.id,
                job_id=job.id,
                event_id=env_id,
                event=event,
                body_encrypted=encrypt_secret({"body": body}),
                next_at=_now(),
            )
            db.add(row)
            db.flush()
            ids.append(row.id)
        db.commit()
    except Exception:  # noqa: BLE001 - ids only in the log
        logger.exception("planner3d: could not queue the %s event for job %s", event, job.id)
        db.rollback()
        return []
    enqueue(ids)
    return ids


def enqueue(delivery_ids: List[str]) -> None:
    """Hand each delivery to the worker (eager dev runs it inline). Never raises."""
    for delivery_id in delivery_ids:
        try:
            from app.workflow_engine.worker import planner3d_deliver

            planner3d_deliver.delay(delivery_id)
        except Exception:  # noqa: BLE001 - the due tick is the backstop
            logger.exception("planner3d delivery enqueue failed for %s", delivery_id)


# ── one attempt ─────────────────────────────────────────────────────────────

def _assert_deliverable(url: str) -> None:
    core_assert_deliverable(url, subject="The URL")


def _check_address(url: str, budget: float) -> float:
    return webhook_post.check_address_within(url, budget, lambda u: _assert_deliverable(u))


def _post(url: str, *, content: bytes, headers: Dict[str, str], timeout: float) -> webhook_post.PostReply:
    """Module-level so a test can replace the outbound call."""
    return webhook_post.run_under_deadline(
        lambda: webhook_post.post_async(
            url, content, headers, timeout, lambda: GuardedAsyncTransport(subject="The URL")
        ),
        timeout,
    )


def _fail(db: Session, delivery: P3Delivery, message: str) -> None:
    delivery.status, delivery.next_at, delivery.last_error = DELIVERY_FAILED, None, message
    db.commit()


def dispatch(db: Session, delivery_id: str) -> str:
    """Run ONE attempt. Returns 'success' | 'retry' | 'dead' | 'skip'."""
    from ..gateway_auth import module_enabled

    delivery = db.query(P3Delivery).filter(P3Delivery.id == delivery_id).first()
    if delivery is None or delivery.status != DELIVERY_PENDING:
        return "skip"
    tenant_id = delivery.tenant_id
    receiver = (
        db.query(P3Receiver)
        .filter(P3Receiver.id == delivery.receiver_id, P3Receiver.tenant_id == tenant_id)
        .first()
    )
    if receiver is None or not receiver.active:
        _fail(db, delivery, "Receiver removed.")
        return "skip"
    if not module_enabled(db, tenant_id):
        _fail(db, delivery, "3D Planner is not enabled for this tenant.")
        return "skip"
    try:
        body = decrypt_secret(delivery.body_encrypted)["body"].encode("utf-8")
        secret = decrypt_secret(receiver.secret_encrypted)["secret"]
    except Exception:  # noqa: BLE001 - undecryptable: dead-letter cleanly
        _fail(db, delivery, "Stored delivery could not be decrypted.")
        return "dead"

    timestamp = str(int(_now().timestamp()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Planner3d-Event": delivery.event,
        "X-Planner3d-Delivery": delivery.id,
        "X-Planner3d-Signature": sign(secret, timestamp, body),
    }
    url = receiver.url
    # Atomic claim: the task and the due tick can reach the same row together; only
    # the one whose UPDATE matches sends. next_at is parked past this attempt's
    # deadline so a crash mid-POST is re-driven by the tick afterwards.
    now = _now()
    claimed = (
        db.query(P3Delivery)
        .filter(
            P3Delivery.id == delivery_id,
            P3Delivery.status == DELIVERY_PENDING,
            P3Delivery.attempt == delivery.attempt,
            P3Delivery.next_at <= now,
        )
        .update(
            {
                "attempt": P3Delivery.attempt + 1,
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
    delivery = db.query(P3Delivery).filter(P3Delivery.id == delivery_id).first()
    if delivery is None or delivery.status != DELIVERY_PENDING:
        return "skip"
    delivery.last_code = outcome.status_code
    delivery.last_error = outcome.error
    if outcome.ok:
        delivery.status, delivery.next_at = DELIVERY_SUCCESS, None
        receiver = (
            db.query(P3Receiver)
            .filter(P3Receiver.id == delivery.receiver_id, P3Receiver.tenant_id == tenant_id)
            .first()
        )
        if receiver is not None:
            receiver.last_success_at = _now()
        db.commit()
        return "success"
    if attempt < MAX_ATTEMPTS:
        delivery.next_at = _now() + timedelta(seconds=RETRY_LADDER[attempt - 1])
        db.commit()
        return "retry"
    delivery.status, delivery.next_at = DELIVERY_FAILED, None
    db.commit()
    return "dead"


def run_due(db: Session, limit: int = 100) -> int:
    """Re-drive PENDING deliveries whose time has come (beat tick)."""
    due = [
        r
        for (r,) in db.query(P3Delivery.id)
        .filter(P3Delivery.status == DELIVERY_PENDING, P3Delivery.next_at <= _now())
        .order_by(P3Delivery.next_at.asc())
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
            logger.exception("planner3d delivery %s failed in the due run", delivery_id)
            db.rollback()
    return attempted
