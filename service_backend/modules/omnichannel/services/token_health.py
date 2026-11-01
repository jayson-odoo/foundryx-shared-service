"""WhatsApp token health (plan 42).

A 6-hourly beat scans for live WhatsApp channels and queues one check each. A
check classifies the stored token (``ok`` | ``dead`` | ``unknown``) and is the
only writer of the ERROR label: ``dead`` sets it (one email on the change),
``ok`` clears it, ``unknown`` changes nothing. ``is_active`` is never written
here, so routing, broadcasts and inbound behave as before.

The status write is guarded on the ``credentials_json`` value the check read, so
a token replaced while the check was in flight is never overwritten. The token
is never logged, returned or stored outside the encrypted credentials.
"""
import html
import logging
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.models.tenant import DEFAULT_TENANT_ID
from app.services.throttle import ThrottleService
from app.services.email_service import OutboxEmailService
from ..adapters.whatsapp_cloud import get_adapter
from ..models import Channel
from ..repositories.channel_repository import ChannelRepository
from ..schemas import ChannelItem, ReplaceTokenResult
from ..security import decrypt_credentials, encrypt_credentials
from . import statuses
from .channel_guards import assert_whatsapp
from .channel_service import ChannelNotFound, ChannelService

logger = logging.getLogger(__name__)

MANAGE_PERMISSION = "channels.manage"
REFUSAL_MESSAGE = "This token could not be verified for this number."


class TokenRefused(Exception):
    """The pasted token did not verify on the channel's own number."""


def _credentials(channel: Channel) -> Optional[dict]:
    if not channel.credentials_json:
        return None
    try:
        return decrypt_credentials(channel.credentials_json)
    except (InvalidToken, ValueError):
        return None


def _checkable(channel: Channel) -> Optional[dict]:
    """Credentials of a channel worth checking, else None (dev, no token, no number)."""
    if channel.channel_type != "WHATSAPP" or channel.is_trashed or not channel.phone_number_id:
        return None
    creds = _credentials(channel)
    if not creds or creds.get("dev") or not creds.get("access_token"):
        return None
    return creds


# ── scan + queue ─────────────────────────────────────────────────────────────
def enqueue_channel_token_check(channel_id: str) -> None:
    """Queue one check on the omni worker (inline in eager dev)."""
    from ..worker import check_channel_token_task

    check_channel_token_task.delay(channel_id)


def run_channel_token_checks(db: Session) -> int:
    """The beat body: queue one check per eligible channel. Makes no Meta call.
    A failed enqueue for one channel never stops the rest."""
    queued = 0
    for channel in ChannelRepository(db).token_check_candidates():
        if _checkable(channel) is None:
            continue
        try:
            enqueue_channel_token_check(channel.id)
            queued += 1
        except Exception:  # noqa: BLE001 - one bad enqueue never stops the scan
            logger.exception("token check enqueue failed for channel %s", channel.id)
    return queued


# ── one check ────────────────────────────────────────────────────────────────
def check_channel_token(db: Session, channel_id: str) -> Optional[str]:
    """Check one channel and apply the verdict. Returns the verdict, or None when
    the channel was not checkable."""
    repo = ChannelRepository(db)
    channel = repo.get_unscoped(channel_id)
    if channel is None:
        return None
    creds = _checkable(channel)
    if creds is None:
        return None
    tenant_id = channel.tenant_id
    read_credentials = channel.credentials_json
    phone_number_id = channel.phone_number_id
    db.rollback()  # no transaction held open across the Meta call

    try:
        verdict = get_adapter("WHATSAPP").check_token(creds, phone_number_id)
    except Exception:  # noqa: BLE001 - an adapter fault is "could not tell"
        logger.warning("token check failed for channel %s", channel_id)
        return "unknown"
    if verdict not in ("ok", "dead"):
        return "unknown"

    statuses.ensure_statuses(db, tenant_id)
    db.commit()
    error_id = statuses.status_id_for(db, tenant_id, "CHANNEL", "ERROR")
    channel = repo.get_by_id(channel_id, tenant_id)
    if channel is None or error_id is None:
        return verdict

    if verdict == "dead":
        if channel.status_id == error_id:
            return verdict
        changed = repo.set_status_if_credentials_unchanged(
            channel, read_credentials, error_id, not_status_id=error_id
        )
        db.commit()
        if changed:
            db.refresh(channel)
            _notify_dead(db, channel)
        return verdict

    if channel.status_id == error_id:
        key = "ACTIVE" if channel.is_active else "INACTIVE"
        target = statuses.status_id_for(db, tenant_id, "CHANNEL", key)
        if target is not None:
            repo.set_status_if_credentials_unchanged(
                channel, read_credentials, target, from_status_id=error_id
            )
            db.commit()
    return verdict


