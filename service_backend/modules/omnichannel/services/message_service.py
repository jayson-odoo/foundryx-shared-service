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
from ..schemas import (
    MessageItem,
    QuickReplyCreate,
    QuickReplyItem,
    QuickReplyUpdate,
    SendMessageRequest,
    TemplateItem,
)
from ..security import decrypt_credentials
from .conversation_service import ConversationService, ThreadNotFound
from .media_pipeline import MediaRejected, sniff_and_validate
from .media_settings_service import MediaSettingsService
from .send_runner import TransientSendError, run_send
from . import realtime


class SendRejected(Exception):
    """Backend CSW / validation rejection (422 — the composer shows the reason)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class QuickReplyNotFound(Exception):
    """The quick reply doesn't exist in this tenant + workspace (→ 404)."""


class ShortcutConflict(Exception):
    """Another quick reply in this workspace already uses the shortcut (→ 409)."""


CSW_CLOSED_MESSAGE = (
    "The 24-hour window has closed — send an approved template to re-engage."
)

# All agents react as the ONE business number (Meta stores one reaction per
# direction) — a single reactor identity keeps our mirror matching Meta.
AGENT_REACTOR = "agent"
# A WhatsApp reaction is a single emoji (possibly a ZWJ sequence); cap defensively.
MAX_EMOJI_LEN = 32


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
            # Same session — see send_runner docstring. A transient failure leaves
            # the row QUEUED for a later retry; eager dev uses the stub adapter
            # (no transient failures), so this never surfaces to the caller.
            try:
                run_send(self.db, row.id)
            except TransientSendError:
                self.db.refresh(row)
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
        *,
        header_content: Optional[bytes] = None,
        header_filename: Optional[str] = None,
    ) -> MessageItem:
        contact = self.repo.get_by_id(contact_id, tenant_id)
        if contact is None:
            raise ThreadNotFound()
        channel = self._channel_for_contact(contact)
        metadata, _ = self._reply_metadata(contact, tenant_id, payload.replyToMessageId)

        message_type = (payload.messageType or "TEXT").upper()
        payload_json: Optional[Dict[str, Any]] = None
        media_key = media_mime = media_filename = None
        media_size: Optional[int] = None
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
            from .template_send import (
                analyze_template,
                build_send_components,
                validate_template_params,
                TemplateParamError,
            )

            shape = analyze_template(tpl.components_json)
            header_vars = payload.templateHeaderVariables or []
            body_vars = payload.templateVariables or []
            button_vars = payload.templateButtonVariables or []
            # Meta rejects a parameter-count mismatch on ANY of header/body/button —
            # validate before queueing (extends the old body-only rule).
            try:
                validate_template_params(
                    shape,
                    header_text_vars=header_vars,
                    body_vars=body_vars,
                    button_vars=button_vars,
                    has_header_media=bool(header_content),
                )
            except TemplateParamError as exc:
                raise SendRejected(str(exc)) from exc

            header_media: Optional[Dict[str, Any]] = None
            if shape.has_media_header:
                # Header media rides the SAME upload-by-id pipeline as every other
                # outbound media: sniff-gate + cap-check + store, then send_runner
                # uploads it + injects the id. Templates are exempt from the 24h
                # CSW, so no window guard here.
                max_bytes = MediaSettingsService(self.db).max_bytes_for(
                    tenant_id, contact.workspace_id, shape.header_format
                )
                sniffed = sniff_and_validate(
                    shape.header_format, header_content, filename=header_filename, max_bytes=max_bytes
                )
                from app.services.storage import storage_for_tenant

                media_key = storage_for_tenant(self.db, tenant_id).save(
                    f"omnichannel/{tenant_id}/template-header", sniffed.content, sniffed.mime
                )
                media_mime = sniffed.mime
                media_size = sniffed.size
                media_filename = header_filename
                header_media = {"kind": shape.header_format.lower()}

            components = build_send_components(
                tpl.components_json,
                header_text_vars=header_vars,
                body_vars=body_vars,
                button_vars=button_vars,
                header_media_id=None,  # injected at send time by send_runner
            )
            body = fill_template(template_body_text(tpl.components_json), body_vars)
            template_payload: Dict[str, Any] = {
                "name": tpl.name,
                "language": tpl.language,
                "components": components or None,
            }
            if header_media is not None:
                template_payload["headerMedia"] = header_media
            payload_json = {"template": template_payload}
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
            media_key=media_key,
            media_mime=media_mime,
            media_filename=media_filename,
            media_size=media_size,
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

    # ── Send (structured: interactive / location / contacts, Slice 2) ─────────
    def _structured_row(
        self,
        contact_id: str,
        tenant_id: str,
        actor_user_id: str,
        *,
        message_type: str,
        body: Optional[str],
        payload_json: Dict[str, Any],
        reply_to_message_id: Optional[str],
        media_key: Optional[str] = None,
        media_mime: Optional[str] = None,
        media_filename: Optional[str] = None,
        media_size: Optional[int] = None,
    ) -> MessageItem:
        contact = self.repo.get_by_id(contact_id, tenant_id)
        if contact is None:
            raise ThreadNotFound()
        channel = self._channel_for_contact(contact)
        # Interactive/location/contacts are free-form → 24h CSW applies (AC-12-25).
        if not _window_open(contact):
            raise SendRejected(CSW_CLOSED_MESSAGE)
        metadata, _ = self._reply_metadata(contact, tenant_id, reply_to_message_id)
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
            media_key=media_key,
            media_mime=media_mime,
            media_filename=media_filename,
            media_size=media_size,
            delivery_status="QUEUED",
            metadata_json=metadata,
            created_at=now,
        )
        self.db.add(row)
        contact.last_message_at = now
        self.db.commit()
        self.db.refresh(row)
        return self._enqueue_and_finalize(row, contact)

    def send_interactive(
        self,
        contact_id: str,
        tenant_id: str,
        actor_user_id: str,
        *,
        defn: Dict[str, Any],
        header_content: Optional[bytes] = None,
        header_filename: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
    ) -> MessageItem:
        from .structured import StructuredError, header_media_kind, validate_interactive

        try:
            validate_interactive(defn)
        except StructuredError as exc:
            raise SendRejected(str(exc)) from exc

        media_key = media_mime = None
        media_size = None
        hkind = header_media_kind(defn)  # image | video | document | None
        if hkind:
            if not header_content:
                raise SendRejected("This interactive message has a media header — attach a file.")
            contact = self.repo.get_by_id(contact_id, tenant_id)
            if contact is None:
                raise ThreadNotFound()
            # Reject on a closed 24h window BEFORE sniffing/storing the header blob —
            # else a closed-window send orphans a persisted blob (never sent).
            if not _window_open(contact):
                raise SendRejected(CSW_CLOSED_MESSAGE)
            max_bytes = MediaSettingsService(self.db).max_bytes_for(
                tenant_id, contact.workspace_id, hkind.upper()
            )
            sniffed = sniff_and_validate(
                hkind.upper(), header_content, filename=header_filename, max_bytes=max_bytes
            )
            from app.services.storage import storage_for_tenant

            media_key = storage_for_tenant(self.db, tenant_id).save(
                f"omnichannel/{tenant_id}/interactive-header", sniffed.content, sniffed.mime
            )
            media_mime = sniffed.mime
            media_size = sniffed.size

        return self._structured_row(
            contact_id,
            tenant_id,
            actor_user_id,
            message_type="INTERACTIVE",
            body=(defn.get("body") or None),
            payload_json=defn,
            reply_to_message_id=reply_to_message_id,
            media_key=media_key,
            media_mime=media_mime,
            media_filename=header_filename if hkind else None,
            media_size=media_size,
        )

    def send_location(
        self,
        contact_id: str,
        tenant_id: str,
        actor_user_id: str,
        *,
        defn: Dict[str, Any],
        reply_to_message_id: Optional[str] = None,
    ) -> MessageItem:
        from .structured import StructuredError, validate_location

        try:
            payload = validate_location(defn)
        except StructuredError as exc:
            raise SendRejected(str(exc)) from exc
        body = payload.get("name") or payload.get("address") or f"{payload['lat']}, {payload['lng']}"
        return self._structured_row(
            contact_id,
            tenant_id,
            actor_user_id,
            message_type="LOCATION",
            body=body,
            payload_json=payload,
            reply_to_message_id=reply_to_message_id,
        )

    def send_contacts(
        self,
        contact_id: str,
        tenant_id: str,
        actor_user_id: str,
        *,
        defn: Dict[str, Any],
        reply_to_message_id: Optional[str] = None,
    ) -> MessageItem:
        from .structured import StructuredError, validate_contacts

        try:
            payload = validate_contacts(defn)
        except StructuredError as exc:
            raise SendRejected(str(exc)) from exc
        first = payload["contacts"][0]["name"].get("formatted_name")
        return self._structured_row(
            contact_id,
            tenant_id,
            actor_user_id,
            message_type="CONTACTS",
            body=first,
            payload_json=payload,
            reply_to_message_id=reply_to_message_id,
        )

    # ── Reactions (plan 12 Slice 3 — AC-12-19/20/21) ────────────────────────
    def react(
        self,
        message_id: str,
        tenant_id: str,
        actor_user_id: str,
        *,
        emoji: Optional[str],
        expected_contact_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """An agent reacts to a message by our DURABLE id (never a raw wamid).
        Sends the reaction to Meta, upserts our row (empty emoji removes), and
        fans WS + consumer-webhook events. Returns ``{targetMessageId, emoji,
        removed}``."""
        target = self.repo.get_message(message_id, tenant_id)
        if target is None:
            raise ThreadNotFound()
        # The message must belong to the thread named in the path (defence in depth).
        if expected_contact_id is not None and target.contact_id != expected_contact_id:
            raise ThreadNotFound()
        contact = self.repo.get_by_id(target.contact_id, tenant_id)
        if contact is None:
            raise ThreadNotFound()
        channel = self._channel_for_contact(contact)
        # Reactions are free-form → the 24h window applies (Meta rule, AC-12-25).
        if not _window_open(contact):
            raise SendRejected(CSW_CLOSED_MESSAGE)
        if not target.external_message_id:
            raise SendRejected("This message hasn't been delivered yet — can't react to it.")

        clean = (emoji or "").strip()
        if len(clean) > MAX_EMOJI_LEN:
            raise SendRejected("That doesn't look like an emoji reaction.")
        credentials = decrypt_credentials(channel.credentials_json)
        adapter = get_adapter(channel.channel_type)
        from ..adapters.base import SendError

        try:
            adapter.send(
                credentials,
                channel.phone_number_id or "",
                "".join(ch for ch in (contact.phone or "") if ch.isdigit()),
                reaction={"message_id": target.external_message_id, "emoji": clean},
            )
        except SendError as exc:
            raise SendRejected(str(exc)) from exc

        # Meta stores ONE reaction per direction — every agent reacts as the same
        # business number, so a later agent's emoji OVERWRITES the earlier one at
        # Meta. Key AGENT reactions by a single business identity (not the actor)
        # so our mirror matches: agent B replaces agent A's row, one agent chip.
        _, removed = self.repo.set_reaction(
            target,
            reactor_type="AGENT",
            reactor=AGENT_REACTOR,
            emoji=clean,
            workspace_id=contact.workspace_id,
        )
        self.db.commit()

        now = datetime.now(timezone.utc)
        from . import reactions

        reactions.emit_reaction(
            self.db,
            channel,
            workspace_id=contact.workspace_id,
            contact_id=target.contact_id,
            target_message_id=target.id,
            reactor_type="AGENT",
            emoji=clean,
            removed=removed,
            event_id=f"{target.id}:{AGENT_REACTOR}:{now.timestamp()}",
        )
        return {"targetMessageId": target.id, "emoji": clean, "removed": removed}

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
        from .template_send import analyze_template

        body = template_body_text(t.components_json)
        shape = analyze_template(t.components_json)
        return TemplateItem(
            id=t.id,
            channelId=t.channel_id,
            name=t.name,
            language=t.language,
            category=t.category,
            bodyText=body,
            variableCount=shape.body_var_count,
            headerFormat=shape.header_format,
            headerVariableCount=shape.header_text_var_count,
            buttonVariableCount=shape.button_url_var_count,
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
        return [self._quick_reply_item(r) for r in rows]

    def _quick_reply_item(self, r: QuickReply) -> QuickReplyItem:
        return QuickReplyItem(
            id=r.id, workspaceId=r.workspace_id, shortcut=r.shortcut, body=r.body
        )

    def _require_workspace(self, workspace_id: str, tenant_id: str) -> None:
        """Verify the workspace belongs to the tenant (never trust client input).
        Raises ``WorkspaceNotFound`` (→ 404) otherwise."""
        from ..repositories.workspace_repository import WorkspaceRepository
        from .workspace_service import WorkspaceNotFound

        if WorkspaceRepository(self.db).get_by_id(workspace_id, tenant_id) is None:
            raise WorkspaceNotFound()

    def _quick_reply_row(
        self, quick_reply_id: str, workspace_id: str, tenant_id: str
    ) -> Optional[QuickReply]:
        return (
            self.db.query(QuickReply)
            .filter(
                QuickReply.id == quick_reply_id,
                QuickReply.tenant_id == tenant_id,
                QuickReply.workspace_id == workspace_id,
            )
            .first()
        )

    def _shortcut_taken(
        self,
        workspace_id: str,
        tenant_id: str,
        shortcut: Optional[str],
        *,
        exclude_id: Optional[str] = None,
    ) -> bool:
        if not shortcut:
            return False
        q = self.db.query(QuickReply.id).filter(
            QuickReply.tenant_id == tenant_id,
            QuickReply.workspace_id == workspace_id,
            QuickReply.shortcut == shortcut,
        )
        if exclude_id is not None:
            q = q.filter(QuickReply.id != exclude_id)
        return q.first() is not None

    def create_quick_reply(
        self,
        workspace_id: str,
        tenant_id: str,
        payload: QuickReplyCreate,
        *,
        actor_user_id: Optional[str] = None,
    ) -> QuickReplyItem:
        self._require_workspace(workspace_id, tenant_id)
        if self._shortcut_taken(workspace_id, tenant_id, payload.shortcut):
            raise ShortcutConflict()
        row = QuickReply(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            shortcut=payload.shortcut,
            body=payload.body,
            created_by=actor_user_id,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self._quick_reply_item(row)

    def update_quick_reply(
        self,
        quick_reply_id: str,
        workspace_id: str,
        tenant_id: str,
        payload: QuickReplyUpdate,
    ) -> QuickReplyItem:
        self._require_workspace(workspace_id, tenant_id)
        row = self._quick_reply_row(quick_reply_id, workspace_id, tenant_id)
        if row is None:
            raise QuickReplyNotFound()
        fields = payload.model_fields_set
        if "shortcut" in fields and self._shortcut_taken(
            workspace_id, tenant_id, payload.shortcut, exclude_id=quick_reply_id
        ):
            raise ShortcutConflict()
        if "shortcut" in fields:
            row.shortcut = payload.shortcut
        if "body" in fields and payload.body is not None:
            row.body = payload.body
        self.db.commit()
        self.db.refresh(row)
        return self._quick_reply_item(row)

    def delete_quick_reply(
        self, quick_reply_id: str, workspace_id: str, tenant_id: str
    ) -> None:
        self._require_workspace(workspace_id, tenant_id)
        row = self._quick_reply_row(quick_reply_id, workspace_id, tenant_id)
        if row is None:
            raise QuickReplyNotFound()
        self.db.delete(row)
        self.db.commit()
