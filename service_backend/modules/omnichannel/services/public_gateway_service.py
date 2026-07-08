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
from ..schemas import PublicSendRequest, PublicTemplateItem, SendMessageRequest
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


def _digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


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
    def list_templates(self, tenant_id: str, workspace_id: str) -> list[PublicTemplateItem]:
        channel = self._workspace_channel(tenant_id, workspace_id)
        rows = (
            self.db.query(WhatsappTemplate)
            .filter(
                WhatsappTemplate.tenant_id == tenant_id,
                WhatsappTemplate.channel_id == channel.id,
                WhatsappTemplate.status == "APPROVED",
            )
            .order_by(WhatsappTemplate.name.asc())
            .all()
        )
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
