"""Website chat adapter (plan 34 / A7b, D-A7B-1) - ``channel_type = "WEBCHAT"``.

There is no external provider on the far side (D-A7B-29): the "provider" is
our own public visitor API (``routers/webchat_public.py``, slice S2). This
keeps the adapter a thin, honest skeleton in slice S1 - the registry row
(``adapters/__init__.py``) is what makes ``WEBCHAT`` a real channel type for
every generic caller (``get_adapter``, ``messaging_policy``,
``channel_addressing``). ``parse_inbound`` is implemented for real in slice
S2 (``services/webchat_visitor_service.py`` is its only caller); ``send``
stays stubbed here for slice S3 - nothing calls it before that slice lands,
so a stub that fails loudly is safer than a stub that pretends to succeed.

``exchange_code`` / ``fetch_phone_details`` / ``fetch_media`` /
``list_templates`` are permanently unreachable for this channel type (no
OAuth, no WABA phone identity, visitor uploads are disabled in v1 - D-A7B-20,
and ``messaging_policy.CAPABILITIES["WEBCHAT"].template`` is False) and raise
``NotImplementedError`` rather than silently no-op.

Slice S3 (AC-WEB-36..38) implements ``send``/``upload_media`` for real: no
network call of any kind (D-A7B-29 - the "provider" IS our own backend), a
locally-minted external id, and an immediate return so ``send_runner`` stamps
the row ``SENT`` in the SAME run. Every keyword ``send_runner`` can pass for
any message kind this channel type's own capability row
(``messaging_policy.CAPABILITIES["WEBCHAT"]``) actually allows through
``assert_kind_supported`` (``text``, ``media``, and ``interactive`` for a
quick-reply-buttons send - ``template``/``location``/``contacts``/
``reaction`` are rejected upstream before they would ever reach here) is
accepted; anything else lands in ``**_ignored`` (the `MessengerAdapter`
precedent) so this stays correct even if a caller passed something the
policy layer should already have refused.
"""
import uuid
from typing import Any, Dict, List, Optional

from .base import ConnectionStatus


class WebChatAdapter:
    channel_type = "WEBCHAT"

    def __init__(self, client: Optional[Any] = None, recorder: Optional[Any] = None):
        # Uniform adapter constructor signature (`get_adapter`) - web chat
        # makes no HTTP call of its own, so both are accepted and unused.
        self._client = client
        self._recorder = recorder

    def exchange_code(self, code: str) -> Dict[str, Any]:
        raise NotImplementedError("Web chat has no OAuth code exchange.")

    def subscribe_webhook(
        self, credentials: Dict[str, Any], waba_id: str, callback_url: str
    ) -> None:
        return None  # no provider webhook to subscribe to.

    def fetch_phone_details(
        self, credentials: Dict[str, Any], phone_number_id: str
    ) -> Dict[str, Any]:
        return {}  # No phone / WABA identity concept for web chat.

    def test_connection(
        self, credentials: Dict[str, Any], phone_number_id: str
    ) -> ConnectionStatus:
        """Trivially ok (AC-WEB-12's registry-conformance requirement) - the
        "provider" is this very backend, so there is nothing external to
        ping. ``channel_service.test_connection`` still resolves a routing id
        the same way it does for every channel type (falls through to
        ``external_account_id``, which is always ``None`` for a WEBCHAT
        channel); this adapter ignores it either way."""
        return ConnectionStatus(
            ok=True, message="Web chat is ready - there is no external connection to test."
        )

    # ── Message processing - S2 (inbound) / S3 (outbound) ───────────────────
    def upload_media(
        self, credentials: Dict[str, Any], phone_number_id: str, content: bytes, mime: str
    ) -> str:
        """No external upload (D-A7B-29) - the row's OWN `media_key` (already
        written by `MessageService.send_media` before `send_runner` ever
        runs) is what `webchat_projection` turns into a signed URL for the
        visitor; this id is never read back by anything. A synthetic value
        keeps `send_runner`'s generic upload-then-send flow uniform across
        every channel type without a `channel_type` branch there."""
        return f"webchat-media-{uuid.uuid4().hex[:12]}"

    def send(
        self,
        credentials: Dict[str, Any],
        phone_number_id: str,
        to: str,
        *,
        text: Optional[str] = None,
        template: Optional[Dict[str, Any]] = None,
        media: Optional[Dict[str, Any]] = None,
        interactive: Optional[Dict[str, Any]] = None,
        structured: Optional[Dict[str, Any]] = None,
        messaging_type: Optional[str] = None,
        tag: Optional[str] = None,
        context_message_id: Optional[str] = None,
        **_ignored: Any,
    ) -> Dict[str, Any]:
        """AC-WEB-36 - no network call of any kind: `to` (the visitor's
        `external_user_id`, `channel_addressing.recipient_ref`) is not
        addressed anywhere, there is no provider to reject the send, so this
        always succeeds and returns immediately. `send_runner` stamps the row
        SENT in the SAME run this returns from - there is no async provider
        round trip to await, unlike every other channel type."""
        return {"external_message_id": f"web:out:{uuid.uuid4().hex}"}

    def parse_inbound(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The visitor-POST -> canonical event-dict translation
        (`services/webchat_visitor_service.py` builds `payload` and calls
        `InboundService.process_payload` directly - there is no webhook for
        this channel type, so `payload` is already the house canonical shape
        the caller assembled, not a Meta envelope). ALWAYS exactly one
        `"message"` event: web chat carries no delivery-receipt or reaction
        concept from the visitor side (D-A7B-20 - no visitor uploads either,
        so `message_type` is always `"TEXT"`). Deliberately NEVER sets
        `profile_name` - D-A7B-8 forbids any stitch signal reaching
        `InboundService._resolve_contact`, and a `WEBCHAT` channel already
        skips the phone stitch there (it is not `WHATSAPP`); omitting
        `profile_name` closes the one remaining lever (a Messenger/Instagram-
        style Graph name lookup) that resolver has for a non-WhatsApp type."""
        return [
            {
                "kind": "message",
                "from": payload["from"],
                "external_message_id": payload["external_message_id"],
                "body": payload.get("body"),
                "message_type": "TEXT",
            }
        ]

    def fetch_media(self, credentials: Dict[str, Any], media_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Web chat visitor uploads are disabled in v1 (D-A7B-20).")

    def list_templates(self, credentials: Dict[str, Any], waba_id: str) -> list:
        raise NotImplementedError("Web chat has no message templates.")
