"""Visitor projection (plan 34 / A7b S2, D-A7B-17) - the SINGLE chokepoint
everything a visitor ever sees passes through.

Fail-closed allowlist: `visitor_message_item` (REST history/messages) and
`visitor_frame` (the realtime relay S3 wires up) both DROP - return `None` -
for any sender source, message kind, or frame type they do not explicitly
allow, rather than passing an unrecognized shape through by default. Neither
function ever reads `sender_id`, `sender_external_agent_id`, assignee, tags,
lifecycle, custom fields or close reasons - the AGENT display name comes
ONLY from the CHANNEL's own `widget_config_json.appearance.agentDisplayName`
(R2 - the workspace realtime room and the internal `MessageItem` both carry
staff PII this module exists to keep off a public browser surface).
"""
from typing import Any, Dict, Optional

from ..models import Channel, ConversationMessage
from ..security import signed_media_url

# `sender_type` values this surface will ever project (AC-WEB-34: internal
# notes are `sender_type="SYSTEM"` with `channel_id=None` - already excluded
# by the caller's `channel_id` filter, but dropped HERE too, defense in
# depth per R2/AC-WEB-35).
_ALLOWED_SENDER_TYPES = {"AGENT", "CONTACT"}
# Message kinds wired end-to-end for a visitor. `UNSUPPORTED` is the house
# placeholder for an inbound type the pipeline could not render (never
# leaked as anything more revealing than "unsupported"). The five media
# kinds (S3, AC-WEB-41) are AGENT-OUT only in practice - a visitor can never
# author one (D-A7B-20, `webchat_visitor_service.post_message` refuses any
# media reference before a row is ever created) - but the allowlist itself
# does not encode direction; `_media_dict` below does, as defense in depth
# (R2). `STICKER`/`TEMPLATE`/`INTERACTIVE`(list)/`LOCATION`/`CONTACTS` stay
# DROPPED - `messaging_policy.CAPABILITIES["WEBCHAT"]` already refuses them
# at send time, so a WEBCHAT thread never has one, but this allowlist is the
# fail-closed backstop if that policy ever drifts.
_ALLOWED_MESSAGE_KINDS = {"TEXT", "UNSUPPORTED", "IMAGE", "VIDEO", "AUDIO", "VOICE", "DOCUMENT"}
_MEDIA_KINDS = {"IMAGE", "VIDEO", "AUDIO", "VOICE", "DOCUMENT"}
# Realtime frame types the visitor relay (S3) will ever forward.
_ALLOWED_FRAME_TYPES = {"message.created"}

_DIRECTION_BY_SENDER = {"CONTACT": "in", "AGENT": "out"}

# Delivery statuses a visitor may ever see, mapped onto the wire vocabulary
# `schemas.VisitorMessage.status` pins (review round 1, B1). The allowlist
# lives HERE, not in the Pydantic `Literal`: `ConversationMessage.delivery_
# status` also legitimately holds `QUEUED` (the instant an agent reply is
# committed, before the Celery send task picks it up) and `SENDING`, and
# passing either through raised a `ValidationError` INSIDE the public route -
# a 500 that took the visitor's whole transcript with it, permanently while
# the omnichannel worker was down. An in-flight or unrecognized status now
# projects as `None` ("no receipt yet"), the same fail-closed discipline
# sender type and message kind already follow (AC-WEB-35).
_STATUS_BY_DELIVERY = {
    "SENT": "sent",
    "DELIVERED": "delivered",
    "READ": "read",
    "FAILED": "failed",
}


def _project_status(raw: Any) -> Optional[str]:
    """The ONE place a stored/serialized delivery status becomes a visitor-
    visible one. Anything not on `_STATUS_BY_DELIVERY` - `QUEUED`, `SENDING`,
    `None`, a non-string, or a value some future provider adds - is `None`."""
    if not isinstance(raw, str):
        return None
    return _STATUS_BY_DELIVERY.get(raw.strip().upper())


def _agent_display_name(channel: Channel) -> str:
    cfg = channel.widget_config_json or {}
    appearance = cfg.get("appearance") or {}
    return appearance.get("agentDisplayName") or "Support"


def _media_dict(
    *, direction: str, kind: str, has_blob: Any, message_id: str,
    mime: Optional[str], filename: Optional[str],
) -> Optional[Dict[str, Any]]:
    """AC-WEB-41 - a signed, short-TTL URL bound to the message id, built
    ONLY for an AGENT-sent (`direction == "out"`) media message that actually
    has a stored blob (`has_blob` is truthy - the row's own `media_key` for
    `visitor_message_item`, the frame's `mediaUrl` presence for
    `visitor_frame`, both meaning the same thing: a blob was stored). A
    visitor never has anything to project here (D-A7B-20 - there is no
    visitor-authored media path at all), but this checks direction
    explicitly rather than relying on that absence (R2, defense in depth)."""
    if direction != "out" or kind not in _MEDIA_KINDS or not has_blob:
        return None
    return {"url": signed_media_url(message_id), "mimeType": mime, "name": filename}


