"""Web chat widget service (plan 34 / A7b S1) - provisioning, config
read/write, secret mint/rotate, and mass visitor sign-out (epoch bump) for a
WEBCHAT channel.

The widget SECRET (D-A7B-10) lives Fernet-encrypted inside the channel's
existing `credentials_json` (the same column WhatsApp/Messenger/Instagram use
for their own provider tokens) - revealed exactly once, at connect and at
each rotate, never echoed by any read (AC-WEB-18/19). `widget_config_json`
carries every OTHER piece of configuration (appearance, greetings, pre-chat
toggles, allowed origins) - never the secret.

D-A7B-6: rotating the secret and bumping the epoch are two separate admin
actions that never touch each other's state.

Plan 34 S5 (D-A7B-9/AC-WEB-55/56) adds `verify_host_identity` - the ONLY
place a host identity assertion is checked, HMAC-SHA256 against this SAME
channel's CURRENT widget secret via `widget_secret_for` above.
"""
import hashlib
import hmac
import re
import secrets as pysecrets
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings

from ..models import Channel
from ..origins import _validate_origins
from ..repositories.channel_repository import ChannelRepository
from ..repositories.workspace_repository import WorkspaceRepository
from ..schemas import (
    ConnectWebchatRequest,
    RotateWidgetSecretResult,
    SignOutVisitorsResult,
    UpdateWebchatConfigInput,
    WebchatAppearance,
    WebchatConfig,
    WebchatConnectResult,
    WebchatHostIdentity,
    WebchatPreChatToggles,
)
from ..security import decrypt_credentials, encrypt_credentials
from . import statuses
from .channel_guards import assert_webchat
from .channel_service import ChannelNotFound, ChannelService
# Reuse the SAME `WorkspaceNotFound` the WhatsApp/Meta connect flows already
# raise (`onboarding.py`'s router already catches it) rather than minting a
# second identically-named exception class.
from .onboarding_service import WorkspaceNotFound

WIDGET_KEY_PREFIX = "wk_"
WIDGET_SECRET_PREFIX = "whsec_"

# D-A7B-9/AC-WEB-56: a `userRef` is bounded in length + charset so a hostile
# value cannot forge or collide with an anonymous visitor id. The `host:` /
# `visitor:` identity-key PREFIX already makes the two namespaces disjoint
# regardless of `userRef`'s own content (a userRef of literally "vis_..."
# still resolves to `host:vis_...`, never `visitor:vis_...`), but an
# unbounded value could still carry control characters, whitespace, or blow
# past what a customer's own user-id scheme would ever produce - rejected
# outright rather than merely accepted-and-prefixed.
_USER_REF_RE = re.compile(r"^[A-Za-z0-9_.@+-]{1,128}$")

DEFAULT_APPEARANCE: Dict[str, Any] = {
    "accentColor": "#FF5A00",
    "position": "right",
    "headerTitle": "Chat with us",
    "agentDisplayName": "Support",
}
DEFAULT_GREETING = "Hi! How can we help you today?"
DEFAULT_OFFLINE_GREETING = "We're offline right now - leave a message and we'll reply."
DEFAULT_PRE_CHAT: Dict[str, bool] = {"askName": True, "askEmail": True, "askPhone": False}


def _mint_widget_key() -> str:
    return f"{WIDGET_KEY_PREFIX}{uuid4().hex}"


def _mint_widget_secret() -> str:
    return f"{WIDGET_SECRET_PREFIX}{pysecrets.token_urlsafe(32)}"


def _snippet(widget_key: str) -> str:
    base = settings.public_base_url.rstrip("/")
    return f'<script src="{base}/omnichannel/widget/{widget_key}.js" async></script>'


def widget_secret_for(channel: Channel) -> Optional[str]:
    """Decrypt a WEBCHAT channel's current signing secret - the seam slice S2
    (`webchat_auth.py`'s HMAC host-identity-assertion check) and slice S5 will
    call. Returns None only for a channel that somehow has no credentials
    stored yet (never true post-`connect`)."""
    if not channel.credentials_json:
        return None
    creds = decrypt_credentials(channel.credentials_json)
    return creds.get("widgetSecret")


