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


def run_send(db: Session, message_id: str) -> str:
    """Execute a QUEUED outbound row. Returns the final delivery status.

    Idempotent: a row already past QUEUED is left untouched (double-dispatch
    guard). Never raises for a Meta/transcode failure — the row is stamped
    FAILED and the error surfaces via WS + the delivery tick."""
    row = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.id == message_id)
        .first()
    )
    if row is None or (row.delivery_status not in (None, "QUEUED")):
        return row.delivery_status if row else "MISSING"

    channel = (
        db.query(Channel)
        .filter(Channel.id == row.channel_id, Channel.tenant_id == row.tenant_id)
        .first()
    )
    contact = ContactRepository(db).get_by_id(row.contact_id, row.tenant_id)
    if channel is None or contact is None:
        row.delivery_status = "FAILED"
        row.error_message = "No active channel for this thread."
        db.commit()
        _publish_status(db, row)
        return "FAILED"

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
    except (SendError, MediaRejected, httpx.HTTPError, OSError) as exc:
        row.delivery_status = "FAILED"
        row.error_message = getattr(exc, "message", None) or str(exc)
        db.commit()
        _publish_status(db, row)
        return "FAILED"

    row.external_message_id = result.get("external_message_id")
    row.delivery_status = "SENT"
    db.commit()
    _publish_status(db, row)
    return "SENT"
