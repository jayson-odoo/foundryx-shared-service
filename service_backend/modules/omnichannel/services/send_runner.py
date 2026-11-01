"""Async outbound send executor (plan 12 §Locked D-Q10, AC-12-03/04).

``run_send(db, message_id)`` is the ONE path every outbound message takes after
the endpoint has created its ``QUEUED`` row: resolve channel + creds → (media)
transcode/upload-by-id → ``adapter.send`` → stamp ``SENT``/``FAILED`` +
``external_message_id`` → publish a WS ``message.status`` event.

The Celery task (``worker.omnichannel_send_message``) calls this on a fresh
session in prod; in eager dev/tests ``MessageService`` calls it INLINE on the
request session (a worker would open a different DB session and not see the
in-request row - the workflow-engine eager pattern).
"""
import logging
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from ..adapters.base import SendError
from ..adapters.whatsapp_cloud import get_adapter
from ..models import MEDIA_MESSAGE_TYPES, Channel, ConversationMessage
from ..repositories.contact_repository import ContactRepository
from ..security import decrypt_credentials
from . import realtime
from .channel_addressing import NoChannelIdentity, recipient_ref, sender_ref
from .media_pipeline import MediaRejected, transcode_voice

logger = logging.getLogger(__name__)

WORKFLOW_TEST_METADATA_KEY = "workflowTest"
SANDBOX_ONLY_KEY = "sandboxOnly"
SANDBOX_CREDENTIALS_ERROR = (
    "Sandbox-only workflow test blocked because the channel is no longer in dev mode."
)
SANDBOX_CHANNEL_ERROR = (
    "Sandbox-only workflow test blocked because the channel is no longer active."
)


def _read_media(db: Session, tenant_id: str, media_key: str) -> bytes:
    """Read a stored media blob back by key (local path or remote URL)."""
    from app.services.storage import (
        StorageReadError,
        UnresolvableKey,
        read_object,
        storage_for_tenant,
    )

    # Errors carry the status only: the address is never part of the text.
    try:
        return read_object(storage_for_tenant(db, tenant_id), media_key, timeout=15.0)
    except StorageReadError as exc:
        if isinstance(exc.__cause__, UnresolvableKey):
            raise exc.__cause__ from None
        if exc.status is not None:
            raise OSError(f"Media read failed with status {exc.status}") from None
        if isinstance(exc.__cause__, httpx.HTTPError):
            raise OSError(f"Media read failed ({type(exc.__cause__).__name__})") from None
        raise OSError("Stored media could not be read") from None
    except OSError:
        raise OSError("Stored media could not be read") from None


def _emit_status_webhook(
    db: Session, row: ConversationMessage, outcome: Optional[str] = None
) -> None:
    """Consumer `message.status` for the sender-side SENT / FAILED outcome (plan
    38 AC-38-09/10): one event per status (`<id>:<STATUS>`), same data shape as
    the receipt path. Sandbox rows skip. Failure-isolated; the row is already
    committed so a rollback here loses nothing."""
    row_id = row.id  # plain local: the session may need a rollback in the handler
    try:
        if ((row.metadata_json or {}).get(WORKFLOW_TEST_METADATA_KEY) or {}).get(SANDBOX_ONLY_KEY) is True:
            return
        from .webhook_delivery import enqueue_event

        channel = (
            db.query(Channel)
            .filter(Channel.id == row.channel_id, Channel.tenant_id == row.tenant_id)
            .first()
        )
        if channel is None:
            return
        outcome = outcome or row.delivery_status
        failed = outcome == "FAILED"
        # `outcome` is what this sender reached; the row may already have moved
        # on (a receipt can land between the commit and this call).
        enqueue_event(
            db,
            channel,
            "message.status",
            f"{row.id}:{outcome}",
            lambda: {
                "messageId": row.id,
                "externalMessageId": row.external_message_id,
                "contactId": row.contact_id,
                "deliveryStatus": outcome,
                # Error fields ride FAILED only (AC-38-15).
                "errorCode": row.error_code if failed else None,
                "errorMessage": row.error_message if failed else None,
            },
        )
    except Exception:  # noqa: BLE001 - a webhook bug must never break a send
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.exception("message.status webhook failed for message %s", row_id)


