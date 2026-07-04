"""CRM quotations routes (sprint-4/08) — B2B quote Resource CRUD with nested
lines, revise (lineage), status transitions, export. Gated crm_quotations.read /
crm_quotations.manage; document attach rides core /documents/file-links."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.crm.schemas import (
    ExportRequest,
    ListResponse,
    QuotationIn,
    QuotationOut,
    QuotationPatch,
    TransitionIn,
)
from modules.crm.services import QuotationService

router = APIRouter()


@router.get("", response_model=ListResponse)
def list_quotations(
    search: Optional[str] = Query(None),
    trashed: bool = Query(False),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("desc"),
    client_id: Optional[str] = Query(None, alias="clientId"),
    current_user: User = Depends(require_permission("crm_quotations.read")),
    db: Session = Depends(get_db),
):
    rows, total = QuotationService(db).list(
        current_user.tenant_id, search=search, page=page, page_size=page_size,
        trashed=trashed, sort_by=sort_by, sort_dir=sort_dir, client_id=client_id,
    )
    return ListResponse(items=[QuotationOut.from_row(r) for r in rows], total=total, page=page, pageSize=page_size)


@router.get("/{quotation_id}/revisions", response_model=list[QuotationOut])
def quotation_revisions(
    quotation_id: str,
    current_user: User = Depends(require_permission("crm_quotations.read")),
    db: Session = Depends(get_db),
):
    rows = QuotationService(db).revisions(current_user.tenant_id, quotation_id)
    return [QuotationOut.from_row(r) for r in rows]


@router.post("/export", response_class=PlainTextResponse)
def export_quotations(
    body: ExportRequest,
    current_user: User = Depends(require_permission("crm_quotations.read")),
    db: Session = Depends(get_db),
):
    csv_text = QuotationService(db).export_csv(
        current_user.tenant_id, body.columns, ids=body.ids, search=body.search, trashed=body.trashed
    )
    return PlainTextResponse(csv_text, media_type="text/csv")


@router.post("", response_model=QuotationOut, status_code=201)
def create_quotation(
    body: QuotationIn,
    current_user: User = Depends(require_permission("crm_quotations.manage")),
    db: Session = Depends(get_db),
):
    return QuotationOut.from_row(QuotationService(db).create(current_user.tenant_id, body.model_dump(), current_user))


@router.get("/{quotation_id}", response_model=QuotationOut)
def get_quotation(
    quotation_id: str,
    current_user: User = Depends(require_permission("crm_quotations.read")),
    db: Session = Depends(get_db),
):
    return QuotationOut.from_row(QuotationService(db).get(current_user.tenant_id, quotation_id))


@router.patch("/{quotation_id}", response_model=QuotationOut)
def update_quotation(
    quotation_id: str,
    body: QuotationPatch,
    current_user: User = Depends(require_permission("crm_quotations.manage")),
    db: Session = Depends(get_db),
):
    return QuotationOut.from_row(
        QuotationService(db).update(current_user.tenant_id, quotation_id, body.model_dump(exclude_unset=True))
    )


@router.delete("/{quotation_id}", status_code=204)
def delete_quotation(
    quotation_id: str,
    current_user: User = Depends(require_permission("crm_quotations.manage")),
    db: Session = Depends(get_db),
):
    QuotationService(db).delete(current_user.tenant_id, quotation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{quotation_id}/transition", response_model=QuotationOut)
def transition_quotation(
    quotation_id: str,
    body: TransitionIn,
    current_user: User = Depends(require_permission("crm_quotations.manage")),
    db: Session = Depends(get_db),
):
    return QuotationOut.from_row(
        QuotationService(db).transition(current_user.tenant_id, quotation_id, body.toStatusId, current_user)
    )


@router.post("/{quotation_id}/revise", response_model=QuotationOut)
def revise_quotation(
    quotation_id: str,
    current_user: User = Depends(require_permission("crm_quotations.manage")),
    db: Session = Depends(get_db),
):
    return QuotationOut.from_row(QuotationService(db).revise(current_user.tenant_id, quotation_id, current_user))
