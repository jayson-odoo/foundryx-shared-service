"""Contact-segment routes (plan 26 S1, D-A2-3). Mounted under
`/omnichannel/workspaces/{ws_id}/contact-segments` (manifest router entry,
prefix `/omnichannel/workspaces`). Reading is gated `contacts.read`; writing
is gated `segments.manage` (AC-CTM-20/22)."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..models import ContactSegment
from ..schemas import ContactSegmentCreate, ContactSegmentItem, ContactSegmentUpdate
from ..services.contact_segment_service import (
    ContactSegmentService,
    SegmentNotFound,
    SegmentValidationError,
)
from ..services.workspace_service import WorkspaceService

router = APIRouter()


def _to_item(row: ContactSegment) -> ContactSegmentItem:
    return ContactSegmentItem(
        id=row.id,
        workspaceId=row.workspace_id,
        name=row.name,
        description=row.description,
        filter=row.filter_json,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


@router.get("/{ws_id}/contact-segments", response_model=List[ContactSegmentItem])
def list_contact_segments(
    ws_id: str,
    current_user: User = Depends(require_permission("contacts.read")),
    db: Session = Depends(get_db),
) -> List[ContactSegmentItem]:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    rows = ContactSegmentService(db).list(ws_id, current_user.tenant_id)
    return [_to_item(r) for r in rows]


@router.post(
    "/{ws_id}/contact-segments",
    response_model=ContactSegmentItem,
    status_code=status.HTTP_201_CREATED,
)
def create_contact_segment(
    ws_id: str,
    body: ContactSegmentCreate,
    current_user: User = Depends(require_permission("segments.manage")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> ContactSegmentItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        row = ContactSegmentService(db).create(
            ws_id, current_user.tenant_id, body, actor_user_id=actor_user_id
        )
    except SegmentValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})
    return _to_item(row)


@router.patch("/{ws_id}/contact-segments/{segment_id}", response_model=ContactSegmentItem)
def update_contact_segment(
    ws_id: str,
    segment_id: str,
    body: ContactSegmentUpdate,
    current_user: User = Depends(require_permission("segments.manage")),
    db: Session = Depends(get_db),
) -> ContactSegmentItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    svc = ContactSegmentService(db)
    try:
        row = svc.update(segment_id, ws_id, current_user.tenant_id, body)
    except SegmentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment not found.")
    except SegmentValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})
    return _to_item(row)


@router.delete("/{ws_id}/contact-segments/{segment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact_segment(
    ws_id: str,
    segment_id: str,
    current_user: User = Depends(require_permission("segments.manage")),
    db: Session = Depends(get_db),
) -> Response:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        ContactSegmentService(db).delete(segment_id, ws_id, current_user.tenant_id)
    except SegmentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
