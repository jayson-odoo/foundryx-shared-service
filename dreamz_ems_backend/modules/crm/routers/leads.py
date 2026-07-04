"""CRM leads routes (sprint-4/08) — opportunity Resource CRUD + status
transitions + export + Won→create-event (repeatable, via EMS capability) + a
cross-module Events list. Gated crm_leads.read / crm_leads.manage."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.crm.schemas import (
    ExportRequest,
    LeadCreateEventIn,
    LeadEventOut,
    LeadIn,
    LeadOut,
    LeadPatch,
    ListResponse,
    TransitionIn,
)
from modules.crm.services import LeadService

router = APIRouter()


@router.get("", response_model=ListResponse)
def list_leads(
    search: Optional[str] = Query(None),
    trashed: bool = Query(False),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("desc"),
    client_id: Optional[str] = Query(None, alias="clientId"),
    current_user: User = Depends(require_permission("crm_leads.read")),
    db: Session = Depends(get_db),
):
    rows, total = LeadService(db).list(
        current_user.tenant_id, search=search, page=page, page_size=page_size,
        trashed=trashed, sort_by=sort_by, sort_dir=sort_dir, client_id=client_id,
    )
    return ListResponse(items=[LeadOut.model_validate(r) for r in rows], total=total, page=page, pageSize=page_size)


@router.post("/export", response_class=PlainTextResponse)
def export_leads(
    body: ExportRequest,
    current_user: User = Depends(require_permission("crm_leads.read")),
    db: Session = Depends(get_db),
):
    csv_text = LeadService(db).export_csv(
        current_user.tenant_id, body.columns, ids=body.ids, search=body.search, trashed=body.trashed
    )
    return PlainTextResponse(csv_text, media_type="text/csv")


@router.post("", response_model=LeadOut, status_code=201)
def create_lead(
    body: LeadIn,
    current_user: User = Depends(require_permission("crm_leads.manage")),
    db: Session = Depends(get_db),
):
    return LeadOut.model_validate(LeadService(db).create(current_user.tenant_id, body.model_dump()))


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: str,
    current_user: User = Depends(require_permission("crm_leads.read")),
    db: Session = Depends(get_db),
):
    return LeadOut.model_validate(LeadService(db).get(current_user.tenant_id, lead_id))


@router.get("/{lead_id}/events", response_model=list[LeadEventOut])
def lead_events(
    lead_id: str,
    current_user: User = Depends(require_permission("crm_leads.read")),
    db: Session = Depends(get_db),
):
    return [LeadEventOut(**e) for e in LeadService(db).list_events(current_user.tenant_id, lead_id)]


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: str,
    body: LeadPatch,
    current_user: User = Depends(require_permission("crm_leads.manage")),
    db: Session = Depends(get_db),
):
    return LeadOut.model_validate(
        LeadService(db).update(current_user.tenant_id, lead_id, body.model_dump(exclude_unset=True))
    )


@router.delete("/{lead_id}", status_code=204)
def delete_lead(
    lead_id: str,
    current_user: User = Depends(require_permission("crm_leads.manage")),
    db: Session = Depends(get_db),
):
    LeadService(db).delete(current_user.tenant_id, lead_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{lead_id}/transition", response_model=LeadOut)
def transition_lead(
    lead_id: str,
    body: TransitionIn,
    current_user: User = Depends(require_permission("crm_leads.manage")),
    db: Session = Depends(get_db),
):
    return LeadOut.model_validate(
        LeadService(db).transition(current_user.tenant_id, lead_id, body.toStatusId, current_user)
    )


@router.post("/{lead_id}/create-event", response_model=LeadEventOut)
def create_event_from_lead(
    lead_id: str,
    body: LeadCreateEventIn,
    current_user: User = Depends(require_permission("crm_leads.manage")),
    db: Session = Depends(get_db),
):
    return LeadEventOut(**LeadService(db).create_event(current_user.tenant_id, lead_id, body.model_dump(), current_user))
