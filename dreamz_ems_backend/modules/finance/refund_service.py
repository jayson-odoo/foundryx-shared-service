"""Finance refund service (sprint-4/07 Cluster F slice 4).

Per-ticket refunds (AC-07-37..43). The refund method MIRRORS the payment method
(AC-07-38): GATEWAY/FPX route through the gateway refund API and confirm via the
webhook; CASH/BANK are MANUAL records that confirm immediately. Σ refunds never
exceeds Σ payments — guarded under ``SELECT invoice FOR UPDATE`` (AC-07-39).

At CONFIRM (immediate for manual; on webhook for gateway):
  • a gapless ``credit_note`` number is assigned (AC-07-40)
  • each refund-line ticket is refunded via the EMS ``ticket.refund@1`` capability
    → QR rotated dead + capacity released (AC-07-41/42)
  • the invoice re-derives Partially Refunded / Refunded (AC-07-43, derived)
  • participant eligibility re-derives off the refunded tickets (AC-07-44, derived)
  • a Remitted-settlement ticket spawns an ADJUSTMENT settlement (AC-07-48)

Money is exact Decimal throughout (AC-07-51). Tenant-scoped everywhere (AC-07-49).
Failure-isolated: a broken downstream reaction never 500s the request/webhook
(AC-07-50) — the after-commit bus owns the cross-entity re-derivations.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.finance.models import (
    GATEWAY_REFUND_METHODS,
    INVOICE_ENTITY,
    REFUND_ENTITY,
    Invoice,
    Payment,
    Refund,
    RefundLine,
)
from modules.finance.services import _money, _status_id_by_key, _status_key_by_id

logger = logging.getLogger("dreamz.finance.refunds")


class RefundService:
    def __init__(self, db: Session):
        self.db = db

    # ── public: create a per-ticket refund (AC-07-37/38/39) ──────────────────
    def create(self, tenant_id: str, invoice_id: str, payload: dict, actor) -> dict:
        """Refund SELECTED tickets on an invoice. ``payload``: ticketIds[],
        reason?. The amount is derived per ticket from the invoice's per-ticket
        share; the method mirrors the invoice's primary payment method."""
        ticket_ids: List[str] = payload.get("ticketIds") or []
        if not ticket_ids:
            raise HTTPException(422, "Select at least one ticket to refund.")

        # Lock the invoice so Σrefunds can't race past Σpayments (AC-07-39).
        inv = (
            self.db.query(Invoice)
            .filter(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
            .with_for_update()
            .first()
        )
        if inv is None:
            raise HTTPException(404, "Invoice not found.")

        paid_total = self._paid_total(invoice_id)
        if paid_total <= 0:
            raise HTTPException(409, "This invoice has no captured payments to refund.")
        already_refunded = self._refunded_total(invoice_id)

        # Resolve the invoice's refundable tickets via the EMS capability and
        # validate the selection (tenant-scoped, AC-07-49).
        tickets = self._invoice_tickets(tenant_id, invoice_id)
        ticket_by_id = {t["id"]: t for t in tickets}
        selected = []
        for tid in ticket_ids:
            t = ticket_by_id.get(tid)
            if t is None:
                raise HTTPException(422, "A selected ticket does not belong to this invoice.")
            if not t.get("refundable"):
                raise HTTPException(409, "A selected ticket can no longer be refunded.")
            selected.append(t)
        if not selected:
            raise HTTPException(422, "No refundable tickets in the selection.")

        # Per-ticket share: split the invoice total evenly across its refundable-
        # at-issue ticket count (v1 = one admission ticket priced per attendee;
        # an even split reconciles exactly with a last-ticket remainder).
        amount = self._lines_amount(tenant_id, invoice_id, len(selected), len(tickets))

        # Over-refund guard (AC-07-39): Σ refunds (confirmed + this) ≤ Σ payments.
        if already_refunded + amount > paid_total:
            raise HTTPException(
                409, "Refund exceeds the captured payments — over-refund is not allowed."
            )

        # The method mirrors the primary payment (AC-07-38).
        payment = self._primary_payment(invoice_id)
        method = (payment.method if payment is not None else "CASH").upper()
        is_gateway = method in GATEWAY_REFUND_METHODS

        pending_id = _status_id_by_key(self.db, REFUND_ENTITY, tenant_id, "pending")
        refund = Refund(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            payment_id=payment.id if payment is not None else None,
            amount=amount,
            method=method,
            status_id=pending_id,
            reason=payload.get("reason"),
        )
        self.db.add(refund)
        self.db.flush()
        # Split the refund evenly across the selected tickets; the LAST line takes
        # the rounding remainder so Σ lines == refund.amount EXACTLY (AC-07-51).
        per = _money(amount / Decimal(len(selected)))
        running = _money(0)
        for idx, t in enumerate(selected):
            line_amount = _money(amount - running) if idx == len(selected) - 1 else per
            running += line_amount
            self.db.add(
                RefundLine(
                    tenant_id=tenant_id,
                    refund_id=refund.id,
                    ticket_id=t["id"],
                    amount=line_amount,
                )
            )
        self.db.flush()

        if is_gateway:
            # Route through the gateway refund API (AC-07-37). Billplz has no
            # public refund API → returns a ``manual:`` ref (operator settles in
            # the dashboard) — still a gateway-initiated record. Stripe confirms
            # via the webhook; we confirm here on the API result for both since
            # the refund record is the truth (the webhook is idempotent on it).
            gateway_ref = self._gateway_refund(tenant_id, inv, payment, amount)
            refund.gateway_ref = gateway_ref
            self.db.flush()
            # Confirm now: the API call succeeded (or returned the manual marker).
            self._confirm(tenant_id, refund, inv, actor)
        else:
            # CASH/BANK manual refund — confirm immediately (AC-07-38).
            self._confirm(tenant_id, refund, inv, actor)

        self.db.commit()
        # Cross-entity re-derivations (invoice status, participant eligibility,
        # settlement adjustment) ride the after-commit bus, failure-isolated.
        self._emit_post_confirm(tenant_id, refund)
        self.db.refresh(refund)
        return self._to_dict(refund)

    # ── confirm: number + refund tickets + settlement adjustment ─────────────
    def _confirm(self, tenant_id: str, refund: Refund, inv: Invoice, actor) -> None:
        from app.services.numbering_service import NumberingService

        now = datetime.now(timezone.utc)
        if not refund.credit_note_number:
            refund.credit_note_number = NumberingService(self.db).next_number(
                tenant_id, "credit_note", now.date()
            )  # AC-07-40
        confirmed = _status_id_by_key(self.db, REFUND_ENTITY, tenant_id, "confirmed")
        refund.status_id = confirmed
        refund.confirmed_at = now
        self.db.flush()

        # Refund each ticket (QR dead + capacity released, AC-07-41/42) via the
        # EMS capability — within THIS transaction (commit owned by create()).
        lines = (
            self.db.query(RefundLine)
            .filter(RefundLine.refund_id == refund.id, RefundLine.tenant_id == tenant_id)
            .all()
        )
        for ln in lines:
            self._refund_ticket(tenant_id, ln.ticket_id)
        self.db.flush()

    def _refund_ticket(self, tenant_id: str, ticket_id: str) -> None:
        from app.module_platform import resolve_capability

        handler = resolve_capability(self.db, tenant_id, "ticket.refund", 1)
        if handler is None:
            logger.warning("ticket.refund capability unavailable for tenant %s", tenant_id)
            return
        try:
            res = handler(self.db, tenant_id, {"ticketId": ticket_id})
            if not (res or {}).get("ok"):
                logger.info("ticket %s not refundable: %s", ticket_id, (res or {}).get("reason"))
        except Exception:  # noqa: BLE001 — one bad ticket never breaks the refund
            logger.exception("ticket.refund failed (%s)", ticket_id)

    def _emit_post_confirm(self, tenant_id: str, refund: Refund) -> None:
        """Emit the refund + ticket status_changed events AFTER commit so the
        derived-status bus re-derives the invoice (Partially Refunded/Refunded),
        participant eligibility, and spawns a settlement ADJUSTMENT if the
        invoice is already in a Remitted settlement. Failure-isolated."""
        from app.workflow_engine.entity_events import notify_entity_event

        try:
            notify_entity_event(
                self.db, REFUND_ENTITY, "status_changed", refund, tenant_id=tenant_id
            )
        except Exception:  # noqa: BLE001
            logger.exception("refund post-confirm emit failed (%s)", refund.id)
        # Re-derive each refunded ticket's owning participant (AC-07-44). The
        # ticket move happened with commit=False inside the txn, so its own
        # status_changed event was not emitted — emit now off the committed rows.
        try:
            self._emit_ticket_events(tenant_id, refund)
        except Exception:  # noqa: BLE001
            logger.exception("refund ticket events emit failed (%s)", refund.id)

    def _emit_ticket_events(self, tenant_id: str, refund: Refund) -> None:
        from app.workflow_engine.entity_events import notify_entity_event

        lines = (
            self.db.query(RefundLine)
            .filter(RefundLine.refund_id == refund.id, RefundLine.tenant_id == tenant_id)
            .all()
        )
        ticket_ids = [ln.ticket_id for ln in lines]
        handler = self._ems_ticket_loader(tenant_id)
        for tid in ticket_ids:
            t = handler(tid) if handler else None
            if t is not None:
                notify_entity_event(self.db, "ticket", "status_changed", t, tenant_id=tenant_id)

    def _ems_ticket_loader(self, tenant_id: str):
        try:
            from modules.ems.models import Ticket
        except Exception:  # noqa: BLE001 — EMS not installed
            return None

        def _load(ticket_id: str):
            return (
                self.db.query(Ticket)
                .filter(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
                .first()
            )

        return _load

    # ── gateway refund (AC-07-37/38) ─────────────────────────────────────────
    def _gateway_refund(self, tenant_id: str, inv: Invoice, payment: Optional[Payment], amount: Decimal) -> str:
        from app.integrations import PaymentError, get_provider
        from app.repositories.connection_repository import ConnectionRepository
        from app.secrets import decrypt_secret

        if payment is None or not payment.gateway_connection_id or not payment.external_payment_id:
            # No gateway charge to reverse — record a manual marker so the credit
            # note + ledger still apply (operator settles out-of-band).
            return "manual:no-charge"
        conn = ConnectionRepository(self.db).get(payment.gateway_connection_id, tenant_id)
        if conn is None:
            raise HTTPException(409, "The original payment gateway is no longer configured.")
        provider = get_provider(conn.provider)
        if provider is None or getattr(provider, "type", None) != "payment":
            raise HTTPException(409, "The original payment provider is unavailable.")
        try:
            credentials = decrypt_secret(conn.credentials_json) if conn.credentials_json else {}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, "Stored gateway credentials could not be read.") from e
        try:
            result = provider.refund(
                conn.config_json or {}, credentials,
                external_payment_id=payment.external_payment_id,
                amount=amount, currency=inv.currency,
            )
        except PaymentError as e:
            raise HTTPException(502, f"The gateway refund failed: {e}") from e
        return result.external_refund_id or "gateway:ok"

    # ── webhook reaction: idempotent confirm of a gateway refund (AC-07-34) ──
    def apply_refund_event(self, tenant_id: str, payload: dict) -> dict:
        """Called by the gateway webhook ingest for a normalised ``refund`` event.
        Finds the originating payment by ``external_ref`` (our payment id) and, if
        a Pending refund exists, confirms it idempotently. A refund created via
        the API path is already Confirmed → this is a no-op (the record is the
        truth). Out-of-order (payment not present) → RetryableWebhook."""
        from app.services.payment_gateway_service import RetryableWebhook

        external_ref = payload.get("externalRef")
        if not external_ref:
            return {"applied": False, "reason": "no_external_ref"}
        payment = (
            self.db.query(Payment)
            .filter(Payment.id == external_ref, Payment.tenant_id == tenant_id)
            .first()
        )
        if payment is None:
            raise RetryableWebhook(f"payment {external_ref} not found yet")
        pending = (
            self.db.query(Refund)
            .filter(
                Refund.tenant_id == tenant_id,
                Refund.payment_id == payment.id,
            )
            .all()
        )
        pending_id = _status_id_by_key(self.db, REFUND_ENTITY, tenant_id, "pending")
        unconfirmed = [r for r in pending if r.status_id == pending_id]
        if not unconfirmed:
            return {"applied": False, "reason": "already_confirmed_or_api_path"}
        inv = (
            self.db.query(Invoice)
            .filter(Invoice.id == payment.invoice_id, Invoice.tenant_id == tenant_id)
            .with_for_update()
            .first()
        )
        for refund in unconfirmed:
            self._confirm(tenant_id, refund, inv, None)
        self.db.commit()
        for refund in unconfirmed:
            self._emit_post_confirm(tenant_id, refund)
        return {"applied": True, "confirmed": [r.id for r in unconfirmed]}

    # ── credit-note PDF (AC-07-40) ───────────────────────────────────────────
    def render_credit_note_pdf(self, tenant_id: str, refund_id: str) -> bytes:
        from modules.finance.pdf import render_credit_note_pdf

        refund = (
            self.db.query(Refund)
            .filter(Refund.id == refund_id, Refund.tenant_id == tenant_id)
            .first()
        )
        if refund is None:
            raise HTTPException(404, "Refund not found.")
        inv = (
            self.db.query(Invoice)
            .filter(Invoice.id == refund.invoice_id, Invoice.tenant_id == tenant_id)
            .first()
        )
        if inv is None:
            raise HTTPException(404, "Invoice not found.")
        return render_credit_note_pdf(self.db, tenant_id, refund, inv)

    # ── reads / helpers ──────────────────────────────────────────────────────
    def list_for_invoice(self, tenant_id: str, invoice_id: str) -> List[dict]:
        rows = (
            self.db.query(Refund)
            .filter(Refund.tenant_id == tenant_id, Refund.invoice_id == invoice_id)
            .order_by(Refund.created_at.asc())
            .all()
        )
        return [self._to_dict(r) for r in rows]

    def _to_dict(self, r: Refund) -> dict:
        lines = (
            self.db.query(RefundLine)
            .filter(RefundLine.refund_id == r.id, RefundLine.tenant_id == r.tenant_id)
            .all()
        )
        status_key = _status_key_by_id(self.db, r.status_id)
        return {
            "id": r.id,
            "invoiceId": r.invoice_id,
            "amount": float(_money(r.amount)),
            "method": r.method,
            "statusId": r.status_id,
            "statusKey": status_key,
            "creditNoteNumber": r.credit_note_number,
            "gatewayRef": r.gateway_ref,
            "reason": r.reason,
            "ticketIds": [ln.ticket_id for ln in lines],
            "createdAt": r.created_at,
        }

    def _invoice_tickets(self, tenant_id: str, invoice_id: str) -> List[dict]:
        from app.module_platform import resolve_capability

        handler = resolve_capability(self.db, tenant_id, "tickets.for_invoice", 1)
        if handler is None:
            return []
        return handler(self.db, tenant_id, {"invoiceId": invoice_id}) or []

    def _lines_amount(self, tenant_id: str, invoice_id: str, n_selected: int, n_total: int) -> Decimal:
        """The refund amount for ``n_selected`` of ``n_total`` tickets = an even
        share of the invoice total. Quantized 4dp; the per-line split in create()
        divides this evenly (the small remainder lands on the rounding of the
        last line — Σ lines == refund.amount, AC-07-51)."""
        inv = (
            self.db.query(Invoice)
            .filter(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
            .first()
        )
        total = _money(inv.total) if inv is not None else _money(0)
        if n_total <= 0:
            return total
        per = (total / Decimal(n_total))
        return _money(per * Decimal(n_selected))

    def _primary_payment(self, invoice_id: str) -> Optional[Payment]:
        """The Succeeded payment that captured money (AC-07-38 method mirror). v1
        invoices have a single capture; pick the first Succeeded one."""
        return (
            self.db.query(Payment)
            .filter(Payment.invoice_id == invoice_id, Payment.paid_at.isnot(None))
            .order_by(Payment.created_at.asc())
            .first()
        )

    def _paid_total(self, invoice_id: str) -> Decimal:
        val = (
            self.db.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(Payment.invoice_id == invoice_id, Payment.paid_at.isnot(None))
            .scalar()
        )
        return _money(val)

    def _refunded_total(self, invoice_id: str) -> Decimal:
        """Σ confirmed refund amounts on the invoice (exact Decimal)."""
        val = (
            self.db.query(func.coalesce(func.sum(Refund.amount), 0))
            .filter(Refund.invoice_id == invoice_id, Refund.confirmed_at.isnot(None))
            .scalar()
        )
        return _money(val)
