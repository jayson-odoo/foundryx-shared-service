"""Contact erase repository (plan 56 C): the rows that reference one contact.

Pure SQLAlchemy. Every query is tenant scoped, and workspace scoped where the
table carries a workspace. No commit here: the service owns the transaction.
Order of use is fixed by the service (no foreign key cascades exist)."""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from ..models import (
    Broadcast,
    BroadcastRecipient,
    Contact,
    ContactChannelIdentity,
    ContactTagLink,
    ConversationEvent,
    ConversationMessage,
    MessageReaction,
    MigrationRef,
    WebhookDelivery,
    WorkflowContactFire,
    WorkflowWait,
)

TOMBSTONE_ENTITY = "contact_erased"
TOMBSTONE_LOCAL_ID = "erased"
ENTITY_CONTACT = "contact"


class ContactEraseRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_contact(self, contact_id: str, tenant_id: str, workspace_id: str) -> Optional[Contact]:
        return (
            self.db.query(Contact)
            .filter(
                Contact.id == contact_id,
                Contact.tenant_id == tenant_id,
                Contact.workspace_id == workspace_id,
            )
            .first()
        )

    def get_contact_in_tenant(self, contact_id: str, tenant_id: str) -> Optional[Contact]:
        return (
            self.db.query(Contact)
            .filter(Contact.id == contact_id, Contact.tenant_id == tenant_id)
            .first()
        )

    def messages(self, contact_id: str, tenant_id: str) -> List[Tuple[str, Optional[str], Optional[str]]]:
        """(id, media_key, media_url) of every message of the contact."""
        return (
            self.db.query(
                ConversationMessage.id, ConversationMessage.media_key, ConversationMessage.media_url
            )
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.contact_id == contact_id,
            )
            .all()
        )

    def waits(self, contact_id: str, tenant_id: str) -> List[WorkflowWait]:
        return (
            self.db.query(WorkflowWait)
            .filter(WorkflowWait.tenant_id == tenant_id, WorkflowWait.contact_id == contact_id)
            .all()
        )

    def event_ids(self, contact_id: str, tenant_id: str) -> List[str]:
        return [
            r[0]
            for r in self.db.query(ConversationEvent.id).filter(
                ConversationEvent.tenant_id == tenant_id, ConversationEvent.contact_id == contact_id
            )
        ]

    def identity_ids(self, contact_id: str, tenant_id: str) -> List[str]:
        return [
            r[0]
            for r in self.db.query(ContactChannelIdentity.id).filter(
                ContactChannelIdentity.tenant_id == tenant_id,
                ContactChannelIdentity.contact_id == contact_id,
            )
        ]

    def delete_reactions(self, message_ids: List[str], tenant_id: str) -> None:
        for chunk in _chunks(message_ids):
            self.db.query(MessageReaction).filter(
                MessageReaction.tenant_id == tenant_id,
                MessageReaction.target_message_id.in_(chunk),
            ).delete(synchronize_session=False)

    def delete_messages(self, contact_id: str, tenant_id: str) -> None:
        self.db.query(ConversationMessage).filter(
            ConversationMessage.tenant_id == tenant_id, ConversationMessage.contact_id == contact_id
        ).delete(synchronize_session=False)

    def delete_events(self, contact_id: str, tenant_id: str) -> None:
        self.db.query(ConversationEvent).filter(
            ConversationEvent.tenant_id == tenant_id, ConversationEvent.contact_id == contact_id
        ).delete(synchronize_session=False)

    def delete_identities(self, contact_id: str, tenant_id: str) -> None:
        self.db.query(ContactChannelIdentity).filter(
            ContactChannelIdentity.tenant_id == tenant_id,
            ContactChannelIdentity.contact_id == contact_id,
        ).delete(synchronize_session=False)

    def delete_tag_links(self, contact_id: str, tenant_id: str) -> None:
        self.db.query(ContactTagLink).filter(
            ContactTagLink.tenant_id == tenant_id, ContactTagLink.contact_id == contact_id
        ).delete(synchronize_session=False)

    def delete_waits(self, contact_id: str, tenant_id: str) -> None:
        self.db.query(WorkflowWait).filter(
            WorkflowWait.tenant_id == tenant_id, WorkflowWait.contact_id == contact_id
        ).delete(synchronize_session=False)

    def delete_fires(self, contact_id: str, tenant_id: str) -> None:
        self.db.query(WorkflowContactFire).filter(
            WorkflowContactFire.tenant_id == tenant_id, WorkflowContactFire.contact_id == contact_id
        ).delete(synchronize_session=False)

    def delete_recipients(self, contact_id: str, tenant_id: str) -> None:
        self.db.query(BroadcastRecipient).filter(
            BroadcastRecipient.tenant_id == tenant_id, BroadcastRecipient.contact_id == contact_id
        ).delete(synchronize_session=False)

    def drop_from_audiences(self, contact_id: str, tenant_id: str, workspace_id: str) -> None:
        """Remove the id from every explicit audience list (fresh list: SQLAlchemy
        misses in-place JSON mutation)."""
        rows = (
            self.db.query(Broadcast)
            .filter(
                Broadcast.tenant_id == tenant_id,
                Broadcast.workspace_id == workspace_id,
                cast(Broadcast.audience_contact_ids_json, String).like(f"%{contact_id}%"),
            )
            .all()
        )
        for b in rows:
            ids = b.audience_contact_ids_json
            if isinstance(ids, list) and contact_id in ids:
                b.audience_contact_ids_json = [i for i in ids if i != contact_id]

    def migration_refs(self, tenant_id: str, workspace_id: str, local_ids: List[str]) -> List[MigrationRef]:
        rows: List[MigrationRef] = []
        for chunk in _chunks(local_ids):
            rows.extend(
                self.db.query(MigrationRef)
                .filter(
                    MigrationRef.tenant_id == tenant_id,
                    MigrationRef.workspace_id == workspace_id,
                    MigrationRef.local_id.in_(chunk),
                )
                .all()
            )
        return rows

    def delete_ref(self, ref: MigrationRef) -> None:
        self.db.delete(ref)

    def tombstone_ref(self, ref: MigrationRef) -> None:
        ref.entity_type = TOMBSTONE_ENTITY
        ref.local_id = TOMBSTONE_LOCAL_ID

    def deliveries_naming(self, contact_id: str, tenant_id: str) -> List[WebhookDelivery]:
        return (
            self.db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.tenant_id == tenant_id,
                cast(WebhookDelivery.payload_json, String).like(f"%{contact_id}%"),
            )
            .all()
        )

    def delete_contact(self, contact_id: str, tenant_id: str, workspace_id: str) -> None:
        self.db.query(Contact).filter(
            Contact.id == contact_id,
            Contact.tenant_id == tenant_id,
            Contact.workspace_id == workspace_id,
        ).delete(synchronize_session=False)

    def flush(self) -> None:
        self.db.flush()


def _chunks(items: List[Any], size: int = 500):
    for i in range(0, len(items), size):
        yield items[i : i + size]
