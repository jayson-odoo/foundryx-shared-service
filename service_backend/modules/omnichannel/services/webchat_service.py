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
"""
import secrets as pysecrets
from typing import Any, Dict, Optional
from uuid import uuid4

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

    def _config_dict(self, channel: Channel) -> Dict[str, Any]:
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
        cfg = self._config_dict(channel)
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
        cfg = self._config_dict(channel)
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
