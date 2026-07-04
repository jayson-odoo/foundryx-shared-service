"""Finance settlement service (sprint-4/07 Cluster F slice 4).

Agency give-back settlement (AC-07-45..48). An AGENCY project's paid attendee
invoices roll up into ONE PRIMARY settlement:

    net_payable = gross_collected − gateway_fees − fee_amount   (all three shown)

Lifecycle rides the status engine (Draft→Approved→Remitted, AC-07-47). A
post-remit refund spawns a supplementary ADJUSTMENT settlement (may be negative)
— the original Remitted PRIMARY is never mutated (AC-07-48).

Money is exact Decimal throughout (AC-07-51). Tenant-scoped everywhere
(AC-07-49). Commercial config + the PER_TICKET base are read from the EMS project
via the ``project.commercial@1`` capability (BL-030 soft-ref).
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.status import Status
from app.services import status_machine
from modules.finance.models import (
    SETTLEMENT_ADJUSTMENT,
    SETTLEMENT_ENTITY,
    SETTLEMENT_PRIMARY,
    Invoice,
    Payment,
    Refund,
    Settlement,
    SettlementLine,
)
from modules.finance.services import _money, _status_id_by_key, _status_key_by_id

logger = logging.getLogger("dreamz.finance.settlement")


class SettlementService:
    def __init__(self, db: Session):
        self.db = db

    # ── PRIMARY settlement generation (AC-07-45/46) ──────────────────────────
    def generate(self, tenant_id: str, project_id: str, actor) -> dict:
        """Roll up an AGENCY project's paid attendee invoices into a Draft PRIMARY
        settlement. SELF_RUN projects produce nothing (409). Idempotent: a project
        that already has a PRIMARY settlement is refused (409 — regenerate by
        deleting the Draft first; a remitted one is final)."""
        commercial = self._project_commercial(tenant_id, project_id)
        if commercial is None:
            raise HTTPException(404, "Event not found.")
        if (commercial.get("commercialMode") or "SELF_RUN") != "AGENCY":
            raise HTTPException(409, "Only AGENCY events produce a settlement.")

        existing = (
            self.db.query(Settlement)
            .filter(
                Settlement.tenant_id == tenant_id,
                Settlement.project_id == project_id,
                Settlement.kind == SETTLEMENT_PRIMARY,
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(409, "A settlement already exists for this event.")

        gross, fees, invoice_amounts = self._rollup(tenant_id, project_id)
        fee_amount = self._fee_amount(commercial, gross, invoice_amounts)
        net = _money(gross - fees - fee_amount)

        draft = _status_id_by_key(self.db, SETTLEMENT_ENTITY, tenant_id, "draft")
        settlement = Settlement(
            tenant_id=tenant_id,
            project_id=project_id,
            client_id=commercial.get("clientId"),
            kind=SETTLEMENT_PRIMARY,
            gross_collected=gross,
            gateway_fees=fees,
            fee_type=commercial.get("feeType"),
            fee_amount=fee_amount,
            net_payable=net,
            status_id=draft,
        )
        self.db.add(settlement)
        self.db.flush()
        for invoice_id, amount in invoice_amounts.items():
            self.db.add(
                SettlementLine(
                    tenant_id=tenant_id,
                    settlement_id=settlement.id,
                    invoice_id=invoice_id,
                    amount=amount,
                )
            )
        self.db.commit()
        self.db.refresh(settlement)
        return self._to_dict(settlement)

    def _rollup(self, tenant_id: str, project_id: str):
        """(gross_collected, gateway_fees, {invoice_id: net_collected}) over the
        project's paid invoices. gross = Σ succeeded payments − Σ confirmed
        refunds (the money actually held); fees = Σ payment gateway_fee. Exact
        Decimal (AC-07-51)."""
        invoices = (
            self.db.query(Invoice)
            .filter(Invoice.tenant_id == tenant_id, Invoice.project_id == project_id)
            .all()
        )
        gross = _money(0)
        fees = _money(0)
        amounts: Dict[str, Decimal] = {}
        for inv in invoices:
            paid = self._paid_total(inv.id)
            refunded = self._refunded_total(inv.id)
            net_collected = _money(paid - refunded)
            inv_fees = self._fees_total(inv.id)
            if net_collected == 0 and inv_fees == 0:
                continue
            gross += net_collected
            fees += inv_fees
            amounts[inv.id] = net_collected
        return _money(gross), _money(fees), amounts

    def _fee_amount(self, commercial: dict, gross: Decimal, invoice_amounts: Dict[str, Decimal]) -> Decimal:
        """Agency fee (AC-07-45). PERCENT = gross × value%; FLAT = value;
        PER_TICKET = value × paid-ticket count. Exact Decimal."""
        fee_type = commercial.get("feeType")
        value = _money(commercial.get("feeValue") or 0)
        if fee_type == "PERCENT":
            return _money(gross * (value / Decimal(100)))
        if fee_type == "FLAT":
            return value
        if fee_type == "PER_TICKET":
            count = int(commercial.get("ticketCount") or 0)
            return _money(value * Decimal(count))
        return _money(0)

    # ── lifecycle (AC-07-47) ─────────────────────────────────────────────────
    def transition(self, tenant_id: str, settlement_id: str, to_status_id: str, payload: dict, actor) -> dict:
        s = self._get(tenant_id, settlement_id)
        target_key = _status_key_by_id(self.db, to_status_id)
        if target_key == "remitted":
            ref = (payload or {}).get("remittanceRef")
            if not ref:
                raise HTTPException(422, "A remittance reference is required to mark remitted.")
            s.remittance_ref = ref
            s.remitted_at = datetime.now(timezone.utc)
        status_machine.transition(
            self.db, SETTLEMENT_ENTITY, s, to_status_id, actor, tenant_id=tenant_id, commit=False
        )
        self.db.commit()
        self.db.refresh(s)
        return self._to_dict(s)

    # ── ADJUSTMENT on a post-remit refund (AC-07-48) ─────────────────────────
    def spawn_adjustment_for_refund(self, tenant_id: str, refund: Refund) -> Optional[dict]:
        """If the refund's invoice is in a REMITTED PRIMARY settlement, spawn a
        supplementary ADJUSTMENT settlement clawing back the refunded amount
        (net negative). The original Remitted PRIMARY is untouched. Returns the
        adjustment dict or None. Tenant-scoped, failure-isolated by the caller."""
        line = (
            self.db.query(SettlementLine)
            .filter(
                SettlementLine.tenant_id == tenant_id,
                SettlementLine.invoice_id == refund.invoice_id,
            )
            .first()
        )
        if line is None:
            return None
        primary = (
            self.db.query(Settlement)
            .filter(Settlement.id == line.settlement_id, Settlement.tenant_id == tenant_id)
            .first()
        )
        if primary is None or primary.kind != SETTLEMENT_PRIMARY:
            return None
        if _status_key_by_id(self.db, primary.status_id) != "remitted":
            return None  # only a remitted settlement needs a clawback adjustment

        # Recompute the fee delta on the refunded amount so the net reverses the
        # original three-way split (gross down by the refund, fee proportional).
        commercial = self._project_commercial(tenant_id, primary.project_id) or {}
        refunded = _money(refund.amount)
        fee_delta = self._fee_amount(
            commercial, refunded, {refund.invoice_id: refunded}
        ) if commercial.get("feeType") in ("PERCENT",) else _money(0)
        # ADJUSTMENT net = −(gross_clawed − fee_clawed): we paid the agency net on
        # the original; a refund returns money, so the give-back reverses by the
        # net of the refunded share (negative).
        net = _money(-(refunded - fee_delta))

        draft = _status_id_by_key(self.db, SETTLEMENT_ENTITY, tenant_id, "draft")
        adj = Settlement(
            tenant_id=tenant_id,
            project_id=primary.project_id,
            client_id=primary.client_id,
            kind=SETTLEMENT_ADJUSTMENT,
            gross_collected=_money(-refunded),
            gateway_fees=_money(0),
            fee_type=primary.fee_type,
            fee_amount=_money(-fee_delta),
            net_payable=net,
            status_id=draft,
        )
        self.db.add(adj)
        self.db.flush()
        self.db.add(
            SettlementLine(
                tenant_id=tenant_id,
                settlement_id=adj.id,
                invoice_id=refund.invoice_id,
                amount=_money(-refunded),
            )
        )
        self.db.flush()
        return self._to_dict(adj)

    # ── reads ────────────────────────────────────────────────────────────────
    def list(self, tenant_id: str, *, page=0, page_size=25, project_id=None):
        q = self.db.query(Settlement).filter(Settlement.tenant_id == tenant_id)
        if project_id:
            q = q.filter(Settlement.project_id == project_id)
        q = q.order_by(Settlement.created_at.desc())
        total = q.count()
        rows = q.offset(page * page_size).limit(page_size).all()
        return [self._to_dict(r) for r in rows], total

    def get(self, tenant_id: str, settlement_id: str) -> dict:
        return self._to_dict(self._get(tenant_id, settlement_id))

    def _get(self, tenant_id: str, settlement_id: str) -> Settlement:
        s = (
            self.db.query(Settlement)
            .filter(Settlement.id == settlement_id, Settlement.tenant_id == tenant_id)
            .first()
        )
        if s is None:
            raise HTTPException(404, "Settlement not found.")
        return s

    def _to_dict(self, s: Settlement) -> dict:
        lines = (
            self.db.query(SettlementLine)
            .filter(SettlementLine.settlement_id == s.id, SettlementLine.tenant_id == s.tenant_id)
            .all()
        )
        st = self.db.query(Status).filter(Status.id == s.status_id).first() if s.status_id else None
        return {
            "id": s.id,
            "projectId": s.project_id,
            "clientId": s.client_id,
            "kind": s.kind,
            "grossCollected": float(_money(s.gross_collected)),
            "gatewayFees": float(_money(s.gateway_fees)),
            "feeType": s.fee_type,
            "feeAmount": float(_money(s.fee_amount)),
            "netPayable": float(_money(s.net_payable)),
            "statusId": s.status_id,
            "statusKey": st.key if st else None,
            "statusLabel": st.label if st else None,
            "remittanceRef": s.remittance_ref,
            "generatedAt": s.generated_at,
            "lines": [{"id": ln.id, "invoiceId": ln.invoice_id, "amount": float(_money(ln.amount))} for ln in lines],
        }

    # ── helpers ──────────────────────────────────────────────────────────────
    def _project_commercial(self, tenant_id: str, project_id: str) -> Optional[dict]:
        from app.module_platform import resolve_capability

        handler = resolve_capability(self.db, tenant_id, "project.commercial", 1)
        if handler is None:
            return None
        return handler(self.db, tenant_id, {"id": project_id})

    def _paid_total(self, invoice_id: str) -> Decimal:
        val = (
            self.db.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(Payment.invoice_id == invoice_id, Payment.paid_at.isnot(None))
            .scalar()
        )
        return _money(val)

    def _fees_total(self, invoice_id: str) -> Decimal:
        val = (
            self.db.query(func.coalesce(func.sum(Payment.gateway_fee), 0))
            .filter(Payment.invoice_id == invoice_id, Payment.paid_at.isnot(None))
            .scalar()
        )
        return _money(val)

    def _refunded_total(self, invoice_id: str) -> Decimal:
        val = (
            self.db.query(func.coalesce(func.sum(Refund.amount), 0))
            .filter(Refund.invoice_id == invoice_id, Refund.confirmed_at.isnot(None))
            .scalar()
        )
        return _money(val)
