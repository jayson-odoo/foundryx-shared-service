"""Close-reason registry routes (plan 27 A3, S2) - HTTP + Pydantic only.
Mounted under `/omnichannel/workspaces/{ws_id}/close-reasons` (manifest
router entry, prefix `/omnichannel/workspaces`, sibling of `contact_tags`).
Reading is gated `conversations.read`; writing is gated `close_reasons.manage`
(AC-IVE-25)."""
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User

from ..models import CloseReason
from ..rbac import require_any_permission
from ..schemas import CloseReasonCreate, CloseReasonItem, CloseReasonUpdate
from ..services.close_reason_service import (
    CloseReasonInUse,
    CloseReasonNotFound,
    CloseReasonService,
    CloseReasonValidationError,
)
from ..services.workspace_service import WorkspaceService

router = APIRouter()


def _to_item(row: CloseReason, counts: Dict[str, int]) -> CloseReasonItem:
    return CloseReasonItem(
        id=row.id,
        workspaceId=row.workspace_id,
        name=row.name,
        sortOrder=row.sort_order,
        isActive=row.is_active,
        usesCount=counts.get(row.id, 0),
        createdAt=row.created_at,
    )


@router.get("/{ws_id}/close-reasons", response_model=List[CloseReasonItem])
def list_close_reasons(
    ws_id: str,
    current_user: User = Depends(require_any_permission("conversations.read")),
    db: Session = Depends(get_db),
) -> List[CloseReasonItem]:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    svc = CloseReasonService(db)
    rows = svc.list(ws_id, current_user.tenant_id)
    counts = svc.uses_counts(ws_id, current_user.tenant_id)
    return [_to_item(r, counts) for r in rows]


@router.post(
    "/{ws_id}/close-reasons", response_model=CloseReasonItem, status_code=status.HTTP_201_CREATED
)
def create_close_reason(
    ws_id: str,
    body: CloseReasonCreate,
    current_user: User = Depends(require_any_permission("close_reasons.manage")),
    db: Session = Depends(get_db),
) -> CloseReasonItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        row = CloseReasonService(db).create(ws_id, current_user.tenant_id, body)
    except CloseReasonValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": {exc.field: exc.message}}
        )
    return _to_item(row, {})


@router.patch("/{ws_id}/close-reasons/{reason_id}", response_model=CloseReasonItem)
def update_close_reason(
    ws_id: str,
    reason_id: str,
    body: CloseReasonUpdate,
    current_user: User = Depends(require_any_permission("close_reasons.manage")),
    db: Session = Depends(get_db),
) -> CloseReasonItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    svc = CloseReasonService(db)
    try:
        row = svc.update(reason_id, ws_id, current_user.tenant_id, body)
    except CloseReasonNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Close reason not found.")
    except CloseReasonValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": {exc.field: exc.message}}
        )
    counts = svc.uses_counts(ws_id, current_user.tenant_id)
    return _to_item(row, counts)


@router.delete("/{ws_id}/close-reasons/{reason_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_close_reason(
    ws_id: str,
    reason_id: str,
    current_user: User = Depends(require_any_permission("close_reasons.manage")),
    db: Session = Depends(get_db),
) -> Response:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        CloseReasonService(db).delete(reason_id, ws_id, current_user.tenant_id)
    except CloseReasonNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Close reason not found.")
    except CloseReasonInUse:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "close_reason_in_use", "message": "This close reason is used by past events."},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
