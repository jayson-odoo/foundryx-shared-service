"""Public gateway orchestration (plan sprint-1/01 Slice 3).

Bridges the workspace-key public API to the existing (agent-path) message
pipeline: resolve/create the contact from the raw `to` phone, reuse
`MessageService.send_message` (SAME CSW gate + adapter + realtime publish), and
translate rejections into the structured `/api/v1/*` error envelope. Idempotency
dedup is workspace-scoped with a 24h TTL.
"""
from datetime import datetime, timezone
from typing import Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.api_errors import ApiError

from ..models import MEDIA_MESSAGE_TYPES, Channel, Contact, WhatsappTemplate
from ..repositories.contact_repository import ContactRepository
from ..schemas import (
    PublicSendRequest,
    PublicTemplateItem,
    RioAssignee,
    RioContactItem,
    RioCustomField,
    RioMessageItem,
    RioMessagePayload,
    RioMessageReaction,
    RioMessageReplyTo,
    RioMessageSender,
    RioMessageStatus,
    SendMessageRequest,
)
from ..security import signed_media_url
from .media_pipeline import META_CEILINGS, MediaRejected
from .message_service import (
    CSW_CLOSED_MESSAGE,
    MessageService,
    SendRejected,
    _window_open,
    template_body_text,
    template_variable_count,
)
from . import idempotency, statuses

_MEDIA_HARD_CAP = max(META_CEILINGS.values()) + 1

# Wire-format switch on the read endpoints (`?format=`). GUIDE is the DEFAULT
# and the documented contract (`MessageItem`/`ThreadItem`, the richer flat
# shape); RIO is the opt-in respond.io-parity shape for consumers migrating
# from respond.io. Both are derived from the same internal objects, so they
# cannot drift apart.
FORMAT_GUIDE = "guide"
FORMAT_RIO = "rio"
WIRE_FORMATS = (FORMAT_GUIDE, FORMAT_RIO)


def _digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _epoch(dt) -> Optional[int]:
    """Aware-UTC datetime → epoch seconds (respond.io wire format)."""
    return int(dt.timestamp()) if dt else None


def _iso_z(dt) -> Optional[str]:
    """Aware-UTC datetime → ISO-8601 Z. Used for FoundryX-extension fields on
    the Rio shapes (`cswExpiresAt`), which follow the house convention rather
    than respond.io's epoch ints."""
    if not dt:
        return None
    # SQLite can hand back a naive datetime (and an in-session assignment may be
    # read off the identity map before refresh) — treat naive as UTC, never as
    # local, or the CSW deadline shifts by the host offset. Mirrors
    # `message_service._window_open`.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ConversationMessage.delivery_status → respond.io status vocabulary.
_RIO_STATUS = {
    "QUEUED": "pending",
    "SENDING": "pending",
    "SENT": "sent",
    "DELIVERED": "delivered",
    "READ": "read",
    "FAILED": "failed",
}
_RIO_SENDER_SOURCE = {"AGENT": "user", "CONTACT": "contact", "SYSTEM": "system"}


