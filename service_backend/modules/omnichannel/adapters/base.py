"""Channel adapter contract — one per channel type (WhatsApp now; Messenger/IG/
Douyin/XHS later). Onboarding + channel services depend on this interface, never
on a concrete provider, so new channels are additive (plan 04 §5.3).
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


@dataclass
class ConnectionStatus:
    ok: bool
    message: str


class CodeExchangeError(Exception):
    """Provider rejected the Embedded Signup code exchange (carries the provider's
    human-readable reason so the wizard can show it instead of a generic failure)."""


class SendError(Exception):
    """Provider rejected an outbound send (carries the provider's reason so the
    composer can surface it — e.g. re-engagement outside the 24h window).

    ``transient`` distinguishes a retryable transport/5xx failure (network blip,
    Meta 5xx → the send task retries with backoff) from a permanent rejection
    (bad number, 4xx, template issue → stamp FAILED, plan 12 review)."""

    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class ChannelAdapter(Protocol):
    channel_type: str

    def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange an Embedded Signup auth code for a permanent credentials bundle."""
        ...

    def subscribe_webhook(self, credentials: Dict[str, Any], waba_id: str, callback_url: str) -> None:
        """Subscribe our app to the WABA's webhooks (best-effort)."""
        ...

    def fetch_phone_details(self, credentials: Dict[str, Any], phone_number_id: str) -> Dict[str, Any]:
        """Resolve display_phone_number + verified_name for a phone number id."""
        ...

    def test_connection(self, credentials: Dict[str, Any], phone_number_id: str) -> ConnectionStatus:
        """Lightweight ping to verify the number is reachable."""
        ...

    # ── Message processing (plan 05) ─────────────────────────────────────────
    def send(
        self,
        credentials: Dict[str, Any],
        phone_number_id: str,
        to: str,
        *,
        text: Optional[str] = None,
        template: Optional[Dict[str, Any]] = None,
        context_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a text/template message; returns {"external_message_id": ...}."""
        ...

    def parse_inbound(self, payload: Dict[str, Any]) -> list:
        """Normalize a provider webhook payload into canonical event dicts."""
        ...

    def fetch_media(self, credentials: Dict[str, Any], media_id: str) -> Optional[Dict[str, Any]]:
        """Resolve a provider media id → {"content": bytes, "mime_type": str}."""
        ...

    def list_templates(self, credentials: Dict[str, Any], waba_id: str) -> list:
        """List the account's message templates (read-only mirror)."""
        ...
