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

# `sender_type` values this surface will ever project (AC-WEB-34: internal
# notes are `sender_type="SYSTEM"` with `channel_id=None` - already excluded
# by the caller's `channel_id` filter, but dropped HERE too, defense in
# depth per R2/AC-WEB-35).
_ALLOWED_SENDER_TYPES = {"AGENT", "CONTACT"}
# Message kinds wired end-to-end for a visitor in THIS slice. `UNSUPPORTED`
# is the house placeholder for an inbound type the pipeline could not render
# (never leaked as anything more revealing than "unsupported"). Every other
# kind (media types land in S3) is DROPPED until explicitly added here.
_ALLOWED_MESSAGE_KINDS = {"TEXT", "UNSUPPORTED"}
# Realtime frame types the visitor relay (S3) will ever forward.
_ALLOWED_FRAME_TYPES = {"message.created"}

_DIRECTION_BY_SENDER = {"CONTACT": "in", "AGENT": "out"}


def _agent_display_name(channel: Channel) -> str:
    cfg = channel.widget_config_json or {}
    appearance = cfg.get("appearance") or {}
    return appearance.get("agentDisplayName") or "Support"


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
        # message id - wired up in S3 (D-A7B-41/`signed_media_url`); no
        # media path exists yet for a visitor to read (D-A7B-20 - no
        # visitor-authored media at all, ever).
        "media": None,
        "quickReplies": None,
        "agentName": _agent_display_name(channel) if direction == "out" else None,
        "createdAt": message.created_at,
        "status": (message.delivery_status or "").lower() or None,
    }


def visitor_frame(
    frame: Dict[str, Any], channel: Channel, contact_id: str
) -> Optional[Dict[str, Any]]:
    """Project ONE realtime pub/sub frame for relay to a visitor's own
    socket (S3 wires the actual WS relay through this chokepoint - built now
    so AC-WEB-35's fail-closed test covers the frame-type case, not only the
    REST-read case). Any frame type not explicitly allowed, or one that does
    not belong to THIS visitor's own contact, is dropped (R1)."""
    if frame.get("type") not in _ALLOWED_FRAME_TYPES:
        return None
    message = frame.get("message") or {}
    if message.get("contactId") != contact_id:
        return None
    sender_type = message.get("senderType")
    if sender_type not in _ALLOWED_SENDER_TYPES:
        return None
    kind = (message.get("messageType") or "TEXT").upper()
    if kind not in _ALLOWED_MESSAGE_KINDS:
        return None
    direction = _DIRECTION_BY_SENDER[sender_type]
    return {
        "id": message.get("id"),
        "direction": direction,
        "text": message.get("body") if kind == "TEXT" else None,
        "media": None,
        "quickReplies": None,
        "agentName": _agent_display_name(channel) if direction == "out" else None,
        "createdAt": message.get("createdAt"),
        "status": (message.get("deliveryStatus") or "").lower() or None,
    }
