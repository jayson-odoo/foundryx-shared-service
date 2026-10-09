"""Broadcast delivery/read receipts (plan 29 S2b, roadmap A4, D-A4-10).

`record_delivery(db, message_row)` is the ONE place a `ConversationMessage`'s
delivery-status change (SENT/DELIVERED/READ/FAILED) is fanned out to its
owning `broadcast_recipients` row (if any) - the broadcast's denormalized
counts + a realtime `broadcast.updated` publish. It is called from THREE
EXISTING seams (plan §5.5): `send_runner`'s SENT commit and `_fail()`, and
`inbound_service._handle_status`'s receipt commit - each call site wraps this
in its own `try/except Exception: logger.exception(...)` (a broadcast bug
must NEVER break a send or drop an inbound WhatsApp message).

Resolution is by `(tenant_id, broadcast_id, contact_id)` first, falling back
to `message_id` - NOT the marker's `recipientId` alone, because the very
FIRST receipt (send_runner's SENT stamp, fired from inside
`MessageService.send_message` itself) lands BEFORE `broadcast_send_service.
_process_recipient` has had a chance to write `recipient.message_id` back
onto the row. `(broadcast_id, contact_id)` is always resolvable immediately
(both are on the message/marker from the moment it is created), and
`broadcast_recipients.UNIQUE(broadcast_id, contact_id)` makes that lookup
exact. A `test-send` message (`marker.get("test")`) carries no recipient row
by design (D-A4-18) and is a deliberate no-op here.
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..models import Broadcast, BroadcastRecipient, ConversationMessage, Status
from . import realtime
from .broadcast_audience import recompute_counts

logger = logging.getLogger("foundryx.omnichannel.broadcasts")

# Delivery status (the message's own column) -> recipient state. FAILED is
# handled separately below (it can arrive at ANY point, even after SENT -
# Meta can report a post-accept failure - so it is not part of this
# forward-only ladder).
_DELIVERY_TO_RECIPIENT = {"SENT": "sent", "DELIVERED": "delivered", "READ": "read"}

# Forward-only rank (AC-BRD-37: "queued -> sent -> delivered -> read"; a late
# `sent` after `read` is ignored). `failed`/`skipped` are terminal - ranked
# above every ladder step so nothing downgrades them; an unrecognised state
# (defensive) ranks at -1 so it never blocks a legitimate first receipt.
_RECIPIENT_RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 4, "skipped": 4}


def _find_recipient(db: Session, message_row: ConversationMessage, broadcast_id: str) -> Optional[BroadcastRecipient]:
    recipient = (
        db.query(BroadcastRecipient)
        .filter(
            BroadcastRecipient.tenant_id == message_row.tenant_id,
            BroadcastRecipient.broadcast_id == broadcast_id,
            BroadcastRecipient.contact_id == message_row.contact_id,
        )
        .first()
    )
    if recipient is not None:
        return recipient
    return (
        db.query(BroadcastRecipient)
        .filter(
            BroadcastRecipient.tenant_id == message_row.tenant_id,
            BroadcastRecipient.message_id == message_row.id,
        )
        .first()
    )


def _counts_dict(b: Broadcast) -> Dict[str, int]:
    return {
        "total": b.total_count, "sent": b.sent_count, "delivered": b.delivered_count,
        "read": b.read_count, "failed": b.failed_count, "skipped": b.skipped_count,
    }


def record_delivery(db: Session, message_row: ConversationMessage) -> None:
    """Apply one delivery-status change to its broadcast recipient, if any.
    Idempotent on a duplicate/replayed receipt (a repeat of the SAME status
    is a no-op the second time, since it can never rank strictly higher than
    itself); never raises - callers still wrap this defensively, but every
    branch here is deliberately a clean early return rather than an
    assumption that could throw on a partially-consistent row."""
    marker: Optional[Dict[str, Any]] = None
    if message_row.metadata_json:
        marker = message_row.metadata_json.get("broadcast")
    if not marker or marker.get("test"):
        return
    broadcast_id = marker.get("id")
    if not broadcast_id:
        return

    recipient = _find_recipient(db, message_row, broadcast_id)
    if recipient is None:
        # The recipient row (or the whole broadcast) may have been deleted
        # since the message was sent, or this message predates the marker
        # ever being written correctly - never raise, just skip.
        return

    if recipient.message_id is None:
        recipient.message_id = message_row.id

    new_status = (message_row.delivery_status or "").upper()
    if new_status == "FAILED":
        if recipient.state == "failed":
            return  # idempotent replay
        recipient.state = "failed"
        recipient.error_code = message_row.error_code
        recipient.error_text = message_row.error_message or "The message could not be delivered."
    elif new_status in _DELIVERY_TO_RECIPIENT:
        target = _DELIVERY_TO_RECIPIENT[new_status]
        current_rank = _RECIPIENT_RANK.get(recipient.state, -1)
        target_rank = _RECIPIENT_RANK[target]
        if target_rank <= current_rank:
            return  # forward-only (AC-BRD-37) - also protects a terminal row
        recipient.state = target
    else:
        # QUEUED/SENDING (or any future status) - nothing to record yet, but
        # the message_id stamp above (if it just happened) still stands.
        db.commit()
        return

    # `recompute_counts` runs its OWN aggregate query against
    # `broadcast_recipients` - flush the pending `recipient.state` write
    # first (some sessions run `autoflush=False`, so a bare query would
    # otherwise read the row's OLD state and under-count).
    db.flush()
    broadcast = (
        db.query(Broadcast)
        .filter(Broadcast.id == broadcast_id, Broadcast.tenant_id == message_row.tenant_id)
        .first()
    )
    if broadcast is None:
        db.commit()
        return
    recompute_counts(db, broadcast)
    db.commit()
    status_key = (
        db.query(Status.key)
        .filter(Status.id == broadcast.status_id, Status.tenant_id == broadcast.tenant_id, Status.scope == "BROADCAST")
        .scalar()
    )
    realtime.publish(
        broadcast.workspace_id,
        {
            "type": "broadcast.updated",
            "broadcastId": broadcast.id,
            "status": status_key,  # a receipt never changes lifecycle status, only counts
            "counts": _counts_dict(broadcast),
        },
    )
