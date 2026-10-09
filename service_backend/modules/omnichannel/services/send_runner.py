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
    from app.services.storage import storage_for_tenant

    kind, value = storage_for_tenant(db, tenant_id).resolve(media_key)
    if kind == "path":
        with open(value, "rb") as fh:
            return fh.read()
    resp = httpx.get(value, timeout=15.0)
    resp.raise_for_status()
    return resp.content


def _publish_status(db: Session, row: ConversationMessage) -> None:
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


class TransientSendError(Exception):
    """A retryable send failure (network/5xx/storage blip). The Celery task
    re-raises this so ``autoretry_for`` applies bounded backoff; eager dev leaves
    the row QUEUED for a later manual retry (dev uses the stub adapter - no
    transient failures)."""


def _record_broadcast_receipt(db: Session, row: ConversationMessage) -> None:
    """Plan 29 S2b (D-A4-10) - a lazily-imported, fully failure-isolated hook
    into `broadcast_receipts.record_delivery`. A broadcast bug must NEVER
    break an outbound send; called AFTER the row's own commit."""
    try:
        from .broadcast_receipts import record_delivery

        record_delivery(db, row)
    except Exception:  # noqa: BLE001 - never let a broadcast bug break a send
        logger.exception("broadcast receipt hook failed for message %s", row.id)


def _fail(db: Session, row: ConversationMessage, message: str) -> str:
    row.delivery_status = "FAILED"
    row.error_message = message
    db.commit()
    _record_broadcast_receipt(db, row)
    _publish_status(db, row)
    return "FAILED"


def _requeue_transient(db: Session, row: ConversationMessage, message: str) -> None:
    """Reset a claimed row to QUEUED so a retry re-sends (the send did NOT reach
    the contact), then raise for backoff. Only reached BEFORE ``adapter.send``
    returns - a post-success commit failure leaves the row SENDING (never re-sent)."""
    row.delivery_status = "QUEUED"
    row.error_message = message
    db.commit()
    raise TransientSendError(message)


def run_send(db: Session, message_id: str, trace_id: Optional[str] = None) -> str:
    """Execute a QUEUED outbound row. Returns the final delivery status.

    IDEMPOTENT double-send guard (plan 12 review): the row is CLAIMED (QUEUED →
    SENDING, committed) BEFORE ``adapter.send`` touches Meta. A row not in QUEUED
    is a no-op - so if the post-send commit fails and Celery retries, the retry
    sees SENDING and never re-calls ``adapter.send`` (the contact can't get it
    twice). A transient failure (network/5xx/storage) raises ``TransientSendError``
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
            _requeue_transient(db, row, str(exc))
        return _fail(db, row, str(exc))
    except (httpx.HTTPError, OSError) as exc:
        # Transport / stored-media read blip - retryable with backoff.
        _requeue_transient(db, row, str(exc))

    row.external_message_id = result.get("external_message_id")
    row.delivery_status = "SENT"
    db.commit()
    _record_broadcast_receipt(db, row)
    _publish_status(db, row)
    return "SENT"