def visitor_message_item(
    message: ConversationMessage, channel: Channel
) -> Optional[Dict[str, Any]]:
    """Project ONE stored `ConversationMessage` into the small object a
    visitor may see, or `None` if it must be dropped."""
    if message.sender_type not in _ALLOWED_SENDER_TYPES:
        return None
    kind = (message.message_type or "TEXT").upper()
    if kind not in _ALLOWED_MESSAGE_KINDS:
        return None
    direction = _DIRECTION_BY_SENDER[message.sender_type]
    return {
        "id": message.id,
        "direction": direction,
        "text": message.body if kind == "TEXT" else None,
        # Agent-to-visitor media rides a signed short-TTL URL bound to the
        # message id (AC-WEB-41, D-A7B-20 - no visitor-authored media path
        # exists, so this is only ever populated for an AGENT-out message).
        # `getattr(..., None)` (not a bare attribute read) - S2's own unit
        # tests construct a bare `SimpleNamespace` row with no media columns
        # at all for the non-media cases; a real `ConversationMessage` ORM
        # instance always has these three columns regardless.
        "media": _media_dict(
            direction=direction, kind=kind, has_blob=getattr(message, "media_key", None),
            message_id=message.id, mime=getattr(message, "media_mime", None),
            filename=getattr(message, "media_filename", None),
        ),
        "quickReplies": None,
        "agentName": _agent_display_name(channel) if direction == "out" else None,
        "createdAt": message.created_at,
        "status": _project_status(message.delivery_status),
    }


def visitor_frame(
    frame: Dict[str, Any], channel: Channel, contact_id: str, channel_id: str
) -> Optional[Dict[str, Any]]:
    """Project ONE realtime pub/sub frame for relay to a visitor's own
    socket (S3 wires the actual WS relay through this chokepoint - built now
    so AC-WEB-35's fail-closed test covers the frame-type case, not only the
    REST-read case). Any frame type not explicitly allowed, or one that does
    not belong to THIS visitor's own contact ON THIS VISITOR'S OWN CHANNEL,
    is dropped (R1).

    `channel_id` (review round 1, B2) closes the gap the contact filter alone
    left open: one contact can legitimately carry identities on several
    channels (a visitor who also messages the business on WhatsApp stitches
    onto the SAME contact), the realtime room is per WORKSPACE, and the REST
    read has always filtered `ConversationMessage.channel_id == channel.id` -
    so without this check the socket delivered strictly MORE than the poll
    (AC-WEB-40), including agent WhatsApp replies and their signed media
    URLs, to a browser sitting on a public website. Fail closed: a frame
    whose `message.channelId` is missing or `None` is dropped, never relayed
    on the assumption that it is ours."""
    if frame.get("type") not in _ALLOWED_FRAME_TYPES:
        return None
    message = frame.get("message") or {}
    if message.get("contactId") != contact_id:
        return None
    if not channel_id or message.get("channelId") != channel_id:
        return None
    sender_type = message.get("senderType")
    if sender_type not in _ALLOWED_SENDER_TYPES:
        return None
    kind = (message.get("messageType") or "TEXT").upper()
    if kind not in _ALLOWED_MESSAGE_KINDS:
        return None
    direction = _DIRECTION_BY_SENDER[sender_type]
    # The frame's `message` is a `MessageItem.model_dump(mode="json")` - its
    # `mediaUrl` is the INTERNAL Bearer-authed relative path
    # (`/omnichannel/media/{id}`), never handed to a visitor; only the id +
    # its own media_key presence (mirrored here by `mediaUrl` being set)
    # decide whether a signed URL gets minted (AC-WEB-41).
    media = _media_dict(
        direction=direction, kind=kind,
        has_blob=message.get("mediaUrl"), message_id=message.get("id"),
        mime=message.get("mediaMime"), filename=message.get("mediaFilename"),
    )
    return {
        "id": message.get("id"),
        "direction": direction,
        "text": message.get("body") if kind == "TEXT" else None,
        "media": media,
        "quickReplies": None,
        "agentName": _agent_display_name(channel) if direction == "out" else None,
        "createdAt": message.get("createdAt"),
        "status": _project_status(message.get("deliveryStatus")),
    }
