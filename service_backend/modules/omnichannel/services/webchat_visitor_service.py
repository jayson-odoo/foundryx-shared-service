"""The public web chat visitor API (plan 34 / A7b S2) - the ONLY writer on
the unauthenticated public path.

Everything here answers one of three calls a visitor's browser ever makes:
`start_session` (mint/renew a visitor token + return widget config + any
existing history - AC-WEB-23..25/28/29), `post_message` (the ONE write - lazy
contact creation on the visitor's FIRST message via the UNCHANGED
`InboundService`, AC-WEB-26/32/33), and `history` (the visitor's own thread,
oldest to newest, page-capped - AC-WEB-34, also the poll fallback S3 wires).

Every query derives `tenant_id`/`channel_id`/`contact_id` from the resolved
CHANNEL (by widget key, globally unique over live rows) and the VERIFIED
token's own `visitor_id` - never from any request body field (AC-WEB-27).
`visitor_projection.visitor_message_item` is the ONE place a stored message
becomes visitor-visible (D-A7B-17); nothing in this file builds a visitor-
facing message shape any other way.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import Request
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.tenant_branding import TenantBranding
from app.repositories.module_repository import ModuleRepository

from ..models import Channel, Contact, ConversationMessage
from ..repositories.contact_repository import ContactRepository
from ..webchat_auth import (
    InvalidVisitorToken,
    VisitorClaims,
    mint_visitor_token,
    needs_renewal,
    verify_visitor_token,
)
from .inbound_service import InboundService
from .webchat_projection import visitor_message_item
from .webchat_service import WebchatService

logger = logging.getLogger(__name__)

MODULE_NAME = "omnichannel"
TEXT_MAX_CHARS = 4096
# The request body's own read cap (D-A7B-21) - well above the 4096-char text
# cap even at worst-case UTF-8 (4 bytes/char) plus a small preChat/honeypot
# envelope, well below anything a DoS attempt would need to matter.
BODY_MAX_BYTES = 24_000
HISTORY_PAGE_LIMIT = 50
HISTORY_PAGE_LIMIT_MAX = 100


class WebchatNotFound(Exception):
    """Uniform 404 (R7) - unknown widget key, trashed/inactive channel,
    module inactive, tenant blocked, OR a missing/disallowed Origin. One
    byte-identical response for every case; the caller never learns which."""


class WebchatUnauthorized(Exception):
    """One indistinguishable 401 (R4) - forged, expired, wrong-`typ`, wrong-
    channel or epoch-revoked token. No detail distinguishes the cases."""


class WebchatInvalidRequest(Exception):
    """A typed 422 - `code` is the wire-visible reason (`text_too_long`,
    `unsupported_content`, `malformed_body`)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _allowed_origins(channel: Channel) -> List[str]:
    cfg = channel.widget_config_json or {}
    return cfg.get("allowedOrigins") or []


def cors_headers_for(channel: Channel, origin: Optional[str]) -> Dict[str, str]:
    """The exact allowlisted origin, never `*` (D-A7B-11), always `Vary:
    Origin`, and no `Access-Control-Allow-Credentials` (there is no cookie -
    D-A7B-4). An origin NOT on the list gets no `Allow-Origin` at all - the
    browser blocks the read regardless of the response body."""
    headers = {"Vary": "Origin"}
    if origin and origin in _allowed_origins(channel):
        headers["Access-Control-Allow-Origin"] = origin
    return headers


def origins_for_frame_policy(db: Session, widget_key: str) -> List[str]:
    """S4 - the panel document's `Content-Security-Policy: frame-ancestors`
    source (D-A7B-11/AC-WEB-47), mirroring the plan-11H embed precedent's
    `EmbedSessionService.allowed_origins_for` exactly: unknown/trashed/
    inactive/module-off/tenant-blocked all resolve to an EMPTY list (never a
    404 - this is a read the Next.js middleware makes on every panel request,
    so it stays uniform-by-shape rather than uniform-by-status-code) and a
    read-only lookup, zero DB writes."""
    try:
        channel = resolve_live_channel(db, widget_key)
    except WebchatNotFound:
        return []
    return _allowed_origins(channel)


