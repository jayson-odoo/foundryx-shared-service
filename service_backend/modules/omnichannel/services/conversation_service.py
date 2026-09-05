"""Conversation (thread + message) service - plan 05.

Maps Contact/ConversationMessage rows to the camelCase API shapes, resolves
status keys + user display names, maintains the read marker, and applies the
PATCH operations (assign / lifecycle / priority).
"""
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.status import Status as CoreStatus
from app.models.user import User
from ..models import Channel, Contact, ConversationMessage, Status
from ..repositories.contact_repository import ContactRepository
from ..schemas import ContactLifecycleSummary, ContactTagRefItem, MessageItem, ReplyRefItem, ThreadItem
from . import realtime, statuses
from .contact_tag_service import ContactTagService
from .lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY_TYPE
from .lifecycle_service import fireable_moves as _lifecycle_fireable_moves
from .lifecycle_service import move as _lifecycle_move

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

    def _user_names(self, user_ids: List[str], tenant_id: str) -> Dict[str, str]:
        """Batched id → display name, TENANT-SCOPED.

        The polymorphic-target_id house rule: a STORED user id must be resolved
        scoped, never by bare id. `assigned_user_id` is validated on write by
        `patch_thread`, but it is not the only writer and `sender_id` is never
        validated - and this resolves to a name/EMAIL that is rendered to the
        caller, including on the key-authed public gateway. An id belonging to
        another tenant must resolve to nothing, not to their user's address."""
        ids = [u for u in set(user_ids) if u]
        if not ids:
            return {}
        rows = (
            self.db.query(User)
            .filter(User.tenant_id == tenant_id, User.id.in_(ids))
            .all()
        )
        return {u.id: (u.name or u.email) for u in rows}

    def _external_agents(self, agent_ids: List[str], tenant_id: str):
        """Tenant-scoped id → ExternalAgent for federated-attribution display
        (plan 11H Slice 1). Batched; returns {} when there are no embed ids."""
        from .external_agent_service import ExternalAgentService

        ids = [a for a in set(agent_ids) if a]
        if not ids:
            return {}
        return ExternalAgentService(self.db).names(ids, tenant_id)

    def _lifecycle_map(
        self, contacts: List[Contact], tenant_id: str
    ) -> Dict[Tuple[str, str], ContactLifecycleSummary]:
        """Batched `(workspace_id, lifecycle_status_id) -> ContactLifecycleSummary`,
        resolved tenant + entity-type + WORKSPACE (scope_id) scoped in ONE query
        (AC-CDM-19; the polymorphic stored-id rule - never resolve a stored
        status id unscoped). The lifecycle machine is scoped per workspace
        (`Status.scope_id == workspace_id`), so a status id that happens to
        exist for another workspace of the same tenant must NOT resolve -
        keying by `(scope_id, status_id)` enforces that."""
        pairs = {
            (c.workspace_id, c.lifecycle_status_id)
            for c in contacts
            if c.lifecycle_status_id
        }
        if not pairs:
            return {}
        status_ids = {sid for _, sid in pairs}
        rows = (
            self.db.query(CoreStatus)
            .filter(
                CoreStatus.id.in_(status_ids),
                CoreStatus.tenant_id == tenant_id,
                CoreStatus.entity_type == LIFECYCLE_ENTITY_TYPE,
            )
            .all()
        )
        by_id = {s.id: s for s in rows}
        result: Dict[Tuple[str, str], ContactLifecycleSummary] = {}
        for workspace_id, status_id in pairs:
            s = by_id.get(status_id)
            if s is None or s.scope_id != workspace_id:
                continue
            result[(workspace_id, status_id)] = ContactLifecycleSummary(
                statusId=s.id,
                key=s.key,
                label=s.label,
                color=s.color,
                isWon=bool(s.is_terminal),
                isLost=bool(s.is_archived),
            )
        return result

    def _channel_types(self, channel_ids: List[str], tenant_id: str) -> Dict[str, str]:
        """Tenant-scoped for the same reason as `_user_names` (lower impact -
        leaks only a channel_type - but the same stored-id resolution rule)."""
        ids = [c for c in set(channel_ids) if c]
        if not ids:
            return {}
        rows = (
            self.db.query(Channel)
            .filter(Channel.tenant_id == tenant_id, Channel.id.in_(ids))
            .all()
        )
        return {c.id: c.channel_type for c in rows}

    def _field_registry(self, contacts: List[Contact], tenant_id: str) -> Dict[str, set]:
        """`workspace_id -> {registered ContactField.key}`, ONE query per
        DISTINCT workspace on the page (not per contact) - the guide (~716)
        and AC-CDM promise registered keys only on the wire. Used to intersect
        `custom_fields_json`'s raw blob so a legacy/unregistered key (a field
        deleted from the registry after some contacts still carry stale JSON)
        never surfaces on any read path (list/detail/gateway/webhook -
        review round 1, finding 5)."""
        from .contact_field_service import ContactFieldService

        workspace_ids = {c.workspace_id for c in contacts if c.workspace_id}
        if not workspace_ids:
            return {}
        svc = ContactFieldService(self.db)
        return {
            ws_id: {f.key for f in svc.list(ws_id, tenant_id)} for ws_id in workspace_ids
        }

    # ── Mapping ──────────────────────────────────────────────────────────────
    def _thread_items(self, contacts: List[Contact], tenant_id: str) -> List[ThreadItem]:
        if not contacts:
            return []
        ids = [c.id for c in contacts]
        previews = self.repo.previews_for(ids, tenant_id)
        unread = self.repo.unread_counts_for(contacts, tenant_id)
        status_keys = self._status_keys(tenant_id)
        names = self._user_names([c.assigned_user_id for c in contacts], tenant_id)
        agents = self._external_agents(
            [c.assigned_external_agent_id for c in contacts], tenant_id
        )
        channel_types = self._channel_types(
            [previews[c.id].channel_id for c in contacts if c.id in previews], tenant_id
        )
        tag_refs = ContactTagService(self.db).refs_for_contacts(ids, tenant_id)
        lifecycle_map = self._lifecycle_map(contacts, tenant_id)
        field_registry = self._field_registry(contacts, tenant_id)

        items: List[ThreadItem] = []
        for c in contacts:
            preview = previews.get(c.id)
            channel_id = preview.channel_id if preview else None
            # Assignee display resolves from whichever assignee column is set -
            # native user OR federated external agent (they are mutually exclusive).
            agent = agents.get(c.assigned_external_agent_id) if c.assigned_external_agent_id else None
            if agent is not None:
                assigned_name = agent.name
                assigned_avatar = agent.avatar_url
            else:
                assigned_name = names.get(c.assigned_user_id) if c.assigned_user_id else None
                assigned_avatar = None
            items.append(
                ThreadItem(
                    id=c.id,
                    tenantId=c.tenant_id,
                    workspaceId=c.workspace_id,
                    name=contact_display_name(c),
                    firstName=c.first_name,
                    lastName=c.last_name,
                    phone=c.phone,
                    email=c.email,
                    language=c.language,
                    countryCode=c.country_code,
                    avatarUrl=c.avatar_url,
                    assignedUserId=c.assigned_user_id,
                    assignedUserName=assigned_name,
                    assignedExternalAgentId=c.assigned_external_agent_id,
                    assignedAvatarUrl=assigned_avatar,
                    status=status_keys.get(c.status_id, "OPEN"),
                    priority=c.priority or "MEDIUM",
                    channelId=channel_id,
                    channelType=channel_types.get(channel_id, "WHATSAPP"),
                    cswExpiresAt=c.csw_expires_at,
                    lastIncomingMessageAt=c.last_incoming_message_at,
                    lastMessageAt=c.last_message_at,
                    lastMessagePreview=preview.body if preview else None,
                    unreadCount=unread.get(c.id, 0),
                    customFields={
                        k: v
                        for k, v in (c.custom_fields_json or {}).items()
                        if k in field_registry.get(c.workspace_id, set())
                    },
                    tags=[ContactTagRefItem(**t) for t in tag_refs.get(c.id, [])],
                    lifecycle=(
                        lifecycle_map.get((c.workspace_id, c.lifecycle_status_id))
                        if c.lifecycle_status_id
                        else None
                    ),
                    createdAt=c.created_at,
                )
            )
        return items

    def thread_item(self, contact: Contact) -> ThreadItem:
        return self._thread_items([contact], contact.tenant_id)[0]

    def message_items(self, messages: List[ConversationMessage]) -> List[MessageItem]:
        tenant_id = messages[0].tenant_id if messages else ""
        names = self._user_names([m.sender_id for m in messages if m.sender_id], tenant_id)
        agents = self._external_agents(
            [m.sender_external_agent_id for m in messages if m.sender_external_agent_id],
            tenant_id,
        )
        # Batched reaction chips (plan 12 Slice 3) - one query for the whole page.
        reactions_by_msg = self.repo.reactions_for(
            [m.id for m in messages],
            tenant_id,
        )
        items: List[MessageItem] = []
        for m in messages:
            meta = m.metadata_json or {}
            reply = meta.get("reply_to")
            # Sender display resolves from whichever sender column is set - native
            # user OR federated external agent.
            agent = agents.get(m.sender_external_agent_id) if m.sender_external_agent_id else None
            if agent is not None:
                sender_name = agent.name
                sender_avatar = agent.avatar_url
            else:
                sender_name = names.get(m.sender_id) if m.sender_id else None
                sender_avatar = None
            items.append(
                MessageItem(
                    reactions=reactions_by_msg.get(m.id, []),
                    id=m.id,
                    contactId=m.contact_id,
                    channelId=m.channel_id,
                    senderType=m.sender_type,
                    senderId=m.sender_id,
                    senderName=sender_name,
                    senderExternalAgentId=m.sender_external_agent_id,
                    senderAvatarUrl=sender_avatar,
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

    # ── Lifecycle (plan 25 S2) ───────────────────────────────────────────────
    def move_lifecycle(
        self, contact_id: str, tenant_id: str, to_status_id: str, actor: Optional[User] = None
    ) -> ThreadItem:
        """Move a contact's lifecycle stage (AC-CDM-17). Raises
        `LifecycleStageNotFound` / the `status_machine` errors on failure - the
        router maps them to 404/403/409; nothing is written on any of them
        (the executor validates before it ever calls `setattr`)."""
        c = self.repo.get_by_id(contact_id, tenant_id)
        if c is None:
            raise ThreadNotFound()
        _lifecycle_move(self.db, c, to_status_id, actor=actor)
        self.db.commit()
        self.db.refresh(c)
        item = self.thread_item(c)
        self._publish_contact_updated(c, item, tenant_id)
        return item

    def _publish_contact_updated(self, c: Contact, item: ThreadItem, tenant_id: str) -> None:
        """ONE fan-out for every `contact.updated` producer - realtime WS/pubsub
        for the internal inbox AND the consumer-webhook event the guide (`## 6`)
        promises on "any lifecycle change". `move_lifecycle` and `patch_thread`
        both call this (review round 1, finding 1) so an internal lifecycle move
        (no profile fields touched) still fans out to consumer webhooks, not
        just realtime. Fully isolated - the caller already committed, forwarding
        must never fail the request."""
        realtime.publish(
            c.workspace_id,
            {"type": "contact.updated", "thread": item.model_dump(mode="json")},
        )
        # Endpoints are per-channel, so forward on the contact's current
        # channel (its latest message's); skip if the contact has never
        # messaged on a channel yet.
        if not item.channelId:
            return
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
        except Exception:  # noqa: BLE001 - forwarding never breaks the caller
            logger.exception("contact.updated webhook fan-out failed for %s", c.id)

    def lifecycle_moves(
        self, contact_id: str, tenant_id: str, actor: Optional[User] = None
    ) -> list:
        """Fireable outgoing edges for this contact right now (AC-CDM-18)."""
        c = self.repo.get_by_id(contact_id, tenant_id)
        if c is None:
            raise ThreadNotFound()
        return _lifecycle_fireable_moves(self.db, c, actor=actor)

    # ── Patch (assign / lifecycle / priority / profile) ─────────────────────
    def patch_thread(
        self,
        contact_id: str,
        tenant_id: str,
        *,
        assigned_user_id: Optional[str] = ...,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        first_name: Optional[str] = ...,
        last_name: Optional[str] = ...,
        phone: Optional[str] = ...,
        email: Optional[str] = ...,
        language: Optional[str] = ...,
        country_code: Optional[str] = ...,
        custom_fields: Optional[dict] = ...,
        tag_ids: Optional[list] = ...,
        lifecycle_status_id: Optional[str] = ...,
        actor: Optional[User] = None,
        actor_id: Optional[str] = None,
        external_connection_id: Optional[str] = None,
    ) -> ThreadItem:
        c = self.repo.get_by_id(contact_id, tenant_id)
        if c is None:
            raise ThreadNotFound()

        if assigned_user_id is not ...:
            if external_connection_id is not None:
                # Embed principal: the assignee id is an EXTERNAL agent id - it
                # must belong to the token's connection (a token can only assign
                # to its own consumer's agents; cross-consumer is impossible).
                if assigned_user_id is not None:
                    from .external_agent_service import ExternalAgentService

                    agent = ExternalAgentService(self.db).get_for_connection(
                        assigned_user_id, external_connection_id, tenant_id
                    )
                    if agent is None:
                        raise InvalidPatch("Assignee not found for this consumer.")
                # Federated + native assignees are mutually exclusive.
                c.assigned_external_agent_id = assigned_user_id
                c.assigned_user_id = None
            else:
                if assigned_user_id is not None:
                    user = (
                        self.db.query(User)
                        .filter(User.id == assigned_user_id, User.tenant_id == tenant_id)
                        .first()
                    )
                    if user is None:
                        raise InvalidPatch("Assignee not found in this tenant.")
                c.assigned_user_id = assigned_user_id
                c.assigned_external_agent_id = None

        if status is not None:
            if status not in VALID_THREAD_STATUS:
                raise InvalidPatch(f"Invalid thread status: {status}")
            c.status_id = statuses.status_id_for(self.db, tenant_id, "THREAD", status)

        if priority is not None:
            if priority not in VALID_PRIORITY:
                raise InvalidPatch(f"Invalid priority: {priority}")
            c.priority = priority

        # System fields + typed custom fields + tags (plan 25) route through the
        # ONE contact-profile seam so validation (AC-CDM-06/07/10) applies on
        # every write path (this method is called by both the internal PATCH
        # and the gateway PATCH) and the `omnichannel_contact` `updated` entity
        # event carries a real `changes` diff (AC-CDM-23).
        profile_kwargs: dict = {}
        if first_name is not ...:
            profile_kwargs["first_name"] = first_name
        if last_name is not ...:
            profile_kwargs["last_name"] = last_name
        if phone is not ...:
            profile_kwargs["phone"] = phone
        if email is not ...:
            profile_kwargs["email"] = email
        if language is not ...:
            profile_kwargs["language"] = language
        if country_code is not ...:
            profile_kwargs["country_code"] = country_code
        if custom_fields is not ...:
            profile_kwargs["custom_fields"] = custom_fields
        if tag_ids is not ...:
            profile_kwargs["tag_ids"] = tag_ids
        if profile_kwargs:
            from .contact_profile_service import ContactProfileService

            ContactProfileService(self.db).patch(
                c, actor=actor, actor_id=actor_id, **profile_kwargs
            )

        # A lifecycle move (plan 25 S3, gateway PATCH `lifecycle:`) rides the
        # SAME unit of work as the profile patch above - `_lifecycle_move`
        # validates the edge graph and raises BEFORE writing anything
        # (`status_machine.transition` never `setattr`s until every check
        # passes), so a bad target/no-edge/forbidden move rolls back any
        # profile/tag changes already applied in this same call, and nothing
        # is committed until BOTH have succeeded.
        if lifecycle_status_id is not ...:
            _lifecycle_move(self.db, c, lifecycle_status_id, actor=actor)

        self.db.commit()
        self.db.refresh(c)
        item = self.thread_item(c)
        # Other agents' inboxes update live (assignment moves threads between
        # buckets; snooze/close changes the row chip) AND fan out to consumer
        # webhooks (Slice 4) - the ONE shared publisher (finding 1).
        self._publish_contact_updated(c, item, tenant_id)
        return item
