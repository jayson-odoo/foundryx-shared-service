"""Invoice PDF render (sprint-4/07 Cluster F, AC-07-17/18).

Resolves the tenant's ``finance.invoice`` document template (tenant fork else the
seeded platform default), builds the merge facts from the invoice + its lines +
its Succeeded payments, and renders the WeasyPrint PDF via the F2
``render_document`` pipeline. When the invoice is Paid the payments table + a
"PAID" stamp surface — that IS the receipt (same template/number, AC-07-18).
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.finance.models import Invoice, InvoiceLine, Payment

_CENTS = Decimal("0.0001")


def _money(v) -> Decimal:
    if v is None:
        return Decimal("0").quantize(_CENTS)
    return Decimal(str(v)).quantize(_CENTS)


def _fmt_money(v, currency: str) -> str:
    """`<CUR> 1,234.56` — currency-symbol-agnostic (the wire renders the symbol
    on screen; the PDF prints the ISO code for unambiguous documents)."""
    amount = _money(v)
    return f"{currency} {amount:,.2f}"


def _fmt_date(v: Optional[datetime]) -> str:
    if v is None:
        return ""
    return v.strftime("%d %b %Y")


def _tax_label(rate: Decimal) -> str:
    if rate == 0:
        return "Exempt"
    pct = (rate * Decimal(100)).normalize()
    return f"{pct}%"


def _status_key(db: Session, status_id: Optional[str]) -> Optional[str]:
    from app.models.status import Status

    if not status_id:
        return None
    row = db.query(Status).filter(Status.id == status_id).first()
    return row.key if row else None


def _status_label(db: Session, status_id: Optional[str]) -> str:
    from app.models.status import Status

    if not status_id:
        return ""
    row = db.query(Status).filter(Status.id == status_id).first()
    return row.label if row else ""


def build_invoice_facts(db: Session, tenant_id: str, inv: Invoice) -> Dict[str, Any]:
    currency = inv.currency or "USD"
    lines: List[InvoiceLine] = (
        db.query(InvoiceLine).filter(InvoiceLine.invoice_id == inv.id).all()
    )
    payments: List[Payment] = (
        db.query(Payment)
        .filter(Payment.invoice_id == inv.id, Payment.paid_at.isnot(None))
        .order_by(Payment.paid_at.asc())
        .all()
    )
    paid_total = sum((_money(p.amount) for p in payments), Decimal("0").quantize(_CENTS))
    balance = _money(inv.total) - paid_total
    status_key = _status_key(db, inv.status_id)

    company = _tenant_name(db, tenant_id)
    bill_to = _bill_to_name(db, tenant_id, inv.bill_to_type, inv.bill_to_id) or inv.bill_to_id

    line_rows = [
        {
            "description": ln.description or "—",
            "qty": str(ln.qty),
            "unitPrice": _fmt_money(ln.unit_price, currency),
            "taxLabel": _tax_label(_money(ln.tax_rate)),
            "amount": _fmt_money(ln.amount, currency),
        }
        for ln in lines
    ]
    payment_rows = [
        {
            "date": _fmt_date(p.paid_at),
            "method": p.method,
            "amount": _fmt_money(p.amount, currency),
        }
        for p in payments
    ]

    return {
        "companyName": company,
        "recipientName": bill_to,
        "buyerTin": inv.buyer_tin or "",
        "invoiceNumber": inv.invoice_number or "(draft)",
        "invoiceDate": _fmt_date(inv.issued_at or inv.created_at),
        "dueDate": _fmt_date(inv.due_date),
        "statusLabel": _status_label(db, inv.status_id),
        "subtotal": _fmt_money(inv.subtotal, currency),
        "tax": _fmt_money(inv.tax, currency),
        "total": _fmt_money(inv.total, currency),
        "amountPaid": _fmt_money(paid_total, currency),
        "balanceDue": _fmt_money(balance, currency),
        # Paid stamp surfaces only in Paid state (AC-07-18) — blank otherwise.
        "paidStamp": "PAID" if status_key == "paid" else "",
        "notes": inv.notes or "",
        "lineItems": line_rows,
        "payments": payment_rows,
    }


def render_invoice_pdf(db: Session, tenant_id: str, inv: Invoice) -> bytes:
    from app.template_engine.contexts import ensure_core_contexts
    from app.template_engine.renderer import render_document
    from app.services.template_service import TemplateService

    ensure_core_contexts()
    template = TemplateService(db).resolve_by_key("finance.invoice", tenant_id)
    if template is None:
        raise RuntimeError("Invoice template not seeded — run finance install.")
    facts = build_invoice_facts(db, tenant_id, inv)
    return render_document(db, template, tenant_id, facts, mode="send")


def render_credit_note_pdf(db: Session, tenant_id: str, refund, inv: Invoice) -> bytes:
    """Credit-note PDF (AC-07-40) — reuses the ``finance.invoice`` template +
    context. The facts are the originating invoice's, overridden with the credit-
    note number + the refunded amount as the document total (the refund lines'
    tickets are the line items)."""
    from app.template_engine.contexts import ensure_core_contexts
    from app.template_engine.renderer import render_document
    from app.services.template_service import TemplateService

    ensure_core_contexts()
    template = TemplateService(db).resolve_by_key("finance.invoice", tenant_id)
    if template is None:
        raise RuntimeError("Invoice template not seeded — run finance install.")
    currency = inv.currency or "USD"
    facts = build_invoice_facts(db, tenant_id, inv)
    refund_amount = _money(refund.amount)
    facts.update({
        "invoiceNumber": refund.credit_note_number or "(pending)",
        "invoiceDate": _fmt_date(refund.confirmed_at or refund.created_at),
        "statusLabel": "Credit Note",
        "total": _fmt_money(refund_amount, currency),
        "subtotal": _fmt_money(refund_amount, currency),
        "tax": _fmt_money(0, currency),
        "amountPaid": _fmt_money(refund_amount, currency),
        "balanceDue": _fmt_money(0, currency),
        "paidStamp": "REFUNDED",
        "notes": (refund.reason or "") or facts.get("notes", ""),
    })
    return render_document(db, template, tenant_id, facts, mode="send")


def _tenant_name(db: Session, tenant_id: str) -> str:
    from app.models.tenant import Tenant

    row = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    return (row.name if row else "") or ""


def _bill_to_name(db: Session, tenant_id: str, bill_to_type: str, bill_to_id: str) -> str:
    from app.module_platform import resolve_capability

    key = "client.resolve" if bill_to_type == "Client" else "profile.resolve"
    handler = resolve_capability(db, tenant_id, key, 1)
    if handler is None:
        return ""
    res = handler(db, tenant_id, {"id": bill_to_id})
    if not res:
        return ""
    return res.get("name") or res.get("fullName") or res.get("email") or ""