def resolve_live_channel(db: Session, widget_key: str) -> Channel:
    """GLOBAL lookup by widget key (unauthenticated, no tenant context yet) -
    the SAME resolution `routers/webchat_widget.py`'s loader route already
    uses; `widget_key` carries its own service-wide PARTIAL UNIQUE index over
    live rows, so this can only ever resolve the ONE channel that
    legitimately owns it."""
    channel = (
        db.query(Channel)
        .filter(
            Channel.widget_key == widget_key,
            Channel.channel_type == "WEBCHAT",
            Channel.is_trashed.is_(False),
        )
        .first()
    )
    if channel is None or not channel.is_active:
        raise WebchatNotFound()
    if not ModuleRepository(db).is_active(channel.tenant_id, MODULE_NAME):
        raise WebchatNotFound()
    tenant = db.query(Tenant).filter(Tenant.id == channel.tenant_id).first()
    if tenant is None or not tenant.signin_allowed:
        raise WebchatNotFound()
    return channel


async def read_capped_json(request: Request, *, cap: int = BODY_MAX_BYTES) -> Dict[str, Any]:
    """A manually capped, streamed body read (D-A7B-21) - refused WITHOUT
    buffering the rest once `cap` is exceeded, and refused up front for any
    content type that is not plain JSON (AC-WEB-33 - there is no upload
    endpoint of any kind on this surface, so multipart is rejected before a
    single byte of it is read)."""
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type and content_type != "application/json":
        raise WebchatInvalidRequest("unsupported_content", "Unsupported content type.")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > cap:
            raise WebchatInvalidRequest("body_too_large", "Request body is too large.")
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise WebchatInvalidRequest("malformed_body", "Malformed request body.") from exc
    if not isinstance(parsed, dict):
        raise WebchatInvalidRequest("malformed_body", "Malformed request body.")
    return parsed


def stamp_last_seen(db: Session, channel_id: str, visitor_id: str) -> None:
    """AC-WEB-42 - a presence fact (D-A7B-19), stamped on session start, a
    message post and a WS connect (this function's three call sites: here,
    `WebchatVisitorService.post_message`, and `routers/ws.py`'s visitor
    `_authorize` branch). A no-op before the visitor's first message (D-A7B-
    7 - the identity does not exist yet; there is nothing to stamp, which is
    the correct lazy-creation state, not a gap)."""
    identity = ContactRepository(db).find_identity(channel_id, f"visitor:{visitor_id}")
    if identity is not None:
        identity.last_seen_at = datetime.now(timezone.utc)
        db.commit()