class PublicGatewayService:
    def __init__(self, db: Session):
        self.db = db
        self.messages = MessageService(db)
        self.contacts = ContactRepository(db)

    # ── Channel + contact resolution ─────────────────────────────────────────
    def _workspace_channel(self, tenant_id: str, workspace_id: str) -> Channel:
        channel = (
            self.db.query(Channel)
            .filter(
                Channel.tenant_id == tenant_id,
                Channel.workspace_id == workspace_id,
                Channel.is_active.is_(True),
                Channel.is_trashed.is_(False),
            )
            .order_by(Channel.created_at.asc())
            .first()
        )
        if channel is None:
            raise ApiError(
                409, "no_active_channel", "No active channel is connected to this workspace."
            )
        return channel

    # ── Contact identifier resolution (respond.io-style) ─────────────────────
    def _resolve_contact(self, tenant_id: str, workspace_id: str, identifier: str) -> Contact:
        """Resolve a contact from a polymorphic identifier — ``phone:+60…``,
        ``id:<uuid>``, or a bare id. Always workspace-scoped; a miss (or a
        contact in another workspace) is a uniform ``404 contact_not_found``."""
        ident = (identifier or "").strip()
        if ident.lower().startswith("phone:"):
            contact = self.contacts.find_by_phone_in_workspace(
                _digits(ident.split(":", 1)[1]), workspace_id, tenant_id
            )
        else:
            cid = ident.split(":", 1)[1] if ident.lower().startswith("id:") else ident
            contact = self.contacts.get_by_id(cid, tenant_id)
        if contact is None or contact.workspace_id != workspace_id:
            raise ApiError(404, "contact_not_found", "Contact not found for this workspace.")
        return contact

    # ── respond.io-parity mappers ────────────────────────────────────────────
    def _users_by_id(self, tenant_id: str, user_ids) -> dict:
        """Batch-load core users for assignee rendering, TENANT-SCOPED (the
        polymorphic-target_id house rule — resolve a stored user id scoped, never
        via a bare id lookup, even though patch_thread validates on write)."""
        from app.models.user import User

        ids = [u for u in {uid for uid in user_ids if uid}]
        if not ids:
            return {}
        rows = (
            self.db.query(User)
            .filter(User.tenant_id == tenant_id, User.id.in_(ids))
            .all()
        )
        return {u.id: u for u in rows}

    def _rio_contact(
        self, contact: Contact, *, thread: "ThreadItem", users: dict
    ) -> RioContactItem:
        """Map the internal ThreadItem (+ the ORM row, which carries `email` and
        custom fields the ThreadItem omits) to the respond.io shape.

        Anything ThreadItem carries that respond.io has no field for is kept as
        an explicit FoundryX extension rather than dropped — a gateway consumer
        has no other read source for `unreadCount`/`lastMessagePreview`, and an
        inbox list cannot be built without them (BL-SS-026)."""
        cf = contact.custom_fields_json or {}
        custom = [RioCustomField(name=str(k), value=None if v is None else str(v)) for k, v in cf.items()]
        assignee = None
        if contact.assigned_user_id and contact.assigned_user_id in users:
            u = users[contact.assigned_user_id]
            assignee = RioAssignee(id=u.id, firstName=u.name, lastName=None, email=u.email)
        return RioContactItem(
            id=contact.id,
            firstName=contact.first_name,
            lastName=contact.last_name,
            phone=contact.phone,
            email=contact.email,
            language=None,          # not modeled (respond.io parity field)
            profilePic=contact.avatar_url,
            countryCode=None,       # not modeled
            custom_fields=custom,
            status=(thread.status or "OPEN").lower(),
            tags=[],                # not modeled
            assignee=assignee,
            lifecycle=None,         # not modeled
            created_at=_epoch(contact.created_at),
            isBlocked=False,        # not modeled
            cswExpiresAt=_iso_z(thread.cswExpiresAt),
            priority=thread.priority,
            channelId=thread.channelId,
            channelType=thread.channelType,
            unreadCount=thread.unreadCount,
            lastMessageAt=_iso_z(thread.lastMessageAt),
            lastIncomingMessageAt=_iso_z(thread.lastIncomingMessageAt),
            lastMessagePreview=thread.lastMessagePreview,
        )

    def _rio_message(self, m, *, reactions: Optional[list] = None) -> RioMessageItem:
        meta = m.metadata_json or {}
        traffic = "incoming" if m.sender_type == "CONTACT" else "outgoing"
        # Media URL: a stored blob becomes an absolute, signed, clickable link;
        # a legacy stored URL passes through.
        url = None
        if getattr(m, "media_key", None):
            url = signed_media_url(m.id)
        elif getattr(m, "media_url", None):
            url = m.media_url
        # The text/caption split keys off the MESSAGE TYPE, never off `url`
        # presence. A TEMPLATE or INTERACTIVE row can carry a header image in
        # `media_key` (so `url` is set) while its body still belongs in `text`;
        # conversely an inbound media row whose blob failed to store has no
        # `url` but is still media, and its body is still a caption.
        is_media = (m.message_type or "").upper() in MEDIA_MESSAGE_TYPES
        payload = RioMessagePayload(
            type=(m.message_type or "text").lower(),
            # A media message's body IS its caption — expose it once, in
            # `caption`, never duplicated into `text`.
            text=None if is_media else m.body,
            url=url,
            caption=m.body if is_media else None,
            filename=m.media_filename,
            mimeType=m.media_mime,
            size=m.media_size,
            # interactive buttons / location coordinates / contact cards /
            # template binding — flattening these into `text` loses them.
            # `payload_json` is free-form JSON: guard the stored shape (same
            # treatment as `reply_to` below) so a rogue row can't 500 a read.
            payload=m.payload_json if isinstance(m.payload_json, dict) else None,
            messageTag=meta.get("message_tag"),
        )
        # `metadata_json` is free-form: never assume the stored shape (a legacy
        # or hand-written row must not 500 a read).
        reply = meta.get("reply_to")
        reply = reply if isinstance(reply, dict) else {}
        reply_to = (
            RioMessageReplyTo(
                messageId=reply.get("id"),
                text=reply.get("body"),
                senderType=reply.get("senderType"),
                senderName=reply.get("senderName"),
            )
            if reply.get("id")
            else None
        )
        status: list = []
        if m.delivery_status:
            status.append(
                RioMessageStatus(
                    value=_RIO_STATUS.get(m.delivery_status, m.delivery_status.lower()),
                    timestamp=_epoch(m.created_at),
                    message=m.error_message,
                    code=m.error_code,
                )
            )
        sender = RioMessageSender(
            source=_RIO_SENDER_SOURCE.get(m.sender_type, "system"),
            userId=m.sender_id if m.sender_type == "AGENT" else None,
            teamId=None,
        )
        return RioMessageItem(
            messageId=m.id,
            channelMessageId=m.external_message_id,
            contactId=m.contact_id,
            channelId=m.channel_id,
            traffic=traffic,
            # Inbound messages never carry a delivery receipt, so `status[]` is
            # empty for them — this is the ONE time key present on every message.
            timestamp=_epoch(m.created_at),
            message=payload,
            status=status,
            sender=sender,
            reactions=[RioMessageReaction(**r) for r in (reactions or [])],
            replyTo=reply_to,
        )

    # ── Contact read ─────────────────────────────────────────────────────────
    def get_contact(
        self, tenant_id: str, workspace_id: str, identifier: str, *, fmt: str = FORMAT_GUIDE
    ):
        """``ThreadItem`` (default, the documented shape) or ``RioContactItem``
        when ``fmt='rio'``. ThreadItem is the superset — Rio is derived from it,
        so the two can never drift apart."""
        from .conversation_service import ConversationService

        contact = self._resolve_contact(tenant_id, workspace_id, identifier)
        thread = ConversationService(self.db).thread_item(contact)
        if fmt != FORMAT_RIO:
            return thread
        users = self._users_by_id(tenant_id, [contact.assigned_user_id])
        return self._rio_contact(contact, thread=thread, users=users)

    def list_contacts(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        status: Optional[str] = None,
        assignee: str = "all",
        priority: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 0,
        page_size: int = 50,
        fmt: str = FORMAT_GUIDE,
    ):
        """Returns ``(items, total)`` — ``ThreadItem``s by default, ``RioContactItem``s
        when ``fmt='rio'``. Filtering/pagination reuse the inbox's ``list_threads``
        (offset-based); the router turns page/total into the documented envelope."""
        from .conversation_service import ConversationService

        items, total = ConversationService(self.db).list_threads(
            tenant_id,
            workspace_id=workspace_id,
            status_key=status,
            assignee=assignee or "all",
            priority=priority,
            search=search,
            page=page,
            page_size=page_size,
        )
        if fmt != FORMAT_RIO:
            return items, total
        # Rio needs the ORM rows too — ThreadItem omits email + custom fields.
        ids = [t.id for t in items]
        contacts = (
            self.db.query(Contact)
            .filter(Contact.tenant_id == tenant_id, Contact.id.in_(ids))
            .all()
            if ids
            else []
        )
        by_id = {c.id: c for c in contacts}
        users = self._users_by_id(tenant_id, [c.assigned_user_id for c in contacts])
        rio = [
            self._rio_contact(by_id[t.id], thread=t, users=users)
            for t in items
            if t.id in by_id
        ]
        return rio, total

    def list_contact_messages(
        self,
        tenant_id: str,
        workspace_id: str,
        identifier: str,
        *,
        limit: int,
        before_id: Optional[str] = None,
        after_id: Optional[str] = None,
        fmt: str = FORMAT_GUIDE,
    ):
        """Read-only message history for a contact — ALL message types. Returns
        ``(contact_id, items)``: ``MessageItem``s by default, ``RioMessageItem``s
        when ``fmt='rio'``. Two-way keyset paging (``before_id`` older /
        ``after_id`` newer); always oldest→newest. Workspace-scoped and
        side-effect-free (a consumer read never marks the thread read)."""
        from .conversation_service import ConversationService

        contact = self._resolve_contact(tenant_id, workspace_id, identifier)
        rows = self.contacts.list_messages_recent(
            contact.id, tenant_id, limit=limit, before_id=before_id, after_id=after_id
        )
        if fmt != FORMAT_RIO:
            return contact.id, ConversationService(self.db).message_items(rows)
        # Reaction chips: ONE batched query for the whole page (never per-row).
        reactions = self.contacts.reactions_for([m.id for m in rows], tenant_id)
        return contact.id, [
            self._rio_message(m, reactions=reactions.get(m.id)) for m in rows
        ]

    def get_contact_message(
        self, tenant_id: str, workspace_id: str, identifier: str, message_id: str,
        *, fmt: str = FORMAT_GUIDE,
    ):
        from .conversation_service import ConversationService

        contact = self._resolve_contact(tenant_id, workspace_id, identifier)
        msg = self.contacts.get_message(message_id, tenant_id)
        if msg is None or msg.contact_id != contact.id:
            raise ApiError(404, "message_not_found", "Message not found for this contact.")
        if fmt != FORMAT_RIO:
            return ConversationService(self.db).message_items([msg])[0]
        reactions = self.contacts.reactions_for([msg.id], tenant_id)
        return self._rio_message(msg, reactions=reactions.get(msg.id))

    # ── Contact / conversation mutation ──────────────────────────────────────
    def update_contact(
        self,
        tenant_id: str,
        workspace_id: str,
        identifier: str,
        *,
        first_name=...,
        last_name=...,
        priority: Optional[str] = None,
        assigned_user_id=...,
        custom_fields=...,
        fmt: str = FORMAT_GUIDE,
    ):
        from .conversation_service import ConversationService, InvalidPatch

        contact = self._resolve_contact(tenant_id, workspace_id, identifier)
        try:
            thread = ConversationService(self.db).patch_thread(
                contact.id,
                tenant_id,
                assigned_user_id=assigned_user_id,
                priority=priority,
                first_name=first_name,
                last_name=last_name,
                custom_fields=custom_fields,
            )
        except InvalidPatch as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc
        return self._after_patch(tenant_id, contact.id, thread, fmt=fmt)

    def set_conversation_state(
        self, tenant_id: str, workspace_id: str, identifier: str, *, open_: bool,
        fmt: str = FORMAT_GUIDE,
    ):
        from .conversation_service import ConversationService, InvalidPatch

        contact = self._resolve_contact(tenant_id, workspace_id, identifier)
        try:
            thread = ConversationService(self.db).patch_thread(
                contact.id, tenant_id, status="OPEN" if open_ else "CLOSED"
            )
        except InvalidPatch as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc
        return self._after_patch(tenant_id, contact.id, thread, fmt=fmt)

    def _after_patch(self, tenant_id: str, contact_id: str, thread, *, fmt: str = FORMAT_GUIDE):
        """Re-read the mutated contact and render it in the requested shape, so
        a write echoes exactly what the matching GET would return."""
        if fmt != FORMAT_RIO:
            return thread
        contact = self.contacts.get_by_id(contact_id, tenant_id)
        users = self._users_by_id(tenant_id, [contact.assigned_user_id])
        return self._rio_contact(contact, thread=thread, users=users)

    def add_comment(self, tenant_id: str, workspace_id: str, identifier: str, body: str):
        """Add an internal note (comment) to a contact's thread — SYSTEM bubble,
        never sent to the customer. No user actor (consumer/API-key context)."""
        contact = self._resolve_contact(tenant_id, workspace_id, identifier)
        if not (body or "").strip():
            raise ApiError(422, "invalid_request", "Comment body is required.")
        return self.messages.add_internal_note(contact.id, tenant_id, None, body)

    def _resolve_or_create_contact(
        self, tenant_id: str, workspace_id: str, phone: str
    ) -> Contact:
        digits = _digits(phone)
        if not digits:
            raise ApiError(422, "invalid_recipient", "A valid recipient phone number is required.")
        # Reuse the same within-workspace phone stitch as the inbound path.
        existing = self.contacts.find_by_phone_in_workspace(digits, workspace_id, tenant_id)
        if existing is not None:
            return existing
        contact = Contact(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            phone=digits,
            priority="MEDIUM",
            status_id=statuses.status_id_for(self.db, tenant_id, "THREAD", "OPEN"),
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(contact)
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def _resolve_template_id(
        self, tenant_id: str, channel_id: str, req: PublicSendRequest
    ) -> str:
        tpl = req.template
        if tpl is None or (not tpl.id and not tpl.name):
            raise ApiError(422, "invalid_request", "A template id or name is required.")
        q = self.db.query(WhatsappTemplate).filter(
            WhatsappTemplate.tenant_id == tenant_id,
            WhatsappTemplate.channel_id == channel_id,
        )
        row = (
            q.filter(WhatsappTemplate.id == tpl.id).first()
            if tpl.id
            else q.filter(WhatsappTemplate.name == tpl.name).first()
        )
        if row is None:
            raise ApiError(422, "template_not_found", "Template not found for this workspace.")
        return row.id

    # ── Send ─────────────────────────────────────────────────────────────────
    def send(
        self,
        tenant_id: str,
        workspace_id: str,
        key_id: str,
        req: PublicSendRequest,
        idempotency_key: Optional[str],
    ) -> Tuple[str, bool]:
        """Returns (our_message_id, was_idempotency_replay)."""
        store = idempotency.get_store()
        reserved = False
        if idempotency_key:
            # Reserve-before-send: atomically claim the slot so two concurrent
            # identical requests can't both send.
            claimed = store.reserve(workspace_id, idempotency_key)
            if claimed is not None:
                if claimed == idempotency.PENDING:
                    raise ApiError(
                        409,
                        "idempotency_in_progress",
                        "A request with this Idempotency-Key is still being processed.",
                    )
                return claimed, True  # completed → replay the stored id
            reserved = True

        try:
            message_id = self._do_send(tenant_id, workspace_id, key_id, req)
        except Exception:
            if reserved:
                store.release(workspace_id, idempotency_key)  # let a retry re-claim
            raise

        if reserved:
            store.finalize(workspace_id, idempotency_key, message_id)
        return message_id, False

    def _do_send(
        self, tenant_id: str, workspace_id: str, key_id: str, req: PublicSendRequest
    ) -> str:
        msg_type = (req.type or "text").lower()
        channel = self._workspace_channel(tenant_id, workspace_id)

        if msg_type == "text":
            if req.text is None or not (req.text.body or "").strip():
                raise ApiError(422, "invalid_request", "text.body is required.")
            payload = SendMessageRequest(messageType="TEXT", body=req.text.body)
        elif msg_type == "template":
            template_id = self._resolve_template_id(tenant_id, channel.id, req)
            payload = SendMessageRequest(
                messageType="TEMPLATE",
                templateId=template_id,
                templateVariables=(req.template.variables if req.template else None) or [],
            )
        elif msg_type.upper() in MEDIA_MESSAGE_TYPES:
            # Media-by-URL (plan 12 AC-12-10): fetch the bytes + re-upload through
            # the SAME upload-by-id pipeline (never pass Meta a bare `link`).
            if req.media is None or not (req.media.url or "").strip():
                raise ApiError(422, "invalid_request", "media.url is required.")
            # Enforce the 24h CSW BEFORE fetching (don't do SSRF-fetch work on a
            # closed window; media is free-form → an open window is required).
            contact = self._resolve_or_create_contact(tenant_id, workspace_id, req.to)
            if not _window_open(contact):
                raise ApiError(409, "csw_window_closed", CSW_CLOSED_MESSAGE)
            content = self._fetch_url(req.media.url)
            return self._send_media(
                tenant_id,
                workspace_id,
                key_id,
                kind=msg_type.upper(),
                content=content,
                filename=req.media.filename,
                caption=req.media.caption,
                to=req.to,
            )
        elif msg_type in ("interactive", "location", "contacts"):
            return self._send_structured(tenant_id, workspace_id, key_id, msg_type, req)
        elif msg_type == "reaction":
            return self._send_reaction(tenant_id, workspace_id, key_id, req)
        else:
            raise ApiError(400, "unsupported_type", f"Unknown message type '{msg_type}'.")

        contact = self._resolve_or_create_contact(tenant_id, workspace_id, req.to)
        actor = f"apikey:{key_id}"
        try:
            item = self.messages.send_message(contact.id, tenant_id, actor, payload)
        except SendRejected as exc:
            if exc.message == CSW_CLOSED_MESSAGE:
                raise ApiError(409, "csw_window_closed", exc.message) from exc
            raise ApiError(422, "send_rejected", exc.message) from exc
        return item.id

    def _fetch_url(self, url: str) -> bytes:
        """Fetch a media URL so it can be re-uploaded by id (plan 12 review — SSRF).

        Reuses the consumer-webhook SSRF guard (``validate_callback_url``): https
        only, blocks private/loopback/link-local/reserved/metadata targets given
        as a literal, numeric/hex IP, OR a hostname that resolves to one. Redirects
        are DISABLED (a 3xx to an internal host would bypass the guard); the read
        is streamed + capped so a hostile body can't exhaust memory."""
        from .webhook_service import WebhookError, validate_callback_url

        try:
            safe = validate_callback_url(url)
        except WebhookError as exc:
            raise ApiError(422, "invalid_media_url", str(exc)) from exc
        try:
            with httpx.Client(timeout=15.0, follow_redirects=False) as client:
                with client.stream("GET", safe) as resp:
                    if resp.is_redirect:
                        raise ApiError(
                            422, "invalid_media_url", "Redirects are not allowed for media URLs."
                        )
                    if resp.status_code >= 400:
                        raise ApiError(
                            422, "media_fetch_failed", f"Media url returned {resp.status_code}."
                        )
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > _MEDIA_HARD_CAP:
                            raise ApiError(422, "oversize", "The fetched media exceeds the maximum size.")
                        chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise ApiError(422, "media_fetch_failed", f"Could not fetch media url: {exc}") from exc
        return b"".join(chunks)

    def _send_media(
        self,
        tenant_id: str,
        workspace_id: str,
        key_id: str,
        *,
        kind: str,
        content: bytes,
        filename: Optional[str],
        caption: Optional[str],
        to: str,
    ) -> str:
        contact = self._resolve_or_create_contact(tenant_id, workspace_id, to)
        actor = f"apikey:{key_id}"
        try:
            item = self.messages.send_media(
                contact.id,
                tenant_id,
                actor,
                kind=kind,
                content=content,
                filename=filename,
                caption=caption,
            )
        except MediaRejected as exc:
            raise ApiError(422, exc.code, exc.message) from exc
        except SendRejected as exc:
            if exc.message == CSW_CLOSED_MESSAGE:
                raise ApiError(409, "csw_window_closed", exc.message) from exc
            raise ApiError(422, "send_rejected", exc.message) from exc
        return item.id

    # ── Structured send (interactive / location / contacts) ───────────────────
    def _send_structured(
        self, tenant_id: str, workspace_id: str, key_id: str, msg_type: str, req: PublicSendRequest
    ) -> str:
        # Ensure the workspace has a channel (uniform error shape) before sending.
        self._workspace_channel(tenant_id, workspace_id)
        contact = self._resolve_or_create_contact(tenant_id, workspace_id, req.to)
        actor = f"apikey:{key_id}"
        messages = self.messages
        try:
            if msg_type == "interactive":
                if not req.interactive:
                    raise ApiError(422, "invalid_request", "interactive is required.")
                defn = dict(req.interactive)
                # Validate the definition BEFORE doing any header fetch/store work —
                # a malformed interactive must 422 without a wasted SSRF fetch.
                from .structured import StructuredError, validate_interactive

                try:
                    validate_interactive(defn)
                except StructuredError as exc:
                    raise ApiError(422, "invalid_request", str(exc)) from exc
                header_content = None
                header_filename = None
                # A media header may reference a URL — fetch it (SSRF-guarded) so it
                # rides the upload-by-id pipeline (never a bare Meta link).
                header = defn.get("header") or {}
                if str(header.get("type") or "") in ("image", "video", "document") and header.get("url"):
                    header_content = self._fetch_url(header["url"])
                    header_filename = header.get("filename")
                item = messages.send_interactive(
                    contact.id,
                    tenant_id,
                    actor,
                    defn=defn,
                    header_content=header_content,
                    header_filename=header_filename,
                )
            elif msg_type == "location":
                if not req.location:
                    raise ApiError(422, "invalid_request", "location is required.")
                item = messages.send_location(contact.id, tenant_id, actor, defn=dict(req.location))
            else:  # contacts
                if not req.contacts:
                    raise ApiError(422, "invalid_request", "contacts is required.")
                item = messages.send_contacts(
                    contact.id, tenant_id, actor, defn={"contacts": req.contacts}
                )
        except MediaRejected as exc:
            raise ApiError(422, exc.code, exc.message) from exc
        except SendRejected as exc:
            if exc.message == CSW_CLOSED_MESSAGE:
                raise ApiError(409, "csw_window_closed", exc.message) from exc
            raise ApiError(422, "invalid_request", exc.message) from exc
        return item.id

    # ── Reaction send (targets OUR durable id — AC-12-21) ─────────────────────
    def _send_reaction(
        self, tenant_id: str, workspace_id: str, key_id: str, req: PublicSendRequest
    ) -> str:
        if not req.reaction or not (req.reaction.messageId or "").strip():
            raise ApiError(422, "invalid_request", "reaction.messageId is required.")
        # Resolve OUR durable id → message, scoped to this key's tenant AND
        # workspace (a key can never react on another workspace's thread).
        target = self.messages.repo.get_message(req.reaction.messageId, tenant_id)
        if target is None:
            raise ApiError(404, "not_found", "Message not found.")
        contact = self.messages.repo.get_by_id(target.contact_id, tenant_id)
        if contact is None or contact.workspace_id != workspace_id:
            raise ApiError(404, "not_found", "Message not found.")
        actor = f"apikey:{key_id}"
        try:
            self.messages.react(
                req.reaction.messageId, tenant_id, actor, emoji=req.reaction.emoji
            )
        except SendRejected as exc:
            if exc.message == CSW_CLOSED_MESSAGE:
                raise ApiError(409, "csw_window_closed", exc.message) from exc
            raise ApiError(422, "invalid_request", exc.message) from exc
        return target.id

    # ── Multipart media send (file part) ──────────────────────────────────────
    def send_multipart(
        self,
        tenant_id: str,
        workspace_id: str,
        key_id: str,
        *,
        kind: str,
        content: bytes,
        filename: Optional[str],
        caption: Optional[str],
        to: str,
        idempotency_key: Optional[str],
    ) -> Tuple[str, bool]:
        """Gateway multipart media send (plan 12 AC-12-10). Same idempotency
        semantics as the JSON ``send`` path."""
        if kind.upper() not in MEDIA_MESSAGE_TYPES:
            raise ApiError(400, "unsupported_type", f"Unknown media type '{kind}'.")
        if not (to or "").strip():
            raise ApiError(422, "invalid_recipient", "A recipient phone number is required.")
        store = idempotency.get_store()
        reserved = False
        if idempotency_key:
            claimed = store.reserve(workspace_id, idempotency_key)
            if claimed is not None:
                if claimed == idempotency.PENDING:
                    raise ApiError(
                        409,
                        "idempotency_in_progress",
                        "A request with this Idempotency-Key is still being processed.",
                    )
                return claimed, True
            reserved = True
        try:
            message_id = self._send_media(
                tenant_id,
                workspace_id,
                key_id,
                kind=kind.upper(),
                content=content,
                filename=filename,
                caption=caption,
                to=to,
            )
        except Exception:
            if reserved:
                store.release(workspace_id, idempotency_key)
            raise
        if reserved:
            store.finalize(workspace_id, idempotency_key, message_id)
        return message_id, False

    # ── Templates (read-only mirror) ─────────────────────────────────────────
    def list_templates(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        channel_id: Optional[str] = None,
        search: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[PublicTemplateItem]:
        """Approved templates for the workspace. ``channel_id`` targets a specific
        channel (default = the workspace's active channel); a channel in another
        workspace/tenant is a uniform 404. ``search`` filters by name substring
        (case-insensitive); ``category`` filters by Meta category (UTILITY|…)."""
        if channel_id:
            channel = (
                self.db.query(Channel)
                .filter(
                    Channel.id == channel_id,
                    Channel.tenant_id == tenant_id,
                    Channel.workspace_id == workspace_id,
                    Channel.is_trashed.is_(False),
                )
                .first()
            )
            if channel is None:
                raise ApiError(404, "channel_not_found", "Channel not found for this workspace.")
        else:
            channel = self._workspace_channel(tenant_id, workspace_id)
        q = self.db.query(WhatsappTemplate).filter(
            WhatsappTemplate.tenant_id == tenant_id,
            WhatsappTemplate.channel_id == channel.id,
            WhatsappTemplate.status == "APPROVED",
        )
        if search and search.strip():
            q = q.filter(WhatsappTemplate.name.ilike(f"%{search.strip()}%"))
        if category and category.strip():
            q = q.filter(WhatsappTemplate.category == category.strip().upper())
        rows = q.order_by(WhatsappTemplate.name.asc()).all()
        out: list[PublicTemplateItem] = []
        for t in rows:
            body = template_body_text(t.components_json)
            out.append(
                PublicTemplateItem(
                    id=t.id,
                    name=t.name,
                    language=t.language,
                    category=t.category,
                    bodyText=body,
                    variableCount=template_variable_count(body),
                )
            )
        return out
