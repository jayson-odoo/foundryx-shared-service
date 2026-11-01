"""Consumer webhook delivery outbox (Slice 4, AC-01-23/24).

The inbound pipeline calls ``enqueue_event`` after it persists a message/status/
contact change. That fans the event to every ACTIVE endpoint that subscribed to
the type and covers the channel (its own, or an all-channels endpoint of the
channel's tenant and workspace), writing a durable ``webhook_deliveries`` row per endpoint
and queuing the HTTP POST. ``dispatch`` runs one attempt with an HMAC signature;
on failure it backs off, and after N dead-letters the endpoint auto-disables.

Delivery NEVER runs synchronously inside inbound processing and is fully failure-
isolated - a broken/slow consumer can't 500 or block a WhatsApp message landing
in the inbox.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Union

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import Channel, ConversationMessage, WebhookDelivery, WebhookEndpoint
from ..schemas import MessageItem
from ..security import decrypt_secret
from .webhook_service import AUTO_DISABLE_THRESHOLD, WebhookError, assert_deliverable

logger = logging.getLogger(__name__)

# Exponential backoff between attempts (seconds): ~1m, 5m, 25m, 1h, 6h.
_BACKOFF = [60, 300, 1500, 3600, 21600]
MAX_ATTEMPTS = len(_BACKOFF) + 1  # 6 total attempts before dead-letter
DELIVERY_TIMEOUT = 10.0
# Reject a timestamp older than this on the consumer side (advisory - documented).
SIGNATURE_TOLERANCE_SECONDS = 300


def _backoff_seconds(attempt: int) -> int:
    """Delay before the NEXT attempt, given how many attempts have run."""
    idx = min(attempt - 1, len(_BACKOFF) - 1)
    return _BACKOFF[max(idx, 0)]


def build_envelope(
    event_type: str,
    workspace_id: str,
    channel_id: Optional[str],
    event_id: str,
    data: Dict[str, Any],
    occurred_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """``channel_id`` is None for a workspace-level event with no channel."""
    when = occurred_at or datetime.now(timezone.utc)
    return {
        "id": event_id,
        "type": event_type,
        "workspaceId": workspace_id,
        "channelId": channel_id,
        "occurredAt": when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data": data,
    }


def sign_body(secret: str, timestamp: str, body: bytes) -> str:
    """`sha256=` HMAC over ``{timestamp}.{rawbody}`` - timestamp-bound so a
    captured body can't be replayed against a different time."""
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body,
        hashlib.sha256,
    )
    return "sha256=" + mac.hexdigest()


def _active_endpoints(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    channel_id: Optional[str],
    event_type: str,
) -> List[WebhookEndpoint]:
    """Subscribed ACTIVE endpoints for an event. With a ``channel_id``: that
    channel's own endpoints plus the all-channels ones (``channel_id`` NULL);
    with None: the all-channels ones only. Always filtered by tenant and
    workspace, which is the only boundary of an all-channels row."""
    covers = WebhookEndpoint.channel_id.is_(None)
    if channel_id is not None:
        covers = or_(WebhookEndpoint.channel_id == channel_id, covers)
    rows = (
        db.query(WebhookEndpoint)
        .filter(
            WebhookEndpoint.tenant_id == tenant_id,
            WebhookEndpoint.workspace_id == workspace_id,
            covers,
            WebhookEndpoint.status == "ACTIVE",
        )
        .all()
    )
    return [r for r in rows if event_type in (r.events_json or [])]


def consumer_message_payload(item: MessageItem, row: ConversationMessage) -> Dict[str, Any]:
    """The consumer-facing message object shared by `message.inbound` and
    `message.outbound`: media rides an ABSOLUTE, API-key-authed gateway URL
    (plan 12 AC-12-11) and uses mimeType/filename/size, distinct from the
    internal FE naming."""
    from app.config import settings

    payload = item.model_dump(mode="json")
    if row.media_key:
        payload["mediaUrl"] = f"{settings.public_base_url}/omnichannel/media/{row.id}"
        payload["mimeType"] = payload.pop("mediaMime", None)
        payload["filename"] = payload.pop("mediaFilename", None)
        payload["size"] = payload.pop("mediaSize", None)
    return payload


