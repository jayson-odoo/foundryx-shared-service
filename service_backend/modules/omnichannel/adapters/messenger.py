"""Facebook Messenger adapter (Meta Graph API) - plan 32 / A7a.

Rides the SAME Meta app as WhatsApp (D-A7-1: no `connections` row, no second
credential model) via `MetaGraphMixin` (telemetry, dev-safe gate, HTTP client,
base URL - `meta_graph.py`). Slice S1 ships inbound parsing only
(`parse_inbound` - text, attachments-as-pending-media-refs, quick replies,
postbacks, echo drop, receipts parsed but not yet applied); `send`/
`test_connection`/`exchange_code`/`subscribe_webhook` are honest dev-safe
stubs here, completed by plan 32 S2 (window policy + addressing + send) and S3
(the connect flow) on top of this same file - not a second adapter.

Sources (cited per CLAUDE.md, section 10 of the plan):
- Messenger Platform webhooks (object `page`, `entry[].messaging[]`,
  `X-Hub-Signature-256`):
  https://developers.facebook.com/docs/messenger-platform/webhooks
- Messenger Send API (`POST /{PAGE_ID}/messages`, `messaging_type`, `tag`):
  https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages
- Messenger/Instagram messaging policy (24h standard window, the Human Agent
  7-day extension):
  https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy
"""
import logging
from typing import Any, Dict, Optional

import httpx

from .base import ConnectionStatus
from .meta_graph import MetaGraphMixin

logger = logging.getLogger(__name__)

# Messenger `attachment.type` -> the house canonical message-type vocabulary
# (plan §5.6). `file` (document) is Messenger-only - Instagram never carries
# it (capability table, §5.5).
_ATTACHMENT_TYPES = {
    "image": "IMAGE",
    "video": "VIDEO",
    "audio": "AUDIO",
    "file": "DOCUMENT",
}


