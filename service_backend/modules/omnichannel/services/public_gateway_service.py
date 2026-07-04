"""Public gateway orchestration (plan sprint-1/01 Slice 3).

Bridges the workspace-key public API to the existing (agent-path) message
pipeline: resolve/create the contact from the raw `to` phone, reuse
`MessageService.send_message` (SAME CSW gate + adapter + realtime publish), and
translate rejections into the structured `/api/v1/*` error envelope. Idempotency
dedup is workspace-scoped with a 24h TTL.
"""
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.api_errors import ApiError

from ..models import Channel, Contact, WhatsappTemplate
from ..schemas import PublicSendRequest, PublicTemplateItem, SendMessageRequest
from .message_service import (
    CSW_CLOSED_MESSAGE,
    MessageService,
    SendRejected,
    template_body_text,
    template_variable_count,
)
from . import idempotency


def _digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


class PublicGatewayService:
    def __init__(self, db: Session):
        self.db = db
        self.messages = MessageService(db)

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
        # Match on digits-only equality against stored phones (tenant+workspace).
        existing = (
            self.db.query(Contact)
            .filter(Contact.tenant_id == tenant_id, Contact.workspace_id == workspace_id)
            .all()
        )
        for c in existing:
            if _digits(c.phone or "") == digits:
                return c
        contact = Contact(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            phone=digits,
            priority="MEDIUM",
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
        if idempotency_key:
            existing = idempotency.get_store().lookup(workspace_id, idempotency_key)
            if existing:
                return existing, True

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
        elif msg_type in ("media", "interactive"):
            # Media outbound (durable both ways) lands in Slice 4; interactive is
            # deferred to BL-SS-002. Foolproof: reject with a stable code.
            raise ApiError(
                400, "unsupported_type", f"Message type '{msg_type}' is not supported yet."
            )
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

        if idempotency_key:
            idempotency.get_store().remember(workspace_id, idempotency_key, item.id)
        return item.id, False

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
