"""Inbound webhook processing (plan 05 §4): parse → idempotency → contact
resolution/stitching → persist → CSW re-open → broadcast.

Runs inside the Celery worker (the webhook endpoint only fast-ACKs + enqueues).
All logic takes an explicit db session so tests drive it directly.

Plan 32 (A7a): ONE ingress serves WhatsApp, Messenger and Instagram
(D-A7-2) - ``_resolve_parts`` dispatches on the payload's ``object`` field
before falling back to the URL id; ``_resolve_contact`` runs the phone stitch
ONLY for WhatsApp (D-A7-4, a PSID/IGSID carries no phone); every inbound
message stamps the identity's own re-engagement window via
``messaging_policy.stamp_inbound_window`` (D-A7-5).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..adapters import get_adapter
from ..adapters.meta_graph import provider_error_text, sanitise_stored_pricing
from ..models import Channel, Contact, ContactChannelIdentity, ConversationMessage
from ..phone import digits_only
from ..repositories.contact_repository import ContactRepository
from ..security import signed_media_url
from . import event_service, messaging_policy, realtime, statuses
from .conversation_service import ConversationService

logger = logging.getLogger(__name__)

CSW_WINDOW = timedelta(hours=24)


_TEMPLATE_FIELDS = (
    "message_template_status_update",
    "message_template_quality_update",
    "message_template_category_update",
)
_LOOKUP_CHUNK = 500

# Part kinds: the identifier a webhook part names decides which channel owns it.
_PHONE, _PAGE, _WABA = "phone", "page", "waba"

RoutedPart = Tuple[Optional[str], Optional[str], Dict[str, Any]]  # (kind, identifier, part)


def _ident(value: Any) -> Optional[str]:
    """A usable identifier: a non-empty string or an int, anything else is none."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value:
        return value
    return None


def _routed_parts(payload: Dict[str, Any]) -> List[RoutedPart]:
    """Split a webhook POST into ``(kind, identifier, part)`` triples. Meta may
    batch several entries/changes naming different numbers/pages, so each part
    is routed by its own identifier: a WhatsApp change by
    ``value.metadata.phone_number_id``, a template change by its entry id (the
    WABA id), a Messenger/Instagram entry by its entry id. A part is minimal
    (``object`` plus its one entry/change) so the adapter parses it unchanged.
    Odd shapes are skipped; siblings are still processed."""
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return []
    obj = payload.get("object")
    is_page = obj in ("page", "instagram")
    parts: List[RoutedPart] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = _ident(entry.get("id"))
        if is_page:
            if entry_id is None and entry.get("id") is not None:
                entry_id = ""  # present but unusable: still names an identifier
            parts.append((_PAGE, entry_id, {"object": obj, "entry": [entry]}))
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            part = {"object": obj, "entry": [{"id": entry.get("id"), "changes": [change]}]}
            if change.get("field") in _TEMPLATE_FIELDS:
                parts.append((_WABA, entry_id, part))
                continue
            meta = value.get("metadata")
            raw = meta.get("phone_number_id") if isinstance(meta, dict) else None
            pnid = _ident(raw)
            if pnid is None and raw is not None:
                pnid = ""  # present but unusable: still names an identifier
            parts.append((_PHONE if pnid is not None else None, pnid, part))
    return parts


# Delivery receipts only ever move forward (a late DELIVERED after READ is
# dropped); FAILED always applies.
_STATUS_RANK = {"SENT": 0, "DELIVERED": 1, "READ": 2}


