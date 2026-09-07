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
token's own `identity_key` - never from any request body field (AC-WEB-27).
`visitor_projection.visitor_message_item` is the ONE place a stored message
becomes visitor-visible (D-A7B-17); nothing in this file builds a visitor-
facing message shape any other way.

Plan 34 S5 adds three things, none of which touch the identity/authorization
model above: `online` computed via the EXISTING `BusinessHoursService`
(AC-WEB-52), a host identity assertion resolved to `host:<userRef>` at
session start (AC-WEB-55/56, D-A7B-9 - `identity_key` on the minted token IS
the sanctioned stitch, never a lookup by pre-chat data), and pre-chat
write-if-empty on the visitor's OWN already-resolved contact (AC-WEB-54,
D-A7B-8 - never a lookup or merge against any OTHER contact).
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import Request
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.tenant import Tenant
from app.models.tenant_branding import TenantBranding
from app.repositories.module_repository import ModuleRepository

from ..models import Channel, Contact, ConversationMessage
from ..phone import digits_only
from ..repositories.contact_repository import ContactRepository
from ..webchat_auth import (
    InvalidVisitorToken,
    VisitorClaims,
    mint_visitor_token,
    needs_renewal,
    verify_visitor_token,
)
from .business_hours import MissingBusinessHours, evaluate as evaluate_business_hours
from .inbound_service import InboundService
from .webchat_projection import visitor_message_item
from .webchat_service import WebchatService, verify_host_identity

logger = logging.getLogger(__name__)

MODULE_NAME = "omnichannel"
TEXT_MAX_CHARS = 4096
# The request body's own read cap (D-A7B-21) - well above the 4096-char text
# cap even at worst-case UTF-8 (4 bytes/char) plus a small preChat/honeypot
# envelope, well below anything a DoS attempt would need to matter.
BODY_MAX_BYTES = 24_000
HISTORY_PAGE_LIMIT = 50
HISTORY_PAGE_LIMIT_MAX = 100

# AC-WEB-54: pre-chat values are normalized + capped, NEVER rejected - a bad
# value is silently dropped and the message still lands (foolproof-UI: the
# visitor never sees a validation error for a field they can't even see once
# it's been asked once).
_PRE_CHAT_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PRE_CHAT_NAME_MAX_CHARS = 120
PRE_CHAT_EMAIL_MAX_CHARS = 254
PRE_CHAT_PHONE_MAX_CHARS = 32
PRE_CHAT_PHONE_MIN_DIGITS = 5


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


def panel_origin() -> str:
    """The app's own origin - the one the PANEL iframe is served from, and
    therefore the `Origin` its own fetches carry (BL-SS-183). Never a valid
    value for session start (that call is the LOADER's, from the customer's
    top-level document); the only valid value for the Bearer-authed message
    routes, which only the panel ever calls."""
    return settings.frontend_url.rstrip("/")


def cors_headers_for(
    channel: Channel, origin: Optional[str], *, allow_panel_origin: bool = False
) -> Dict[str, str]:
    """The exact allowlisted origin, never `*` (D-A7B-11), always `Vary:
    Origin`, and no `Access-Control-Allow-Credentials` (there is no cookie -
    D-A7B-4). An origin NOT on the list gets no `Allow-Origin` at all - the
    browser blocks the read regardless of the response body.

    Amended 2026-09-09 (BL-SS-183): `allow_panel_origin` widens the echo by
    the app's OWN origin for the Bearer-authed message routes, which are
    fetched from inside the panel iframe and therefore always carry the
    panel's origin. The channel allowlist stays the only accepted set on
    session start - the customer's website is the caller there, and that is
    exactly the value the allowlist is about."""
    headers = {"Vary": "Origin"}
    if not origin:
        return headers
    if origin in _allowed_origins(channel) or (allow_panel_origin and origin == panel_origin()):
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


