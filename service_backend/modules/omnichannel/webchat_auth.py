"""Visitor token mint/verify (plan 34 / A7b S2, D-A7B-5).

A signed, opaque JWT (`typ="webchat"`) bound to tenant + channel + visitor id
(+ contact id, once one exists - D-A7B-7's lazy creation means a freshly
minted token carries `contactId=None`). Uses the core `app.security` JWT
helpers - no new crypto (the plan's own instruction): signed with the
platform's own JWT secret, NEVER the per-channel widget secret (that secret
signs ONLY host-identity-assertion HMACs, slice S5).

There is NO visitor-token table (D-A7B-5) - mass revocation is the per-channel
`widget_token_epoch` integer every token embeds and every verify compares
(D-A7B-6: rotating the widget SECRET never touches this; bumping this never
rotates the secret). A verify failure is ALWAYS the same `InvalidVisitorToken`
regardless of which check failed - forged, expired, wrong-typ, wrong-channel
and epoch-revoked are one indistinguishable case to the caller (AC-WEB-27,
R4); the router maps it to one 401 body.

Plan 34 S5 (D-A7B-9/AC-WEB-55/56) adds `identityKey` - the channel-scoped
`ContactChannelIdentity.external_user_id` this token's conversation is
addressed as: `visitor:<visitorId>` for an ordinary anonymous session, or
`host:<userRef>` once `webchat_service.verify_host_identity` accepts a host
identity assertion. It is decoupled from `visitorId` (which stays the
session/device identifier used as the JWT `sub` and the throttle's `v:`
bucket) precisely so a host-identified visitor keeps ONE contact across
tabs/devices/renewals while an anonymous visitor's identity stays tied to the
one browser that minted it. A token minted before this slice carries no
`identityKey` claim; `verify_visitor_token` defaults it to
`visitor:<visitorId>` so an in-flight token keeps resolving its own thread.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import uuid4

from jose import JWTError

from app.security import create_access_token, decode_access_token

from .models import Channel

WEBCHAT_TOKEN_TYP = "webchat"
# D-A7B-5: 30 day expiry, sliding renewal inside the last 7 days (AC-WEB-29).
VISITOR_TOKEN_TTL_DAYS = 30
VISITOR_TOKEN_RENEW_WITHIN_DAYS = 7


class InvalidVisitorToken(Exception):
    """Signature, `typ`, tenant/channel binding, epoch, or expiry check
    failed - the router maps every case to the SAME 401 body (R4)."""


class VisitorClaims:
    """The verified, trusted claims of a visitor token."""

    __slots__ = (
        "tenant_id",
        "channel_id",
        "visitor_id",
        "contact_id",
        "epoch",
        "expires_at",
        "identity_key",
    )

    def __init__(
        self,
        tenant_id: str,
        channel_id: str,
        visitor_id: str,
        contact_id: Optional[str],
        epoch: int,
        expires_at: Optional[datetime],
        identity_key: str,
    ) -> None:
        self.tenant_id = tenant_id
        self.channel_id = channel_id
        self.visitor_id = visitor_id
        self.contact_id = contact_id
        self.epoch = epoch
        self.expires_at = expires_at
        self.identity_key = identity_key


def mint_visitor_token(
    channel: Channel,
    *,
    visitor_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    identity_key: Optional[str] = None,
) -> Tuple[str, str, datetime]:
    """Mint a fresh (no `visitor_id`) or renewed (same `visitor_id`) token
    bound to `channel`'s CURRENT `widget_token_epoch`. Returns
    `(token, visitor_id, expires_at)`. Never writes to the database - there
    is nothing to persist (D-A7B-5; AC-WEB-25's zero-rows-per-page-view).

    `identity_key` (plan 34 S5) is the `ContactChannelIdentity.external_
    user_id` this token's thread is addressed as - `visitor:<vid>` by
    default, or a caller-supplied `host:<userRef>` once a host identity
    assertion has verified (D-A7B-9)."""
    vid = visitor_id or f"vis_{uuid4().hex}"
    key = identity_key or f"visitor:{vid}"
    ttl_minutes = VISITOR_TOKEN_TTL_DAYS * 24 * 60
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    claims = {
        "sub": vid,
        "typ": WEBCHAT_TOKEN_TYP,
        "tenantId": channel.tenant_id,
        "channelId": channel.id,
        "visitorId": vid,
        "contactId": contact_id,
        "epoch": channel.widget_token_epoch or 0,
        "identityKey": key,
    }
    token = create_access_token(claims, expires_minutes=ttl_minutes)
    return token, vid, expires_at


def verify_visitor_token(token: str, channel: Channel) -> VisitorClaims:
    """Decode + verify a visitor token is valid for THIS channel right now.
    Raises `InvalidVisitorToken` on any failure (AC-WEB-27/R4) - a forged
    signature, an expired token (`decode_access_token`/jose enforces `exp`),
    the wrong `typ`, a token minted for a DIFFERENT tenant or channel, or an
    epoch that no longer matches (an admin's "sign out all visitors")."""
    try:
        claims = decode_access_token(token)
    except JWTError as exc:
        raise InvalidVisitorToken("invalid token") from exc
    if claims.get("typ") != WEBCHAT_TOKEN_TYP:
        raise InvalidVisitorToken("wrong typ")
    if claims.get("tenantId") != channel.tenant_id or claims.get("channelId") != channel.id:
        raise InvalidVisitorToken("wrong channel")
    if claims.get("epoch") != (channel.widget_token_epoch or 0):
        raise InvalidVisitorToken("epoch revoked")
    visitor_id = claims.get("visitorId")
    if not visitor_id:
        raise InvalidVisitorToken("missing visitor id")
    exp = claims.get("exp")
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
    # A token minted before plan 34 S5 carries no `identityKey` claim - default
    # it to the same key `post_message`/`history` used to derive implicitly
    # (`visitor:<visitorId>`) so an in-flight token keeps resolving its thread.
    identity_key = claims.get("identityKey") or f"visitor:{visitor_id}"
    return VisitorClaims(
        tenant_id=claims["tenantId"],
        channel_id=claims["channelId"],
        visitor_id=visitor_id,
        contact_id=claims.get("contactId"),
        epoch=claims.get("epoch") or 0,
        expires_at=expires_at,
        identity_key=identity_key,
    )


def needs_renewal(claims: VisitorClaims) -> bool:
    """AC-WEB-29 - within 7 days of expiry, renew; further out, leave alone."""
    if claims.expires_at is None:
        return True
    return claims.expires_at - datetime.now(timezone.utc) <= timedelta(
        days=VISITOR_TOKEN_RENEW_WITHIN_DAYS
    )
