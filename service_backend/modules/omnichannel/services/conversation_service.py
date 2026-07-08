"""Conversation (thread + message) service — plan 05.

Maps Contact/ConversationMessage rows to the camelCase API shapes, resolves
status keys + user display names, maintains the read marker, and applies the
PATCH operations (assign / lifecycle / priority).
"""
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.user import User
from ..models import Channel, Contact, ConversationMessage, Status
from ..repositories.contact_repository import ContactRepository
from ..schemas import MessageItem, ReplyRefItem, ThreadItem
from . import realtime, statuses

logger = logging.getLogger(__name__)


class ThreadNotFound(Exception):
    pass


class InvalidPatch(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


VALID_THREAD_STATUS = {"OPEN", "SNOOZED", "CLOSED"}
VALID_PRIORITY = {"LOW", "MEDIUM", "HIGH", "URGENT"}


def contact_display_name(c: Contact) -> str:
    parts = [p for p in [c.first_name, c.last_name] if p]
    return " ".join(parts) if parts else (c.phone or "Contact")


class ConversationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ContactRepository(db)

    # ── Lookups ──────────────────────────────────────────────────────────────
    def _status_keys(self, tenant_id: str) -> Dict[str, str]:
        rows = (
            self.db.query(Status)
            .filter(Status.tenant_id == tenant_id, Status.scope == "THREAD")
            .all()
        )
        return {s.id: s.key for s in rows}

    def _user_names(self, user_ids: List[str]) -> Dict[str, str]:
        ids = [u for u in set(user_ids) if u]
        if not ids:
            return {}
        rows = self.db.query(User).filter(User.id.in_(ids)).all()
        return {u.id: (u.name or u.email) for u in rows}

    def _channel_types(self, channel_ids: List[str]) -> Dict[str, str]:
        ids = [c for c in set(channel_ids) if c]
        if not ids:
            return {}
        rows = self.db.query(Channel).filter(Channel.id.in_(ids)).all()
        return {c.id: c.channel_type for c in rows}

    # ── Mapping ──────────────────────────────────────────────────────────────
    def _thread_items(self, contacts: List[Contact], tenant_id: str) -> List[ThreadItem]:
        if not contacts:
            return []
        ids = [c.id for c in contacts]
        previews = self.repo.previews_for(ids, tenant_id)
        unread = self.repo.unread_counts_for(contacts, tenant_id)
        status_keys = self._status_keys(tenant_id)
        names = self._user_names([c.assigned_user_id for c in contacts])
        channel_types = self._channel_types(
            [previews[c.id].channel_id for c in contacts if c.id in previews]
        )

        items: List[ThreadItem] = []
        for c in contacts:
            preview = previews.get(c.id)
            channel_id = preview.channel_id if preview else None
            items.append(
                ThreadItem(
                    id=c.id,
                    tenantId=c.tenant_id,
                    workspaceId=c.workspace_id,
                    name=contact_display_name(c),
                    phone=c.phone,
                    avatarUrl=c.avatar_url,
                    assignedUserId=c.assigned_user_id,
                    assignedUserName=names.get(c.assigned_user_id) if c.assigned_user_id else None,
                    status=status_keys.get(c.status_id, "OPEN"),
                    priority=c.priority or "MEDIUM",
                    channelId=channel_id,
                    channelType=channel_types.get(channel_id, "WHATSAPP"),
                    cswExpiresAt=c.csw_expires_at,
                    lastIncomingMessageAt=c.last_incoming_message_at,
                    lastMessageAt=c.last_message_at,
                    lastMessagePreview=preview.body if preview else None,
                    unreadCount=unread.get(c.id, 0),
                    createdAt=c.created_at,
                )
            )
        return items

    def thread_item(self, contact: Contact) -> ThreadItem:
        return self._thread_items([contact], contact.tenant_id)[0]

    def message_items(self, messages: List[ConversationMessage]) -> List[MessageItem]:
        names = self._user_names([m.sender_id for m in messages if m.sender_id])
        items: List[MessageItem] = []
        for m in messages:
            meta = m.metadata_json or {}
            reply = meta.get("reply_to")
            items.append(
                MessageItem(
                    id=m.id,
                    contactId=m.contact_id,
                    channelId=m.channel_id,
                    senderType=m.sender_type,
                    senderId=m.sender_id,
                    senderName=names.get(m.sender_id) if m.sender_id else None,
                    messageType=m.message_type,
                    body=m.body,
                    mediaUrl=m.media_url_wire,
                    mediaMime=m.media_mime,
                    mediaFilename=m.media_filename,
                    mediaSize=m.media_size,
                    voice=(m.message_type == "VOICE"),
                    payload=m.payload_json,
                    externalMessageId=m.external_message_id,
                    deliveryStatus=m.delivery_status,
                    errorCode=m.error_code,
                    errorMessage=m.error_message,
                    replyTo=ReplyRefItem(**reply) if reply else None,
                    createdAt=m.created_at,
                )
            )
        return items

    # ── Reads ────────────────────────────────────────────────────────────────
    def list_threads(self, tenant_id: str, **filters) -> Tuple[List[ThreadItem], int]:
        rows, total = self.repo.list_threads(tenant_id, **filters)
        return self._thread_items(rows, tenant_id), total

    def get_thread(self, contact_id: str, tenant_id: str) -> ThreadItem:
        c = self.repo.get_by_id(contact_id, tenant_id)
        if c is None:
            raise ThreadNotFound()
        return self.thread_item(c)

    def list_messages(self, contact_id: str, tenant_id: str) -> List[MessageItem]:
        c = self.repo.get_by_id(contact_id, tenant_id)
        if c is None:
            raise ThreadNotFound()
        msgs = self.repo.list_messages(contact_id, tenant_id)
        # Opening the thread marks it read (unreadCount resets).
        self.repo.mark_read(c)
        self.db.commit()
        return self.message_items(msgs)

    # ── Patch (assign / lifecycle / priority) ───────────────────────────────
    def patch_thread(
        self,
        contact_id: str,
        tenant_id: str,
        *,
        assigned_user_id: Optional[str] = ...,
        status: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> ThreadItem:
        c = self.repo.get_by_id(contact_id, tenant_id)
        if c is None:
            raise ThreadNotFound()

        if assigned_user_id is not ...:
            if assigned_user_id is not None:
                user = (
                    self.db.query(User)
                    .filter(User.id == assigned_user_id, User.tenant_id == tenant_id)
                    .first()
                )
                if user is None:
                    raise InvalidPatch("Assignee not found in this tenant.")
            c.assigned_user_id = assigned_user_id

        if status is not None:
            if status not in VALID_THREAD_STATUS:
                raise InvalidPatch(f"Invalid thread status: {status}")
            c.status_id = statuses.status_id_for(self.db, tenant_id, "THREAD", status)

        if priority is not None:
            if priority not in VALID_PRIORITY:
                raise InvalidPatch(f"Invalid priority: {priority}")
            c.priority = priority

        self.db.commit()
        self.db.refresh(c)
        item = self.thread_item(c)
        # Other agents' inboxes update live (assignment moves threads between
        # buckets; snooze/close changes the row chip).
        realtime.publish(
            c.workspace_id,
            {"type": "contact.updated", "thread": item.model_dump(mode="json")},
        )
        # Fan out to consumer webhooks (Slice 4). Endpoints are per-channel, so
        # forward on the contact's current channel (its latest message's); skip
        # if the contact has never messaged on a channel yet. Fully isolated —
        # the PATCH already committed, forwarding must never 500 the response.
        if item.channelId:
            try:
                from .webhook_delivery import enqueue_event

                channel = (
                    self.db.query(Channel)
                    .filter(Channel.id == item.channelId, Channel.tenant_id == tenant_id)
                    .first()
                )
                if channel is not None:
                    enqueue_event(
                        self.db,
                        channel,
                        "contact.updated",
                        f"{c.id}:{int(c.updated_at.timestamp())}",
                        {"contact": item.model_dump(mode="json")},
                    )
            except Exception:  # noqa: BLE001 — forwarding never breaks the PATCH
                logger.exception("contact.updated webhook fan-out failed for %s", c.id)
        return item