def _last_digits(channel: Channel) -> str:
    digits = "".join(ch for ch in (channel.display_phone_number or "") if ch.isdigit())
    return digits[-4:]


def _notify_dead(db: Session, channel: Channel) -> None:
    """One email per active manager of the channel's own tenant. Runs after the
    status commit; a failure is logged (channel id only) and never propagates."""
    try:
        recipients = {}
        for user in ChannelRepository(db).users_with_permission(channel.tenant_id, MANAGE_PERMISSION):
            if user.status == "ACTIVE" and user.email:
                recipients.setdefault(user.email.strip().lower(), user.email.strip())
        name = (channel.name or "WhatsApp").strip()
        tail = _last_digits(channel)
        number = f" ending {tail}" if tail else ""
        subject = f"WhatsApp number{number} needs a new access token"
        text = (
            f"The access token for {name}{number} has expired or been revoked, so the "
            "channel now shows Error. Open Channels, choose Replace token on that row "
            "and paste a new permanent access token."
        )
        body = f"<p>{html.escape(text)}</p>"
    except Exception:  # noqa: BLE001
        logger.exception("token health email could not be composed for channel %s", channel.id)
        db.rollback()
        return
    for address in recipients.values():
        try:
            OutboxEmailService().enqueue_raw(db, channel.tenant_id, address, subject, body, text)
        except Exception:  # noqa: BLE001 - mail trouble never undoes the status change
            logger.exception("token health email failed for channel %s", channel.id)
            db.rollback()


# ── replace ──────────────────────────────────────────────────────────────────
MESSAGING_SCOPE = "whatsapp_business_messaging"


def replace_token(
    db: Session, channel_id: str, access_token: str, tenant_id: str = DEFAULT_TENANT_ID
) -> ReplaceTokenResult:
    repo = ChannelRepository(db)
    channel = repo.get_by_id(channel_id, tenant_id)
    if channel is None or channel.is_trashed:
        raise ChannelNotFound()
    assert_whatsapp(channel)

    token = (access_token or "").strip()
    phone_number_id = channel.phone_number_id
    if not token or not phone_number_id:
        raise TokenRefused()

    # Every attempt counts, refused ones included; checked before any Graph call.
    throttle = ThrottleService(db)
    throttle.enforce_channel_token(channel_id=channel_id)  # raises Throttled
    throttle.record_channel_token(channel_id=channel_id)

    creds = _credentials(channel) or {}
    creds.pop("dev", None)
    creds["access_token"] = token
    adapter = get_adapter("WHATSAPP")
    waba_id = channel.waba_id
    db.rollback()  # no transaction held open across the Meta calls

    try:
        verdict = adapter.check_token(creds, phone_number_id)
    except Exception:  # noqa: BLE001
        logger.warning("replace token check failed for channel %s", channel_id)
        verdict = "unknown"
    if verdict != "ok":
        raise TokenRefused()

    # One read of the token's details, before the save.
    try:
        details = adapter.token_details(token)
    except Exception:  # noqa: BLE001
        details = None
    details = details or {}
    scopes = details.get("scopes")
    if scopes is not None and MESSAGING_SCOPE not in scopes:
        raise TokenRefused()

    statuses.ensure_statuses(db, tenant_id)
    channel = repo.get_by_id(channel_id, tenant_id)
    if channel is None or channel.is_trashed:
        raise ChannelNotFound()
    channel.credentials_json = encrypt_credentials(creds)
    error_id = statuses.status_id_for(db, tenant_id, "CHANNEL", "ERROR")
    if error_id is not None and channel.status_id == error_id:
        key = "ACTIVE" if channel.is_active else "INACTIVE"
        channel.status_id = statuses.status_id_for(db, tenant_id, "CHANNEL", key)
    db.commit()

    # A token minted under another app cannot renew this app's webhook.
    token_app = details.get("app_id")
    own_app = settings.meta_app_id
    other_app = bool(token_app and own_app and str(token_app) != str(own_app))
    subscribed: Optional[bool] = None
    if waba_id:
        if other_app:
            subscribed = False
        else:
            try:
                subscribed = bool(adapter.subscribe_app_checked(creds, waba_id))
            except Exception:  # noqa: BLE001
                logger.warning("webhook renewal failed for channel %s", channel_id)
                subscribed = False
    expires: Optional[datetime] = details.get("expires_at")
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    db.refresh(channel)
    item: ChannelItem = ChannelService(db)._items([channel], tenant_id)[0]
    return ReplaceTokenResult(**item.model_dump(), subscribed=subscribed, tokenExpiresAt=expires)
