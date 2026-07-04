"""Finance services (sprint-4/05, extended sprint-4/07 Cluster F slice 1) —
Service-Repository, tenant-scoped. Invoice creation behind
``finance.create_invoice@1`` + the read behind ``invoice.resolve@1``, plus the
tenant-facing invoice list/transition, Issue (assign number + freeze), the
freeze guard, manual payments, Void, and the PDF render.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.status import Status
from app.services import status_machine
from modules.finance.models import (
    INVOICE_ENTITY,
    MANUAL_PAYMENT_METHODS,
    PAYMENT_ENTITY,
    PAYMENT_METHODS,
    Invoice,
    InvoiceLine,
    Payment,
)

# Money arithmetic = exact Decimal quantized to 4dp (AC-07-02). Never float.
_CENTS = Decimal("0.0001")


def _money(v) -> Decimal:
    """Coerce any numeric input to an exact 4dp Decimal (via str to avoid binary
    float artefacts, e.g. Decimal(0.1))."""
    if v is None:
        return Decimal("0").quantize(_CENTS)
    return Decimal(str(v)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _rate(v) -> Decimal:
    """A tax rate (small fraction, 4dp) — distinct from money."""
    if v is None:
        return Decimal("0").quantize(_CENTS)
    return Decimal(str(v)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _status_id_by_key(db: Session, entity_type: str, tenant_id: str, key: str) -> Optional[str]:
    row = (
        db.query(Status)
        .filter(
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id.is_(None),
            Status.key == key,
        )
        .first()
    )
    return row.id if row else None


def _status_key_by_id(db: Session, status_id: Optional[str]) -> Optional[str]:
    if not status_id:
        return None
    row = db.query(Status).filter(Status.id == status_id).first()
    return row.key if row else None


def _initial_invoice_status(db: Session, tenant_id: str) -> Optional[str]:
    row = (
        db.query(Status)
        .filter(
            Status.entity_type == INVOICE_ENTITY,
            Status.tenant_id == tenant_id,
            Status.scope_id.is_(None),
            Status.is_initial.is_(True),
        )
        .order_by(Status.sort_order.asc())
        .first()
    )
    return row.id if row else None


def _tenant_currency(db: Session, tenant_id: str) -> str:
    from app.models.tenant_settings import DEFAULT_CURRENCY, TenantSettings

    row = db.query(TenantSettings).filter(TenantSettings.tenant_id == tenant_id).first()
    return (row.default_currency if row and row.default_currency else None) or DEFAULT_CURRENCY


def _bill_to_name(db: Session, tenant_id: str, bill_to_type: str, bill_to_id: str) -> str:
    """Resolve the bill-to display name across modules (orphan-safe, BL-030)."""
    from app.module_platform import resolve_capability

    key = "client.resolve" if bill_to_type == "Client" else "profile.resolve"
    handler = resolve_capability(db, tenant_id, key, 1)
    if handler is None:
        return ""
    res = handler(db, tenant_id, {"id": bill_to_id})
    if not res:
        return ""
    return res.get("name") or res.get("fullName") or res.get("email") or ""


class InvoiceService:
    def __init__(self, db: Session):
        self.db = db

    # ── capability: finance.create_invoice@1 ──
    def create_from_payload(self, tenant_id: str, payload: dict) -> dict:
        """Mint a Draft invoice + lines. payload: projectId?, billToType, billToId,
        currency?, lines[{projectProductId?, description?, qty, unitPrice, taxRate?}]."""
        currency = payload.get("currency") or _tenant_currency(self.db, tenant_id)
        inv = Invoice(
            tenant_id=tenant_id,
            project_id=payload.get("projectId"),
            sales_order_id=payload.get("salesOrderId"),  # Cluster F slice 2 (AC-07-21)
            bill_to_type=payload["billToType"],
            bill_to_id=payload["billToId"],
            currency=currency,
            status_id=_initial_invoice_status(self.db, tenant_id),
            subtotal=0,
            tax=0,
            total=0,
        )
        self.db.add(inv)
        self.db.flush()
        subtotal = Decimal("0").quantize(_CENTS)
        tax_total = Decimal("0").quantize(_CENTS)
        for ln in payload.get("lines", []):
            qty = int(ln.get("qty", 1))
            unit = _money(ln.get("unitPrice", 0))
            # quantize per line, then sum the quantized values so the header
            # totals always equal the sum of the stored line items (no cent drift).
            amount = _money(qty * unit)
            # Per-line tax (AC-07-15): exclusive, rate is a small fraction. The
            # payload may carry a percent (``taxRate=9`` = 9%) — divide by 100 to
            # the stored fraction; tax_amount = round(amount * rate) in Decimal.
            rate_fraction = _rate(_money(ln.get("taxRate", 0)) / Decimal(100))
            line_tax = _money(amount * rate_fraction)
            subtotal += amount
            tax_total += line_tax
            self.db.add(
                InvoiceLine(
                    tenant_id=tenant_id,
                    invoice_id=inv.id,
                    project_product_id=ln.get("projectProductId"),
                    description=ln.get("description"),
                    qty=qty,
                    unit_price=unit,
                    tax_rate=rate_fraction,
                    tax_amount=line_tax,
                    tax=line_tax,
                    amount=amount,
                )
            )
        inv.subtotal = subtotal
        inv.tax = tax_total
        inv.total = subtotal + tax_total
        self.db.flush()
        # JSON-safe wire: Decimal → float at the capability boundary (AC-07-02).
        return {"id": inv.id, "total": float(inv.total), "currency": inv.currency, "statusId": inv.status_id}

    # ── capability: invoice.resolve@1 ──
    def resolve(self, tenant_id: str, invoice_id: Optional[str]) -> Optional[dict]:
        if not invoice_id:
            return None
        inv = (
            self.db.query(Invoice)
            .filter(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
            .first()
        )
        if inv is None:
            return None
        return {
            "id": inv.id,
            "total": float(inv.total) if inv.total is not None else 0.0,
            "currency": inv.currency,
            "statusId": inv.status_id,
            "billToType": inv.bill_to_type,
            "billToId": inv.bill_to_id,
            "projectId": inv.project_id,
            "salesOrderId": inv.sales_order_id,
        }

    # ── tax summary (AC-07-15) ──
    def _tax_summary(self, lines) -> list:
        """Group tax by rate (6%/8%/exempt). Each entry: rate fraction, percent
        label, taxable base (Σ line amount), tax (Σ line tax_amount). Exact
        Decimal, ordered by rate."""
        buckets: dict = {}
        for ln in lines:
            rate = _rate(ln.tax_rate)
            base, tax = buckets.get(rate, (Decimal("0").quantize(_CENTS), Decimal("0").quantize(_CENTS)))
            buckets[rate] = (base + _money(ln.amount), tax + _money(ln.tax_amount))
        out = []
        for rate in sorted(buckets):
            base, tax = buckets[rate]
            pct = (rate * Decimal(100)).normalize()
            out.append({
                "rate": float(rate),
                "label": "Exempt" if rate == 0 else f"{pct}%",
                "base": float(base),
                "tax": float(tax),
            })
        return out

    def _paid_total(self, invoice_id: str) -> Decimal:
        """Σ Succeeded (paid_at set) payment amounts — exact Decimal."""
        val = (
            self.db.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(Payment.invoice_id == invoice_id, Payment.paid_at.isnot(None))
            .scalar()
        )
        return _money(val)

    # ── tenant-facing list / get / transition ──
    def _enrich(self, inv: Invoice) -> Invoice:
        inv.billToName = _bill_to_name(self.db, inv.tenant_id, inv.bill_to_type, inv.bill_to_id)
        inv.lines = (
            self.db.query(InvoiceLine).filter(InvoiceLine.invoice_id == inv.id).all()
        )
        inv.payments = (
            self.db.query(Payment)
            .filter(Payment.invoice_id == inv.id)
            .order_by(Payment.created_at.asc())
            .all()
        )
        inv.taxSummary = self._tax_summary(inv.lines)
        inv.paidTotal = float(self._paid_total(inv.id))
        if inv.status_id:
            st = self.db.query(Status).filter(Status.id == inv.status_id).first()
            inv.statusLabel = st.label if st else None
            inv.statusKey = st.key if st else None
        return inv

    def list(self, tenant_id, *, page=0, page_size=25, project_id=None, search=None):
        q = self.db.query(Invoice).filter(Invoice.tenant_id == tenant_id)
        if project_id:
            q = q.filter(Invoice.project_id == project_id)
        if search:
            q = q.filter(Invoice.bill_to_id.ilike(f"%{search}%"))
        q = q.order_by(Invoice.created_at.desc())
        total = q.count()
        rows = q.offset(page * page_size).limit(page_size).all()
        return [self._enrich(r) for r in rows], total

    def get(self, tenant_id, invoice_id) -> Invoice:
        inv = (
            self.db.query(Invoice)
            .filter(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
            .first()
        )
        if inv is None:
            raise HTTPException(404, "Invoice not found.")
        return self._enrich(inv)

    def transition(self, tenant_id, invoice_id, to_status_id, actor) -> Invoice:
        inv = self.get(tenant_id, invoice_id)
        target_key = _status_key_by_id(self.db, to_status_id)

        # Void guard (AC-07-14): only from Issued + zero Succeeded payments.
        if target_key == "void":
            if self._paid_total(inv.id) > 0:
                raise HTTPException(409, "Cannot void an invoice with payments — issue a refund instead.")

        status_machine.transition(
            self.db, INVOICE_ENTITY, inv, to_status_id, actor, tenant_id=tenant_id, commit=False
        )

        # Issue hook (AC-07-06): in the SAME commit as the status change, assign
        # the gapless invoice number, stamp issued_at + due_date, and freeze.
        if target_key == "issued" and not inv.invoice_number:
            from app.services.numbering_service import NumberingService

            now = datetime.now(timezone.utc)
            inv.invoice_number = NumberingService(self.db).next_number(tenant_id, "invoice", now.date())
            inv.issued_at = now
            if inv.due_date is None:
                inv.due_date = self._default_due_date(tenant_id, now)
            self.db.flush()

        self.db.commit()
        self.db.refresh(inv)
        return self._enrich(inv)

    def _default_due_date(self, tenant_id: str, issued_at: datetime) -> datetime:
        """Default payment terms — net 30 (configurable later via settings)."""
        from datetime import timedelta

        return issued_at + timedelta(days=30)

    # ── update (AC-07-09 freeze-after-Issue) ──
    _FINANCIAL_FIELDS = {
        "lines", "currency", "buyerTin", "sstRegNo", "taxCode", "einvoiceType",
        "billToType", "billToId", "projectId",
    }

    def update(self, tenant_id, invoice_id, payload: dict, actor) -> Invoice:
        """PATCH an invoice. Draft = fully editable; once Issued (any non-Draft
        status) financial/buyer fields are FROZEN → 409; notes + due_date stay
        editable. ``lines`` replaces all lines + recomputes totals (Draft only)."""
        inv = self.get(tenant_id, invoice_id)
        status_key = _status_key_by_id(self.db, inv.status_id)
        is_draft = status_key == "draft"

        touched_financial = any(k in payload for k in self._FINANCIAL_FIELDS)
        if touched_financial and not is_draft:
            raise HTTPException(409, "An issued invoice is frozen — financial fields cannot be changed.")

        # Notes are always editable (incl. post-Issue).
        if "notes" in payload:
            inv.notes = payload["notes"]
        # due_date editable while not terminal (operator may extend terms).
        if "dueDate" in payload and is_draft:
            inv.due_date = payload["dueDate"]

        if is_draft:
            for col, key in (
                ("buyer_tin", "buyerTin"), ("sst_reg_no", "sstRegNo"),
                ("tax_code", "taxCode"), ("einvoice_type", "einvoiceType"),
                ("currency", "currency"),
            ):
                if key in payload:
                    setattr(inv, col, payload[key])
            if "lines" in payload:
                self._replace_lines(tenant_id, inv, payload["lines"])

        self.db.flush()
        self.db.commit()
        self.db.refresh(inv)
        return self._enrich(inv)

    def _replace_lines(self, tenant_id: str, inv: Invoice, lines: list) -> None:
        self.db.query(InvoiceLine).filter(InvoiceLine.invoice_id == inv.id).delete(synchronize_session=False)
        subtotal = Decimal("0").quantize(_CENTS)
        tax_total = Decimal("0").quantize(_CENTS)
        for ln in lines:
            qty = int(ln.get("qty", 1))
            unit = _money(ln.get("unitPrice", 0))
            amount = _money(qty * unit)
            rate_fraction = _rate(_money(ln.get("taxRate", 0)) / Decimal(100))
            line_tax = _money(amount * rate_fraction)
            subtotal += amount
            tax_total += line_tax
            self.db.add(
                InvoiceLine(
                    tenant_id=tenant_id,
                    invoice_id=inv.id,
                    project_product_id=ln.get("projectProductId"),
                    description=ln.get("description"),
                    qty=qty,
                    unit_price=unit,
                    tax_rate=rate_fraction,
                    tax_amount=line_tax,
                    tax=line_tax,
                    amount=amount,
                )
            )
        inv.subtotal = subtotal
        inv.tax = tax_total
        inv.total = subtotal + tax_total

    # ── manual record-payment (AC-07-10/11/12) ──
    def record_payment(self, tenant_id, invoice_id, payload: dict, actor) -> Invoice:
        """Record a manual CASH/CARD/BANK payment (Succeeded immediately). The
        invoice re-derives Partially Paid/Paid via the payment→invoice
        DerivedTrigger. Overpayment is rejected under a row lock (AC-07-12)."""
        method = (payload.get("method") or "").upper()
        if method not in PAYMENT_METHODS:
            raise HTTPException(422, f"Unknown payment method '{method}'.")
        if method not in MANUAL_PAYMENT_METHODS:
            # GATEWAY/FPX are webhook-created only (Slice 3).
            raise HTTPException(422, f"'{method}' payments are created by the gateway, not recorded manually.")

        amount = _money(payload.get("amount"))
        if amount <= 0:
            raise HTTPException(422, "Payment amount must be greater than zero.")

        # Lock the invoice row so concurrent payments can't overpay (AC-07-12).
        inv = (
            self.db.query(Invoice)
            .filter(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
            .with_for_update()
            .first()
        )
        if inv is None:
            raise HTTPException(404, "Invoice not found.")
        status_key = _status_key_by_id(self.db, inv.status_id)
        if status_key in ("draft", "cancelled", "void"):
            raise HTTPException(409, "This invoice cannot accept payments.")

        already = self._paid_total(invoice_id)
        if already + amount > _money(inv.total):
            raise HTTPException(409, "Payment exceeds the invoice balance — overpayment is not allowed.")

        succeeded = _status_id_by_key(self.db, PAYMENT_ENTITY, tenant_id, "succeeded")
        now = datetime.now(timezone.utc)
        pay = Payment(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            amount=amount,
            method=method,
            status_id=succeeded,
            paid_at=now,
            note=payload.get("note"),
        )
        self.db.add(pay)
        self.db.flush()
        self.db.commit()
        # Re-derive the invoice (Partially Paid / Paid) via the bus — emit AFTER
        # the commit (notify_entity_event drains on a fresh session).
        from app.workflow_engine.entity_events import notify_entity_event

        notify_entity_event(self.db, PAYMENT_ENTITY, "created", pay, tenant_id=tenant_id, actor=actor)
        self.db.refresh(inv)
        return self._enrich(inv)

    # ── PDF (AC-07-17/18) ──
    def render_pdf(self, tenant_id, invoice_id) -> bytes:
        from modules.finance.pdf import render_invoice_pdf

        inv = self.get(tenant_id, invoice_id)
        return render_invoice_pdf(self.db, tenant_id, inv)