def _fan_out(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    channel_id: Optional[str],
    event_type: str,
    event_id: str,
    data: Union[Dict[str, Any], Callable[[], Dict[str, Any]]],
) -> int:
    """Shared body of ``enqueue_event`` / ``enqueue_workspace_event``. Creates
    durable delivery rows + queues each POST. Failure-isolated: never raises.
    ``data`` may be a callable: it runs only when at least one endpoint
    subscribes, so a scope with no subscriber pays nothing to build the payload."""
    try:
        endpoints = _active_endpoints(db, tenant_id, workspace_id, channel_id, event_type)
        if not endpoints:
            return 0
        envelope = build_envelope(
            event_type, workspace_id, channel_id, event_id, data() if callable(data) else data
        )
        delivery_ids: List[str] = []
        for ep in endpoints:
            row = WebhookDelivery(
                tenant_id=ep.tenant_id,
                endpoint_id=ep.id,
                event_id=event_id,
                event_type=event_type,
                payload_json=envelope,
                status="PENDING",
                next_attempt_at=datetime.now(timezone.utc),
            )
            db.add(row)
            db.flush()
            delivery_ids.append(row.id)
        db.commit()
    except Exception:  # noqa: BLE001 - forwarding must never break inbound
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.exception(
            "webhook enqueue failed for workspace %s channel %s (%s)",
            workspace_id, channel_id, event_type,
        )
        return 0

    # Queue the POSTs out-of-band (eager dev runs them inline).
    for delivery_id in delivery_ids:
        try:
            from ..worker import deliver_webhook

            deliver_webhook.delay(delivery_id)
        except Exception:  # noqa: BLE001
            logger.exception("webhook dispatch enqueue failed for delivery %s", delivery_id)
    return len(delivery_ids)


def enqueue_event(
    db: Session,
    channel: Channel,
    event_type: str,
    event_id: str,
    data: Union[Dict[str, Any], Callable[[], Dict[str, Any]]],
) -> int:
    """Fan an event on ``channel`` to the subscribed endpoints that cover it
    (its own and the workspace's all-channels ones). Returns the number queued,
    never raises into the inbound pipeline."""
    # plain locals: the session may need a rollback in the handler
    return _fan_out(
        db, channel.tenant_id, channel.workspace_id, channel.id, event_type, event_id, data
    )


def enqueue_workspace_event(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    event_type: str,
    event_id: str,
    data: Union[Dict[str, Any], Callable[[], Dict[str, Any]]],
) -> int:
    """Fan an event that belongs to no channel to the workspace's all-channels
    endpoints only (envelope ``channelId`` is null). Never raises."""
    return _fan_out(db, tenant_id, workspace_id, None, event_type, event_id, data)


