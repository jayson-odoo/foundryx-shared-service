"""Contact erase repository (plan 56 C): the rows that reference one contact.

Pure SQLAlchemy. Every query is tenant scoped, and workspace scoped where the
table carries a workspace. No commit here: the service owns the transaction.
Order of use is fixed by the service (no foreign key cascades exist)."""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import String, and_, case, cast, func, or_
from sqlalchemy.orm import Session

from ..models import (
    Broadcast,
    BroadcastRecipient,
    Contact,
    ContactChannelIdentity,
    ContactTagLink,
    ConversationEvent,
    ContactErasure,
    ConversationMessage,
    MessageReaction,
    MigrationRef,
    WebhookDelivery,
    WorkflowContactFire,
    WorkflowWait,
)

MEDIA_PATH = "/omnichannel/media/"
TOMBSTONE_ENTITY = "contact_erased"
TOMBSTONE_LOCAL_ID = "erased"
ENTITY_CONTACT = "contact"


def local_key_from_url(url: Optional[str]) -> Optional[str]:
    """A legacy `media_url` that points at our own media route holds the stored
    key after the prefix; an external link is not a stored file. THE one rule,
    used by the erase and by the counts that the erase dialog shows."""
    from app.config import settings

    if not url:
        return None
    prefix = f"{settings.public_base_url}{MEDIA_PATH}"
    if url.startswith(prefix) and len(url) > len(prefix):
        return url[len(prefix):]
    return None


def own_area_prefixes(tenant_id: str) -> Tuple[str, str]:
    """The storage areas a tenant's own files are written under."""
    return (f"omnichannel/{tenant_id}/", f"omnichannel/migration/{tenant_id}/")


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _safe_raw(raw: str) -> bool:
    if not raw or "\x00" in raw or "\\" in raw or raw.startswith(("/", "~")):
        return False
    return ".." not in raw.split("/")


def split_connection_key(key: str) -> Tuple[Optional[str], str]:
    """`conn:<id>:<raw>` -> (id, raw); a bare key -> (None, key)."""
    if key.startswith("conn:") and key.count(":") >= 2:
        _, connection_id, raw = key.split(":", 2)
        return connection_id, raw
    return None, key


# A bare key the server minted itself for converted legacy media: no slash,
# `<basename>-<8 hex>.<ext>` (the shape the storage layer mints on write).
_MINTED_BARE = re.compile(r"[A-Za-z0-9_-]+-[0-9a-f]{8}\.[A-Za-z0-9]+")
_MINTED_PG = r"^(conn:[^:]+:)?[A-Za-z0-9_-]+-[0-9a-f]{8}\.[A-Za-z0-9]+$"
_MINTED_GLOB = "*-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f].*"


def purgeable_key(key: Optional[str], tenant_id: str, *, native: bool = False) -> bool:
    """THE one rule for which stored keys an erase may delete (and count): a key
    in the tenant's own storage area, free of path tricks. A `conn:` key is
    judged by its raw part; the connection's owner is checked at purge time.
    `native` (no migration ref on the message) also admits a server-minted
    bare key."""
    if not key:
        return False
    _connection_id, raw = split_connection_key(key)
    if native and _MINTED_BARE.fullmatch(raw):
        return True  # converted media on a native row (a migrated row never qualifies)
    return _safe_raw(raw) and any(raw.startswith(p) for p in own_area_prefixes(tenant_id))


class ContactEraseRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_contact(self, contact_id: str, tenant_id: str, workspace_id: str) -> Optional[Contact]:
        """The contact row, held FOR UPDATE: a message arriving meanwhile waits
        for the erase, so the files collected below are the files that go."""
        return (
            self.db.query(Contact)
            .filter(
                Contact.id == contact_id,
                Contact.tenant_id == tenant_id,
                Contact.workspace_id == workspace_id,
            )
            .with_for_update()
            .first()
        )

    def identity_channel_ids(self, contact_id: str, tenant_id: str) -> List[str]:
        return sorted(
            {
                r[0]
                for r in self.db.query(ContactChannelIdentity.channel_id).filter(
                    ContactChannelIdentity.tenant_id == tenant_id,
                    ContactChannelIdentity.contact_id == contact_id,
                )
                if r[0]
            }
        )

    def reaction_deliveries(self, message_ids: List[str], tenant_id: str) -> List[WebhookDelivery]:
        rows: List[WebhookDelivery] = []
        for chunk in _chunks(message_ids, 40):
            rows.extend(
                self.db.query(WebhookDelivery)
                .filter(
                    WebhookDelivery.tenant_id == tenant_id,
                    WebhookDelivery.event_type == "message.reaction",
                    or_(*[cast(WebhookDelivery.payload_json, String).like(f"%{m}%") for m in chunk]),
                )
                .all()
            )
        return rows

    def get_contact_in_tenant(self, contact_id: str, tenant_id: str) -> Optional[Contact]:
        return (
            self.db.query(Contact)
            .filter(Contact.id == contact_id, Contact.tenant_id == tenant_id)
            .first()
        )

    def message_file_counts(
        self, contact_ids: List[str], tenant_id: str
    ) -> Dict[str, Tuple[int, int]]:
        """`{contact_id: (messages, files)}` for a page, in ONE grouped query.
        Every message counts (notes included). A file is a message whose
        `media_key`, or whose legacy local `media_url` (not on a migrated
        row), sits in the tenant's own storage area: the same rule the purge
        keeps to (`purgeable_key`)."""
        from app.config import settings

        if not contact_ids:
            return {}
        areas = own_area_prefixes(tenant_id)
        url_base = f"{settings.public_base_url}{MEDIA_PATH}"
        if self.db.get_bind().dialect.name == "postgresql":
            minted = ConversationMessage.media_key.op("~")(_MINTED_PG)
        else:
            minted = and_(
                ConversationMessage.media_key.op("GLOB")(_MINTED_GLOB),
                ~ConversationMessage.media_key.like("%/%"),
            )
        key_ok = or_(
            *[ConversationMessage.media_key.startswith(p, autoescape=True) for p in areas],
            *[
                ConversationMessage.media_key.like(f"conn:%:{_like_escape(p)}%", escape="\\")
                for p in areas
            ],
        )
        migrated = (
            self.db.query(MigrationRef.id)
            .filter(
                MigrationRef.tenant_id == tenant_id,
                MigrationRef.entity_type == "message",
                MigrationRef.local_id == ConversationMessage.id,
            )
            .exists()
        )
        key_ok = or_(key_ok, and_(~migrated, minted))
        url_ok = and_(
            ~migrated,
            or_(
                *[ConversationMessage.media_url.startswith(url_base + p, autoescape=True) for p in areas],
                *[
                    ConversationMessage.media_url.like(
                        f"{_like_escape(url_base)}conn:%:{_like_escape(p)}%", escape="\\"
                    )
                    for p in areas
                ],
            ),
        )
        has_file = case((or_(key_ok, url_ok), 1), else_=0)
        rows = (
            self.db.query(
                ConversationMessage.contact_id,
                func.count(ConversationMessage.id),
                func.coalesce(func.sum(has_file), 0),
            )
            .filter(
                ConversationMessage.tenant_id == tenant_id,
                ConversationMessage.contact_id.in_(contact_ids),
            )
            .group_by(ConversationMessage.contact_id)
            .all()
        )
        return {cid: (int(m), int(f)) for cid, m, f in rows}

    def migrated_message_ids(self, message_ids: List[str], tenant_id: str) -> set:
        found: set = set()
        for chunk in _chunks(message_ids):
            found.update(
                r[0]
                for r in self.db.query(MigrationRef.local_id).filter(
                    MigrationRef.tenant_id == tenant_id,
                    MigrationRef.entity_type == "message",
                    MigrationRef.local_id.in_(chunk),
                )
            )
        return found

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

    def add_erasure(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        contact_id: str,
        actor_kind: str,
        actor_user_id: Optional[str],
        api_key_id: Optional[str],
        messages: int,
        files: int,
        erased_at: datetime,
    ) -> ContactErasure:
        """The register row (plan 58), written in the erase's own transaction."""
        row = ContactErasure(
            tenant_id=tenant_id, workspace_id=workspace_id, contact_id=contact_id,
            actor_kind=actor_kind, actor_user_id=actor_user_id, api_key_id=api_key_id,
            messages=messages, files=files, erased_at=erased_at,
        )
        self.db.add(row)
        self.db.flush()
        return row


def _chunks(items: List[Any], size: int = 500):
    for i in range(0, len(items), size):
        yield items[i : i + size]