def stamp_last_seen(db: Session, channel_id: str, identity_key: str) -> None:
    """AC-WEB-42 - a presence fact (D-A7B-19), stamped on session start, a
    message post and a WS connect (this function's three call sites: here,
    `WebchatVisitorService.post_message`, and `routers/ws.py`'s visitor
    `_authorize` branch). A no-op before the visitor's first message (D-A7B-
    7 - the identity does not exist yet; there is nothing to stamp, which is
    the correct lazy-creation state, not a gap).

    `identity_key` (plan 34 S5) is the token's OWN resolved identity -
    `visitor:<visitorId>` for an anonymous session or `host:<userRef>` once a
    host identity assertion has verified (D-A7B-9) - never re-derived from a
    visitor id here, so a host-identified visitor's presence lands on the
    SAME identity row its messages do."""
    identity = ContactRepository(db).find_identity(channel_id, identity_key)
    if identity is not None:
        identity.last_seen_at = datetime.now(timezone.utc)
        db.commit()


def _online(db: Session, channel: Channel) -> bool:
    """AC-WEB-52/D-A7B-24 - the EXISTING `BusinessHoursService` (the
    workspace row, else the tenant default row); an unconfigured workspace
    resolves `online: true` rather than guessing a schedule. Never
    duplicates `business_hours.py`'s own open/closed logic - `evaluate` IS
    that logic."""
    try:
        is_open, _tzname, _checked_at = evaluate_business_hours(
            db, channel.tenant_id, channel.workspace_id
        )
    except MissingBusinessHours:
        return True
    return is_open


