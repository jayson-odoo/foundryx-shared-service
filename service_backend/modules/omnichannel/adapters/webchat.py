"""Website chat adapter (plan 34 / A7b, D-A7B-1) - ``channel_type = "WEBCHAT"``.

There is no external provider on the far side (D-A7B-29): the "provider" is
our own public visitor API (``routers/webchat_public.py``, slice S2). This
keeps the adapter a thin, honest skeleton in slice S1 - the registry row
(``adapters/__init__.py``) is what makes ``WEBCHAT`` a real channel type for
every generic caller (``get_adapter``, ``messaging_policy``,
``channel_addressing``); the two methods a live web chat conversation
actually needs (``send``, ``parse_inbound``) are stubbed here and implemented
for real in slices S3 and S2 respectively - nothing calls either of them
before those slices land, so a stub that fails loudly is safer than a stub
that pretends to succeed.

``exchange_code`` / ``fetch_phone_details`` / ``fetch_media`` /
``list_templates`` are permanently unreachable for this channel type (no
OAuth, no WABA phone identity, visitor uploads are disabled in v1 - D-A7B-20,
and ``messaging_policy.CAPABILITIES["WEBCHAT"].template`` is False) and raise
``NotImplementedError`` rather than silently no-op.
"""
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
    def send(
        self,
        credentials: Dict[str, Any],
        phone_number_id: str,
        to: str,
        *,
        text: Optional[str] = None,
        template: Optional[Dict[str, Any]] = None,
        structured: Optional[Dict[str, Any]] = None,
        messaging_type: Optional[str] = None,
        tag: Optional[str] = None,
        context_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Slice S3 (`send_runner` wiring, AC-WEB-36..38) implements this for
        real: no network I/O, a locally-minted external id, immediate SENT.
        Stubbed here so nothing calls it before S3 lands."""
        raise NotImplementedError("WebChatAdapter.send lands in plan 34 slice S3.")

    def parse_inbound(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Slice S2 (`services/webchat_visitor_service.py`) implements the
        visitor-POST -> canonical event-dict translation and calls this
        directly - there is no webhook payload for this channel type, so
        nothing reaches this method before S2 lands."""
        raise NotImplementedError("WebChatAdapter.parse_inbound lands in plan 34 slice S2.")

    def fetch_media(self, credentials: Dict[str, Any], media_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Web chat visitor uploads are disabled in v1 (D-A7B-20).")

    def list_templates(self, credentials: Dict[str, Any], waba_id: str) -> list:
        raise NotImplementedError("Web chat has no message templates.")
