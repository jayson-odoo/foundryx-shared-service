"""Facebook Messenger adapter (Meta Graph API) - plan 32 / A7a.

Rides the SAME Meta app as WhatsApp (D-A7-1: no `connections` row, no second
credential model) via `MetaGraphMixin` (telemetry, dev-safe gate, HTTP client,
base URL - `meta_graph.py`). Slice S1 shipped inbound parsing
(`parse_inbound`); slice S2 completes outbound `send` (text + quick replies,
`messaging_type`/`tag` from `messaging_policy.authorize`) and a dev-safe
`upload_media` placeholder (the real Graph attachment-upload call lands in
plan 32 S5, D-A7-11). `test_connection`/`exchange_code`/`subscribe_webhook`
stay honest dev-safe stubs, completed by plan 32 S3 (the connect flow) on this
same file - not a second adapter.

Sources (cited per CLAUDE.md, section 10 of the plan):
- Messenger Platform webhooks (object `page`, `entry[].messaging[]`,
  `X-Hub-Signature-256`):
  https://developers.facebook.com/docs/messenger-platform/webhooks
- Messenger Send API (`POST /{PAGE_ID}/messages`, `recipient.id`,
  `messaging_type`, `tag`, response `message_id`):
  https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages
- Messenger quick replies (`message.quick_replies[]`, `content_type`,
  max 13, 20-character title):
  https://developers.facebook.com/docs/messenger-platform/send-messages/quick-replies
- Messenger/Instagram messaging policy (24h standard window, the Human Agent
  7-day extension, human-only restriction):
  https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

from .base import ConnectionStatus, SendError
from .meta_graph import MetaGraphMixin, _meta_error_detail

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

    # ── Outbound (plan 32 S2 - window/addressing resolved by the caller;
    #             media-by-id upload completed in plan 32 S5, D-A7-11) ───────
    def upload_media(
        self, credentials: Dict[str, Any], phone_number_id: str, content: bytes, mime: str
    ) -> str:
        """Attachment upload-by-id (D-A7-11 - Meta's attachment upload
        endpoint, never a public URL). Dev-safe stub: a fake id so the
        generalized `send_runner` media branch runs end to end with no Meta
        app; the real `POST /me/message_attachments` call lands in plan 32
        S5."""
        if not self._configured or credentials.get("dev"):
            import uuid

            return f"media.dev-{uuid.uuid4().hex[:12]}"
        raise NotImplementedError(
            "Messenger attachment upload is implemented by plan 32 S5."
        )

    def send(
        self,
        credentials: Dict[str, Any],
        phone_number_id: str,
        to: str,
        *,
        text: Optional[str] = None,
        media: Optional[Dict[str, Any]] = None,
        structured: Optional[Dict[str, Any]] = None,
        messaging_type: Optional[str] = None,
        tag: Optional[str] = None,
        context_message_id: Optional[str] = None,
        **_ignored: Any,
    ) -> Dict[str, Any]:
        """``phone_number_id`` is actually the PAGE_ID / IG account id
        (`channel_addressing.sender_ref`); ``to`` is the PSID/IGSID
        (`channel_addressing.recipient_ref`) - named to match the uniform
        `ChannelAdapter.send` signature every adapter shares. ``structured``
        is the raw friendly interactive definition (only a ``buttons`` kind
        ever reaches this adapter - `messaging_policy.assert_kind_supported`
        refuses `list`/`cta_url`/`location_request` upstream); it maps onto
        Meta quick replies via `structured.build_quick_replies` (D-A7-13).
        ``messaging_type``/``tag`` are `messaging_policy.authorize`'s
        resolved Meta send parameters, used VERBATIM (never re-derived,
        D-A7-8). ``**_ignored`` absorbs any WhatsApp-only kwarg
        (`template`/`interactive`/`location`/`contacts`/`reaction`) a
        uniform caller might still pass - the capability gate upstream
        guarantees none of those kinds ever reach here for real."""
        return self._graph_call(
            "graph:send",
            lambda: self._send_impl(
                credentials, phone_number_id, to,
                text=text, media=media, structured=structured,
                messaging_type=messaging_type, tag=tag,
                context_message_id=context_message_id,
            ),
            extract_ref=lambda result: (result or {}).get("external_message_id"),
        )

    def _send_impl(
        self,
        credentials: Dict[str, Any],
        phone_number_id: str,
        to: str,
        *,
        text: Optional[str] = None,
        media: Optional[Dict[str, Any]] = None,
        structured: Optional[Dict[str, Any]] = None,
        messaging_type: Optional[str] = None,
        tag: Optional[str] = None,
        context_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._configured or credentials.get("dev"):
            import uuid

            return {"external_message_id": f"m.dev-{uuid.uuid4().hex[:12]}", "dev": True}

        from ..services.structured import build_quick_replies

        message: Dict[str, Any] = {}
        quick_replies = build_quick_replies(structured) if structured else None
        if quick_replies:
            message["text"] = (structured or {}).get("body") or text or ""
            message["quick_replies"] = quick_replies
        elif media is not None:
            kind = (media.get("kind") or "").lower()
            att_type = "file" if kind == "document" else kind
            message["attachment"] = {
                "type": att_type,
                "payload": {"attachment_id": media["id"], "is_reusable": True},
            }
        else:
            message["text"] = text or ""
        if context_message_id:
            message["reply_to"] = {"mid": context_message_id}

        body: Dict[str, Any] = {
            "recipient": {"id": to},
            "messaging_type": messaging_type or "RESPONSE",
            "message": message,
        }
        if tag:
            body["tag"] = tag

        client = self._http()
        try:
            resp = client.post(
                f"{self._base}/{phone_number_id}/messages",
                json=body,
                headers={"Authorization": f"Bearer {credentials.get('access_token', '')}"},
            )
            self._last_http_status = resp.status_code
            if resp.status_code != 200:
                raise SendError(_meta_error_detail(resp), transient=resp.status_code >= 500)
            data = resp.json()
            return {"external_message_id": data.get("message_id", "")}
        except httpx.HTTPError as exc:
            raise SendError(f"Could not reach Meta: {exc}", transient=True) from exc
        finally:
            if self._client is None:
                client.close()

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
