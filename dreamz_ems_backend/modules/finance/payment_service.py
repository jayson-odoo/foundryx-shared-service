"""Finance payment-gateway service (sprint-4/07 Cluster F slice 3).

The BUSINESS reaction to the core gateway plumbing (plan §1): checkout (create a
Pending row + open the hosted session, AC-07-27) and ``apply_payment_event`` —
the capability the core webhook ingest calls to flip Pending→Succeeded under a
row lock + derive the invoice toward Paid (AC-07-30/31/32/36).

Money is exact Decimal throughout (AC-07-51); the gateway adapter owns the
cents boundary, so amounts arrive here already in major units.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.services.payment_gateway_service import RetryableWebhook
from modules.finance.models import (
    GATEWAY_PAYMENT_METHODS,
    PAYMENT_ENTITY,
    Invoice,
    Payment,
)
from modules.finance.services import _money, _status_id_by_key, _status_key_by_id

logger = logging.getLogger("dreamz.finance.payments")


class PaymentService:
    def __init__(self, db: Session):
        self.db = db

    # ── checkout (AC-07-25/27) ───────────────────────────────────────────────
    def start_checkout(self, tenant_id: str, invoice_id: str, actor) -> Dict[str, str]:
        """Create a Pending GATEWAY payment row for the invoice's outstanding
        balance, open a hosted-checkout session with the payment id as
        ``external_ref``, and return the buyer redirect URL."""
        from app.integrations import PaymentError, get_provider
        from app.secrets import decrypt_secret

        inv = (
            self.db.query(Invoice)
            .filter(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
            .with_for_update()
            .first()
        )
        if inv is None:
            raise HTTPException(404, "Invoice not found.")
        status_key = _status_key_by_id(self.db, inv.status_id)
        if status_key in ("draft", "cancelled", "void", "paid", "refunded"):
            raise HTTPException(409, "This invoice cannot be paid.")

        balance = _money(inv.total) - self._paid_total(invoice_id)
        if balance <= 0:
            raise HTTPException(409, "This invoice has no outstanding balance.")

        # Resolve the gateway connection: project override → tenant default
        # (AC-07-25). Resolution is tenant-scoped.
        conn = self._resolve_connection(tenant_id, inv.project_id)
        if conn is None:
            raise HTTPException(409, "No payment gateway is configured for this workspace.")
        provider = get_provider(conn.provider)
        if provider is None or getattr(provider, "type", None) != "payment":
            raise HTTPException(409, "The configured payment provider is unavailable.")

        # Create the Pending row FIRST (it owns the external_ref id, AC-07-27).
        pending_id = _status_id_by_key(self.db, PAYMENT_ENTITY, tenant_id, "pending")
        pay = Payment(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            amount=balance,
            method="GATEWAY",
            status_id=pending_id,
            gateway_connection_id=conn.id,
        )
        self.db.add(pay)
        self.db.flush()
        pay.external_ref = pay.id  # the gateway echoes this back on the webhook
        self.db.flush()

        try:
            credentials = decrypt_secret(conn.credentials_json) if conn.credentials_json else {}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, "Stored gateway credentials could not be read.") from e

        base = settings.frontend_url.rstrip("/")
        try:
            result = provider.create_checkout(
                conn.config_json or {}, credentials,
                amount=balance, currency=inv.currency,
                external_ref=pay.external_ref,
                description=f"Invoice {inv.invoice_number or inv.id[:8]}",
                success_url=f"{base}/finance/invoices?paid={invoice_id}",
                cancel_url=f"{base}/finance/invoices?cancelled={invoice_id}",
            )
        except PaymentError as e:
            # Atomicity (AC-07-50): the gateway call failed — roll back the
            # Pending row so we don't strand an orphan.
            self.db.rollback()
            raise HTTPException(502, f"Could not start checkout: {e}") from e

        pay.external_payment_id = result.external_payment_id
        self.db.commit()
        return {"redirectUrl": result.redirect_url, "paymentId": pay.id}

    def _resolve_connection(self, tenant_id: str, project_id: Optional[str]):
        from app.repositories.connection_repository import ConnectionRepository

        repo = ConnectionRepository(self.db)
        if project_id:
            cid = self._project_payment_connection_id(tenant_id, project_id)
            if cid:
                conn = repo.get(cid, tenant_id)
                if conn is not None:
                    return conn
        return repo.resolve_for_type(tenant_id, "payment")

    def _project_payment_connection_id(self, tenant_id: str, project_id: str) -> Optional[str]:
        """Cross-module read of the project's payment_connection_id via the
        capability (BL-030 — no cross-schema query)."""
        from app.module_platform import resolve_capability

        handler = resolve_capability(self.db, tenant_id, "project.payment_connection", 1)
        if handler is None:
            return None
        res = handler(self.db, tenant_id, {"id": project_id})
        return (res or {}).get("paymentConnectionId")

    # ── webhook reaction (AC-07-30/31/32/36) ─────────────────────────────────
    def apply_payment_event(self, tenant_id: str, payload: Dict) -> Dict:
        """Called by the core webhook ingest via ``finance.apply_payment_event@1``.

        Finds the Pending row by ``external_ref`` (our payment id), locks the
        owning invoice and flips the payment idempotently. Raises
        ``RetryableWebhook`` when the referenced payment isn't present yet
        (out-of-order, AC-07-34)."""
        event_type = payload.get("eventType")
        external_ref = payload.get("externalRef")
        if not external_ref:
            return {"applied": False, "reason": "no_external_ref"}

        pay = (
            self.db.query(Payment)
            .filter(Payment.id == external_ref, Payment.tenant_id == tenant_id)
            .first()
        )
        if pay is None:
            # The payment row referenced by the event doesn't exist yet — the
            # checkout commit may be in flight, or a refund event arrived before
            # its payment. Retry rather than hard-fail (AC-07-34).
            raise RetryableWebhook(f"payment {external_ref} not found yet")

        if event_type == "payment.succeeded":
            return self._apply_success(tenant_id, pay, payload)
        if event_type == "payment.failed":
            return self._apply_failure(tenant_id, pay)
        if event_type == "dispute":
            return self._apply_dispute(tenant_id, pay)
        if event_type == "refund":
            # Cluster F slice 4 (AC-07-37): a gateway refund webhook confirms any
            # Pending refund created on this payment. Idempotent (the API path
            # already confirmed it → no-op).
            from modules.finance.refund_service import RefundService

            return RefundService(self.db).apply_refund_event(tenant_id, payload)
        # unknown types are a logged no-op.
        return {"applied": False, "reason": f"unhandled:{event_type}"}

    def _apply_success(self, tenant_id: str, pay: Payment, payload: Dict) -> Dict:
        # Lock the invoice so concurrent confirms can't overpay (AC-07-12/31).
        inv = (
            self.db.query(Invoice)
            .filter(Invoice.id == pay.invoice_id, Invoice.tenant_id == tenant_id)
            .with_for_update()
            .first()
        )
        # Re-read the payment now that we hold the invoice lock.
        self.db.refresh(pay)
        pay_key = _status_key_by_id(self.db, pay.status_id)
        if pay_key in ("succeeded", "refunded", "disputed"):
            # Idempotent flip (AC-07-30): already credited → NEVER re-credit.
            return {"applied": False, "reason": "already_final", "paymentId": pay.id}

        amount = _money(payload.get("amount")) if payload.get("amount") is not None else _money(pay.amount)
        already = self._paid_total(pay.invoice_id)
        if inv is not None and already + amount > _money(inv.total):
            # Overpayment guard (AC-07-12) — reject; leave the payment Pending so
            # a reaper can expire it. Never credit beyond the total.
            logger.warning("gateway overpayment rejected for invoice %s", pay.invoice_id)
            return {"applied": False, "reason": "overpayment", "paymentId": pay.id}

        succeeded = _status_id_by_key(self.db, PAYMENT_ENTITY, tenant_id, "succeeded")
        pay.status_id = succeeded
        pay.amount = amount
        pay.paid_at = datetime.now(timezone.utc)
        if payload.get("externalPaymentId"):
            pay.external_payment_id = payload["externalPaymentId"]
        if payload.get("gatewayFee") is not None:
            pay.gateway_fee = _money(payload["gatewayFee"])  # AC-07-32
        self.db.commit()
        # Re-derive the invoice (Partially Paid / Paid) — failure-isolated bus.
        from app.workflow_engine.entity_events import notify_entity_event

        notify_entity_event(self.db, PAYMENT_ENTITY, "status_changed", pay, tenant_id=tenant_id)
        return {"applied": True, "paymentId": pay.id, "status": "succeeded"}

    def _apply_failure(self, tenant_id: str, pay: Payment) -> Dict:
        pay_key = _status_key_by_id(self.db, pay.status_id)
        if pay_key != "pending":
            return {"applied": False, "reason": "not_pending", "paymentId": pay.id}
        failed = _status_id_by_key(self.db, PAYMENT_ENTITY, tenant_id, "failed")
        pay.status_id = failed
        self.db.commit()
        return {"applied": True, "paymentId": pay.id, "status": "failed"}

    def _apply_dispute(self, tenant_id: str, pay: Payment) -> Dict:
        """AC-07-36 — a chargeback flips a Succeeded payment to Disputed; never
        silently dropped. (Full dispute response = backlog.)"""
        pay_key = _status_key_by_id(self.db, pay.status_id)
        if pay_key not in ("succeeded",):
            return {"applied": False, "reason": "not_succeeded", "paymentId": pay.id}
        disputed = _status_id_by_key(self.db, PAYMENT_ENTITY, tenant_id, "disputed")
        if disputed is None:
            return {"applied": False, "reason": "no_disputed_status", "paymentId": pay.id}
        pay.status_id = disputed
        # Disputed money no longer counts as paid — clearing paid_at drops it from
        # the Σ Succeeded aggregate so the invoice re-derives off-Paid.
        pay.paid_at = None
        self.db.commit()
        from app.workflow_engine.entity_events import notify_entity_event

        notify_entity_event(self.db, PAYMENT_ENTITY, "status_changed", pay, tenant_id=tenant_id)
        return {"applied": True, "paymentId": pay.id, "status": "disputed"}

    # ── abandoned-checkout reaper (AC-07-33) ─────────────────────────────────
    def reap_abandoned(self, tenant_id: Optional[str] = None) -> int:
        """Sweep Pending GATEWAY payments older than the checkout TTL with no
        webhook → Expired (frees the buyer to re-pay). Returns the count swept.
        Tenant-scoped when ``tenant_id`` is given; else all tenants."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.payment_checkout_ttl_minutes)
        q = (
            self.db.query(Payment)
            .filter(
                Payment.method.in_(GATEWAY_PAYMENT_METHODS),
                Payment.paid_at.is_(None),
                Payment.created_at < cutoff,
            )
        )
        if tenant_id is not None:
            q = q.filter(Payment.tenant_id == tenant_id)
        swept = 0
        for pay in q.all():
            pay_key = _status_key_by_id(self.db, pay.status_id)
            if pay_key != "pending":
                continue
            expired = _status_id_by_key(self.db, PAYMENT_ENTITY, pay.tenant_id, "expired")
            if expired is None:
                continue
            pay.status_id = expired
            swept += 1
        if swept:
            self.db.commit()
        return swept

    def _paid_total(self, invoice_id: str) -> Decimal:
        val = (
            self.db.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(Payment.invoice_id == invoice_id, Payment.paid_at.isnot(None))
            .scalar()
        )
        return _money(val)
