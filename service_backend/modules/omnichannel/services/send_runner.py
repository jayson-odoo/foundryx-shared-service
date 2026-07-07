"""Async outbound send executor (plan 12 §Locked D-Q10, AC-12-03/04).

``run_send(db, message_id)`` is the ONE path every outbound message takes after
the endpoint has created its ``QUEUED`` row: resolve channel + creds → (media)
transcode/upload-by-id → ``adapter.send`` → stamp ``SENT``/``FAILED`` +
``external_message_id`` → publish a WS ``message.status`` event.

The Celery task (``worker.omnichannel_send_message``) calls this on a fresh
session in prod; in eager dev/tests ``MessageService`` calls it INLINE on the
request session (a worker would open a different DB session and not see the
in-request row — the workflow-engine eager pattern).
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
from .media_pipeline import MediaRejected, transcode_voice

logger = logging.getLogger(__name__)


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
    the row QUEUED for a later manual retry (dev uses the stub adapter — no
    transient failures)."""


def _fail(db: Session, row: ConversationMessage, message: str) -> str:
    row.delivery_status = "FAILED"
    row.error_message = message
    db.commit()
    _publish_status(db, row)
    return "FAILED"


def _requeue_transient(db: Session, row: ConversationMessage, message: str) -> None:
    """Reset a claimed row to QUEUED so a retry re-sends (the send did NOT reach
    the contact), then raise for backoff. Only reached BEFORE ``adapter.send``
    returns — a post-success commit failure leaves the row SENDING (never re-sent)."""
    row.delivery_status = "QUEUED"
    row.error_message = message
    db.commit()
    raise TransientSendError(message)


def run_send(db: Session, message_id: str) -> str:
    """Execute a QUEUED outbound row. Returns the final delivery status.

    IDEMPOTENT double-send guard (plan 12 review): the row is CLAIMED (QUEUED →
    SENDING, committed) BEFORE ``adapter.send`` touches Meta. A row not in QUEUED
    is a no-op — so if the post-send commit fails and Celery retries, the retry
    sees SENDING and never re-calls ``adapter.send`` (the contact can't get it
    twice). A transient failure (network/5xx/storage) raises ``TransientSendError``
    for backoff; a permanent Meta rejection / transcode error stamps FAILED."""
    row = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.id == message_id)
        .first()
    )
    if row is None:
        return "MISSING"
    if row.delivery_status not in (None, "QUEUED"):
        # Already claimed/sent/failed — never re-send (double-dispatch guard).
        return row.delivery_status

    channel = (
        db.query(Channel)
        .filter(Channel.id == row.channel_id, Channel.tenant_id == row.tenant_id)
        .first()
    )
    contact = ContactRepository(db).get_by_id(row.contact_id, row.tenant_id)
    if channel is None or contact is None:
        return _fail(db, row, "No active channel for this thread.")

    # CLAIM before touching Meta. If this commit fails the row stays QUEUED and a
    # retry safely re-claims (no send happened yet).
    row.delivery_status = "SENDING"
    db.commit()

    credentials = decrypt_credentials(channel.credentials_json)
    adapter = get_adapter(channel.channel_type)
    phone_id = channel.phone_number_id or ""
    to = "".join(ch for ch in (contact.phone or "") if ch.isdigit())
    meta = row.metadata_json or {}
    context_id: Optional[str] = meta.get("context_external_id")

    try:
        if row.message_type == "TEMPLATE":
            template = (row.payload_json or {}).get("template")
            result = adapter.send(
                credentials, phone_id, to, template=template, context_message_id=context_id
            )
        elif row.message_type in MEDIA_MESSAGE_TYPES:
            content = _read_media(db, row.tenant_id, row.media_key)
            mime = row.media_mime or "application/octet-stream"
            if row.message_type == "VOICE":
                content = transcode_voice(content)  # webm/opus → ogg/opus
                mime = "audio/ogg"
                # The stored blob is now ogg — keep media_key/mime consistent so
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
            )
        else:  # TEXT (and any free-form fallback)
            result = adapter.send(
                credentials, phone_id, to, text=row.body, context_message_id=context_id
            )
    except MediaRejected as exc:
        # Sniff/cap/transcode failure — permanent.
        return _fail(db, row, exc.message)
    except SendError as exc:
        if getattr(exc, "transient", False):
            _requeue_transient(db, row, str(exc))
        return _fail(db, row, str(exc))
    except (httpx.HTTPError, OSError) as exc:
        # Transport / stored-media read blip — retryable with backoff.
        _requeue_transient(db, row, str(exc))

    row.external_message_id = result.get("external_message_id")
    row.delivery_status = "SENT"
    db.commit()
    _publish_status(db, row)
    return "SENT"
