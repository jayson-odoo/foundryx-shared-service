"""Billplz payment provider (sprint-4/07 Cluster F slice 3, AC-07-26/29/32/36).

Malaysian FPX/card gateway. Implements ``create_checkout`` (a Billplz Bill),
``verify_webhook`` (X-Signature HMAC-SHA256 over the sorted source string +
``paid_at`` timestamp tolerance), ``refund`` and a ``test`` (collections ping).

THE CENTS BOUNDARY (AC-07-51): Billplz transacts in **sen** (integer minor
units, RM 1 = 100 sen). This adapter is the ONLY place Decimal (major units) ↔
sen conversion happens (``_to_sen`` / ``_from_sen``).
"""
import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.integrations.base import (
    CheckoutResult,
    PaymentError,
    RefundResult,
    TestResult,
    WebhookEvent,
)

_API_BASE = "https://www.billplz.com/api/v3"
_SANDBOX_BASE = "https://www.billplz-sandbox.com/api/v3"
_SEN = Decimal("0.0001")


def _to_sen(amount: Decimal) -> int:
    """Decimal RM → integer sen (the cents boundary)."""
    return int((amount * Decimal(100)).quantize(Decimal("1")))


def _from_sen(sen: int) -> Decimal:
    """Integer sen → exact Decimal RM."""
    return (Decimal(sen) / Decimal(100)).quantize(_SEN)


def _base(config: Dict[str, Any]) -> str:
    return _SANDBOX_BASE if config.get("sandbox") in (True, "true", "True", "1") else _API_BASE


def _auth_header(api_key: str) -> str:
    return "Basic " + base64.b64encode(f"{api_key}:".encode()).decode()


def _request(method: str, base: str, api_key: str, path: str, form: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = urllib.parse.urlencode(form, doseq=True).encode() if form is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method)
    req.add_header("Authorization", _auth_header(api_key))
    req.add_header("User-Agent", "FoundryXEMS/1.0 (+payments)")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:  # noqa: BLE001
        detail = e.read().decode(errors="replace")
        raise PaymentError(f"Billplz API error ({e.code}): {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise PaymentError(f"Could not reach Billplz ({e}).") from e


class BillplzProvider:
    provider = "billplz"
    type = "payment"
    title = "Billplz"
    description = (
        "Accept FPX online-banking + card payments via Billplz. Buyers are "
        "redirected to a Billplz bill page; we reconcile via the X-Signature webhook."
    )
    icon = "landmark"
    test_label = "Verify Billplz keys"
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {"key": "collectionId", "label": "Collection ID", "type": "text",
             "required": True, "placeholder": "abcd1234"},
            {"key": "apiKey", "label": "Secret API key", "type": "password",
             "required": True, "secret": True},
            {"key": "xSignatureKey", "label": "X-Signature key", "type": "password",
             "required": True, "secret": True},
            {"key": "sandbox", "label": "Sandbox mode", "type": "select", "required": False,
             "defaultValue": "false",
             "options": [
                 {"value": "false", "label": "Live"},
                 {"value": "true", "label": "Sandbox"},
             ]},
        ]

    def test(
        self, config: Dict[str, Any], credentials: Dict[str, Any], target: Optional[str] = None
    ) -> TestResult:
        api_key = str(credentials.get("apiKey", ""))
        collection_id = str(config.get("collectionId", ""))
        if not api_key or not collection_id:
            return TestResult(ok=False, message="A Billplz API key and collection ID are required.")
        try:
            _request("GET", _base(config), api_key, f"/collections/{collection_id}")
            return TestResult(ok=True, message="Billplz keys verified.")
        except PaymentError as e:
            return TestResult(ok=False, message=str(e))

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
        api_key = str(credentials.get("apiKey", ""))
        collection_id = str(config.get("collectionId", ""))
        if not api_key or not collection_id:
            raise PaymentError("A Billplz API key and collection ID are required.")
        form = {
            "collection_id": collection_id,
            "description": (description or "Payment")[:200],
            "amount": _to_sen(amount),
            "callback_url": success_url,  # the webhook target (our route)
            "redirect_url": success_url,  # where the buyer lands after paying
            "reference_1_label": "ref",
            "reference_1": external_ref,
            "email": str(config.get("notifyEmail") or "noreply@example.com"),
            "name": "Customer",
        }
        bill = _request("POST", _base(config), api_key, "/bills", form)
        url = bill.get("url")
        if not url:
            raise PaymentError("Billplz did not return a bill URL.")
        return CheckoutResult(redirect_url=url, external_payment_id=bill.get("id", ""))

    def verify_webhook(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        body: bytes,
        headers: Dict[str, str],
        tolerance_seconds: int,
    ) -> WebhookEvent:
        x_sig_key = str(credentials.get("xSignatureKey", ""))
        if not x_sig_key:
            raise PaymentError("No X-Signature key configured.")
        # Billplz POSTs form-encoded params (billplz[id], billplz[paid], …) plus
        # an x_signature computed over the sorted "key value" source string.
        params = self._parse_form(body)
        provided = params.pop("x_signature", "") or headers.get("x-signature", "")
        self._verify_signature(params, provided, x_sig_key)
        self._check_tolerance(params, tolerance_seconds)
        return self._parse_event(params)

    @staticmethod
    def _parse_form(body: bytes) -> Dict[str, str]:
        parsed = urllib.parse.parse_qs(body.decode(errors="replace"))
        out: Dict[str, str] = {}
        for k, v in parsed.items():
            # billplz[id] → id ; keep the flattened key.
            key = k
            if k.startswith("billplz[") and k.endswith("]"):
                key = k[len("billplz["):-1]
            out[key] = v[0] if v else ""
        return out

    def _verify_signature(self, params: Dict[str, str], provided: str, key: str) -> None:
        if not provided:
            raise PaymentError("Missing Billplz X-Signature.")
        # Source string = sorted "key value" pairs joined by '|'.
        source = "|".join(f"{k}{params[k]}" for k in sorted(params))
        expected = hmac.new(key.encode(), source.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, provided):
            raise PaymentError("Invalid Billplz X-Signature.")

    def _check_tolerance(self, params: Dict[str, str], tolerance: int) -> None:
        paid_at = params.get("paid_at")
        if not paid_at:
            return  # unpaid notification — no timestamp to check
        try:
            ts = datetime.fromisoformat(paid_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            return  # unparseable timestamp — don't block on a format we don't know
        age = abs((datetime.now(timezone.utc) - ts).total_seconds())
        if age > tolerance:
            raise PaymentError("Webhook timestamp outside tolerance (stale event).")

    def _parse_event(self, params: Dict[str, str]) -> WebhookEvent:
        paid = str(params.get("paid", "")).lower() == "true"
        amount = _from_sen(int(params["amount"])) if params.get("amount", "").isdigit() else None
        return WebhookEvent(
            event_id=str(params.get("id", "")),
            event_type="payment.succeeded" if paid else "payment.failed",
            external_payment_id=str(params.get("id", "")),
            external_ref=params.get("reference_1") or params.get("ref"),
            amount=amount,
            gateway_fee=None,  # Billplz fees are settled separately, not on the webhook
            raw=params,
        )

    def refund(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        external_payment_id: str,
        amount: Decimal,
        currency: str,
    ) -> RefundResult:
        # Billplz v3 has no public refund API — refunds are operator-initiated in
        # the Billplz dashboard. We record the intent; the actual money movement
        # happens out-of-band (the refund record + credit note still apply).
        return RefundResult(external_refund_id=f"manual:{external_payment_id}")
