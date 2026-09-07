"""Inbound webhook processing (plan 05 §4): parse → idempotency → contact
resolution/stitching → persist → CSW re-open → broadcast.

Runs inside the Celery worker (the webhook endpoint only fast-ACKs + enqueues).
All logic takes an explicit db session so tests drive it directly.

Plan 32 (A7a): ONE ingress serves WhatsApp, Messenger and Instagram
(D-A7-2) - ``_resolve_channel`` dispatches on the payload's ``object`` field
before falling back to the URL id; ``_resolve_contact`` runs the phone stitch
ONLY for WhatsApp (D-A7-4, a PSID/IGSID carries no phone); every inbound
message stamps the identity's own re-engagement window via
``messaging_policy.stamp_inbound_window`` (D-A7-5).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings

from ..adapters import get_adapter
from ..models import Channel, Contact, ContactChannelIdentity, ConversationMessage
from ..phone import digits_only
from ..repositories.contact_repository import ContactRepository
from ..security import signed_media_url
from . import event_service, messaging_policy, realtime, statuses
from .conversation_service import ConversationService

logger = logging.getLogger(__name__)

CSW_WINDOW = timedelta(hours=24)


def _payload_phone_number_id(payload: Dict[str, Any]) -> Optional[str]:
    """Pull ``entry[].changes[].value.metadata.phone_number_id`` from a WhatsApp
    webhook - the number the event is FOR (Meta uses one app-level callback)."""
    try:
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                meta = (change.get("value") or {}).get("metadata") or {}
                pnid = meta.get("phone_number_id")
                if pnid:
                    return str(pnid)
    except AttributeError:
        pass
    return None


def _payload_entry_id(payload: Dict[str, Any]) -> Optional[str]:
    """Pull ``entry[].id`` (PAGE_ID or IG account id) from a Messenger/
    Instagram webhook payload - the same "one app-level callback, the payload
    picks the tenant" pattern as ``_payload_phone_number_id`` (D-A7-2)."""
    try:
        for entry in payload.get("entry", []) or []:
            eid = entry.get("id")
            if eid:
                return str(eid)
    except AttributeError:
        pass
    return None

# Delivery receipts only ever move forward (a late DELIVERED after READ is
# dropped); FAILED always applies.
_STATUS_RANK = {"SENT": 0, "DELIVERED": 1, "READ": 2}


