"""Outbound messaging (plan 05 §5): CSW-enforced send, internal notes,
template mirror (read-only sync from Meta), quick replies.

Security invariant: outbound writes are attributed to the ACTOR (real agent),
never the impersonation target or client input.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings

from ..adapters.whatsapp_cloud import get_adapter
from ..models import (
    MEDIA_MESSAGE_TYPES,
    Channel,
    Contact,
    ContactChannelIdentity,
    ConversationMessage,
    QuickReply,
    WhatsappTemplate,
)
from ..repositories.contact_repository import ContactRepository
from ..schemas import MessageItem, QuickReplyItem, SendMessageRequest, TemplateItem
from ..security import decrypt_credentials
from .conversation_service import ConversationService, ThreadNotFound
from .media_pipeline import MediaRejected, sniff_and_validate
from .media_settings_service import MediaSettingsService
from .send_runner import run_send
from . import realtime


class SendRejected(Exception):
    """Backend CSW / validation rejection (422 — the composer shows the reason)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


CSW_CLOSED_MESSAGE = (
    "The 24-hour window has closed — send an approved template to re-engage."
)


def _window_open(contact: Contact, now: Optional[datetime] = None) -> bool:
    if contact.csw_expires_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    expires = contact.csw_expires_at
    if expires.tzinfo is None:  # SQLite returns naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now


def template_body_text(components: Optional[List[Dict[str, Any]]]) -> str:
    for comp in components or []:
        if (comp.get("type") or "").upper() == "BODY":
            return comp.get("text") or ""
    return ""


def template_variable_count(body_text: str) -> int:
    nums = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", body_text)]
    return max(nums) if nums else 0


def fill_template(body_text: str, variables: List[str]) -> str:
    return re.sub(
        r"\{\{(\d+)\}\}",
        lambda m: variables[int(m.group(1)) - 1] if int(m.group(1)) <= len(variables) else "",
        body_text,
    )