def _clean_pre_chat_value(kind: str, raw: Any) -> Optional[str]:
    """AC-WEB-54 - normalize + cap, never reject; an invalid value is
    dropped (returns `None`), the message still lands unaffected."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if kind == "name":
        return value[:PRE_CHAT_NAME_MAX_CHARS]
    if kind == "email":
        value = value[:PRE_CHAT_EMAIL_MAX_CHARS]
        return value if _PRE_CHAT_EMAIL_RE.match(value) else None
    if kind == "phone":
        if len(digits_only(value)) < PRE_CHAT_PHONE_MIN_DIGITS:
            return None
        return value[:PRE_CHAT_PHONE_MAX_CHARS]
    return None


class WebchatVisitorService:
    def __init__(self, db: Session):
        self.db = db
        self.contacts = ContactRepository(db)

    # ── session ──────────────────────────────────────────────────────────
    def start_session(
        self,
        channel: Channel,
        *,
        origin: Optional[str],
        token: Optional[str],
        identity: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """AC-WEB-23..25/28/29/55/56. Reads ONLY - mints/renews a token but
        never writes a row (D-A7B-7: contact/identity creation is lazy, on
        the FIRST message, never at session start).

        `identity` is the raw `{userRef, hash}` dict straight off the wire;
        `webchat_service.verify_host_identity` is the ONLY place it is
        trusted. A failure of any kind (missing, malformed, non-matching
        hash) is silently ignored and the session proceeds exactly as if
        `identity` had never been sent (AC-WEB-56) - never an error, never a
        distinguishing response."""
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

        # D-A7B-9/AC-WEB-55/56 - verified ONLY here; `None` for every
        # failure mode.
        host_identity_key = verify_host_identity(channel, identity)

        identity_key: str
        contact_id: Optional[str]
        if host_identity_key is not None and (
            claims is None or claims.identity_key != host_identity_key
        ):
            # A fresh, or newly host-identified, session: mint a NEW visitor
            # id bound to the ASSERTED identity rather than inheriting
            # whatever anonymous session the browser already carried - a
            # host identity assertion is the ONLY sanctioned stitch
            # (D-A7B-9) and must never inherit an anonymous token's own
            # separate history.
            identity_key = host_identity_key
            existing = self.contacts.find_identity(channel.id, identity_key)
            contact_id = existing.contact_id if existing is not None else None
            new_token, visitor_id, expires_at = mint_visitor_token(
                channel, contact_id=contact_id, identity_key=identity_key
            )
        elif claims is not None:
            identity_key = claims.identity_key
            contact_id = claims.contact_id
            if contact_id is None:
                # A message may have created the contact SINCE this token
                # was minted (D-A7B-7's lazy creation) - re-resolve it here
                # so the SAME visitor's history/binding survives a page
                # reload without ever writing anything itself.
                existing = self.contacts.find_identity(channel.id, identity_key)
                contact_id = existing.contact_id if existing is not None else None
            if not needs_renewal(claims):
                # AC-WEB-29 - more than 7 days from expiry: returned
                # UNCHANGED, byte-identical. `history`/`post_message`
                # re-derive the contact from the identity key on every call
                # (never from this token's possibly-stale `contactId`), so
                # an unchanged token never goes stale in any way that
                # matters.
                new_token, visitor_id, expires_at = token, claims.visitor_id, claims.expires_at
            else:
                new_token, visitor_id, expires_at = mint_visitor_token(
                    channel,
                    visitor_id=claims.visitor_id,
                    contact_id=contact_id,
                    identity_key=identity_key,
                )
        else:
            contact_id = None
            new_token, visitor_id, expires_at = mint_visitor_token(channel)
            identity_key = f"visitor:{visitor_id}"

        messages: List[Dict[str, Any]] = []
        if contact_id is not None:
            contact = self.contacts.get_by_id(contact_id, channel.tenant_id)
            if contact is not None:
                messages, _ = self._history(channel, contact, after=None, limit=HISTORY_PAGE_LIMIT)

        # AC-WEB-42 - "session start" is one of the three stamp points. A
        # no-op for a brand-new visitor (no identity row exists yet, D-A7B-7).
        stamp_last_seen(self.db, channel.id, identity_key)

        return {
            "token": new_token,
            "expiresAt": expires_at,
            "visitorId": visitor_id,
            "workspaceId": channel.workspace_id,
            "config": self._session_config(channel),
            "online": _online(self.db, channel),  # AC-WEB-52/D-A7B-24
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

        # `claims.identity_key` is the ONLY identity this message is ever
        # attributed to - `visitor:<visitorId>` for an ordinary anonymous
        # session, or `host:<userRef>` once a host identity assertion
        # verified at session start (D-A7B-9). `InboundService._resolve_
        # contact` does the SAME lazy-create-or-reuse-by-external-user-id it
        # already does for every other channel type - no special case here.
        external_message_id = f"web:{claims.visitor_id}:{uuid4().hex}"
        payload = {
            "from": claims.identity_key,
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

        # AC-WEB-54/D-A7B-8 - write-if-empty on the visitor's OWN
        # just-resolved contact ONLY. This is NOT a lookup: `row.contact_id`
        # is the contact `_resolve_contact` above just attached to THIS
        # identity - there is no search by name/email/phone anywhere in this
        # path, on this message or any later one. Honored on every message
        # (not only the first) where the target field is still empty, which
        # is behaviourally identical to "first message only" from each
        # field's own point of view - once a field is set it is never
        # touched here again.
        pre_chat = body.get("preChat")
        if isinstance(pre_chat, dict):
            contact = self.contacts.get_by_id(row.contact_id, channel.tenant_id)
            if contact is not None and self._apply_pre_chat(contact, pre_chat):
                self.db.commit()

        # AC-WEB-42 - "message post" is the second of the three stamp points.
        # The identity now DEFINITELY exists (this call just created it on a
        # first message, or it already did) - unlike session start's no-op.
        stamp_last_seen(self.db, channel.id, claims.identity_key)
        item = visitor_message_item(row, channel)
        return item, False

    def _apply_pre_chat(self, contact: Contact, pre_chat: Dict[str, Any]) -> bool:
        """AC-WEB-54/D-A7B-8 - write ONLY onto fields that are currently
        empty on THIS contact; returns whether anything changed (so the
        caller only commits when needed). Never a lookup, never a merge."""
        changed = False
        name = _clean_pre_chat_value("name", pre_chat.get("name"))
        if name and not contact.first_name and not contact.last_name:
            first, _, last = name.partition(" ")
            contact.first_name = first or None
            contact.last_name = last or None
            changed = True
        email = _clean_pre_chat_value("email", pre_chat.get("email"))
        if email and not contact.email:
            contact.email = email
            changed = True
        phone = _clean_pre_chat_value("phone", pre_chat.get("phone"))
        if phone and not contact.phone:
            contact.phone = phone
            contact.phone_digits = digits_only(phone)
            changed = True
        return changed

    # ── messages: read ───────────────────────────────────────────────────
    def history(
        self, channel: Channel, claims: VisitorClaims, *, after: Optional[str], limit: int
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """AC-WEB-34 - this visitor's OWN thread only, resolved from the
        TOKEN's identity key (never a client-supplied contact id). No
        contact yet (never messaged) -> an empty page, never a 404 (a fresh
        visitor polling before their first send is a normal state, not an
        error)."""
        identity = self.contacts.find_identity(channel.id, claims.identity_key)
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