def _publish_status(db: Session, row: ConversationMessage) -> None:
    """Realtime `message.status`; a failure is logged and never stops the send
    path (a database error also rolls the session back so it stays usable)."""
    row_id = row.id  # plain local: the session may need a rollback in the handler
    try:
        contact = ContactRepository(db).get_by_id(row.contact_id, row.tenant_id)
        if contact is None:
            return
        realtime.publish(
            contact.workspace_id,
            {
                "type": "message.status",
                "messageId": row.id,
                "contactId": row.contact_id,
                "deliveryStatus": row.delivery_status,
                "externalMessageId": row.external_message_id,
                "errorMessage": row.error_message,
            },
        )
    except Exception:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.exception("realtime status publish failed for message %s", row_id)


class TransientSendError(Exception):
    """A retryable send failure (network/5xx/storage blip). The Celery task
    re-raises this so ``autoretry_for`` applies bounded backoff; eager dev leaves
    the row QUEUED for a later manual retry (dev uses the stub adapter - no
    transient failures). ``code`` is the provider's error code when it gave one."""

    def __init__(self, message: str = "", *, code: Optional[str] = None):
        super().__init__(message)
        self.code = code


def _record_broadcast_receipt(db: Session, row: ConversationMessage) -> None:
    """Plan 29 S2b (D-A4-10) - a lazily-imported, fully failure-isolated hook
    into `broadcast_receipts.record_delivery`. A broadcast bug must NEVER
    break an outbound send; called AFTER the row's own commit. A failure rolls
    the session back so the following steps still work."""
    row_id = row.id  # plain local: the session may need a rollback in the handler
    try:
        from .broadcast_receipts import record_delivery

        record_delivery(db, row)
    except Exception:  # noqa: BLE001 - never let a broadcast bug break a send
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.exception("broadcast receipt hook failed for message %s", row_id)


ERROR_MESSAGE_CAP = 300
TRANSIENT_ERROR_TEXT = "Temporary send failure, retrying"


def _fail(db: Session, row: ConversationMessage, message: str, code: Optional[str] = None) -> str:
    row.delivery_status = "FAILED"
    # Capped on the row itself so GET agrees with the consumer event (AC-38-16).
    row.error_message = (message or "")[:ERROR_MESSAGE_CAP] or None
    row.error_code = str(code) if code else None
    db.commit()
    _record_broadcast_receipt(db, row)
    _publish_status(db, row)
    _emit_status_webhook(db, row, "FAILED")
    return "FAILED"


def _requeue_transient(
    db: Session, row: ConversationMessage, message: str, code: Optional[str] = None
) -> None:
    """Reset a claimed row to QUEUED so a retry re-sends (the send did NOT reach
    the contact), then raise for backoff. Only reached BEFORE ``adapter.send``
    returns. The provider's code is kept so the last one survives to the final
    outcome if retries run out."""
    # Log the detail, store only generic text (AC-38-14).
    logger.warning("transient send failure for message %s: %s", row.id, message)
    row.delivery_status = "QUEUED"
    row.error_message = TRANSIENT_ERROR_TEXT
    row.error_code = str(code) if code else None
    db.commit()
    raise TransientSendError(message, code=str(code) if code else None)


UNEXPECTED_ERROR_TEXT = "The message could not be sent"


def fail_unfinished(db: Session, message_id: str, reason: str) -> str:
    """Move a row that is still QUEUED or SENDING to FAILED with generic text
    (one `FAILED` status event). Used when retries run out and when an
    unexpected error stops a send after the claim. The transition is a guarded
    UPDATE, so a row that already reached another outcome (or that a concurrent
    attempt finished) is never overwritten or announced twice."""
    row = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.id == message_id)
        .first()
    )
    if row is None:
        return "MISSING"
    claimed = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.id == message_id,
            ConversationMessage.tenant_id == row.tenant_id,
            ConversationMessage.delivery_status.in_(("QUEUED", "SENDING")),
        )
        .update({"delivery_status": "FAILED"}, synchronize_session=False)
    )
    if not claimed:
        db.rollback()
        db.refresh(row)
        return row.delivery_status or "MISSING"
    db.refresh(row)
    logger.warning("send for message %s ended without an outcome: %s", message_id, reason)
    return _fail(db, row, UNEXPECTED_ERROR_TEXT, code=row.error_code)