class InboundService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ContactRepository(db)
        self.conversations = ConversationService(db)

    def process_payload(self, channel_id: str, payload: Dict[str, Any]) -> Dict[str, int]:
        """Process one raw webhook payload. The channel is resolved by the
        payload's ``metadata.phone_number_id`` (Meta delivers ALL numbers to the
        one app-level callback URL, so the URL's ``channel_id`` can't identify the
        number) - falling back to the URL id for the single-channel/legacy case.
        This is what makes multi-number correct: number #2's inbound is attributed
        to number #2's channel, not the URL's."""
        channel = self._resolve_channel(channel_id, payload)
        if channel is None:
            logger.warning("webhook for unknown channel %s dropped", channel_id)
            return {"messages": 0, "statuses": 0, "skipped": 0}

        # The webhook router is mounted public (no require_module gate) - re-apply
        # the module-active check here so a tenant that uninstalled/deactivated
        # omnichannel doesn't get resurrected inbox rows from late webhooks.
        from app.repositories.module_repository import ModuleRepository

        if not ModuleRepository(self.db).is_active(channel.tenant_id, "omnichannel"):
            logger.info("webhook for inactive-module tenant %s dropped", channel.tenant_id)
            return {"messages": 0, "statuses": 0, "skipped": 0}

        adapter = get_adapter(channel.channel_type)
        counters = {"messages": 0, "statuses": 0, "skipped": 0}
        for event in adapter.parse_inbound(payload):
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
        return counters

    def _resolve_channel(self, channel_id: str, payload: Dict[str, Any]) -> Optional[Channel]:
        """Dispatch on the payload's ``object`` field (D-A7-2): ``page``/
        ``instagram`` resolve a live FACEBOOK/INSTAGRAM channel by
        ``external_account_id``; ``whatsapp_business_account`` (or absent, the
        pre-plan-32 shape) keeps today's ``phone_number_id`` path. The URL's
        channel id is the LAST-RESORT fallback for all three - every
        already-configured per-channel callback URL keeps working, and Meta's
        one app-level callback delivering every tenant's traffic is exactly
        why the payload, never the URL, is authoritative.

        ``external_account_id`` carries its own service-wide PARTIAL UNIQUE
        index over live rows (migration 0017, same design as
        ``phone_number_id``), so this lookup - though intentionally
        unauthenticated, the webhook has no tenant context yet - can only ever
        resolve the ONE channel that legitimately owns that page/account id,
        never a different tenant's."""
        object_type = payload.get("object")
        if object_type in ("page", "instagram"):
            channel_type = "FACEBOOK" if object_type == "page" else "INSTAGRAM"
            entry_id = _payload_entry_id(payload)
            if entry_id:
                by_account = (
                    self.db.query(Channel)
                    .filter(
                        Channel.external_account_id == entry_id,
                        Channel.channel_type == channel_type,
                        Channel.is_trashed.is_(False),
                    )
                    .first()
                )
                if by_account is not None:
                    return by_account
            return self.db.query(Channel).filter(Channel.id == channel_id).first()

        # whatsapp_business_account (or absent) - today's path, unchanged.
        pnid = _payload_phone_number_id(payload)
        if pnid:
            by_phone = (
                self.db.query(Channel)
                .filter(
                    Channel.phone_number_id == pnid,
                    Channel.is_trashed.is_(False),
                )
                .first()
            )
            if by_phone is not None:
                return by_phone
        return self.db.query(Channel).filter(Channel.id == channel_id).first()

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
            stored = self._store_media_from_url(channel, event["media_url"])
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
        from .webhook_delivery import enqueue_event

        # The consumer (EMS) fetches media bytes from an ABSOLUTE, API-key-authed
        # gateway URL (plan 12 AC-12-11) - override the inbox-relative mediaUrl.
        # The consumer-facing envelope uses mimeType/filename/size (the EMS
        # integration ticket + UAC), distinct from the internal FE naming.
        message_payload = item.model_dump(mode="json")
        if row.media_key:
            message_payload["mediaUrl"] = (
                f"{settings.public_base_url}/omnichannel/media/{row.id}"
            )
            message_payload["mimeType"] = message_payload.pop("mediaMime", None)
            message_payload["filename"] = message_payload.pop("mediaFilename", None)
            message_payload["size"] = message_payload.pop("mediaSize", None)

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

    def _store_media_from_url(self, channel: Channel, url: str) -> Optional[Dict[str, Any]]:
        """Inbound Messenger/Instagram attachment (plan 32 S5, D-A7-12/
        AC-CHN-46/47): the payload carries a short-lived CDN URL, not a media
        id. Downloaded with the page token through `adapter.fetch_media_url`
        (HTTPS + Meta CDN allowlist + the shared SSRF guard + capped read +
        bounded redirects + a bounded inline retry, ALL enforced inside the
        adapter that owns the CDN allowlist) then stored through the SAME
        `storage_for_tenant` path as WhatsApp media - a storage hiccup loses
        the media, never the message. Returns {key, mime, size} or None."""
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
            blob = fetch(credentials, url)
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
                msg = self.repo.get_message_by_external_id(mid, channel.tenant_id)
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
        if new_status == "FAILED":
            msg.delivery_status = "FAILED"
            msg.error_code = event.get("error_code")
            msg.error_message = event.get("error_message")
        else:
            current = _STATUS_RANK.get(msg.delivery_status or "SENT", 0)
            if _STATUS_RANK[new_status] <= current and msg.delivery_status:
                return False  # receipts only move forward
            msg.delivery_status = new_status
        self.db.commit()

        # Broadcast receipt hook (plan 29 S2b, D-A4-10) - AFTER this commit,
        # BEFORE the consumer-webhook enqueue below. A broadcast bug must
        # NEVER break the inbound webhook pipeline.
        try:
            from .broadcast_receipts import record_delivery

            record_delivery(self.db, msg)
        except Exception:  # noqa: BLE001
            logger.exception("broadcast receipt hook failed for message %s", msg.id)

        contact = self.repo.get_by_id(msg.contact_id, channel.tenant_id)
        if contact is not None:
            realtime.publish(
                contact.workspace_id,
                {
                    "type": "message.status",
                    "messageId": msg.id,
                    "contactId": msg.contact_id,
                    "deliveryStatus": msg.delivery_status,
                    "errorMessage": msg.error_message,
                },
            )
        # Fan out the receipt to consumer webhooks (Slice 4). event_id per status
        # so each transition (sent→delivered→read) is a distinct consumer event.
        from .webhook_delivery import enqueue_event

        enqueue_event(
            self.db,
            channel,
            "message.status",
            f"{msg.id}:{msg.delivery_status}",
            {
                "messageId": msg.id,
                "externalMessageId": msg.external_message_id,
                "contactId": msg.contact_id,
                "deliveryStatus": msg.delivery_status,
                "errorCode": msg.error_code,
                "errorMessage": msg.error_message,
            },
        )
        return True