class WebchatVisitorService:
    def __init__(self, db: Session):
        self.db = db
        self.contacts = ContactRepository(db)

    # ── session ──────────────────────────────────────────────────────────
    def start_session(
        self, channel: Channel, *, origin: Optional[str], token: Optional[str]
    ) -> Dict[str, Any]:
        """AC-WEB-23..25/28/29. Reads ONLY - mints/renews a token but never
        writes a row (D-A7B-7: contact/identity creation is lazy, on the
        FIRST message, never at session start)."""
        if not origin or origin not in _allowed_origins(channel):
            raise WebchatNotFound()  # AC-WEB-24 - off-list learns nothing

        claims: Optional[VisitorClaims] = None
        if token:
            try:
                claims = verify_visitor_token(token, channel)
            except InvalidVisitorToken:
                # A bad/foreign/epoch-revoked token on a PAGE LOAD starts a
                # fresh session rather than 401ing the visitor out of their
                # own widget (AC-WEB-28 - "a fresh session start immediately
                # succeeds").
                claims = None

        contact_id: Optional[str] = None
        if claims is not None:
            contact_id = claims.contact_id
            if contact_id is None:
                # A message may have created the contact SINCE this token
                # was minted (D-A7B-7's lazy creation) - re-resolve it here
                # so the SAME visitor's history/binding survives a page
                # reload without ever writing anything itself.
                identity = self.contacts.find_identity(
                    channel.id, f"visitor:{claims.visitor_id}"
                )
                contact_id = identity.contact_id if identity is not None else None

        if claims is not None and not needs_renewal(claims):
            # AC-WEB-29 - more than 7 days from expiry: returned UNCHANGED,
            # byte-identical. `history`/`post_message` re-derive the contact
            # from the visitor id on every call (never from this token's
            # possibly-stale `contactId`), so an unchanged token never goes
            # stale in any way that matters.
            new_token, visitor_id, expires_at = token, claims.visitor_id, claims.expires_at
        elif claims is not None:
            new_token, visitor_id, expires_at = mint_visitor_token(
                channel, visitor_id=claims.visitor_id, contact_id=contact_id
            )
        else:
            new_token, visitor_id, expires_at = mint_visitor_token(channel)

        messages: List[Dict[str, Any]] = []
        if contact_id is not None:
            contact = self.contacts.get_by_id(contact_id, channel.tenant_id)
            if contact is not None:
                messages, _ = self._history(channel, contact, after=None, limit=HISTORY_PAGE_LIMIT)

        # AC-WEB-42 - "session start" is one of the three stamp points. A
        # no-op for a brand-new visitor (no identity row exists yet, D-A7B-7).
        stamp_last_seen(self.db, channel.id, visitor_id)

        return {
            "token": new_token,
            "expiresAt": expires_at,
            "visitorId": visitor_id,
            "workspaceId": channel.workspace_id,
            "config": self._session_config(channel),
            # S5 wires the EXISTING `BusinessHoursService` (D-A7B-24); an
            # unconfigured workspace resolves online anyway, so this
            # hardcoded default is the eventual policy's own fallback value,
            # not a placeholder lie.
            "online": True,
            "messages": messages,
        }

    def _session_config(self, channel: Channel) -> Dict[str, Any]:
        cfg = WebchatService(self.db)._config_dict(channel)
        branding = (
            self.db.query(TenantBranding)
            .filter(TenantBranding.tenant_id == channel.tenant_id)
            .first()
        )
        # White-label (`branding_service._to_response`'s own precedent) -
        # NEVER fall back to the raw `tenants.name` column on a PUBLIC
        # surface: a tenant that never set its own branding `appName` gets
        # `None`, never the tenant's row name (which, for the seeded default
        # tenant, is literally "Foundryx EMS").
        tenant_name = branding.app_name if branding else None
        brand_tokens = (branding.tokens_json if branding else None) or {}
        return {
            "appearance": cfg["appearance"],
            "greeting": cfg["greeting"],
            "offlineGreeting": cfg["offlineGreeting"],
            "preChat": cfg["preChat"],
            "agentDisplayName": cfg["appearance"]["agentDisplayName"],
            "tenantName": tenant_name,
            "brandTokens": brand_tokens,
        }

    # ── token verification (message endpoints) ──────────────────────────
    def verify_token(self, channel: Channel, authorization: Optional[str]) -> VisitorClaims:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise WebchatUnauthorized()
        token = authorization[len("bearer "):].strip()
        if not token:
            raise WebchatUnauthorized()
        try:
            return verify_visitor_token(token, channel)
        except InvalidVisitorToken as exc:
            raise WebchatUnauthorized() from exc

    # ── messages: write ──────────────────────────────────────────────────
    def post_message(
        self, channel: Channel, claims: VisitorClaims, body: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Returns `(visitor_message_or_none, is_honeypot)`. A honeypot hit
        stores NOTHING and returns `(None, True)` (AC-WEB-32); otherwise
        `(projected_message, False)`."""
        honeypot = (body.get("hp") or "").strip()
        if honeypot:
            return None, True

        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise WebchatInvalidRequest("text_required", "A message needs some text.")
        if len(text) > TEXT_MAX_CHARS:
            raise WebchatInvalidRequest(
                "text_too_long", f"A message can be at most {TEXT_MAX_CHARS} characters."
            )
        # AC-WEB-33 - no media reference of any kind on this surface, ever.
        if body.get("media") is not None or body.get("mediaKey") is not None:
            raise WebchatInvalidRequest(
                "unsupported_content", "This surface does not accept media."
            )

        # D-A7B-8/D-A7B-54 (S5 writes pre-chat values write-if-empty; S2
        # deliberately ignores them here rather than half-implementing a
        # write path with no tests yet) and D-A7B-9 (a host identity
        # assertion is verified ONLY in S5 - S2 never reads `identity`).
        external_message_id = f"web:{claims.visitor_id}:{uuid4().hex}"
        payload = {
            "from": f"visitor:{claims.visitor_id}",
            "external_message_id": external_message_id,
            "body": text,
        }
        InboundService(self.db).process_payload(channel.id, payload)

        row = (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.tenant_id == channel.tenant_id,
                ConversationMessage.external_message_id == external_message_id,
            )
            .first()
        )
        if row is None:  # pragma: no cover - defensive; process_payload always inserts
            logger.error(
                "webchat message %s vanished after process_payload (channel %s)",
                external_message_id,
                channel.id,
            )
            raise WebchatInvalidRequest("send_failed", "Could not send your message.")
        # AC-WEB-42 - "message post" is the second of the three stamp points.
        # The identity now DEFINITELY exists (this call just created it on a
        # first message, or it already did) - unlike session start's no-op.
        stamp_last_seen(self.db, channel.id, claims.visitor_id)
        item = visitor_message_item(row, channel)
        return item, False

    # ── messages: read ───────────────────────────────────────────────────
    def history(
        self, channel: Channel, claims: VisitorClaims, *, after: Optional[str], limit: int
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """AC-WEB-34 - this visitor's OWN thread only, resolved from the
        TOKEN's visitor id (never a client-supplied contact id). No contact
        yet (never messaged) -> an empty page, never a 404 (a fresh visitor
        polling before their first send is a normal state, not an error)."""
        identity = self.contacts.find_identity(channel.id, f"visitor:{claims.visitor_id}")
        if identity is None:
            return [], None
        contact = self.contacts.get_by_id(identity.contact_id, channel.tenant_id)
        if contact is None:
            return [], None
        return self._history(channel, contact, after=after, limit=limit)

    def _history(
        self,
        channel: Channel,
        contact: Contact,
        *,
        after: Optional[str],
        limit: int,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        capped_limit = max(1, min(limit, HISTORY_PAGE_LIMIT_MAX))
        query = self.db.query(ConversationMessage).filter(
            ConversationMessage.tenant_id == channel.tenant_id,
            ConversationMessage.contact_id == contact.id,
            ConversationMessage.channel_id == channel.id,
        )
        if after:
            cursor = (
                self.db.query(ConversationMessage)
                .filter(
                    ConversationMessage.id == after,
                    ConversationMessage.contact_id == contact.id,
                )
                .first()
            )
            if cursor is not None:
                query = query.filter(
                    or_(
                        ConversationMessage.created_at > cursor.created_at,
                        and_(
                            ConversationMessage.created_at == cursor.created_at,
                            ConversationMessage.id > cursor.id,
                        ),
                    )
                )
        rows = (
            query.order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
            .limit(capped_limit + 1)
            .all()
        )
        has_more = len(rows) > capped_limit
        rows = rows[:capped_limit]
        items = [visitor_message_item(row, channel) for row in rows]
        items = [item for item in items if item is not None]
        next_after = rows[-1].id if has_more and rows else None
        return items, next_after
