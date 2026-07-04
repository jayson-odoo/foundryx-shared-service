"""Stripe payment provider (sprint-4/07 Cluster F slice 3, AC-07-26/29/32/36).

Implements ``create_checkout`` (Checkout Session), ``verify_webhook`` (signing
secret + timestamp tolerance), ``refund`` and a ``test`` (balance ping) — all
over the Stripe REST API via the dependency-free HTTP helper (no SDK; the
network calls are mocked at this boundary in tests).

THE CENTS BOUNDARY (AC-07-51): Stripe transacts in the smallest currency unit
(integer cents). This adapter is the ONLY place ``Decimal`` (major units) ↔
integer minor-units conversion happens — ``_to_minor`` / ``_from_minor``.
"""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.integrations.base import (
    CheckoutResult,
    PaymentError,
    RefundResult,
    TestResult,
    WebhookEvent,
)

_API_BASE = "https://api.stripe.com/v1"
# Zero-decimal currencies (Stripe transacts these in whole units, no cents).
_ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "BIF", "DJF", "GNF", "PYG", "RWF",
                 "UGX", "VUV", "XAF", "XOF", "XPF", "KMF", "MGA"}
_CENTS = Decimal("0.0001")


def _minor_factor(currency: str) -> Decimal:
    return Decimal(1) if currency.upper() in _ZERO_DECIMAL else Decimal(100)


def _to_minor(amount: Decimal, currency: str) -> int:
    """Decimal major-units → integer minor-units (the cents boundary)."""
    return int((amount * _minor_factor(currency)).quantize(Decimal("1")))


def _from_minor(minor: int, currency: str) -> Decimal:
    """Integer minor-units → exact Decimal major-units."""
    return (Decimal(minor) / _minor_factor(currency)).quantize(_CENTS)


