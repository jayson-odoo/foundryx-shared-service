"""Contact-field registry routes (plan 25 S1) - HTTP + Pydantic only. Mounted
under `/omnichannel/workspaces/{ws_id}/contact-fields` (manifest router entry,
prefix `/omnichannel/workspaces`). Reading is gated `conversations.read` OR
`contacts.read`; writing is gated `contact_fields.manage` (AC-CDM-28)."""
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User

from ..models import ContactField
from ..rbac import require_any_permission
from ..schemas import ContactFieldCreate, ContactFieldItem, ContactFieldUpdate
from ..services.contact_field_service import (
    ContactFieldService,
    FieldNotFound,
    FieldValidationError,
)
from ..services.workspace_service import WorkspaceService

router = APIRouter()


def _to_item(row: ContactField, counts: Dict[str, int]) -> ContactFieldItem:
    return ContactFieldItem(
        id=row.id,
        workspaceId=row.workspace_id,
        key=row.key,
        label=row.label,
        description=row.description,
        type=row.type,
        options=row.options_json,
        visibility=row.visibility,
        sortOrder=row.sort_order,
        valuesCount=counts.get(row.key, 0),
        createdAt=row.created_at,
    )


@router.get("/{ws_id}/contact-fields", response_model=List[ContactFieldItem])
def list_contact_fields(
    ws_id: str,
    current_user: User = Depends(require_any_permission("conversations.read", "contacts.read")),
    db: Session = Depends(get_db),
) -> List[ContactFieldItem]:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    svc = ContactFieldService(db)
    rows = svc.list(ws_id, current_user.tenant_id)
    counts = svc.value_counts(ws_id, current_user.tenant_id)
    return [_to_item(r, counts) for r in rows]


@router.post(
    "/{ws_id}/contact-fields", response_model=ContactFieldItem, status_code=status.HTTP_201_CREATED
)
def create_contact_field(
    ws_id: str,
    body: ContactFieldCreate,
    current_user: User = Depends(require_any_permission("contact_fields.manage")),
    db: Session = Depends(get_db),
) -> ContactFieldItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        row = ContactFieldService(db).create(ws_id, current_user.tenant_id, body)
    except FieldValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})
    return _to_item(row, {})


@router.patch("/{ws_id}/contact-fields/{field_id}", response_model=ContactFieldItem)
def update_contact_field(
    ws_id: str,
    field_id: str,
    body: ContactFieldUpdate,
    current_user: User = Depends(require_any_permission("contact_fields.manage")),
    db: Session = Depends(get_db),
) -> ContactFieldItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    svc = ContactFieldService(db)
    try:
        row = svc.update(field_id, ws_id, current_user.tenant_id, body)
    except FieldNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field not found.")
    except FieldValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})
    counts = svc.value_counts(ws_id, current_user.tenant_id)
    return _to_item(row, counts)


@router.delete("/{ws_id}/contact-fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact_field(
    ws_id: str,
    field_id: str,
    current_user: User = Depends(require_any_permission("contact_fields.manage")),
    db: Session = Depends(get_db),
) -> Response:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        ContactFieldService(db).delete(field_id, ws_id, current_user.tenant_id)
    except FieldNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
