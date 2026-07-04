"""CRM clients routes (sprint-4/08) — B2B account Resource CRUD + status
transitions + export + options picker (Lead quick-create). Gated crm_clients.read
/ crm_clients.manage; the loader wraps the router in require_module('crm')."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.crm.schemas import (
    ClientIn,
    ClientOut,
    ClientPatch,
    ExportRequest,
    ListResponse,
    TransitionIn,
)
from modules.crm.services import ClientService

router = APIRouter()


@router.get("", response_model=ListResponse)
def list_clients(
    search: Optional[str] = Query(None),
    trashed: bool = Query(False),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("asc"),
    current_user: User = Depends(require_permission("crm_clients.read")),
    db: Session = Depends(get_db),
):
    rows, total = ClientService(db).list(
        current_user.tenant_id, search=search, page=page, page_size=page_size,
        trashed=trashed, sort_by=sort_by, sort_dir=sort_dir,
    )
    return ListResponse(items=[ClientOut.model_validate(r) for r in rows], total=total, page=page, pageSize=page_size)


@router.get("/options", response_model=list[ClientOut])
def client_options(
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_permission("crm_clients.read")),
    db: Session = Depends(get_db),
):
    return [ClientOut.model_validate(r) for r in ClientService(db).options(current_user.tenant_id, search=search)]


@router.post("/export", response_class=PlainTextResponse)
def export_clients(
    body: ExportRequest,
    current_user: User = Depends(require_permission("crm_clients.read")),
    db: Session = Depends(get_db),
):
    csv_text = ClientService(db).export_csv(
        current_user.tenant_id, body.columns, ids=body.ids, search=body.search, trashed=body.trashed
    )
    return PlainTextResponse(csv_text, media_type="text/csv")


@router.post("", response_model=ClientOut, status_code=201)
def create_client(
    body: ClientIn,
    current_user: User = Depends(require_permission("crm_clients.manage")),
    db: Session = Depends(get_db),
):
    return ClientOut.model_validate(ClientService(db).create(current_user.tenant_id, body.model_dump()))


@router.get("/{client_id}", response_model=ClientOut)
def get_client(
    client_id: str,
    current_user: User = Depends(require_permission("crm_clients.read")),
    db: Session = Depends(get_db),
):
    return ClientOut.model_validate(ClientService(db).get(current_user.tenant_id, client_id))


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(
    client_id: str,
    body: ClientPatch,
    current_user: User = Depends(require_permission("crm_clients.manage")),
    db: Session = Depends(get_db),
):
    return ClientOut.model_validate(
        ClientService(db).update(current_user.tenant_id, client_id, body.model_dump(exclude_unset=True))
    )


@router.delete("/{client_id}", status_code=204)
def delete_client(
    client_id: str,
    current_user: User = Depends(require_permission("crm_clients.manage")),
    db: Session = Depends(get_db),
):
    ClientService(db).delete(current_user.tenant_id, client_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{client_id}/transition", response_model=ClientOut)
def transition_client(
    client_id: str,
    body: TransitionIn,
    current_user: User = Depends(require_permission("crm_clients.manage")),
    db: Session = Depends(get_db),
):
    return ClientOut.model_validate(
        ClientService(db).transition(current_user.tenant_id, client_id, body.toStatusId, current_user)
    )