def run_send(db: Session, message_id: str, trace_id: Optional[str] = None) -> str:
    """Execute a QUEUED outbound row; any unexpected error after the row is
    claimed but before the provider accepted the message ends it FAILED
    (generic text, real error logged) rather than leaving it SENDING. Once the
    provider has accepted the message the row is never failed: its success is
    recorded instead. A retryable failure still raises ``TransientSendError``."""
    progress: dict = {}
    try:
        return _run_send(db, message_id, trace_id, progress)
    except TransientSendError:
        raise
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("unexpected error sending message %s", message_id)
        if progress.get("accepted"):
            return _record_sent_by_id(db, message_id, progress.get("external_id"))
        try:
            db.rollback()
            row = (
                db.query(ConversationMessage)
                .filter(ConversationMessage.id == message_id)
                .first()
            )
            if row is not None and row.delivery_status == "SENDING":
                return fail_unfinished(db, message_id, "unexpected error")
        except Exception:  # noqa: BLE001
            logger.exception("could not record the failure of message %s", message_id)
        raise


def _record_sent_by_id(db: Session, message_id: str, external_id: Optional[str]) -> str:
    """Move a row the provider accepted to SENT with its external id, through a
    guarded UPDATE (only from QUEUED or SENDING), then announce it once. If this
    fails too the row is left as it is and the ids are logged: the message
    reached the contact, so it is never marked FAILED and never re-sent."""
    try:
        db.rollback()
        probe = (
            db.query(ConversationMessage.tenant_id)
            .filter(ConversationMessage.id == message_id)
            .first()
        )
        if probe is None:
            return "MISSING"
        claimed = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.id == message_id,
                ConversationMessage.tenant_id == probe[0],
                ConversationMessage.delivery_status.in_(("QUEUED", "SENDING")),
            )
            .update(
                {
                    "delivery_status": "SENT",
                    "external_message_id": external_id,
                    "error_message": None,
                    "error_code": None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        row = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.id == message_id)
            .first()
        )
        if row is None:
            return "MISSING"
        if not claimed:
            return row.delivery_status or "SENT"
        _record_broadcast_receipt(db, row)
        _publish_status(db, row)
        _emit_status_webhook(db, row, "SENT")
        return "SENT"
    except Exception:  # noqa: BLE001
        logger.exception(
            "could not record the accepted send of message %s (external id %s)",
            message_id,
            external_id,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return "SENDING"


def _run_send(
    db: Session, message_id: str, trace_id: Optional[str] = None, progress: Optional[dict] = None
) -> str:
    """Execute a QUEUED outbound row. Returns the final delivery status.

    IDEMPOTENT double-send guard (plan 12 review): the row is CLAIMED (QUEUED →
    SENDING, committed) BEFORE ``adapter.send`` touches Meta. A row not in QUEUED
    is a no-op, so a retry never re-calls ``adapter.send`` (the contact can't get
    it twice). If recording the success fails, the row is moved to SENT by a
    guarded update instead (see ``_record_sent_by_id``). A transient failure (network/5xx/storage) raises ``TransientSendError``
    for backoff; a permanent Meta rejection / transcode error stamps FAILED.

    ``trace_id`` (sprint-4/12 Slice 2) carries the inbound gateway request's
    correlation id when the send crossed the Celery boundary (the worker's
    contextvar is None by default). We re-seed it here so the ``outbound_meta``
    activity row lands on the SAME trace as the inbound leg (AC-DLC-15). In eager
    dev/tests the contextvar is already set on the request context - passing None
    leaves it untouched."""
    if trace_id is not None:
        from app.activity_log.context import set_trace_id

        set_trace_id(trace_id)
    row = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.id == message_id)
        .first()
    )
    if row is None:
        return "MISSING"
    if row.delivery_status not in (None, "QUEUED"):
        # Already claimed/sent/failed - never re-send (double-dispatch guard).
        return row.delivery_status

    channel = (
        db.query(Channel)
        .filter(Channel.id == row.channel_id, Channel.tenant_id == row.tenant_id)
        .first()
    )
    contact = ContactRepository(db).get_by_id(row.contact_id, row.tenant_id)
    if channel is None or contact is None:
        return _fail(db, row, "No active channel for this thread.")

    meta = row.metadata_json or {}
    sandbox_only = (
        (meta.get(WORKFLOW_TEST_METADATA_KEY) or {}).get(SANDBOX_ONLY_KEY) is True
    )
    sandbox_credentials = None
    if sandbox_only:
        try:
            sandbox_credentials = decrypt_credentials(channel.credentials_json)
        except Exception:  # noqa: BLE001 - malformed/rotated secrets fail closed
            return _fail(db, row, SANDBOX_CREDENTIALS_ERROR)
        if sandbox_credentials.get("dev") is not True:
            return _fail(db, row, SANDBOX_CREDENTIALS_ERROR)

    # CLAIM before touching Meta. If this commit fails the row stays QUEUED and a
    # retry safely re-claims (no send happened yet).
    row.delivery_status = "SENDING"
    db.commit()

    if sandbox_only:
        # Re-read lifecycle state after claiming the row.  A sandbox test can
        # sit queued while an operator deactivates or disconnects its channel;
        # never dispatch such a row, even if the earlier validation saw dev
        # credentials.  Normal sends intentionally retain their existing path.
        channel = (
            db.query(Channel)
            .populate_existing()
            .filter(
                Channel.id == row.channel_id,
                Channel.tenant_id == row.tenant_id,
                Channel.is_active.is_(True),
                Channel.is_trashed.is_(False),
            )
            .first()
        )
        if channel is None:
            return _fail(db, row, SANDBOX_CHANNEL_ERROR)

    # For sandbox rows, keep the credentials snapshot validated above. Even if
    # the DB row changes immediately afterward, this dispatch can only use the
    # already-validated dev adapter credentials.
    credentials = sandbox_credentials or decrypt_credentials(channel.credentials_json)
    # Instrument the outbound Meta call - an ``outbound_meta`` activity row lands
    # on the inbound trace (gateway sends) or standalone (internal inbox sends).
    from .activity import build_meta_recorder

    adapter = get_adapter(
        channel.channel_type,
        recorder=build_meta_recorder(db, channel.tenant_id, channel.workspace_id),
    )
    # Addressing (plan 32 / A7a, AC-CHN-26): ONE helper resolves both parties -
    # WhatsApp keeps digits(contact.phone) from channel.phone_number_id
    # byte-identical to before this slice; Messenger/Instagram address the
    # contact's OWN identity on THIS channel. A contact with no identity on
    # the chosen channel fails the send cleanly rather than addressing empty.
    phone_id = sender_ref(channel)
    try:
        to = recipient_ref(db, channel, contact)
    except NoChannelIdentity as exc:
        return _fail(db, row, str(exc))
    context_id: Optional[str] = meta.get("context_external_id")
    # The Meta send parameters `messaging_policy.authorize` resolved AT
    # ENQUEUE (D-A7-8) - used VERBATIM, never re-derived here. `None` for
    # WhatsApp (its re-engagement mode is "template", not a Meta send param).
    meta_send = meta.get("metaSend") or {}
    messaging_type: Optional[str] = meta_send.get("messagingType")
    send_tag: Optional[str] = meta_send.get("tag")

    try:
        if row.message_type == "TEMPLATE":
            template = (row.payload_json or {}).get("template") or {}
            # A media header rides row.media_key → upload it + inject the id into
            # the built HEADER component before sending (upload-by-id contract).
            if template.get("headerMedia") and row.media_key:
                from .template_send import inject_header_media_id

                content = _read_media(db, row.tenant_id, row.media_key)
                media_id = adapter.upload_media(
                    credentials, phone_id, content, row.media_mime or "application/octet-stream"
                )
                inject_header_media_id(template, media_id)
            result = adapter.send(
                credentials, phone_id, to, template=template, context_message_id=context_id,
                messaging_type=messaging_type, tag=send_tag,
            )
        elif row.message_type in MEDIA_MESSAGE_TYPES:
            content = _read_media(db, row.tenant_id, row.media_key)
            mime = row.media_mime or "application/octet-stream"
            if row.message_type == "VOICE":
                content = transcode_voice(content)  # webm/opus → ogg/opus
                mime = "audio/ogg"
                # The stored blob is now ogg - keep media_key/mime consistent so
                # agent playback + the media endpoint serve the correct type.
                from app.services.storage import storage_for_tenant

                row.media_key = storage_for_tenant(db, row.tenant_id).save(
                    f"omnichannel/{row.tenant_id}/voice", content, mime
                )
                row.media_mime = mime
            media_id = adapter.upload_media(credentials, phone_id, content, mime)
            result = adapter.send(
                credentials,
                phone_id,
                to,
                media={
                    "kind": row.message_type.lower(),
                    "id": media_id,
                    "caption": row.body,
                    "filename": row.media_filename,
                },
                context_message_id=context_id,
                messaging_type=messaging_type, tag=send_tag,
            )
        elif row.message_type == "INTERACTIVE":
            from .structured import build_meta_interactive, header_media_kind

            defn = row.payload_json or {}
            media_id = None
            # A media header rides row.media_key → upload it + inject the id.
            if header_media_kind(defn) and row.media_key:
                content = _read_media(db, row.tenant_id, row.media_key)
                media_id = adapter.upload_media(
                    credentials, phone_id, content, row.media_mime or "application/octet-stream"
                )
            # `interactive` is the pre-built WhatsApp-native object (WhatsApp
            # reads it); `structured` is the SAME defn raw (Messenger/
            # Instagram build Meta quick replies from it, D-A7-13) - passing
            # both keeps this call type-blind (no `channel_type` branch here).
            interactive = build_meta_interactive(defn, media_id=media_id)
            result = adapter.send(
                credentials, phone_id, to,
                interactive=interactive, structured=defn, context_message_id=context_id,
                messaging_type=messaging_type, tag=send_tag,
            )
        elif row.message_type == "LOCATION":
            from .structured import build_meta_location

            result = adapter.send(
                credentials,
                phone_id,
                to,
                location=build_meta_location(row.payload_json or {}),
                context_message_id=context_id,
                messaging_type=messaging_type, tag=send_tag,
            )
        elif row.message_type == "CONTACTS":
            result = adapter.send(
                credentials,
                phone_id,
                to,
                contacts=(row.payload_json or {}).get("contacts") or [],
                context_message_id=context_id,
                messaging_type=messaging_type, tag=send_tag,
            )
        else:  # TEXT (and any free-form fallback)
            result = adapter.send(
                credentials, phone_id, to, text=row.body, context_message_id=context_id,
                messaging_type=messaging_type, tag=send_tag,
            )
    except MediaRejected as exc:
        # Sniff/cap/transcode failure - permanent.
        return _fail(db, row, exc.message)
    except SendError as exc:
        if getattr(exc, "transient", False):
            _requeue_transient(db, row, str(exc), code=getattr(exc, "code", None))
        return _fail(db, row, str(exc), code=getattr(exc, "code", None))
    except (httpx.HTTPError, OSError) as exc:
        # Transport / stored-media read blip - retryable with backoff.
        _requeue_transient(db, row, str(exc))

    external_id = result.get("external_message_id")
    # From here the provider has the message: the fail path must never run.
    if progress is not None:
        progress["accepted"] = True
        progress["external_id"] = external_id
    row.external_message_id = external_id
    row.delivery_status = "SENT"
    row.error_message = None  # clear any earlier transient-failure text
    row.error_code = None
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("recording the SENT outcome of message %s failed", message_id)
        return _record_sent_by_id(db, message_id, external_id)
    _record_broadcast_receipt(db, row)
    _publish_status(db, row)
    _emit_status_webhook(db, row, "SENT")
    return "SENT"
