"""Finance invoice routes (sprint-4/05; Cluster F slice 1) — tenant-facing
invoice list/detail + status transitions + update (freeze-after-Issue) + manual
payments + PDF download. Gated invoices.read / invoices.manage; the loader wraps
the router in require_module('finance'). Router = HTTP/Pydantic only."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.finance.schemas import (
    CheckoutOut,
    InvoiceOut,
    InvoiceUpdateIn,
    ListResponse,
    RecordPaymentIn,
    RefundableTicketOut,
    RefundIn,
    RefundOut,
    TransitionIn,
)
from modules.finance.services import InvoiceService

router = APIRouter()


@router.get("", response_model=ListResponse)
def list_invoices(
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    project_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_permission("invoices.read")),
    db: Session = Depends(get_db),
):
    rows, total = InvoiceService(db).list(
        current_user.tenant_id, page=page, page_size=page_size, project_id=project_id, search=search
    )
    return ListResponse(
        items=[InvoiceOut.model_validate(r) for r in rows], total=total, page=page, pageSize=page_size
    )


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: str,
    current_user: User = Depends(require_permission("invoices.read")),
    db: Session = Depends(get_db),
):
    return InvoiceOut.model_validate(InvoiceService(db).get(current_user.tenant_id, invoice_id))


@router.patch("/{invoice_id}", response_model=InvoiceOut)
def update_invoice(
    invoice_id: str,
    body: InvoiceUpdateIn,
    current_user: User = Depends(require_permission("invoices.manage")),
    db: Session = Depends(get_db),
):
    payload = body.model_dump(exclude_unset=True)
    return InvoiceOut.model_validate(
        InvoiceService(db).update(current_user.tenant_id, invoice_id, payload, current_user)
    )


@router.post("/{invoice_id}/transition", response_model=InvoiceOut)
def transition_invoice(
    invoice_id: str,
    body: TransitionIn,
    current_user: User = Depends(require_permission("invoices.manage")),
    db: Session = Depends(get_db),
):
    return InvoiceOut.model_validate(
        InvoiceService(db).transition(current_user.tenant_id, invoice_id, body.toStatusId, current_user)
    )


@router.post("/{invoice_id}/payments", response_model=InvoiceOut)
def record_payment(
    invoice_id: str,
    body: RecordPaymentIn,
    current_user: User = Depends(require_permission("invoices.manage")),
    db: Session = Depends(get_db),
):
    return InvoiceOut.model_validate(
        InvoiceService(db).record_payment(
            current_user.tenant_id, invoice_id, body.model_dump(), current_user
        )
    )


@router.post("/{invoice_id}/checkout", response_model=CheckoutOut)
def start_checkout(
    invoice_id: str,
    current_user: User = Depends(require_permission("invoices.manage")),
    db: Session = Depends(get_db),
):
    """Open a gateway checkout for the invoice's outstanding balance (AC-07-27):
    creates a Pending payment + returns the buyer redirect URL."""
    from modules.finance.payment_service import PaymentService

    res = PaymentService(db).start_checkout(current_user.tenant_id, invoice_id, current_user)
    return CheckoutOut(redirectUrl=res["redirectUrl"], paymentId=res["paymentId"])


# ── refunds (Cluster F slice 4, AC-07-37..43) ───────────────────────────────
@router.get("/{invoice_id}/refundable-tickets", response_model=list[RefundableTicketOut])
def list_refundable_tickets(
    invoice_id: str,
    current_user: User = Depends(require_permission("invoices.manage")),
    db: Session = Depends(get_db),
):
    """The invoice's tickets + a refundable flag (AC-07-37 picker source)."""
    from modules.finance.refund_service import RefundService

    rows = RefundService(db)._invoice_tickets(current_user.tenant_id, invoice_id)
    return [RefundableTicketOut.model_validate(r) for r in rows]


@router.get("/{invoice_id}/refunds", response_model=list[RefundOut])
def list_refunds(
    invoice_id: str,
    current_user: User = Depends(require_permission("invoices.read")),
    db: Session = Depends(get_db),
):
    from modules.finance.refund_service import RefundService

    rows = RefundService(db).list_for_invoice(current_user.tenant_id, invoice_id)
    return [RefundOut.model_validate(r) for r in rows]


@router.post("/{invoice_id}/refunds", response_model=RefundOut)
def create_refund(
    invoice_id: str,
    body: RefundIn,
    current_user: User = Depends(require_permission("invoices.manage")),
    db: Session = Depends(get_db),
):
    """Refund selected tickets (AC-07-37/38/39): gateway path or manual record,
    over-refund guarded, numbered credit note, tickets Void + capacity released,
    invoice re-derives, settlement adjustment if remitted."""
    from modules.finance.refund_service import RefundService

    res = RefundService(db).create(current_user.tenant_id, invoice_id, body.model_dump(), current_user)
    return RefundOut.model_validate(res)


@router.get("/refunds/{refund_id}/credit-note")
async def download_credit_note_pdf(
    refund_id: str,
    current_user: User = Depends(require_permission("invoices.read")),
    db: Session = Depends(get_db),
):
    """Credit-note PDF (AC-07-40) — reuses the invoice template/context."""
    from modules.finance.refund_service import RefundService

    pdf = await run_in_threadpool(
        RefundService(db).render_credit_note_pdf, current_user.tenant_id, refund_id
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="credit-note-{refund_id}.pdf"',
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=0, no-store",
        },
    )


@router.get("/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: str,
    current_user: User = Depends(require_permission("invoices.read")),
    db: Session = Depends(get_db),
):
    svc = InvoiceService(db)
    # WeasyPrint is CPU-bound + sync — offload off the event loop (mirrors the
    # core template-preview PDF route).
    pdf = await run_in_threadpool(svc.render_pdf, current_user.tenant_id, invoice_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="invoice-{invoice_id}.pdf"',
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=0, no-store",
        },
    )