class MessengerAdapter(MetaGraphMixin):
    channel_type = "FACEBOOK"

    # ── Onboarding (dev-safe stubs; plan 32 S3 completes the real flow) ─────
    def exchange_code(self, code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        if not self._configured:
            return {"access_token": f"dev-token-{code}", "dev": True}
        raise NotImplementedError(
            "Messenger code exchange is implemented by meta_connect_service (plan 32 S3)."
        )

    def subscribe_webhook(self, credentials: Dict[str, Any], page_id: str, callback_url: str) -> None:
        # Best-effort `subscribed_apps` subscription lands with the connect
        # flow (plan 32 S3, D-A7-15) - a no-op here keeps the Protocol whole.
        return None

    def fetch_phone_details(self, credentials: Dict[str, Any], phone_number_id: str) -> Dict[str, Any]:
        return {}  # No phone concept on Messenger.

    def test_connection(self, credentials: Dict[str, Any], routing_id: str) -> ConnectionStatus:
        if not self._configured or credentials.get("dev"):
            return ConnectionStatus(ok=True, message="Connected (dev mode - no live Meta call).")
        return ConnectionStatus(
            ok=False, message="Live Messenger connection check lands in plan 32 S3."
        )

    # ── Outbound (dev-safe stub; plan 32 S2 completes window/addressing/send) ─
    def send(
        self,
        credentials: Dict[str, Any],
        recipient_id: str,
        to: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if not self._configured or credentials.get("dev"):
            import uuid

            return {"external_message_id": f"m.dev-{uuid.uuid4().hex[:12]}", "dev": True}
        raise NotImplementedError(
            "Messenger send is implemented by messaging_policy + channel_addressing (plan 32 S2)."
        )

    def fetch_media(self, credentials: Dict[str, Any], media_id: str) -> Optional[Dict[str, Any]]:
        # Messenger delivers a short-lived CDN URL inline on the attachment,
        # never a media id to resolve - `fetch_media_url` (D-A7-12, the
        # SSRF-guarded URL fetch) lands in plan 32 S5.
        return None

    def list_templates(self, credentials: Dict[str, Any], waba_id: str) -> list:
        return []  # No message-template concept on Messenger/Instagram (D-A7-17).

    def fetch_profile_name(
        self, credentials: Dict[str, Any], external_user_id: str
    ) -> Optional[str]:
        """Best-effort ``GET /{PSID}?fields=name`` (AC-CHN-20 "when
        available") - Messenger's webhook payload never carries the sender's
        name inline, unlike WhatsApp's ``contacts[].profile.name``. Dev/
        unconfigured -> ``None`` (the caller falls back to no name, never a
        crash)."""
        if not self._configured or credentials.get("dev") or not external_user_id:
            return None
        client = self._http()
        try:
            resp = client.get(
                f"{self._base}/{external_user_id}",
                params={"fields": "name", "access_token": credentials.get("access_token", "")},
            )
            if resp.status_code == 200:
                return resp.json().get("name")
            return None
        except httpx.HTTPError:
            return None
        finally:
            if self._client is None:
                client.close()

    # ── Inbound (plan 32 S1) ─────────────────────────────────────────────────
    def parse_inbound(self, payload: Dict[str, Any]) -> list:
        """Normalize a Messenger webhook payload (`entry[].messaging[]`, NOT
        `entry[].changes[]`) into the existing canonical event dicts
        (AC-CHN-18). Never raises - webhook payloads are attacker-controllable
        (a malformed shape yields zero events, AC-CHN-18)."""
        events: list = []
        try:
            for entry in payload.get("entry") or []:
                page_id = entry.get("id")
                for item in entry.get("messaging") or []:
                    event = self._parse_one(item, page_id)
                    if event is not None:
                        events.append(event)
        except (AttributeError, TypeError):
            return []
        return events

    def _parse_one(self, item: Dict[str, Any], page_id: Optional[str]) -> Optional[Dict[str, Any]]:
        sender = (item.get("sender") or {}).get("id")
        if not sender:
            return None
        timestamp = item.get("timestamp")

        message = item.get("message")
        if message is not None:
            # D-A7-23: our own outbound must never come back as a second
            # inbound bubble - dropped in the parser, not downstream.
            if message.get("is_echo"):
                return None
            mid = message.get("mid")
            reply_to = (message.get("reply_to") or {}).get("mid")
            quick_reply = message.get("quick_reply")
            if quick_reply is not None:
                title = message.get("text")
                return {
                    "kind": "message",
                    "external_message_id": mid,
                    "from": sender,
                    "profile_name": None,
                    "message_type": "INTERACTIVE_REPLY",
                    "original_type": "quick_reply",
                    "body": title,
                    "payload": {"kind": "quick_reply", "id": quick_reply.get("payload"), "title": title},
                    "reply_to_external_id": reply_to,
                    "timestamp": timestamp,
                }
            attachments = message.get("attachments") or []
            if attachments:
                att = attachments[0]
                att_type = (att.get("type") or "").lower()
                url = (att.get("payload") or {}).get("url")
                resolved = _ATTACHMENT_TYPES.get(att_type, "UNSUPPORTED")
                return {
                    "kind": "message",
                    "external_message_id": mid,
                    "from": sender,
                    "profile_name": None,
                    "message_type": resolved,
                    "original_type": att_type or "attachment",
                    "body": message.get("text"),
                    "media_url": url,
                    # Not fetched yet (D-A7-12 - the SSRF-guarded fetch lands
                    # in plan 32 S5); persisted as a pending ref so a later
                    # backfill can complete it without re-parsing the payload.
                    "payload": {"pendingMediaUrl": url} if url else None,
                    "reply_to_external_id": reply_to,
                    "timestamp": timestamp,
                }
            if message.get("text") is not None:
                return {
                    "kind": "message",
                    "external_message_id": mid,
                    "from": sender,
                    "profile_name": None,
                    "message_type": "TEXT",
                    "original_type": "text",
                    "body": message.get("text"),
                    "reply_to_external_id": reply_to,
                    "timestamp": timestamp,
                }
            # A message shape with neither text, attachments nor quick_reply -
            # kept as a placeholder, never dropped (AC-CHN-18).
            return {
                "kind": "message",
                "external_message_id": mid,
                "from": sender,
                "profile_name": None,
                "message_type": "UNSUPPORTED",
                "original_type": "message",
                "body": None,
                "reply_to_external_id": reply_to,
                "timestamp": timestamp,
            }

        postback = item.get("postback")
        if postback is not None:
            title = postback.get("title")
            return {
                "kind": "message",
                # Messenger postbacks carry no `mid` - synthesize a stable,
                # per-event id so idempotency/persistence still have one.
                "external_message_id": f"psb.{page_id or ''}.{sender}.{timestamp}",
                "from": sender,
                "profile_name": None,
                "message_type": "INTERACTIVE_REPLY",
                "original_type": "postback",
                "body": title,
                "payload": {"kind": "postback", "id": postback.get("payload"), "title": title},
                "timestamp": timestamp,
            }

        delivery = item.get("delivery")
        if delivery is not None:
            # Receipts are parsed now, applied in plan 32 S5 (D-A7-22, the
            # watermark/mids mapping) - no `external_message_id` here means
            # the existing `_handle_status` guard already no-ops these.
            return {
                "kind": "status",
                "status": "DELIVERED",
                "mids": delivery.get("mids") or [],
                "watermark": delivery.get("watermark"),
                "from": sender,
            }

        read = item.get("read")
        if read is not None:
            return {
                "kind": "status",
                "status": "READ",
                "watermark": read.get("watermark"),
                "from": sender,
            }

        reaction = item.get("reaction")
        if reaction is not None:
            action = reaction.get("action")
            return {
                "kind": "reaction",
                "external_message_id": None,
                "from": sender,
                "target_external_id": reaction.get("mid"),
                "emoji": (reaction.get("emoji") or "") if action != "unreact" else "",
                "timestamp": timestamp,
            }

        return None
