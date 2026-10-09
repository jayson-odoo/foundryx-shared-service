"""Saved inbox-view routes (plan 27 A3, S2) - HTTP + Pydantic only. Mounted
under `/omnichannel/workspaces/{ws_id}/inbox-views` (manifest router entry,
prefix `/omnichannel/workspaces`, sibling of `contact_tags`/`close_reasons`).

Permission split (AC-IVE-19, D-A3-11): every route needs at least
`conversations.read`; a user may create/edit/delete their OWN, non-shared
view with just that. Creating a SHARED view, or editing/deleting a SHARED
view or someone else's, additionally needs `inbox_views.manage` - checked
HERE (the router is the only layer that has both the caller's identity and
permission set at once), never in the service.
"""
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import effective_permission_keys
from app.models.user import User

from ..models import InboxView
from ..rbac import require_any_permission
from ..schemas import InboxViewCreate, InboxViewItem, InboxViewUpdate
from ..services.inbox_view_service import (
    InboxViewNotFound,
    InboxViewService,
    InboxViewValidationError,
)
from ..services.workspace_service import WorkspaceService

router = APIRouter()


def _to_item(row: InboxView, names: Dict[str, str]) -> InboxViewItem:
    return InboxViewItem(
        id=row.id,
        workspaceId=row.workspace_id,
        name=row.name,
        ownerUserId=row.owner_user_id,
        ownerName=names.get(row.owner_user_id),
        isShared=row.is_shared,
        filter=row.filter_json or {},
        sortOrder=row.sort_order,
        createdAt=row.created_at,
    )


def _requires_manage(row: InboxView, current_user: User, *, wants_shared: bool = False) -> bool:
    return bool(row.is_shared or wants_shared or row.owner_user_id != current_user.id)


@router.get("/{ws_id}/inbox-views", response_model=List[InboxViewItem])
def list_inbox_views(
    ws_id: str,
    current_user: User = Depends(require_any_permission("conversations.read")),
    db: Session = Depends(get_db),
) -> List[InboxViewItem]:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    svc = InboxViewService(db)
    rows = svc.list(ws_id, current_user.tenant_id, current_user.id)
    names = svc.owner_names(rows, current_user.tenant_id)
    return [_to_item(r, names) for r in rows]


@router.post(
    "/{ws_id}/inbox-views", response_model=InboxViewItem, status_code=status.HTTP_201_CREATED
)
def create_inbox_view(
    ws_id: str,
    body: InboxViewCreate,
    current_user: User = Depends(require_any_permission("conversations.read")),
    db: Session = Depends(get_db),
) -> InboxViewItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    if body.isShared and "inbox_views.manage" not in effective_permission_keys(current_user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Missing permission: inbox_views.manage"
        )
    svc = InboxViewService(db)
    try:
        row = svc.create(ws_id, current_user.tenant_id, current_user.id, body)
    except InboxViewValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": {exc.field: exc.message}}
        )
    names = svc.owner_names([row], current_user.tenant_id)
    return _to_item(row, names)


@router.patch("/{ws_id}/inbox-views/{view_id}", response_model=InboxViewItem)
def update_inbox_view(
    ws_id: str,
    view_id: str,
    body: InboxViewUpdate,
    current_user: User = Depends(require_any_permission("conversations.read")),
    db: Session = Depends(get_db),
) -> InboxViewItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    svc = InboxViewService(db)
    try:
        row = svc.get(view_id, ws_id, current_user.tenant_id)
    except InboxViewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "View not found.")
    wants_shared = bool(body.isShared) if "isShared" in body.model_fields_set else False
    if (
        _requires_manage(row, current_user, wants_shared=wants_shared)
        and "inbox_views.manage" not in effective_permission_keys(current_user)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Missing permission: inbox_views.manage"
        )
    try:
        row = svc.update(view_id, ws_id, current_user.tenant_id, body)
    except InboxViewValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": {exc.field: exc.message}}
        )
    names = svc.owner_names([row], current_user.tenant_id)
    return _to_item(row, names)


@router.delete("/{ws_id}/inbox-views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inbox_view(
    ws_id: str,
    view_id: str,
    current_user: User = Depends(require_any_permission("conversations.read")),
    db: Session = Depends(get_db),
) -> Response:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    svc = InboxViewService(db)
    try:
        row = svc.get(view_id, ws_id, current_user.tenant_id)
    except InboxViewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "View not found.")
    if (
        _requires_manage(row, current_user)
        and "inbox_views.manage" not in effective_permission_keys(current_user)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Missing permission: inbox_views.manage"
        )
    svc.delete(view_id, ws_id, current_user.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
