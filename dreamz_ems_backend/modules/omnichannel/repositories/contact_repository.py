"""Contact (thread) + message repository — tenant-scoped, pure SQLAlchemy.

The contact IS the thread (plan 05): list/filter threads, fetch a thread's
messages, resolve identities, and maintain the thread metadata columns the
inbox sorts/filters on.
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import Contact, ContactChannelIdentity, ConversationMessage, Status


class ContactRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── Threads ──────────────────────────────────────────────────────────────
    def list_threads(
        self,
        tenant_id: str,
        *,
        workspace_id: Optional[str] = None,
        assignee: str = "all",  # all | me | unassigned
        me_user_id: Optional[str] = None,
        status_key: Optional[str] = None,  # OPEN | SNOOZED | CLOSED | None=ALL
        priority: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 0,
        page_size: int = 50,
    ) -> Tuple[List[Contact], int]:
        q = self.db.query(Contact).filter(Contact.tenant_id == tenant_id)
        if workspace_id:
            q = q.filter(Contact.workspace_id == workspace_id)
        if assignee == "me" and me_user_id:
            q = q.filter(Contact.assigned_user_id == me_user_id)
        elif assignee == "unassigned":
            q = q.filter(Contact.assigned_user_id.is_(None))
        if status_key:
            q = q.join(Status, Contact.status_id == Status.id).filter(Status.key == status_key)
        if priority:
            q = q.filter(Contact.priority == priority)
        if search and search.strip():
            term = f"%{search.strip()}%"
            # WhatsApp-style: name/phone OR any message body in the thread.
            message_match = (
                self.db.query(ConversationMessage.id)
                .filter(
                    ConversationMessage.contact_id == Contact.id,
                    ConversationMessage.body.ilike(term),
                )
                .exists()
            )
            full_name = (
                func.coalesce(Contact.first_name, "") + " " + func.coalesce(Contact.last_name, "")
            )
            q = q.filter(
                or_(
                    full_name.ilike(term),  # covers first, last, and "First Last"
                    Contact.phone.ilike(term),
                    message_match,
                )
            )
        total = q.count()
        rows = (
            q.order_by(Contact.last_message_at.desc().nullslast(), Contact.id.asc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    def get_by_id(self, contact_id: str, tenant_id: str) -> Optional[Contact]:
        return (
            self.db.query(Contact)
            .filter(Contact.tenant_id == tenant_id, Contact.id == contact_id)
            .first()
        )

    def mark_read(self, contact: Contact) -> None:
        contact.agent_last_read_at = datetime.now(timezone.utc)
        self.db.flush()

    # ── Messages ─────────────────────────────────────────────────────────────
    def list_messages(self, contact_id: str, tenant_id: str) -> List[ConversationMessage]:
        return (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.contact_id == contact_id,
            )
            .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
            .all()
        )

    def get_message(self, message_id: str, tenant_id: str) -> Optional[ConversationMessage]:
        return (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.id == message_id,
            )
            .first()
        )

    def get_message_by_external_id(
        self, external_message_id: str, tenant_id: str
    ) -> Optional[ConversationMessage]:
        return (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.external_message_id == external_message_id,
            )
            .first()
        )

    # ── Thread-list computed columns (preview + unread), batched ────────────
    def previews_for(self, contact_ids: List[str], tenant_id: str) -> dict:
        """Latest non-SYSTEM message body per contact (one grouped query)."""
        if not contact_ids:
            return {}
        latest = (
            self.db.query(
                ConversationMessage.contact_id,
                func.max(ConversationMessage.created_at).label("latest_at"),
            )
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.contact_id.in_(contact_ids),
                ConversationMessage.sender_type != "SYSTEM",
            )
            .group_by(ConversationMessage.contact_id)
            .subquery()
        )
        rows = (
            self.db.query(ConversationMessage)
            .join(
                latest,
                (ConversationMessage.contact_id == latest.c.contact_id)
                & (ConversationMessage.created_at == latest.c.latest_at),
            )
            .all()
        )
        # Tie-break: two messages can share an identical created_at (µs-coarse
        # clocks / batched inbound). Order so the highest id wins deterministically
        # — setdefault keeps the first seen per contact.
        preview: dict = {}
        for m in sorted(rows, key=lambda r: r.id, reverse=True):
            preview.setdefault(m.contact_id, m)
        return preview

    def unread_counts_for(self, contacts: List[Contact], tenant_id: str) -> dict:
        """Inbound messages newer than each contact's agent_last_read_at."""
        if not contacts:
            return {}
        ids = [c.id for c in contacts]
        rows = (
            self.db.query(
                ConversationMessage.contact_id,
                ConversationMessage.created_at,
            )
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.contact_id.in_(ids),
                ConversationMessage.sender_type == "CONTACT",
            )
            .all()
        )
        last_read = {c.id: c.agent_last_read_at for c in contacts}
        counts: dict = {}
        for contact_id, created_at in rows:
            marker = last_read.get(contact_id)
            if marker is not None and created_at is not None:
                # SQLite returns naive datetimes; normalise for comparison.
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if marker.tzinfo is None:
                    marker = marker.replace(tzinfo=timezone.utc)
                if created_at <= marker:
                    continue
            counts[contact_id] = counts.get(contact_id, 0) + 1
        return counts

    # ── Identities (webhook contact resolution, plan 05 §4) ─────────────────
    def find_identity(
        self, channel_id: str, external_user_id: str
    ) -> Optional[ContactChannelIdentity]:
        return (
            self.db.query(ContactChannelIdentity)
            .filter(
                ContactChannelIdentity.channel_id == channel_id,
                ContactChannelIdentity.external_user_id == external_user_id,
            )
            .first()
        )

    def find_by_phone_in_workspace(
        self, phone_digits: str, workspace_id: str, tenant_id: str
    ) -> Optional[Contact]:
        """Within-workspace stitch (decision 15): match an existing contact by
        phone. Phones are stored in varying formats — compare digits-only."""
        # Empty digits (malformed wa_id) must NOT match contacts with a digitless
        # phone — that would mis-stitch the message onto an unrelated contact.
        if not phone_digits:
            return None
        candidates = (
            self.db.query(Contact)
            .filter(
                Contact.tenant_id == tenant_id,
                Contact.workspace_id == workspace_id,
                Contact.phone.isnot(None),
            )
            .all()
        )
        for c in candidates:
            if "".join(ch for ch in (c.phone or "") if ch.isdigit()) == phone_digits:
                return c
        return None