class MessageService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ContactRepository(db)
        self.conversations = ConversationService(db)

    # ── Channel resolution ───────────────────────────────────────────────────
    def _channel_for_contact(self, contact: Contact) -> Channel:
        """The channel this thread lives on: the identity's channel, else the
        workspace's first active channel."""
        via_identity = (
            self.db.query(Channel)
            .join(ContactChannelIdentity, Channel.id == ContactChannelIdentity.channel_id)
            .filter(
                ContactChannelIdentity.contact_id == contact.id,
                # Only send on a live channel — a deactivated/trashed identity
                # channel falls through to the workspace's active channel.
                Channel.tenant_id == contact.tenant_id,
                Channel.is_active.is_(True),
                Channel.is_trashed.is_(False),
            )
            .first()
        )
        if via_identity is not None:
            return via_identity
        channel = (
            self.db.query(Channel)
            .filter(
                Channel.tenant_id == contact.tenant_id,
                Channel.workspace_id == contact.workspace_id,
                Channel.is_active.is_(True),
                Channel.is_trashed.is_(False),
            )
            .first()
        )
        if channel is None:
            raise SendRejected("No active channel is connected to this workspace.")
        return channel

    # ── Reply threading ───────────────────────────────────────────────────────
    def _reply_metadata(
        self, contact: Contact, tenant_id: str, reply_to_message_id: Optional[str]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Resolve the reply target → (display metadata, quoted external id).
        The external id threads the WhatsApp quote at send time (async task)."""
        if not reply_to_message_id:
            return None, None
        quoted = self.repo.get_message(reply_to_message_id, tenant_id)
        if quoted is None or quoted.contact_id != contact.id:
            raise SendRejected("The message you are replying to was not found.")
        sender_name = None
        if quoted.sender_id:
            names = self.conversations._user_names([quoted.sender_id])
            sender_name = names.get(quoted.sender_id)
        metadata = {
            "reply_to": {
                "id": quoted.id,
                "body": quoted.body,
                "senderType": quoted.sender_type,
                "senderName": sender_name,
            },
            "context_external_id": quoted.external_message_id,
        }
        return metadata, quoted.external_message_id

    def _enqueue_and_finalize(self, row: ConversationMessage, contact: Contact) -> MessageItem:
        """Publish the optimistic ``message.created`` then dispatch the send
        (inline in eager dev/tests, Celery ``omni`` queue in prod) and return the
        current item (QUEUED optimistic, or SENT/FAILED after the inline run)."""
        item = self.conversations.message_items([row])[0]
        thread = self.conversations.thread_item(contact)
        realtime.publish(
            contact.workspace_id,
            {
                "type": "message.created",
                "message": item.model_dump(mode="json"),
                "thread": thread.model_dump(mode="json"),
            },
        )
        if settings.celery_task_always_eager:
            run_send(self.db, row.id)  # same session — see send_runner docstring
        else:
            from ..worker import omnichannel_send_message

            omnichannel_send_message.delay(row.id)
        self.db.refresh(row)
        return self.conversations.message_items([row])[0]

    # ── Send (text / template) ────────────────────────────────────────────────
    def send_message(
        self,
        contact_id: str,
        tenant_id: str,
        actor_user_id: str,
        payload: SendMessageRequest,
    ) -> MessageItem:
        contact = self.repo.get_by_id(contact_id, tenant_id)
        if contact is None:
            raise ThreadNotFound()
        channel = self._channel_for_contact(contact)
        metadata, _ = self._reply_metadata(contact, tenant_id, payload.replyToMessageId)

        message_type = (payload.messageType or "TEXT").upper()
        payload_json: Optional[Dict[str, Any]] = None
        if message_type == "TEMPLATE":
            tpl = (
                self.db.query(WhatsappTemplate)
                .filter(
                    WhatsappTemplate.tenant_id == tenant_id,
                    WhatsappTemplate.id == payload.templateId,
                )
                .first()
            )
            if tpl is None:
                raise SendRejected("Template not found.")
            if (tpl.status or "").upper() != "APPROVED":
                raise SendRejected("Template is not approved.")
            body_text = template_body_text(tpl.components_json)
            variables = payload.templateVariables or []
            # Meta rejects a parameter-count mismatch — validate before queueing.
            expected = template_variable_count(body_text)
            if len(variables) != expected:
                raise SendRejected(
                    f"This template needs {expected} variable(s); {len(variables)} provided."
                )
            body = fill_template(body_text, variables)
            payload_json = {
                "template": {
                    "name": tpl.name,
                    "language": tpl.language,
                    "components": (
                        [
                            {
                                "type": "body",
                                "parameters": [{"type": "text", "text": v} for v in variables],
                            }
                        ]
                        if variables
                        else None
                    ),
                }
            }
        else:
            message_type = "TEXT"
            # Backend-enforced CSW (decision 14): free-form only inside 24h.
            if not _window_open(contact):
                raise SendRejected(CSW_CLOSED_MESSAGE)
            if not (payload.body or "").strip():
                raise SendRejected("Message body is required.")
            body = (payload.body or "").strip()

        now = datetime.now(timezone.utc)
        row = ConversationMessage(
            tenant_id=tenant_id,
            contact_id=contact.id,
            channel_id=channel.id,
            sender_type="AGENT",
            sender_id=actor_user_id,
            message_type=message_type,
            body=body,
            payload_json=payload_json,
            delivery_status="QUEUED",
            metadata_json=metadata,
            created_at=now,  # µs precision — keeps rapid messages ordered
        )
        self.db.add(row)
        contact.last_message_at = now
        self.db.commit()
        self.db.refresh(row)
        return self._enqueue_and_finalize(row, contact)

    # ── Send (media: image/video/audio/voice/document/sticker) ────────────────
    def send_media(
        self,
        contact_id: str,
        tenant_id: str,
        actor_user_id: str,
        *,
        kind: str,
        content: bytes,
        filename: Optional[str],
        caption: Optional[str],
        reply_to_message_id: Optional[str] = None,
        workspace_id_override: Optional[str] = None,
    ) -> MessageItem:
        """Sniff-gate + cap-check + store an outbound media blob, create a QUEUED
        row and dispatch the async upload-by-id send (AC-12-02/03/10). Raises
        ``SendRejected`` on CSW/validation, ``MediaRejected`` on sniff/cap."""
        contact = self.repo.get_by_id(contact_id, tenant_id)
        if contact is None:
            raise ThreadNotFound()
        channel = self._channel_for_contact(contact)
        kind = (kind or "").upper()
        if kind not in MEDIA_MESSAGE_TYPES:
            raise SendRejected(f"Unsupported media kind '{kind}'.")
        # Media is free-form → 24h CSW applies (AC-12-25).
        if not _window_open(contact):
            raise SendRejected(CSW_CLOSED_MESSAGE)

        max_bytes = MediaSettingsService(self.db).max_bytes_for(
            tenant_id, contact.workspace_id, kind
        )
        sniffed = sniff_and_validate(kind, content, filename=filename, max_bytes=max_bytes)
        metadata, _ = self._reply_metadata(contact, tenant_id, reply_to_message_id)

        from app.services.storage import storage_for_tenant

        media_key = storage_for_tenant(self.db, tenant_id).save(
            f"omnichannel/{tenant_id}/outbound", sniffed.content, sniffed.mime
        )

        now = datetime.now(timezone.utc)
        row = ConversationMessage(
            tenant_id=tenant_id,
            contact_id=contact.id,
            channel_id=channel.id,
            sender_type="AGENT",
            sender_id=actor_user_id,
            message_type=kind,
            body=(caption or None),
            media_key=media_key,
            media_mime=sniffed.mime,
            media_filename=filename,
            media_size=sniffed.size,
            delivery_status="QUEUED",
            metadata_json=metadata,
            created_at=now,
        )
        self.db.add(row)
        contact.last_message_at = now
        self.db.commit()
        self.db.refresh(row)
        return self._enqueue_and_finalize(row, contact)

    # ── Internal notes (SYSTEM bubbles — never sent to the contact) ─────────
    def add_internal_note(
        self, contact_id: str, tenant_id: str, actor_user_id: str, body: str
    ) -> MessageItem:
        contact = self.repo.get_by_id(contact_id, tenant_id)
        if contact is None:
            raise ThreadNotFound()
        if not body.strip():
            raise SendRejected("Note body is required.")
        row = ConversationMessage(
            tenant_id=tenant_id,
            contact_id=contact.id,
            channel_id=None,
            sender_type="SYSTEM",
            sender_id=actor_user_id,
            message_type="TEXT",
            body=body.strip(),
            created_at=datetime.now(timezone.utc),  # µs precision ordering
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        item = self.conversations.message_items([row])[0]
        # Broadcast like every other write — other agents on the thread see the
        # note live (the drawer dedupes by id, so the author won't double-render).
        thread = self.conversations.thread_item(contact)
        realtime.publish(
            contact.workspace_id,
            {
                "type": "message.created",
                "message": item.model_dump(mode="json"),
                "thread": thread.model_dump(mode="json"),
            },
        )
        return item

    # ── Templates (read-only mirror, decision 11) ────────────────────────────
    def list_templates(self, channel_id: str, tenant_id: str, *, sync: bool = True) -> List[TemplateItem]:
        channel = (
            self.db.query(Channel)
            .filter(Channel.tenant_id == tenant_id, Channel.id == channel_id)
            .first()
        )
        if channel is None:
            raise ThreadNotFound()
        if sync:
            self._sync_templates(channel)
        rows = (
            self.db.query(WhatsappTemplate)
            .filter(
                WhatsappTemplate.tenant_id == tenant_id,
                WhatsappTemplate.channel_id == channel_id,
                WhatsappTemplate.status == "APPROVED",
            )
            .order_by(WhatsappTemplate.name.asc())
            .all()
        )
        return [self._template_item(t) for t in rows]

    def _template_item(self, t: WhatsappTemplate) -> TemplateItem:
        body = template_body_text(t.components_json)
        return TemplateItem(
            id=t.id,
            channelId=t.channel_id,
            name=t.name,
            language=t.language,
            category=t.category,
            bodyText=body,
            variableCount=template_variable_count(body),
            status=t.status,
        )

    def _sync_templates(self, channel: Channel) -> None:
        """Mirror Meta's templates for the channel's WABA (no-op in dev mode)."""
        credentials = decrypt_credentials(channel.credentials_json)
        adapter = get_adapter(channel.channel_type)
        fetched = adapter.list_templates(credentials, channel.waba_id or "")
        if not fetched:
            return
        now = datetime.now(timezone.utc)
        existing = {
            (t.name, t.language): t
            for t in self.db.query(WhatsappTemplate).filter(
                WhatsappTemplate.channel_id == channel.id
            )
        }
        for raw in fetched:
            key = (raw.get("name"), raw.get("language"))
            row = existing.get(key)
            if row is None:
                row = WhatsappTemplate(
                    tenant_id=channel.tenant_id,
                    channel_id=channel.id,
                    name=raw.get("name") or "",
                    language=raw.get("language"),
                )
                self.db.add(row)
            row.category = raw.get("category")
            row.status = (raw.get("status") or "").upper() or None
            row.components_json = raw.get("components")
            row.synced_at = now
        self.db.commit()

    # ── Quick replies ────────────────────────────────────────────────────────
    def list_quick_replies(self, workspace_id: str, tenant_id: str) -> List[QuickReplyItem]:
        rows = (
            self.db.query(QuickReply)
            .filter(QuickReply.tenant_id == tenant_id, QuickReply.workspace_id == workspace_id)
            .order_by(QuickReply.shortcut.asc().nullslast(), QuickReply.created_at.asc())
            .all()
        )
        return [
            QuickReplyItem(id=r.id, workspaceId=r.workspace_id, shortcut=r.shortcut, body=r.body)
            for r in rows
        ]