def _post(secret_key: str, path: str, form: Dict[str, Any]) -> Dict[str, Any]:
    data = urllib.parse.urlencode(form, doseq=True).encode()
    req = urllib.request.Request(f"{_API_BASE}{path}", data=data, method="POST")
    req.add_header("Authorization", f"Bearer {secret_key}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "DreamzEMS/1.0 (+payments)")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:  # noqa: BLE001
        detail = e.read().decode(errors="replace")
        raise PaymentError(f"Stripe API error ({e.code}): {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise PaymentError(f"Could not reach Stripe ({e}).") from e


def _get(secret_key: str, path: str) -> Dict[str, Any]:
    req = urllib.request.Request(f"{_API_BASE}{path}", method="GET")
    req.add_header("Authorization", f"Bearer {secret_key}")
    req.add_header("User-Agent", "DreamzEMS/1.0 (+payments)")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:  # noqa: BLE001
        detail = e.read().decode(errors="replace")
        raise PaymentError(f"Stripe API error ({e.code}): {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise PaymentError(f"Could not reach Stripe ({e}).") from e


class StripeProvider:
    provider = "stripe"
    type = "payment"
    title = "Stripe"
    description = (
        "Accept card + wallet payments through Stripe Checkout. Buyers are "
        "redirected to Stripe's hosted page; we reconcile via webhooks."
    )
    icon = "credit-card"
    test_label = "Verify Stripe keys"
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {"key": "publishableKey", "label": "Publishable key", "type": "text",
             "required": False, "placeholder": "pk_live_…"},
            {"key": "secretKey", "label": "Secret key", "type": "password",
             "required": True, "secret": True, "placeholder": "sk_live_…"},
            {"key": "webhookSigningSecret", "label": "Webhook signing secret",
             "type": "password", "required": True, "secret": True,
             "placeholder": "whsec_…"},
        ]

    # ── balance ping (AC-07-26) ─────────────────────────────────────────────
    def test(
        self, config: Dict[str, Any], credentials: Dict[str, Any], target: Optional[str] = None
    ) -> TestResult:
        secret = str(credentials.get("secretKey", ""))
        if not secret:
            return TestResult(ok=False, message="A Stripe secret key is required.")
        try:
            _get(secret, "/balance")
            return TestResult(ok=True, message="Stripe keys verified.")
        except PaymentError as e:
            return TestResult(ok=False, message=str(e))

    # ── checkout (AC-07-27) ─────────────────────────────────────────────────
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
        secret = str(credentials.get("secretKey", ""))
        if not secret:
            raise PaymentError("A Stripe secret key is required.")
        form = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": external_ref,
            "payment_intent_data[metadata][external_ref]": external_ref,
            "metadata[external_ref]": external_ref,
            "line_items[0][quantity]": 1,
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": _to_minor(amount, currency),
            "line_items[0][price_data][product_data][name]": description or "Payment",
        }
        session = _post(secret, "/checkout/sessions", form)
        url = session.get("url")
        if not url:
            raise PaymentError("Stripe did not return a checkout URL.")
        return CheckoutResult(
            redirect_url=url,
            external_payment_id=session.get("payment_intent") or session.get("id") or "",
        )

    # ── webhook verify + parse (AC-07-29/30/32/36) ──────────────────────────
    def verify_webhook(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        body: bytes,
        headers: Dict[str, str],
        tolerance_seconds: int,
    ) -> WebhookEvent:
        signing_secret = str(credentials.get("webhookSigningSecret", ""))
        if not signing_secret:
            raise PaymentError("No webhook signing secret configured.")
        sig_header = headers.get("stripe-signature") or headers.get("Stripe-Signature") or ""
        self._verify_signature(body, sig_header, signing_secret, tolerance_seconds)
        try:
            event = json.loads(body or b"{}")
        except ValueError as e:
            raise PaymentError("Malformed webhook body.") from e
        return self._parse_event(event)

    def _verify_signature(self, body: bytes, header: str, secret: str, tolerance: int) -> None:
        # Stripe header: "t=timestamp,v1=signature[,v1=…]".
        parts = dict(
            p.split("=", 1) for p in header.split(",") if "=" in p
        )
        ts = parts.get("t")
        sig = parts.get("v1")
        if not ts or not sig:
            raise PaymentError("Missing Stripe signature.")
        # Anti-replay: reject stale events (AC-07-29).
        try:
            if abs(time.time() - int(ts)) > tolerance:
                raise PaymentError("Webhook timestamp outside tolerance (stale event).")
        except ValueError as e:
            raise PaymentError("Invalid Stripe signature timestamp.") from e
        signed = f"{ts}.".encode() + body
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise PaymentError("Invalid Stripe signature.")

    def _parse_event(self, event: Dict[str, Any]) -> WebhookEvent:
        etype = event.get("type", "")
        obj = (event.get("data") or {}).get("object") or {}
        currency = (obj.get("currency") or "usd").upper()
        # Normalise the Stripe event vocabulary to our internal one.
        if etype in ("checkout.session.completed", "payment_intent.succeeded", "charge.succeeded"):
            normalised = "payment.succeeded"
        elif etype in ("payment_intent.payment_failed", "charge.failed"):
            normalised = "payment.failed"
        elif etype in ("charge.refunded", "refund.created", "charge.refund.updated"):
            normalised = "refund"
        elif etype.startswith("charge.dispute."):
            normalised = "dispute"
        else:
            normalised = etype  # passed through; the service ignores unknowns
        external_ref = (
            obj.get("client_reference_id")
            or (obj.get("metadata") or {}).get("external_ref")
        )
        amount_minor = (
            obj.get("amount_total")
            or obj.get("amount_received")
            or obj.get("amount")
            or obj.get("amount_refunded")
        )
        amount = _from_minor(int(amount_minor), currency) if amount_minor is not None else None
        # Processing fee comes from the balance transaction (expanded) when present.
        fee = None
        bt = obj.get("balance_transaction")
        if isinstance(bt, dict) and bt.get("fee") is not None:
            fee = _from_minor(int(bt["fee"]), currency)
        return WebhookEvent(
            event_id=str(event.get("id", "")),
            event_type=normalised,
            external_payment_id=obj.get("payment_intent") or obj.get("id"),
            external_ref=external_ref,
            amount=amount,
            gateway_fee=fee,
            raw=event,
        )

    # ── refund (AC-07-37) ───────────────────────────────────────────────────
    def refund(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        external_payment_id: str,
        amount: Decimal,
        currency: str,
    ) -> RefundResult:
        secret = str(credentials.get("secretKey", ""))
        if not secret:
            raise PaymentError("A Stripe secret key is required.")
        form = {
            "payment_intent": external_payment_id,
            "amount": _to_minor(amount, currency),
        }
        res = _post(secret, "/refunds", form)
        return RefundResult(external_refund_id=res.get("id", ""))