class InboundService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ContactRepository(db)
        self.conversations = ConversationService(db)

    def process_payload(self, channel_id: str, payload: Dict[str, Any]) -> Dict[str, int]:
        """Process one raw webhook payload. Meta delivers ALL numbers/pages to
        one app-level callback URL, so the URL's ``channel_id`` can't identify
        the target: the payload is split into parts and each part is handled
        under the live channel that owns the identifier it names (see
        ``_resolve_parts``). Counters are summed over the parts."""
        from app.repositories.module_repository import ModuleRepository

        counters = {"messages": 0, "statuses": 0, "skipped": 0}
        if not isinstance(payload, dict):
            return counters
        parts = _routed_parts(payload)
        resolved = self._resolve_parts(channel_id, payload.get("object"), parts)
        active: Dict[str, bool] = {}
        for (kind, identifier, part), channels in zip(parts, resolved):
            if not channels:
                logger.warning("webhook part for unknown channel %s dropped", channel_id)
                continue
            for channel in channels:
                # The webhook router is mounted public (no require_module gate) -
                # re-apply the module-active check per resolved channel's tenant
                # so a tenant that uninstalled/deactivated omnichannel doesn't
                # get resurrected inbox rows from late webhooks.
                if channel.tenant_id not in active:
                    active[channel.tenant_id] = ModuleRepository(self.db).is_active(
                        channel.tenant_id, "omnichannel"
                    )
                if not active[channel.tenant_id]:
                    logger.info("webhook for inactive-module tenant %s dropped", channel.tenant_id)
                    continue
                self._handle_part(channel, part, counters)
        return counters

    def process_direct(self, channel: Channel, payload: Dict[str, Any]) -> Dict[str, int]:
        """Handle a canonical-shape payload under an ALREADY-resolved channel
        (web chat: the visitor session names the channel, there is no Meta
        envelope to route). Module-active is checked for the channel's tenant;
        this never resolves a channel from the payload."""
        from app.repositories.module_repository import ModuleRepository

        counters = {"messages": 0, "statuses": 0, "skipped": 0}
        if not ModuleRepository(self.db).is_active(channel.tenant_id, "omnichannel"):
            logger.info("direct payload for inactive-module tenant %s dropped", channel.tenant_id)
            return counters
        self._handle_part(channel, payload, counters)
        return counters

    def _resolve_parts(
        self, channel_id: str, obj: Any, parts: List[RoutedPart]
    ) -> List[List[Channel]]:
        """The channels each part is handled under, in part order. Identifiers
        are looked up in bulk (one ``IN`` query per kind), so the number of
        queries does not grow with the number of parts. A part naming an
        identifier goes to the live channel of the right type that owns it; if
        none does, the URL channel is used ONLY when it is live, of the same
        type and has no identifier of its own (legacy single-channel setups).
        Template events resolve to the live WhatsApp channel(s) of their WABA."""
        page_type = {"page": "FACEBOOK", "instagram": "INSTAGRAM"}.get(obj) if isinstance(obj, str) else None
        channel_type = page_type or "WHATSAPP"
        primary = _PAGE if page_type else _PHONE
        column = Channel.external_account_id if page_type else Channel.phone_number_id
        ids = {i for k, i, _ in parts if k == primary and i}
        # ONE query per kind: the primary identifiers and the URL channel
        # together (chunked), plus one for template WABAs. Query count does not
        # grow with the number of parts.
        owners: Dict[str, List[Channel]] = {}
        url_channel: Optional[Channel] = None
        values = sorted(ids)
        for i in range(0, max(len(values), 1), _LOOKUP_CHUNK):
            rows = (
                self.db.query(Channel)
                .filter(
                    or_(column.in_(values[i : i + _LOOKUP_CHUNK]), Channel.id == channel_id),
                    Channel.is_trashed.is_(False),
                )
                .order_by(Channel.created_at, Channel.id)
                .all()
            )
            for ch in rows:
                if ch.channel_type != channel_type:
                    continue
                if ch.id == channel_id:
                    url_channel = ch
                key = ch.external_account_id if page_type else ch.phone_number_id
                if key in ids:
                    owners.setdefault(key, []).append(ch)
        wabas = {i for k, i, _ in parts if k == _WABA and i}
        waba_owners = self._waba_owners(wabas)

        def legacy_url_channel(names_identifier: bool) -> Optional[Channel]:
            """The URL channel. A part that names an identifier gets it only when
            the channel has no number/account of its own."""
            if url_channel is None:
                return None
            if not names_identifier:
                return url_channel
            own = url_channel.external_account_id if page_type else url_channel.phone_number_id
            return url_channel if own is None else None

        result: List[List[Channel]] = []
        for kind, identifier, _ in parts:
            if kind == _WABA:
                result.append(waba_owners.get(identifier or "", []))
            elif kind == primary and identifier and owners.get(identifier):
                result.append(owners[identifier][:1])
            else:
                fallback = legacy_url_channel(identifier is not None)
                result.append([fallback] if fallback is not None else [])
        return result

    def _waba_owners(self, ids: set) -> Dict[str, List[Channel]]:
        """WABA id -> live WhatsApp channels of that WABA (chunked IN)."""
        found: Dict[str, List[Channel]] = {}
        values = sorted(ids)
        for i in range(0, len(values), _LOOKUP_CHUNK):
            rows = (
                self.db.query(Channel)
                .filter(
                    Channel.waba_id.in_(values[i : i + _LOOKUP_CHUNK]),
                    Channel.channel_type == "WHATSAPP",
                    Channel.is_trashed.is_(False),
                )
                .order_by(Channel.created_at, Channel.id)
                .all()
            )
            for ch in rows:
                found.setdefault(ch.waba_id, []).append(ch)
        return found

    def _handle_part(self, channel: Channel, payload: Dict[str, Any], counters: Dict[str, int]) -> None:
        """Handle the events of one routed part under its own channel."""
        adapter = get_adapter(channel.channel_type)
        try:
            events = adapter.parse_inbound(payload)
        except Exception as exc:  # odd shapes in one part never block its siblings
            logger.warning("webhook part could not be parsed and was dropped (%s)", type(exc).__name__)
            return
        for event in events:
            if event["kind"] == "message":
                if self._handle_message(channel, event):
                    counters["messages"] += 1
                else:
                    counters["skipped"] += 1
            elif event["kind"] == "status":
                if self._handle_status(channel, event):
                    counters["statuses"] += 1
                else:
                    counters["skipped"] += 1
            elif event["kind"] == "reaction":
                if self._handle_reaction(channel, event):
                    counters["reactions"] = counters.get("reactions", 0) + 1
                else:
                    counters["skipped"] += 1
            elif event["kind"] in ("template_status", "template_quality", "template_category"):
                # Template review/quality/category webhooks (plan 07 T6). Safe +
                # idempotent; never crashes the pipeline.
                from .template_management_service import TemplateManagementService

                if TemplateManagementService(self.db).apply_webhook_event(channel, event):
                    counters["templates"] = counters.get("templates", 0) + 1
                else:
                    counters["skipped"] += 1

    # ── Inbound messages ─────────────────────────────────────────────────────
    def _handle_message(self, channel: Channel, event: Dict[str, Any]) -> bool:
        external_id = event.get("external_message_id")
        if not external_id or not event.get("from"):
            return False
        # Idempotency (§4.2.2): Meta retries webhooks - same wamid = skip.
        if self.repo.get_message_by_external_id(external_id, channel.tenant_id):
            return False

        contact, identity = self._resolve_contact(channel, event)

        # Reply context → quoted metadata (mirrors the outbound shape).
        metadata: Optional[Dict[str, Any]] = None
        reply_ext = event.get("reply_to_external_id")
        if reply_ext:
            quoted = self.repo.get_message_by_external_id(reply_ext, channel.tenant_id)
            if quoted is not None:
                sender_name = None
                if quoted.sender_id:
                    names = self.conversations._user_names([quoted.sender_id], channel.tenant_id)
                    sender_name = names.get(quoted.sender_id)
                metadata = {
                    "reply_to": {
                        "id": quoted.id,
                        "body": quoted.body,
                        "senderType": quoted.sender_type,
                        "senderName": sender_name,
                    }
                }

        # Media (§4.2.4 / plan 12 AC-12-09): fetch via Graph + store by KEY.
        # Dev/unconfigured → no key, the body/caption still lands. Plan 32 S5
        # (D-A7-12/AC-CHN-46): Messenger/Instagram never carry a media id -
        # the payload's `media_url` (a short-lived CDN link) is fetched
        # through the SSRF-guarded `fetch_media_url` seam instead.
        media_key = None
        media_mime = event.get("media_mime")
        media_size = None
        media_unavailable = False
        if event.get("media_id"):
            stored = self._store_media(channel, event["media_id"])
            if stored is not None:
                media_key = stored["key"]
                media_mime = stored.get("mime") or media_mime
                media_size = stored.get("size")
        elif event.get("media_url"):
            stored = self._store_media_from_url(
                channel, event["media_url"], kind=event.get("message_type")
            )
            if stored is not None:
                media_key = stored["key"]
                media_mime = stored.get("mime") or media_mime
                media_size = stored.get("size")
            else:
                media_unavailable = True

        message_type = event.get("message_type") or "TEXT"
        # Unsupported inbound type → placeholder, never dropped (plan 12 AC-12-17).
        if message_type == "UNSUPPORTED":
            logger.info(
                "unsupported inbound type '%s' from %s (channel %s) stored as placeholder",
                event.get("original_type"),
                event.get("from"),
                channel.id,
            )

        now = datetime.now(timezone.utc)
        row = ConversationMessage(
            tenant_id=channel.tenant_id,
            contact_id=contact.id,
            channel_id=channel.id,
            sender_type="CONTACT",
            message_type=message_type,
            body=event.get("body"),
            media_key=media_key,
            media_mime=media_mime,
            media_filename=event.get("media_filename"),
            media_size=media_size,
            # Structured payload (interactive-reply / location / contacts, Slice 2).
            # AC-CHN-46: a Messenger/Instagram `pendingMediaUrl` placeholder is
            # CONSUMED here - a successful fetch clears it (the media_key
            # carries the durable reference now); a failure replaces it with
            # a `mediaUnavailable` marker rather than the now-expired CDN URL
            # (persisting a short-lived link for a later retry is dead
            # weight - `fetch_media_url` already retried once inline). The
            # message still lands either way - never dropped.
            payload_json=(
                ({"mediaUnavailable": True} if media_unavailable else None)
                if event.get("media_url")
                else event.get("payload")
            ),
            external_message_id=external_id,
            metadata_json=metadata,
            # Explicit (µs precision) - the DB server_default is second-granular
            # on SQLite, which scrambles ordering for rapid messages.
            created_at=now,
        )
        self.db.add(row)

        # Re-open + CSW reset (§4.2.6): any inbound restarts the 24h window.
        # `reopened`/`unsnoozed` event (plan 27 A3, AC-IVE-04) - capture the
        # PREVIOUS status key before overwriting; an already-OPEN thread
        # writes no event (`new_status_id == contact.status_id` below).
        open_status_id = statuses.status_id_for(self.db, channel.tenant_id, "THREAD", "OPEN")
        if open_status_id != contact.status_id:
            prev_status_id = contact.status_id
            prev_key = self.conversations.status_keys(channel.tenant_id).get(prev_status_id)
            event_type = (
                "reopened" if prev_key == "CLOSED"
                else "unsnoozed" if prev_key == "SNOOZED"
                else None
            )
            if event_type:
                event_service.record(
                    self.db, contact, event_type,
                    from_value=prev_status_id, to_value=open_status_id,
                    channel_id=channel.id,
                )
        contact.status_id = open_status_id
        # `contacts.csw_expires_at`/`last_incoming_message_at` are a WhatsApp-
        # ONLY dual write (plan 32 / A7a, D-A7-5, F4) - the documented gateway
        # field + the composer's window lock must not change meaning for a
        # type that never wrote them before this slice. Every OTHER channel
        # type's window lives on the identity only (stamped below).
        if channel.channel_type == "WHATSAPP":
            contact.csw_expires_at = now + CSW_WINDOW
            contact.last_incoming_message_at = now
        contact.last_message_at = now
        # AC-CHN-21: the identity's OWN window on every channel type.
        messaging_policy.stamp_inbound_window(identity, contact, channel, now=now)
        self.db.commit()
        self.db.refresh(row)

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
        # Fan out to consumer webhooks (Slice 4). event_id = wamid so the consumer
        # dedups across our retries. Failure-isolated inside enqueue_event.
        from .webhook_delivery import consumer_message_payload, enqueue_event

        # The consumer (EMS) fetches media bytes from an ABSOLUTE, API-key-authed
        # gateway URL (plan 12 AC-12-11) - override the inbox-relative mediaUrl.
        # The consumer-facing envelope uses mimeType/filename/size (the EMS
        # integration ticket + UAC), distinct from the internal FE naming.
        message_payload = consumer_message_payload(item, row)

        # Resume a run PARKED on an Ask-a-question step for this contact
        # (plan sprint-4/31 S4, AC-WFP-45, D-A5-8/F2). This runs BEFORE the
        # `message_received` dispatch below and, when it claims the message,
        # CONSUMES it: no `message_received` run is created for an answer, or a
        # workflow that asks a question and is itself triggered by an incoming
        # message would re-ask on every reply. Isolated exactly like the
        # dispatch below - a broken workflow never drops a message.
        consumed_by_wait = False
        try:
            from .workflow_waits import resume_from_inbound

            consumed_by_wait = resume_from_inbound(
                self.db, contact=contact, tenant_id=channel.tenant_id, text=row.body
            )
        except Exception:  # noqa: BLE001 - a broken wait never drops a message
            logger.exception("workflow wait resume failed for inbound message %s", row.id)
            consumed_by_wait = False

        # Start any workflow whose trigger is "Incoming omnichannel message"
        # (plan sprint-4/17) - failure-isolated (CLAUDE.md: workflow dispatch
        # must never break the triggering request), on top of
        # notify_entity_event's own internal dispatch-failure isolation.
        if not consumed_by_wait:
            try:
                from app.workflow_engine.entity_events import notify_entity_event

                name = " ".join(
                    part for part in [contact.first_name, contact.last_name] if part
                ).strip()
                # AC-WFP-14: "first message only" - no PRIOR contact message exists
                # for this contact before the one just inserted (`row`, already
                # flushed above so it has an id to exclude).
                is_first_message = (
                    self.db.query(ConversationMessage.id)
                    .filter(
                        ConversationMessage.tenant_id == channel.tenant_id,
                        ConversationMessage.contact_id == contact.id,
                        ConversationMessage.sender_type == "CONTACT",
                        ConversationMessage.id != row.id,
                    )
                    .first()
                    is None
                )
                notify_entity_event(
                    self.db,
                    "omnichannel_message",
                    "received",
                    row,
                    tenant_id=channel.tenant_id,
                    extra={
                        "channelId": channel.id,
                        "channelName": channel.name,
                        "channelType": channel.channel_type,
                        "workspaceId": channel.workspace_id,
                        "contactId": contact.id,
                        "contactName": name or contact.phone or "",
                        "contactPhone": contact.phone or "",
                        "conversationId": contact.id,
                        "messageId": row.id,
                        "messageType": row.message_type,
                        "messageText": row.body,
                        "mediaUrl": signed_media_url(row.id) if row.media_key else None,
                        "mediaMime": row.media_mime,
                        "isFirstMessage": is_first_message,
                    },
                )
            except Exception:  # noqa: BLE001 - a broken workflow never drops a message
                logger.exception("workflow trigger dispatch failed for inbound message %s", row.id)

        enqueue_event(
            self.db,
            channel,
            "message.inbound",
            external_id,
            {
                "message": message_payload,
                "contact": thread.model_dump(mode="json"),
            },
        )
        return True

    # ── Inbound reactions (plan 12 AC-12-19/20) ──────────────────────────────
    def _handle_reaction(self, channel: Channel, event: Dict[str, Any]) -> bool:
        """A contact reacted to one of our messages. Upsert (emoji) / delete
        (empty emoji) keyed to the target message + reactor - never a bubble.
        Unknown target wamid → drop + log."""
        target_ext = event.get("target_external_id")
        reactor = event.get("from")
        if not target_ext or not reactor:
            return False
        target = self.repo.get_message_by_external_id(target_ext, channel.tenant_id)
        if target is None:
            logger.info(
                "inbound reaction for unknown target %s (channel %s) dropped",
                target_ext,
                channel.id,
            )
            return False
        contact = self.repo.get_by_id(target.contact_id, channel.tenant_id)
        workspace_id = contact.workspace_id if contact is not None else None
        # A reaction is a single emoji - clamp a garbage/oversize payload defensively.
        emoji = (event.get("emoji") or "")[:32]
        _, removed = self.repo.set_reaction(
            target,
            reactor_type="CONTACT",
            reactor=reactor,
            emoji=emoji,
            workspace_id=workspace_id,
        )
        self.db.commit()

        from . import reactions

        reactions.emit_reaction(
            self.db,
            channel,
            workspace_id=workspace_id,
            contact_id=target.contact_id,
            target_message_id=target.id,
            reactor_type="CONTACT",
            emoji=emoji,
            removed=removed,
            event_id=event.get("external_message_id") or f"{target.id}:{reactor}",
        )
        return True

    def _resolve_contact(
        self, channel: Channel, event: Dict[str, Any]
    ) -> Tuple[Contact, ContactChannelIdentity]:
        """Contact resolution & stitching (§4; plan 32 / A7a, D-A7-4): identity
        -> [phone stitch, WHATSAPP ONLY] -> create. A PSID/IGSID carries no
        phone, no email and no stable name - merging on a display name would
        silently fuse two customers, so a non-WhatsApp channel type NEVER
        attempts the phone stitch (an empty digits string must never match a
        phone-less contact, AC-CHN-20)."""
        external_user_id = event["from"]
        identity = self.repo.find_identity(channel.id, external_user_id)
        if identity is not None:
            contact = self.repo.get_by_id(identity.contact_id, channel.tenant_id)
            if contact is not None:
                # Profile names drift - keep the identity fresh.
                if event.get("profile_name") and identity.profile_name != event["profile_name"]:
                    identity.profile_name = event["profile_name"]
                return contact, identity

        is_whatsapp = channel.channel_type == "WHATSAPP"
        digits = digits_only(external_user_id) if is_whatsapp else ""
        contact = None
        if is_whatsapp:
            contact = self.repo.find_by_phone_in_workspace(
                digits, channel.workspace_id, channel.tenant_id
            )

        profile_name = event.get("profile_name") or ""
        if contact is None and not profile_name and not is_whatsapp:
            # Messenger/Instagram never carry a name inline (unlike WhatsApp's
            # `contacts[].profile.name`) - one best-effort Graph lookup, only
            # when actually creating a brand-new contact (AC-CHN-20 "the
            # display name taken from the Graph user profile when available").
            profile_name = self._fetch_profile_name(channel, external_user_id) or ""

        if contact is None:
            from .lifecycle_service import initial_status_id

            first, _, last = profile_name.partition(" ")
            contact = Contact(
                tenant_id=channel.tenant_id,
                workspace_id=channel.workspace_id,
                first_name=first or None,
                last_name=last or None,
                # AC-CHN-20: phone / phone_digits stay NULL for a PSID/IGSID
                # contact - WhatsApp keeps its exact pre-existing shape.
                phone=f"+{digits}" if is_whatsapp else None,
                phone_digits=digits if is_whatsapp else None,
                status_id=statuses.status_id_for(self.db, channel.tenant_id, "THREAD", "OPEN"),
                priority="MEDIUM",
                # A workspace with no lifecycle graph "should not happen" post-
                # backfill (plan 25 S2) - None just leaves the column NULL
                # rather than crash the inbound pipeline (AC-CDM-16).
                lifecycle_status_id=initial_status_id(
                    self.db, channel.tenant_id, channel.workspace_id
                ),
            )
            self.db.add(contact)
            self.db.flush()
            # `opened` event (plan 27 A3, AC-IVE-03) - exactly one per new
            # thread, `to_value` = the OPEN status just assigned above.
            event_service.record(
                self.db, contact, "opened", to_value=contact.status_id, channel_id=channel.id
            )

        new_identity = ContactChannelIdentity(
            tenant_id=channel.tenant_id,
            contact_id=contact.id,
            channel_id=channel.id,
            external_user_id=external_user_id,
            profile_name=event.get("profile_name") or (profile_name or None),
        )
        self.db.add(new_identity)
        self.db.flush()
        return contact, new_identity

    def _fetch_profile_name(self, channel: Channel, external_user_id: str) -> Optional[str]:
        """Best-effort Graph profile-name lookup for a brand-new Messenger/
        Instagram contact (AC-CHN-20) - failure-isolated exactly like
        ``_store_media``: a Graph hiccup must never fail contact creation, and
        dev/unconfigured credentials return ``None`` (the adapter's own
        dev-safe gate)."""
        from ..security import decrypt_credentials

        adapter = get_adapter(channel.channel_type)
        fetch = getattr(adapter, "fetch_profile_name", None)
        if fetch is None:
            return None
        try:
            credentials = decrypt_credentials(channel.credentials_json)
        except Exception:  # noqa: BLE001 - bad/dev credentials: no name, keep the message
            return None
        try:
            return fetch(credentials, external_user_id)
        except Exception:  # noqa: BLE001 - a Graph hiccup must never break contact creation
            logger.exception(
                "profile-name lookup failed for channel %s user %s", channel.id, external_user_id
            )
            return None

    def _store_media(self, channel: Channel, media_id: str) -> Optional[Dict[str, Any]]:
        """Fetch inbound media via Graph + store by KEY (plan 12 AC-12-09).
        Returns {key, mime, size} or None (dev/unconfigured/hiccup - media-less
        beats a dropped message)."""
        from app.services.storage import storage_for_tenant

        from ..security import decrypt_credentials

        adapter = get_adapter(channel.channel_type)
        try:
            credentials = decrypt_credentials(channel.credentials_json)
        except Exception:  # noqa: BLE001 - bad/dev credentials: skip media, keep the message
            return None
        blob = adapter.fetch_media(credentials, media_id)
        if not blob:
            return None
        content = blob["content"]
        mime = blob.get("mime_type") or "application/octet-stream"
        # Connection-driven storage (plan 06 D1). Best-effort: a storage hiccup
        # (bad bucket creds, network) must not fail the task and drop the MESSAGE.
        try:
            key = storage_for_tenant(self.db, channel.tenant_id).save(
                f"omnichannel/{channel.tenant_id}/{media_id}", content, mime
            )
        except Exception:  # noqa: BLE001
            logger.exception("media store failed for channel %s media %s", channel.id, media_id)
            return None
        return {"key": key, "mime": mime, "size": len(content)}

    def _store_media_from_url(
        self, channel: Channel, url: str, *, kind: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Inbound Messenger/Instagram attachment (plan 32 S5, D-A7-12/
        AC-CHN-46/47): the payload carries a short-lived CDN URL, not a media
        id. Downloaded with the page token through `adapter.fetch_media_url`
        (HTTPS + Meta CDN allowlist + the shared SSRF guard + capped read +
        bounded redirects + a bounded inline retry, ALL enforced inside the
        adapter that owns the CDN allowlist) then stored through the SAME
        `storage_for_tenant` path as WhatsApp media - a storage hiccup loses
        the media, never the message. ``kind`` (the resolved house message
        type) widens the adapter's sniff allowlist for a `"DOCUMENT"` row to
        the outbound document family (should-fix, security review round 1) -
        every other kind is unaffected. Returns {key, mime, size} or None."""
        from app.services.storage import storage_for_tenant

        from ..security import decrypt_credentials

        adapter = get_adapter(channel.channel_type)
        fetch = getattr(adapter, "fetch_media_url", None)
        if fetch is None:
            return None
        try:
            credentials = decrypt_credentials(channel.credentials_json)
        except Exception:  # noqa: BLE001 - bad/dev credentials: skip media, keep the message
            return None
        try:
            blob = fetch(credentials, url, kind=kind)
        except Exception:  # noqa: BLE001 - a fetch hiccup must never drop the message
            logger.exception("media URL fetch failed for channel %s", channel.id)
            return None
        if not blob:
            return None
        content = blob["content"]
        mime = blob.get("mime_type") or "application/octet-stream"
        # Connection-driven storage (plan 06 D1). Best-effort: a storage hiccup
        # (bad bucket creds, network) must not fail the task and drop the MESSAGE.
        try:
            key = storage_for_tenant(self.db, channel.tenant_id).save(
                f"omnichannel/{channel.tenant_id}/{uuid4().hex}", content, mime
            )
        except Exception:  # noqa: BLE001
            logger.exception("media store (url fetch) failed for channel %s", channel.id)
            return None
        return {"key": key, "mime": mime, "size": len(content)}

    # ── Delivery receipts ────────────────────────────────────────────────────
    def _handle_status(self, channel: Channel, event: Dict[str, Any]) -> bool:
        """Apply a `status` event to every message it targets. WhatsApp
        (unchanged, AC-CHN-23): one `external_message_id` per webhook row.
        Messenger/Instagram (plan 32 S5, D-A7-22): a `delivery`/`read`
        webhook carries `mids[]` when Meta has them, else only a `watermark`
        - every outbound message sent at or before that instant is a target.
        Whatever the target set, EACH message goes through the same
        `_apply_receipt` (rank-forward guard, broadcast hook, realtime
        publish, consumer-webhook fan-out) - one path, never a second one for
        the bulk case. Returns True iff at least one target actually moved."""
        new_status = event.get("status")
        if new_status not in ("SENT", "DELIVERED", "READ", "FAILED"):
            return False
        targets = self._resolve_status_targets(channel, event)
        if not targets:
            return False
        applied_any = False
        for msg in targets:
            if self._apply_receipt(channel, msg, new_status, event):
                applied_any = True
        return applied_any

    def _resolve_status_targets(
        self, channel: Channel, event: Dict[str, Any]
    ) -> List[ConversationMessage]:
        """WhatsApp/Messenger's per-message case: `external_message_id`
        resolves ONE row (AC-CHN-23, byte-identical). Messenger/Instagram's
        `mids[]` (AC-CHN-49 "by mids[] when present") resolves each mid
        exactly. Otherwise (Messenger/Instagram with no mids) fall back to
        the `watermark` (D-A7-22): resolve the sending identity by PSID/IGSID
        (`event["from"]`) and target every outbound row on that thread sent
        at or before the watermark instant."""
        external_id = event.get("external_message_id")
        if external_id:
            msg = self.repo.get_message_by_external_id(external_id, channel.tenant_id)
            return [msg] if msg is not None else []

        mids = event.get("mids") or []
        if mids:
            seen: set = set()
            targets: List[ConversationMessage] = []
            for mid in mids:
                # Channel-scoped like the sibling watermark path (nit,
                # security review round 1) - Meta mids are globally unique
                # in practice, but the two receipt paths should scope
                # identically.
                msg = self.repo.get_message_by_external_id(mid, channel.tenant_id, channel_id=channel.id)
                if msg is not None and msg.id not in seen:
                    seen.add(msg.id)
                    targets.append(msg)
            return targets

        watermark = event.get("watermark")
        sender = event.get("from")
        if watermark is None or not sender:
            return []
        identity = self.repo.find_identity(channel.id, sender)
        if identity is None:
            return []
        try:
            at = datetime.fromtimestamp(int(watermark) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return []  # malformed watermark - never crash the inbound pipeline
        return self.repo.outbound_before_watermark(
            identity.contact_id, channel.id, channel.tenant_id, at=at
        )

    def _apply_receipt(
        self, channel: Channel, msg: ConversationMessage, new_status: str, event: Dict[str, Any]
    ) -> bool:
        """The ONE per-message receipt application (rank-forward guard +
        commit + broadcast hook + realtime publish + consumer-webhook fan-out)
        - shared verbatim by the single-`external_message_id` case AND every
        message a watermark/`mids[]` receipt bulk-targets."""
        # Meta's per-message pricing (plan 56 B): the latest non-null object
        # wins and is kept even when the status itself does not move forward.
        pricing = event.get("pricing") if msg.sender_type != "CONTACT" else None
        if isinstance(pricing, dict) and pricing:
            msg.metadata_json = {
                **(msg.metadata_json if isinstance(msg.metadata_json, dict) else {}),
                "pricing": dict(pricing),
            }
        if new_status == "FAILED":
            msg.delivery_status = "FAILED"
            msg.error_code = event.get("error_code")
            msg.error_message = (
                provider_error_text(str(event.get("error_message") or ""))
                or "The provider could not deliver this message"
            )
        else:
            current = _STATUS_RANK.get(msg.delivery_status or "SENT", 0)
            if _STATUS_RANK[new_status] <= current and msg.delivery_status:
                if isinstance(pricing, dict):
                    self.db.commit()  # pricing alone: no status change, no webhook
                return False  # receipts only move forward
            msg.delivery_status = new_status
        self.db.commit()

        # Broadcast receipt hook (plan 29 S2b, D-A4-10) - AFTER this commit,
        # BEFORE the consumer-webhook enqueue below. A broadcast bug must
        # NEVER break the inbound webhook pipeline.
        # Plain locals first: the rollback below expires ORM attributes.
        msg_id = msg.id
        contact_id = msg.contact_id
        status_now = msg.delivery_status
        error_now = msg.error_message
        error_code_now = msg.error_code
        ext_id = msg.external_message_id
        pricing_now = sanitise_stored_pricing(
            msg.metadata_json.get("pricing") if isinstance(msg.metadata_json, dict) else None
        )
        try:
            from .broadcast_receipts import record_delivery

            record_delivery(self.db, msg)
        except Exception:  # noqa: BLE001
            try:
                self.db.rollback()
            except Exception:  # noqa: BLE001
                pass
            logger.exception("broadcast receipt hook failed for message %s", msg_id)

        contact = self.repo.get_by_id(contact_id, channel.tenant_id)
        if contact is not None:
            realtime.publish(
                contact.workspace_id,
                {
                    "type": "message.status",
                    "messageId": msg_id,
                    "contactId": contact_id,
                    "deliveryStatus": status_now,
                    "errorMessage": error_now,
                },
            )
        # Fan out the receipt to consumer webhooks (Slice 4). event_id per status
        # so each transition (sent→delivered→read) is a distinct consumer event.
        from .webhook_delivery import enqueue_event

        enqueue_event(
            self.db,
            channel,
            "message.status",
            f"{msg_id}:{status_now}",
            {
                "messageId": msg_id,
                "externalMessageId": ext_id,
                "contactId": contact_id,
                "deliveryStatus": status_now,
                # Error fields ride FAILED only (AC-38-15).
                "errorCode": error_code_now if status_now == "FAILED" else None,
                "errorMessage": error_now if status_now == "FAILED" else None,
                "pricing": pricing_now,
            },
        )
        return True