def verify_host_identity(channel: Channel, identity: Any) -> Optional[str]:
    """D-A7B-9/AC-WEB-55/56 - verify a host identity assertion
    `{userRef, hash}` against `channel`'s CURRENT widget secret:
    `hash == hex(HMAC-SHA256(userRef, secret))`, constant-time compared.

    Returns the identity key `host:<userRef>` on success, `None` for EVERY
    failure mode (missing, malformed, wrong shape, a `userRef` outside
    `_USER_REF_RE`, a channel with no stored secret yet, or a non-matching
    hash) - the caller treats `None` as "proceed anonymously", never an
    error (AC-WEB-56's silent-ignore contract; a `userRef` is NEVER trusted
    without a valid signature, under any circumstance).

    Only the CURRENT secret is ever checked - `rotate_secret` overwrites
    `credentials_json` in place (D-A7B-6) and keeps no history, so an
    assertion signed with a since-rotated secret fails exactly like a
    missing one. This is a decision the plan left open (the epoch stays
    unchanged on rotate, but nothing says the OLD secret keeps verifying):
    honoring only the current secret matches "the epoch is a separate
    control from the secret" - a customer who wants zero-downtime secret
    rotation for identity assertions would need dual-secret support, which
    is not built here (BL candidate, not required by any AC).

    `identity` arrives RAW off the wire (review round 1, S1): the session
    body model deliberately types it `Any`, because AC-WEB-56 requires a
    wrong-shaped assertion to be silently ignored rather than 422'd, and a
    strict envelope would have made a typo in an integrator's payload an
    error the visitor sees. The shape check is therefore HERE, through the
    documented `WebchatHostIdentity` model - one declaration of the shape,
    used, rather than a second hand-rolled copy of it (N1)."""
    try:
        assertion = WebchatHostIdentity.model_validate(identity)
    except ValidationError:
        return None
    user_ref = assertion.userRef
    hash_hex = assertion.hash
    if not _USER_REF_RE.fullmatch(user_ref):
        return None
    secret = widget_secret_for(channel)
    if not secret:
        return None
    expected = hmac.new(
        secret.encode("utf-8"), user_ref.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, hash_hex.strip().lower()):
        return None
    return f"host:{user_ref}"


