"""CRM sales-order routes (sprint-4/07, Cluster F slice 2) — Resource CRUD with
nested lines, create-from-quotation, Confirm (assigns doc_number), status
transitions, "create invoice from SO" (cross-module via finance.create_invoice@1),
export. Gated crm_sales_orders.read / crm_sales_orders.manage."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.crm.schemas import (
    CreatedInvoiceOut,
    CreateInvoiceFromSoIn,
    ExportRequest,
    ListResponse,
    SalesOrderFromQuotationIn,
    SalesOrderIn,
    SalesOrderOut,
    SalesOrderPatch,
    TransitionIn,
)
from modules.crm.services import SalesOrderService

router = APIRouter()


@router.get("", response_model=ListResponse)
def list_sales_orders(
    search: Optional[str] = Query(None),
    trashed: bool = Query(False),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("desc"),
    client_id: Optional[str] = Query(None, alias="clientId"),
    current_user: User = Depends(require_permission("crm_sales_orders.read")),
    db: Session = Depends(get_db),
):
    rows, total = SalesOrderService(db).list(
        current_user.tenant_id, search=search, page=page, page_size=page_size,
        trashed=trashed, sort_by=sort_by, sort_dir=sort_dir, client_id=client_id,
    )
    return ListResponse(items=[SalesOrderOut.from_row(r) for r in rows], total=total, page=page, pageSize=page_size)


@router.post("/export", response_class=PlainTextResponse)
def export_sales_orders(
    body: ExportRequest,
    current_user: User = Depends(require_permission("crm_sales_orders.read")),
    db: Session = Depends(get_db),
):
    csv_text = SalesOrderService(db).export_csv(
        current_user.tenant_id, body.columns, ids=body.ids, search=body.search, trashed=body.trashed
    )
    return PlainTextResponse(csv_text, media_type="text/csv")


@router.post("", response_model=SalesOrderOut, status_code=201)
def create_sales_order(
    body: SalesOrderIn,
    current_user: User = Depends(require_permission("crm_sales_orders.manage")),
    db: Session = Depends(get_db),
):
    return SalesOrderOut.from_row(
        SalesOrderService(db).create(current_user.tenant_id, body.model_dump(), current_user)
    )


@router.post("/from-quotation", response_model=SalesOrderOut, status_code=201)
def create_from_quotation(
    body: SalesOrderFromQuotationIn,
    current_user: User = Depends(require_permission("crm_sales_orders.manage")),
    db: Session = Depends(get_db),
):
    return SalesOrderOut.from_row(
        SalesOrderService(db).create_from_quotation(current_user.tenant_id, body.quotationId, current_user)
    )


@router.get("/{sales_order_id}", response_model=SalesOrderOut)
def get_sales_order(
    sales_order_id: str,
    current_user: User = Depends(require_permission("crm_sales_orders.read")),
    db: Session = Depends(get_db),
):
    return SalesOrderOut.from_row(SalesOrderService(db).get(current_user.tenant_id, sales_order_id))


@router.patch("/{sales_order_id}", response_model=SalesOrderOut)
def update_sales_order(
    sales_order_id: str,
    body: SalesOrderPatch,
    current_user: User = Depends(require_permission("crm_sales_orders.manage")),
    db: Session = Depends(get_db),
):
    return SalesOrderOut.from_row(
        SalesOrderService(db).update(current_user.tenant_id, sales_order_id, body.model_dump(exclude_unset=True))
    )


@router.delete("/{sales_order_id}", status_code=204)
def delete_sales_order(
    sales_order_id: str,
    current_user: User = Depends(require_permission("crm_sales_orders.manage")),
    db: Session = Depends(get_db),
):
    SalesOrderService(db).delete(current_user.tenant_id, sales_order_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{sales_order_id}/transition", response_model=SalesOrderOut)
def transition_sales_order(
    sales_order_id: str,
    body: TransitionIn,
    current_user: User = Depends(require_permission("crm_sales_orders.manage")),
    db: Session = Depends(get_db),
):
    return SalesOrderOut.from_row(
        SalesOrderService(db).transition(current_user.tenant_id, sales_order_id, body.toStatusId, current_user)
    )


@router.post("/{sales_order_id}/create-invoice", response_model=CreatedInvoiceOut, status_code=201)
def create_invoice_from_so(
    sales_order_id: str,
    body: CreateInvoiceFromSoIn,
    current_user: User = Depends(require_permission("crm_sales_orders.manage")),
    db: Session = Depends(get_db),
):
    result = SalesOrderService(db).create_invoice_from_so(
        current_user.tenant_id,
        sales_order_id,
        [s.model_dump() for s in body.selections],
        current_user,
    )
    return CreatedInvoiceOut(**result)
