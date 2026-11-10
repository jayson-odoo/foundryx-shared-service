"""Contact-tag registry routes (plan 25 S1) - HTTP + Pydantic only. Mounted
under `/omnichannel/workspaces/{ws_id}/contact-tags` (manifest router entry,
prefix `/omnichannel/workspaces`). Reading is gated `conversations.read` OR
`contacts.read`; writing is gated `contact_tags.manage` (AC-CDM-28)."""
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User

from ..models import ContactTag
from ..rbac import require_any_permission
from ..schemas import ContactTagCreate, ContactTagItem, ContactTagUpdate
from ..services.contact_tag_service import (
    ContactTagService,
    TagNotFound,
    TagValidationError,
)
from ..services.workspace_service import WorkspaceService

router = APIRouter()


def _to_item(row: ContactTag, counts: Dict[str, int]) -> ContactTagItem:
    return ContactTagItem(
        id=row.id,
        workspaceId=row.workspace_id,
        name=row.name,
        emoji=row.emoji,
        color=row.color,
        description=row.description,
        contactsCount=counts.get(row.id, 0),
        createdAt=row.created_at,
    )


@router.get("/{ws_id}/contact-tags", response_model=List[ContactTagItem])
def list_contact_tags(
    ws_id: str,
    current_user: User = Depends(require_any_permission("conversations.read", "contacts.read")),
    db: Session = Depends(get_db),
) -> List[ContactTagItem]:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    svc = ContactTagService(db)
    rows = svc.list(ws_id, current_user.tenant_id)
    counts = svc.contacts_counts(ws_id, current_user.tenant_id)
    return [_to_item(r, counts) for r in rows]


@router.post(
    "/{ws_id}/contact-tags", response_model=ContactTagItem, status_code=status.HTTP_201_CREATED
)
def create_contact_tag(
    ws_id: str,
    body: ContactTagCreate,
    current_user: User = Depends(require_any_permission("contact_tags.manage")),
    db: Session = Depends(get_db),
) -> ContactTagItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        row = ContactTagService(db).create(ws_id, current_user.tenant_id, body)
    except TagValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": {exc.field: exc.message}})
    return _to_item(row, {})


@router.patch("/{ws_id}/contact-tags/{tag_id}", response_model=ContactTagItem)
def update_contact_tag(
    ws_id: str,
    tag_id: str,
    body: ContactTagUpdate,
    current_user: User = Depends(require_any_permission("contact_tags.manage")),
    db: Session = Depends(get_db),
) -> ContactTagItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    svc = ContactTagService(db)
    try:
        row = svc.update(tag_id, ws_id, current_user.tenant_id, body)
    except TagNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found.")
    except TagValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": {exc.field: exc.message}})
    counts = svc.contacts_counts(ws_id, current_user.tenant_id)
    return _to_item(row, counts)


@router.delete("/{ws_id}/contact-tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact_tag(
    ws_id: str,
    tag_id: str,
    current_user: User = Depends(require_any_permission("contact_tags.manage")),
    db: Session = Depends(get_db),
) -> Response:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        ContactTagService(db).delete(tag_id, ws_id, current_user.tenant_id)
    except TagNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