class WebchatService:
    def __init__(self, db: Session):
        self.db = db
        self.channels = ChannelRepository(db)

    # ── internal ─────────────────────────────────────────────────────────
    def _channel(self, channel_id: str, tenant_id: str) -> Channel:
        c = self.channels.get_by_id(channel_id, tenant_id)
        if c is None:
            raise ChannelNotFound()
        assert_webchat(c)
        return c

    def config_dict(self, channel: Channel) -> Dict[str, Any]:
        """The channel's stored widget config merged over the house defaults -
        the ONE place those defaults are applied. Public (review round 1, N2):
        `webchat_visitor_service._session_config` builds the PUBLIC session
        payload from it, and a sibling service reaching into a private method
        is exactly how the two copies of a default drift apart."""
        cfg = channel.widget_config_json or {}
        appearance = {**DEFAULT_APPEARANCE, **(cfg.get("appearance") or {})}
        pre_chat = {**DEFAULT_PRE_CHAT, **(cfg.get("preChat") or {})}
        return {
            "allowedOrigins": cfg.get("allowedOrigins") or [],
            "appearance": appearance,
            "greeting": cfg.get("greeting") or DEFAULT_GREETING,
            "offlineGreeting": cfg.get("offlineGreeting") or DEFAULT_OFFLINE_GREETING,
            "preChat": pre_chat,
        }

    def _to_config(self, channel: Channel) -> WebchatConfig:
        cfg = self.config_dict(channel)
        widget_key = channel.widget_key or ""
        return WebchatConfig(
            widgetKey=widget_key,
            allowedOrigins=cfg["allowedOrigins"],
            tokenEpoch=channel.widget_token_epoch,
            appearance=WebchatAppearance(**cfg["appearance"]),
            greeting=cfg["greeting"],
            offlineGreeting=cfg["offlineGreeting"],
            preChat=WebchatPreChatToggles(**cfg["preChat"]),
            snippet=_snippet(widget_key),
        )

    # ── reads ────────────────────────────────────────────────────────────
    def get_config(self, channel_id: str, tenant_id: str) -> WebchatConfig:
        channel = self._channel(channel_id, tenant_id)
        return self._to_config(channel)

    # ── writes ───────────────────────────────────────────────────────────
    def connect(self, payload: ConnectWebchatRequest, tenant_id: str) -> WebchatConnectResult:
        ws = WorkspaceRepository(self.db).get_by_id(payload.workspaceId, tenant_id)
        if ws is None:
            raise WorkspaceNotFound()

        statuses.ensure_statuses(self.db, tenant_id)
        widget_key = _mint_widget_key()
        widget_secret = _mint_widget_secret()
        origins = _validate_origins(payload.allowedOrigins)

        channel = Channel(
            tenant_id=tenant_id,
            workspace_id=payload.workspaceId,
            channel_type="WEBCHAT",
            name=payload.name.strip(),
            credentials_json=encrypt_credentials({"widgetSecret": widget_secret}),
            widget_key=widget_key,
            widget_config_json={"allowedOrigins": origins},
            widget_token_epoch=0,
            is_active=True,
            status_id=statuses.status_id_for(self.db, tenant_id, "CHANNEL", "ACTIVE"),
        )
        self.db.add(channel)
        self.db.commit()
        self.db.refresh(channel)

        item = ChannelService(self.db)._items([channel], tenant_id)[0]
        return WebchatConnectResult(**item.model_dump(), widgetSecret=widget_secret)

    def update_config(
        self, channel_id: str, payload: UpdateWebchatConfigInput, tenant_id: str
    ) -> WebchatConfig:
        channel = self._channel(channel_id, tenant_id)
        cfg = self.config_dict(channel)
        if payload.allowedOrigins is not None:
            cfg["allowedOrigins"] = _validate_origins(payload.allowedOrigins)
        if payload.appearance is not None:
            patch = payload.appearance.model_dump(exclude_none=True)
            cfg["appearance"] = {**cfg["appearance"], **patch}
        if payload.greeting is not None:
            cfg["greeting"] = payload.greeting
        if payload.offlineGreeting is not None:
            cfg["offlineGreeting"] = payload.offlineGreeting
        if payload.preChat is not None:
            patch = payload.preChat.model_dump(exclude_none=True)
            cfg["preChat"] = {**cfg["preChat"], **patch}
        # Reassign a NEW dict so SQLAlchemy tracks the JSON change (house rule
        # - in-place JSON mutation is invisible to the ORM).
        channel.widget_config_json = {**cfg}
        self.db.commit()
        self.db.refresh(channel)
        return self._to_config(channel)

    def rotate_secret(self, channel_id: str, tenant_id: str) -> RotateWidgetSecretResult:
        channel = self._channel(channel_id, tenant_id)
        widget_secret = _mint_widget_secret()
        # D-A7B-6: rotating the secret NEVER bumps the epoch - the previous
        # secret stops verifying immediately (S2's HMAC check decrypts fresh
        # every time, so there is nothing further to invalidate).
        channel.credentials_json = encrypt_credentials({"widgetSecret": widget_secret})
        self.db.commit()
        return RotateWidgetSecretResult(widgetSecret=widget_secret)

    def sign_out_visitors(self, channel_id: str, tenant_id: str) -> SignOutVisitorsResult:
        channel = self._channel(channel_id, tenant_id)
        # D-A7B-6: bumping the epoch NEVER rotates the secret.
        channel.widget_token_epoch = (channel.widget_token_epoch or 0) + 1
        self.db.commit()
        self.db.refresh(channel)
        return SignOutVisitorsResult(tokenEpoch=channel.widget_token_epoch)