def dispatch(db: Session, delivery_id: str) -> str:
    """Run ONE delivery attempt. Returns 'success' | 'retry' | 'dead' | 'skip'.
    Reschedules (next_attempt_at) on retry; the caller/beat re-drives due rows."""
    delivery = (
        db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
    )
    if delivery is None or delivery.status != "PENDING":
        return "skip"
    endpoint = (
        db.query(WebhookEndpoint)
        .filter(WebhookEndpoint.id == delivery.endpoint_id)
        .first()
    )
    if endpoint is None or endpoint.status != "ACTIVE":
        delivery.status = "FAILED"
        delivery.error = "Endpoint inactive."
        db.commit()
        return "skip"

    body = json.dumps(delivery.payload_json, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    try:
        secret = decrypt_secret(endpoint.secret_encrypted)
    except Exception:  # noqa: BLE001 - undecryptable secret: dead-letter cleanly
        delivery.status = "FAILED"
        delivery.error = "Signing secret could not be decrypted."
        db.commit()
        return "dead"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Foundryx-Webhooks/1.0",
        "X-Fx-Event-Id": delivery.event_id,
        "X-Fx-Event-Type": delivery.event_type,
        "X-Fx-Timestamp": timestamp,
        "X-Fx-Signature": sign_body(secret, timestamp, body),
    }

    delivery.attempt_count += 1
    delivery.last_attempt_at = datetime.now(timezone.utc)
    started = datetime.now(timezone.utc)
    ok = False
    status_code: Optional[int] = None
    error: Optional[str] = None
    try:
        # SSRF guard, re-run per attempt: the URL passed validation at
        # registration, but DNS may have been re-pointed since (and the URL is
        # externally supplied on the API-key surface). Never POST to a target
        # that resolves internally NOW.
        assert_deliverable(endpoint.url)
        resp = httpx.post(
            endpoint.url, content=body, headers=headers, timeout=DELIVERY_TIMEOUT
        )
        status_code = resp.status_code
        ok = 200 <= resp.status_code < 300
        if not ok:
            error = f"Consumer returned {resp.status_code}."
    except WebhookError as exc:
        # Blocked target - a real failure, but never a network call.
        error = f"Delivery refused: {exc}"
    except httpx.HTTPError as exc:
        error = f"Delivery failed: {exc}"

    delivery.response_status = status_code
    delivery.response_ms = int(
        (datetime.now(timezone.utc) - started).total_seconds() * 1000
    )
    delivery.error = error

    # Denormalize this attempt into the Developers → Logs console as a
    # ``webhook_delivery`` row (sprint-4/12 Slice 2, AC-DLC-16). ``webhook_deliveries``
    # stays the operational source of truth (retry queue); this is the observability
    # copy, attached to the originating trace by wamid - written via the CORE seam so
    # the console needs NO cross-schema read. Best-effort, own isolated session.
    _record_webhook_activity(db, delivery, ok=ok, status_code=status_code, error=error)

    if ok:
        delivery.status = "SUCCESS"
        delivery.next_attempt_at = None
        endpoint.consecutive_failures = 0
        endpoint.last_success_at = datetime.now(timezone.utc)
        db.commit()
        return "success"

    if delivery.attempt_count < MAX_ATTEMPTS:
        delta = _backoff_seconds(delivery.attempt_count)
        delivery.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delta)
        db.commit()
        return "retry"

    # Dead-letter: attempts preserved, endpoint failure counter bumped.
    delivery.status = "FAILED"
    delivery.next_attempt_at = None
    endpoint.consecutive_failures += 1
    if endpoint.consecutive_failures >= AUTO_DISABLE_THRESHOLD:
        endpoint.status = "AUTO_DISABLED"
        endpoint.disabled_at = datetime.now(timezone.utc)
        endpoint.disabled_reason = (
            f"Auto-disabled after {endpoint.consecutive_failures} failed deliveries."
        )
    db.commit()
    return "dead"


def _record_webhook_activity(
    db: Session,
    delivery: "WebhookDelivery",
    *,
    ok: bool,
    status_code: Optional[int],
    error: Optional[str],
) -> None:
    """Write ONE ``webhook_delivery`` activity row for this attempt, attached to
    the originating trace by the message's wamid when resolvable. Fully failure-
    isolated: runs on a FRESH session (never touches the delivery transaction)
    and swallows every error - a logging failure can NEVER break delivery."""
    try:
        from app.activity_log.service import ActivityLogService
        from app.models.integration_activity import SOURCE_WEBHOOK_DELIVERY

        data = (delivery.payload_json or {}).get("data") or {}
        # The wamid ties the receipt back to the outbound_meta leg's external_ref;
        # fall back to our durable message id, then the event id.
        external_ref = (
            data.get("externalMessageId")
            or data.get("messageId")
            or delivery.event_id
        )
        fresh = Session(bind=db.get_bind())
        try:
            svc = ActivityLogService(fresh)
            trace_id = svc.trace_for_external_ref(delivery.tenant_id, external_ref)
            svc.record(
                tenant_id=delivery.tenant_id,
                source=SOURCE_WEBHOOK_DELIVERY,
                operation=f"webhook:{delivery.event_type}",
                status="success" if ok else "error",
                trace_id=trace_id,
                status_code=status_code,
                latency_ms=delivery.response_ms,
                error_code=(str(status_code) if (status_code and not ok) else None),
                error_message=error,
                external_ref=external_ref,
                request=data,
            )
        finally:
            fresh.close()
    except Exception:  # noqa: BLE001 - logging must never break delivery.
        logger.exception("webhook activity record failed for delivery %s", delivery.id)


def run_due_deliveries(db: Session, limit: int = 100) -> int:
    """Re-drive PENDING deliveries whose backoff has elapsed (beat/backstop)."""
    now = datetime.now(timezone.utc)
    due = (
        db.query(WebhookDelivery)
        .filter(
            WebhookDelivery.status == "PENDING",
            WebhookDelivery.next_attempt_at <= now,
        )
        .order_by(WebhookDelivery.next_attempt_at.asc())
        .limit(limit)
        .all()
    )
    for row in due:
        dispatch(db, row.id)
    return len(due)
