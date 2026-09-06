"""Broadcast send engine (plan 29 S2a, roadmap A4) - the `background_jobs`
job of type `omnichannel.broadcast_send` that turns a DRAFT/SCHEDULED
broadcast into an actual fan-out through the ONE `MessageService.send_message`
path (plan §5.4).

Snapshot -> chunk loop -> finalize, ONE code path shared by eager dev/test
(the handler loops `run_one_chunk` inline) and prod (each chunk is a SEPARATE
chained Celery task on the omnichannel `omni` queue, `worker.broadcast_chunk`,
so at most one chunk per broadcast is ever in flight - D-A4-7/AC-BRD-30).

Per-recipient idempotency (D-A4-8, AC-BRD-31): `BroadcastRepository.
claim_recipient` is the ONE atomic `UPDATE ... WHERE attempted_at IS NULL`
gate every send goes through - a job retry, a duplicate chunk-task delivery,
or a resumed job re-reads a claimed row and skips it. Never double-sends.

Cooperative cancellation (D-A4-14, AC-BRD-40): every chunk boundary re-reads
the broadcast's OWN status with a fresh scalar query (never the possibly-
stale ORM attribute) before touching a single recipient.

Receipts / the crash-window reconciler / the scheduled beat tick / test-send
are S2b (this slice deliberately stops at send + cancel).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.service import JobService
from app.models.background_job import JOB_DONE, JOB_FAILED, BackgroundJob
from app.models.status import Status as CoreStatus
from app.workflow_engine.entity_events import emit_entity_event

from ..models import (
    Broadcast,
    BroadcastRecipient,
    Channel,
    Contact,
    ConversationMessage,
    Status,
    WhatsappTemplate,
)
from ..repositories.broadcast_repository import BroadcastRepository
from ..schemas import BroadcastBindings, SendMessageRequest
from . import realtime
from .broadcast_audience import recompute_counts, snapshot_audience
from .broadcast_bindings import SkipMissingVariable
from .broadcast_bindings import resolve as resolve_bindings
from .conversation_service import ThreadNotFound
from .lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY_TYPE
from .message_service import MessageService, SendRejected
from .send_runner import TransientSendError, run_send

logger = logging.getLogger("foundryx.omnichannel.broadcasts")

SEND_JOB_TYPE = "omnichannel.broadcast_send"
CHUNK_SIZE = 100


class PreflightFailed(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ── pure helpers (unit-testable without a DB) ───────────────────────────────
def compute_chunk_pacing(count: int, rate_per_second: float, elapsed_seconds: float = 0.0) -> float:
    """Seconds to wait BEFORE the next chunk given this chunk dispatched
    `count` messages at `rate_per_second` (D-A4-12, AC-BRD-35). Pacing is
    CHUNK-granular, not per-message: within a chunk sends run back-to-back,
    and the wait sits between chunks so `chunk_size / rate_per_second`
    messages-per-second holds over the whole run. A pure function - asserted
    directly by a test that measures the computed delay, never by sleeping."""
    if rate_per_second <= 0:
        return 0.0
    return max(0.0, (count / rate_per_second) - max(0.0, elapsed_seconds))


def rate_for_channel(channel: Optional[Channel]) -> float:
    if channel is not None and channel.broadcast_rate_per_second:
        return float(channel.broadcast_rate_per_second)
    return float(settings.omnichannel_broadcast_rate_per_second)


# ── small DB helpers ─────────────────────────────────────────────────────────
def channel_or_none(db: Session, broadcast: Broadcast) -> Optional[Channel]:
    return (
        db.query(Channel)
        .filter(Channel.id == broadcast.channel_id, Channel.tenant_id == broadcast.tenant_id)
        .first()
    )


def _status_key_to_id(db: Session, tenant_id: str) -> Dict[str, str]:
    rows = db.query(Status).filter(Status.tenant_id == tenant_id, Status.scope == "BROADCAST").all()
    return {r.key: r.id for r in rows}


def _current_status_key(db: Session, broadcast: Broadcast) -> Optional[str]:
    """Fresh scalar read of the broadcast's CURRENT status - never the
    possibly-stale ORM attribute on an object another session may have
    mutated (D-A4-14's cooperative-cancel guard)."""
    status_id = (
        db.query(Broadcast.status_id)
        .filter(Broadcast.id == broadcast.id, Broadcast.tenant_id == broadcast.tenant_id)
        .scalar()
    )
    if status_id is None:
        return None
    row = (
        db.query(Status.key)
        .filter(Status.id == status_id, Status.tenant_id == broadcast.tenant_id, Status.scope == "BROADCAST")
        .first()
    )
    return row[0] if row else None


def _counts_dict(b: Broadcast) -> Dict[str, int]:
    return {
        "total": b.total_count, "sent": b.sent_count, "delivered": b.delivered_count,
        "read": b.read_count, "failed": b.failed_count, "skipped": b.skipped_count,
    }


def _result_dict(b: Broadcast, *, cancelled: bool) -> Dict[str, Any]:
    return {
        "total": b.total_count, "sent": b.sent_count, "failed": b.failed_count,
        "skipped": b.skipped_count, "cancelled": cancelled,
    }


def _publish(broadcast: Broadcast, status_key: Optional[str]) -> None:
    realtime.publish(
        broadcast.workspace_id,
        {
            "type": "broadcast.updated",
            "broadcastId": broadcast.id,
            "status": status_key,
            "counts": _counts_dict(broadcast),
        },
    )


def _resolve_actor(db: Session, tenant_id: str, created_by_user_id: Optional[str]) -> Optional[str]:
    """AC-BRD-32: the actor is `createdByUserId` resolved TENANT-SCOPED at USE
    time (the polymorphic stored-id rule) - a deleted or foreign user resolves
    to no actor, never to another tenant's user."""
    if not created_by_user_id:
        return None
    from app.models.user import User

    row = (
        db.query(User.id).filter(User.id == created_by_user_id, User.tenant_id == tenant_id).first()
    )
    return row[0] if row else None


def _lifecycle_labels(db: Session, contacts: List[Contact], tenant_id: str, workspace_id: str) -> Dict[str, str]:
    """Batched `status_id -> label` for the lifecycle contact-field binding
    (mirrors `contact_export_service._lifecycle_labels`) - every contact in
    ONE broadcast's audience shares the same workspace, so a bare status-id
    key (scope-checked against THIS workspace) is unambiguous."""
    status_ids = {c.lifecycle_status_id for c in contacts if c.lifecycle_status_id}
    if not status_ids:
        return {}
    rows = (
        db.query(CoreStatus)
        .filter(
            CoreStatus.id.in_(status_ids),
            CoreStatus.tenant_id == tenant_id,
            CoreStatus.entity_type == LIFECYCLE_ENTITY_TYPE,
            CoreStatus.scope_id == workspace_id,
        )
        .all()
    )
    return {s.id: s.label for s in rows}


def _preflight(db: Session, broadcast: Broadcast) -> None:
    """Plan §5.4 step 1: the channel must still be ACTIVE and the template
    still APPROVED at the moment the job actually runs (both may have changed
    since the broadcast was saved or scheduled)."""
    channel = (
        db.query(Channel)
        .filter(
            Channel.id == broadcast.channel_id,
            Channel.tenant_id == broadcast.tenant_id,
            Channel.is_active.is_(True),
            Channel.is_trashed.is_(False),
        )
        .first()
    )
    if channel is None:
        raise PreflightFailed("The channel is no longer active.")
    template = (
        db.query(WhatsappTemplate)
        .filter(
            WhatsappTemplate.id == broadcast.template_id,
            WhatsappTemplate.tenant_id == broadcast.tenant_id,
            WhatsappTemplate.status == "APPROVED",
        )
        .first()
    )
    if template is None:
        raise PreflightFailed("The template is no longer approved.")


def _fail_broadcast(db: Session, broadcast: Broadcast, message: str) -> None:
    key_to_id = _status_key_to_id(db, broadcast.tenant_id)
    broadcast.status_id = key_to_id["FAILED"]
    broadcast.error = message
    broadcast.finished_at = datetime.now(timezone.utc)
    db.flush()
    emit_entity_event(db, "omnichannel_broadcast", "updated", broadcast, tenant_id=broadcast.tenant_id)
    emit_entity_event(
        db, "omnichannel_broadcast", "completed", broadcast, tenant_id=broadcast.tenant_id,
        extra={"status": "FAILED", "counts": _counts_dict(broadcast), "error": message},
    )
    db.commit()
    _publish(broadcast, "FAILED")


def _process_recipient(
    db: Session,
    repo: BroadcastRepository,
    broadcast: Broadcast,
    recipient_id: str,
    bindings: BroadcastBindings,
    lifecycle_labels: Dict[str, str],
    actor_user_id: Optional[str],
) -> str:
    """Claim -> resolve bindings -> send -> record outcome for ONE recipient.
    NEVER raises (AC-BRD-36: one failed recipient never aborts the run, never
    rolls back another). Returns one of `sent|failed|skipped|queued|claimed`
    (`claimed` = another pass already owns this row - not tallied again)."""
    if not repo.claim_recipient(broadcast.tenant_id, recipient_id):
        return "claimed"
    recipient = repo.get_recipient(broadcast.tenant_id, recipient_id)
    if recipient is None:
        return "claimed"

    contact = (
        db.query(Contact)
        .filter(Contact.id == recipient.contact_id, Contact.tenant_id == broadcast.tenant_id)
        .first()
    )
    if contact is None:
        recipient.state = "failed"
        recipient.error_code = "contact_missing"
        recipient.error_text = "The contact no longer exists."
        db.commit()
        return "failed"

    try:
        values = resolve_bindings(
            bindings, contact, lifecycle_label=lifecycle_labels.get(contact.lifecycle_status_id or "")
        )
    except SkipMissingVariable:
        recipient.state = "skipped"
        recipient.skip_reason = "missing_variable"
        db.commit()
        return "skipped"

    req = SendMessageRequest(
        messageType="TEMPLATE",
        templateId=broadcast.template_id,
        templateHeaderVariables=values["header"],
        templateVariables=values["body"],
        templateButtonVariables=values["buttons"],
    )
    try:
        item = MessageService(db).send_message(
            contact.id, broadcast.tenant_id, actor_user_id, req,
            channel_id_override=broadcast.channel_id,
            metadata_extra={"broadcast": {"id": broadcast.id, "recipientId": recipient.id}},
        )
    except (SendRejected, ThreadNotFound) as exc:
        db.rollback()
        recipient = repo.get_recipient(broadcast.tenant_id, recipient_id)
        recipient.state = "failed"
        recipient.error_code = "send_rejected"
        recipient.error_text = str(exc)
        db.commit()
        return "failed"
    except Exception as exc:  # noqa: BLE001 - a bad recipient never aborts the run
        logger.exception("broadcast %s recipient %s send crashed", broadcast.id, recipient_id)
        db.rollback()
        recipient = repo.get_recipient(broadcast.tenant_id, recipient_id)
        recipient.state = "failed"
        recipient.error_code = "unexpected_error"
        recipient.error_text = str(exc)[:500]
        db.commit()
        return "failed"

    final_status = item.deliveryStatus
    message_id = item.id
    # ONE bounded retry for a SYNCHRONOUS transient failure - the only mode
    # where `send_message` can return with the row left QUEUED after
    # `run_send` caught `TransientSendError` internally (eager dev/tests).
    # Never retried again after this within the SAME run (D-A4-8); a
    # still-ambiguous outcome across job retries is S2b's reconciler
    # (`send_result_unknown`, F6).
    if final_status == "QUEUED" and settings.celery_task_always_eager:
        try:
            run_send(db, message_id)
        except TransientSendError:
            pass
        row = db.query(ConversationMessage).filter(ConversationMessage.id == message_id).first()
        if row is not None:
            final_status = row.delivery_status

    recipient = repo.get_recipient(broadcast.tenant_id, recipient_id)
    recipient.message_id = message_id
    if final_status == "FAILED":
        row = db.query(ConversationMessage).filter(ConversationMessage.id == message_id).first()
        recipient.state = "failed"
        recipient.error_code = "send_failed"
        recipient.error_text = (row.error_message if row is not None else None) or "The message could not be sent."
        db.commit()
        return "failed"
    if final_status == "QUEUED":
        # Still pending (normal async dispatch in prod, or an unresolved
        # transient blip) - stays `queued` (claimed via attempted_at) so the
        # message's own retry path / S2b's receipt hooks / reconciler move it
        # forward. Never re-attempted again within THIS job.
        db.commit()
        return "queued"
    recipient.state = "sent"
    db.commit()
    return "sent"


def run_one_chunk(
    db: Session, broadcast: Broadcast, job: BackgroundJob, *, chunk_size: int = CHUNK_SIZE
) -> bool:
    """Process ONE bounded chunk of `queued` recipients (AC-BRD-30 - the SAME
    function eager dev loops inline, prod chains via `worker.broadcast_chunk`).
    Returns True while more dispatchable recipients remain."""
    repo = BroadcastRepository(db)

    current_status = _current_status_key(db, broadcast)
    if current_status == "CANCELLED":
        repo.skip_remaining_queued(broadcast.tenant_id, broadcast.id, reason="cancelled")
        db.refresh(broadcast)
        recompute_counts(db, broadcast)
        db.commit()
        _publish(broadcast, "CANCELLED")
        return False

    ids = repo.queued_recipient_ids(broadcast.tenant_id, broadcast.id, limit=chunk_size)
    if not ids:
        return False

    db.refresh(broadcast)
    bindings = BroadcastBindings.model_validate(
        broadcast.bindings_json or {"header": [], "body": [], "buttons": []}
    )
    actor_user_id = _resolve_actor(db, broadcast.tenant_id, broadcast.created_by_user_id)

    contacts = (
        db.query(Contact)
        .join(BroadcastRecipient, Contact.id == BroadcastRecipient.contact_id)
        .filter(BroadcastRecipient.id.in_(ids))
        .all()
    )
    lifecycle_labels = _lifecycle_labels(db, contacts, broadcast.tenant_id, broadcast.workspace_id)

    processed = 0
    send_failed = 0
    for recipient_id in ids:
        outcome = _process_recipient(
            db, repo, broadcast, recipient_id, bindings, lifecycle_labels, actor_user_id
        )
        if outcome == "claimed":
            continue
        processed += 1
        if outcome == "failed":
            send_failed += 1

    db.refresh(broadcast)
    recompute_counts(db, broadcast)
    db.commit()
    if processed:
        JobService(db).advance(job, done=processed, failed=send_failed)
    _publish(broadcast, current_status)
    return repo.has_dispatchable_recipients(broadcast.tenant_id, broadcast.id)


def finalize_broadcast(db: Session, broadcast: Broadcast, job: BackgroundJob) -> None:
    """Plan §5.4 step 4 (send + cancel half - reconcile() is S2b). Every
    recipient has reached a terminal-for-dispatch state (or the broadcast was
    cancelled mid-run, already handled at the last chunk boundary) - flip the
    broadcast to its final state, emit the completion event, finish the job."""
    db.refresh(broadcast)
    recompute_counts(db, broadcast)
    current_status = _current_status_key(db, broadcast)
    if current_status == "CANCELLED":
        db.commit()
        JobService(db).finish(job, status=JOB_DONE, result=_result_dict(broadcast, cancelled=True))
        _publish(broadcast, "CANCELLED")
        return

    key_to_id = _status_key_to_id(db, broadcast.tenant_id)
    broadcast.status_id = key_to_id["SENT"]
    broadcast.finished_at = datetime.now(timezone.utc)
    db.flush()
    emit_entity_event(db, "omnichannel_broadcast", "updated", broadcast, tenant_id=broadcast.tenant_id)
    emit_entity_event(
        db, "omnichannel_broadcast", "completed", broadcast, tenant_id=broadcast.tenant_id,
        extra={"status": "SENT", "counts": _counts_dict(broadcast)},
    )
    db.commit()
    JobService(db).finish(job, status=JOB_DONE, result=_result_dict(broadcast, cancelled=False))
    _publish(broadcast, "SENT")


def run_broadcast_send(db: Session, job: BackgroundJob) -> None:
    """`omnichannel.broadcast_send` job handler (plan §5.4) - registered via
    `register_job_handler` (no bespoke job table, AC-BRD-50)."""
    tenant_id = job.tenant_id
    payload = job.payload_json or {}
    broadcast_id = payload.get("broadcastId")
    broadcast = (
        db.query(Broadcast)
        .filter(Broadcast.id == broadcast_id, Broadcast.tenant_id == tenant_id)
        .first()
    )
    if broadcast is None:
        JobService(db).finish(job, status=JOB_FAILED, error="Broadcast not found.")
        return

    status_key = _current_status_key(db, broadcast)
    if status_key != "SENDING":
        # Idempotent re-entry (plan §5.4 step 0): a resumed/duplicated job on
        # an already-terminal or cancelled broadcast is a clean no-op.
        JobService(db).finish(job, status=JOB_DONE, result={"note": "not sending", "status": status_key})
        return

    try:
        _preflight(db, broadcast)
    except PreflightFailed as exc:
        _fail_broadcast(db, broadcast, exc.message)
        JobService(db).finish(job, status=JOB_FAILED, error=exc.message)
        return

    repo = BroadcastRepository(db)
    if repo.recipient_count(tenant_id, broadcast.id) == 0:
        snapshot_audience(db, broadcast)
        db.commit()
    db.refresh(broadcast)
    JobService(db).set_total(job, broadcast.total_count)

    if settings.celery_task_always_eager:
        while run_one_chunk(db, broadcast, job):
            pass
        finalize_broadcast(db, broadcast, job)
        return

    more = run_one_chunk(db, broadcast, job)
    if more:
        from ..worker import broadcast_chunk

        delay = compute_chunk_pacing(CHUNK_SIZE, rate_for_channel(channel_or_none(db, broadcast)))
        broadcast_chunk.apply_async((job.id,), countdown=max(1, int(delay)) if delay else 1)
    else:
        finalize_broadcast(db, broadcast, job)


_HANDLER_DEF = JobHandlerDef(SEND_JOB_TYPE, run_broadcast_send, "Broadcast send")


def register_broadcast_send_handler() -> None:
    """Idempotent boot registration (mirrors the contacts-export handler)."""
    register_job_handler(_HANDLER_DEF)
