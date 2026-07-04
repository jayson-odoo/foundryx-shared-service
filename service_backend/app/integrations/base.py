"""Provider contract + registry (plan 09 §4).

A provider declares its identity, a config schema (drives the frontend wizard)
and the runtime operations: `test` (no target = connection check; with target =
the provider's targeted test, e.g. send a real email) and — for email-type
providers — `send` (used by the outbox dispatcher).
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class TestResult:
    ok: bool
    message: str


@dataclass
class CheckoutResult:
    """A hosted-checkout session (AC-07-27). ``redirect_url`` = where to send the
    buyer; ``external_payment_id`` = the gateway's id for the intent/bill, stored
    on the payment row for later reconciliation."""

    redirect_url: str
    external_payment_id: str


@dataclass
class WebhookEvent:
    """A verified, parsed inbound webhook (AC-07-29..32/36). The gateway adapter
    is the ONLY place ``amount``/``fee`` cross the integer-cents ↔ Decimal
    boundary — these are already exact ``Decimal`` (major units)."""

    event_id: str  # provider event id (idempotency key)
    event_type: str  # normalised: payment.succeeded | payment.failed | refund | dispute
    external_payment_id: Optional[str]  # gateway charge/bill id
    external_ref: Optional[str]  # OUR payment row id (passed at checkout)
    amount: Optional["Decimal"] = None  # noqa: F821 (Decimal — imported lazily)
    gateway_fee: Optional["Decimal"] = None  # noqa: F821
    raw: Optional[Dict[str, Any]] = None


@dataclass
class RefundResult:
    external_refund_id: str
    gateway_fee: Optional["Decimal"] = None  # noqa: F821


class IntegrationProvider(Protocol):
    """What an integration provider implements (core or App Store module)."""

    provider: str  # registry key, e.g. "smtp"
    type: str  # email | storage | llm | erp
    title: str
    description: str
    icon: Optional[str]  # frontend lucide key
    test_label: str  # CTA for the optional targeted test
    # None = connection check only; else {"label", "placeholder"}.
    test_target: Optional[Dict[str, str]]

    def fields(self) -> List[Dict[str, Any]]:
        """Config schema rows (key/label/type/required/secret/…) for the wizard."""
        ...

    def test(
        self, config: Dict[str, Any], credentials: Dict[str, Any], target: Optional[str] = None
    ) -> TestResult:
        """Verify the connection; optionally run the targeted test."""
        ...


class PaymentError(Exception):
    """A gateway API call failed (create_checkout / refund). The caller maps this
    to a clean HTTP error and leaves local state untouched (atomicity)."""


class PaymentProvider(IntegrationProvider, Protocol):
    """An ``IntegrationProvider`` of ``type == 'payment'`` (Stripe, Billplz).

    The adapter owns the integer-cents ↔ Decimal conversion at its boundary
    (AC-07-51) — every amount that crosses into the rest of the system is an
    exact ``Decimal`` in major units.
    """

    def create_checkout(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        amount: Decimal,
        currency: str,
        external_ref: str,
        description: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutResult:
        """Open a hosted-checkout session; return the buyer redirect + the
        gateway's payment id. ``external_ref`` is OUR Pending payment row id —
        the gateway echoes it back on the webhook so we can reconcile."""
        ...

    def verify_webhook(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        body: bytes,
        headers: Dict[str, str],
        tolerance_seconds: int,
    ) -> WebhookEvent:
        """Verify the signature + timestamp tolerance, then parse to a
        normalised ``WebhookEvent``. Raises ``PaymentError`` on an invalid
        signature or a stale event (anti-replay, AC-07-29)."""
        ...

    def refund(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        external_payment_id: str,
        amount: Decimal,
        currency: str,
    ) -> RefundResult:
        """Issue a gateway refund against a prior charge (AC-07-37)."""
        ...


_REGISTRY: Dict[str, IntegrationProvider] = {}


def register_provider(provider: IntegrationProvider) -> None:
    _REGISTRY[provider.provider] = provider


def get_provider(key: str) -> Optional[IntegrationProvider]:
    return _REGISTRY.get(key)


def all_providers() -> List[IntegrationProvider]:
    return list(_REGISTRY.values())
