"""Inbound webhook processing (plan 05 §4): parse → idempotency → contact
resolution/stitching → persist → CSW re-open → broadcast.

Runs inside the Celery worker (the webhook endpoint only fast-ACKs + enqueues).
All logic takes an explicit db session so tests drive it directly.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.config import settings

from ..adapters.whatsapp_cloud import get_adapter
from ..models import Channel, Contact, ContactChannelIdentity, ConversationMessage
from ..repositories.contact_repository import ContactRepository
from ..security import signed_media_url
from .conversation_service import ConversationService
from . import realtime, statuses

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
        """Prefer the number in the payload (unique + indexed); fall back to the
        URL's channel id."""
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

        contact = self._resolve_contact(channel, event)

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
        # Dev/unconfigured → no key, the body/caption still lands.
        media_key = None
        media_mime = event.get("media_mime")
        media_size = None
        if event.get("media_id"):
            stored = self._store_media(channel, event["media_id"])
            if stored is not None:
                media_key = stored["key"]
                media_mime = stored.get("mime") or media_mime
                media_size = stored.get("size")

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
            payload_json=event.get("payload"),
            external_message_id=external_id,
            metadata_json=metadata,
            # Explicit (µs precision) - the DB server_default is second-granular
            # on SQLite, which scrambles ordering for rapid messages.
            created_at=now,
        )
        self.db.add(row)

        # Re-open + CSW reset (§4.2.6): any inbound restarts the 24h window.
        contact.status_id = statuses.status_id_for(
            self.db, channel.tenant_id, "THREAD", "OPEN"
        )
        contact.csw_expires_at = now + CSW_WINDOW
        contact.last_incoming_message_at = now
        contact.last_message_at = now
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

        # Start any workflow whose trigger is "Incoming omnichannel message"
        # (plan sprint-4/17) - failure-isolated (CLAUDE.md: workflow dispatch
        # must never break the triggering request), on top of
        # notify_entity_event's own internal dispatch-failure isolation.
        try:
            from app.workflow_engine.entity_events import notify_entity_event

            name = " ".join(
                part for part in [contact.first_name, contact.last_name] if part
            ).strip()
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

    def _resolve_contact(self, channel: Channel, event: Dict[str, Any]) -> Contact:
        """Contact resolution & stitching (§4): identity → phone stitch → create."""
        wa_id = event["from"]
        identity = self.repo.find_identity(channel.id, wa_id)
        if identity is not None:
            contact = self.repo.get_by_id(identity.contact_id, channel.tenant_id)
            if contact is not None:
                # Profile names drift - keep the identity fresh.
                if event.get("profile_name") and identity.profile_name != event["profile_name"]:
                    identity.profile_name = event["profile_name"]
                return contact

        digits = "".join(ch for ch in wa_id if ch.isdigit())
        contact = self.repo.find_by_phone_in_workspace(
            digits, channel.workspace_id, channel.tenant_id
        )
        if contact is None:
            from .lifecycle_service import initial_status_id

            profile_name = event.get("profile_name") or ""
            first, _, last = profile_name.partition(" ")
            contact = Contact(
                tenant_id=channel.tenant_id,
                workspace_id=channel.workspace_id,
                first_name=first or None,
                last_name=last or None,
                phone=f"+{digits}",
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

        self.db.add(
            ContactChannelIdentity(
                tenant_id=channel.tenant_id,
                contact_id=contact.id,
                channel_id=channel.id,
                external_user_id=wa_id,
                profile_name=event.get("profile_name"),
            )
        )
        self.db.flush()
        return contact

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

    # ── Delivery receipts ────────────────────────────────────────────────────
    def _handle_status(self, channel: Channel, event: Dict[str, Any]) -> bool:
        external_id = event.get("external_message_id")
        new_status = event.get("status")
        if not external_id or new_status not in ("SENT", "DELIVERED", "READ", "FAILED"):
            return False
        msg = self.repo.get_message_by_external_id(external_id, channel.tenant_id)
        if msg is None:
            return False

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
                "externalMessageId": external_id,
                "contactId": msg.contact_id,
                "deliveryStatus": msg.delivery_status,
                "errorCode": msg.error_code,
                "errorMessage": msg.error_message,
            },
        )
        return True
