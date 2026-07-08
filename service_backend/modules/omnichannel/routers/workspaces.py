"""Workspace routes — thin; gated by omnichannel `workspaces.*` permissions.
All tenant-scoped via the JWT user."""
import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User
from ..schemas import (
    AssignMembersRequest,
    ExportRequest,
    IdsRequest,
    MemberCandidateItem,
    QuickReplyCreate,
    QuickReplyItem,
    QuickReplyUpdate,
    WorkspaceCreate,
    WorkspaceItem,
    WorkspaceListResponse,
    WorkspaceMemberItem,
    WorkspaceNeighborResponse,
    WorkspaceUpdate,
)
from ..services.workspace_service import (
    DefaultWorkspaceProtected,
    WorkspaceNotFound,
    WorkspaceService,
)

router = APIRouter()


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    current_user: User = Depends(require_permission("workspaces.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: str = Query("active"),
) -> WorkspaceListResponse:
    items, total = WorkspaceService(db).list(
        current_user.tenant_id,
        page=page,
        page_size=page_size,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        status_view=status_view,
    )
    return WorkspaceListResponse(data=items, total=total, page=page)


@router.get("/at", response_model=WorkspaceNeighborResponse)
def workspace_at(
    current_user: User = Depends(require_permission("workspaces.read")),
    db: Session = Depends(get_db),
    index: int = Query(..., ge=0),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: str = Query("active"),
) -> WorkspaceNeighborResponse:
    ws, total = WorkspaceService(db).get_at(
        index, current_user.tenant_id, status_view=status_view,
        search=search, sort_by=sort_by, sort_dir=sort_dir,
    )
    return WorkspaceNeighborResponse(workspace=ws, total=total)


@router.post("/trash", status_code=status.HTTP_204_NO_CONTENT)
def trash_workspaces(
    body: IdsRequest,
    current_user: User = Depends(require_permission("workspaces.manage")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        WorkspaceService(db).trash(body.ids, current_user.tenant_id)
    except DefaultWorkspaceProtected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The default workspace can't be trashed.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_workspaces(
    body: IdsRequest,
    current_user: User = Depends(require_permission("workspaces.manage")),
    db: Session = Depends(get_db),
) -> Response:
    WorkspaceService(db).restore(body.ids, current_user.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/export", response_class=PlainTextResponse)
def export_workspaces(
    body: ExportRequest,
    current_user: User = Depends(require_permission("workspaces.read")),
    db: Session = Depends(get_db),
) -> str:
    items, _ = WorkspaceService(db).list(
        current_user.tenant_id, page=0, page_size=10_000,
        search=body.search, sort_by=body.sortBy, sort_dir=body.sortDir or "asc",
        status_view=body.statusView or "active",
    )
    if body.ids:
        keep = set(body.ids)
        items = [w for w in items if w.id in keep]
    col_value = {
        "name": lambda w: w.name,
        "status": lambda w: w.status,
        "channels": lambda w: str(w.channelCount),
        "members": lambda w: str(w.memberCount),
        "created": lambda w: w.createdAt.isoformat(),
    }
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(body.columns)
    for w in items:
        writer.writerow([col_value.get(c, lambda _w: "")(w) for c in body.columns])
    return buf.getvalue()


@router.post("", response_model=WorkspaceItem, status_code=status.HTTP_201_CREATED)
def create_workspace(
    body: WorkspaceCreate,
    current_user: User = Depends(require_permission("workspaces.manage")),
    db: Session = Depends(get_db),
) -> WorkspaceItem:
    return WorkspaceService(db).create(body, current_user.tenant_id)


@router.get("/{ws_id}", response_model=WorkspaceItem)
def get_workspace(
    ws_id: str,
    current_user: User = Depends(require_permission("workspaces.read")),
    db: Session = Depends(get_db),
) -> WorkspaceItem:
    try:
        return WorkspaceService(db).get(ws_id, current_user.tenant_id)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")


@router.patch("/{ws_id}", response_model=WorkspaceItem)
def update_workspace(
    ws_id: str,
    body: WorkspaceUpdate,
    current_user: User = Depends(require_permission("workspaces.manage")),
    db: Session = Depends(get_db),
) -> WorkspaceItem:
    try:
        return WorkspaceService(db).update(ws_id, body, current_user.tenant_id)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")


@router.get("/{ws_id}/members", response_model=list[WorkspaceMemberItem])
def list_members(
    ws_id: str,
    current_user: User = Depends(require_permission("workspaces.read")),
    db: Session = Depends(get_db),
    search: Optional[str] = None,
) -> list[WorkspaceMemberItem]:
    try:
        return WorkspaceService(db).members(ws_id, current_user.tenant_id, search)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")


@router.get("/{ws_id}/assignable", response_model=list[MemberCandidateItem])
def list_assignable(
    ws_id: str,
    current_user: User = Depends(require_permission("workspaces.manage")),
    db: Session = Depends(get_db),
    search: Optional[str] = None,
) -> list[MemberCandidateItem]:
    try:
        return WorkspaceService(db).list_assignable(ws_id, current_user.tenant_id, search)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")


@router.post("/{ws_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def assign_members(
    ws_id: str,
    body: AssignMembersRequest,
    current_user: User = Depends(require_permission("workspaces.manage")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        WorkspaceService(db).assign_members(ws_id, body.userIds, current_user.tenant_id)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{ws_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    ws_id: str,
    user_id: str,
    current_user: User = Depends(require_permission("workspaces.manage")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        WorkspaceService(db).remove_member(ws_id, user_id, current_user.tenant_id)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{ws_id}/quick-replies")
def list_quick_replies(
    ws_id: str,
    current_user: User = Depends(require_permission("conversations.read")),
    db: Session = Depends(get_db),
):
    """Canned responses for the composer's ★ picker."""
    from ..services.message_service import MessageService

    return MessageService(db).list_quick_replies(ws_id, current_user.tenant_id)


@router.post(
    "/{ws_id}/quick-replies",
    response_model=QuickReplyItem,
    status_code=status.HTTP_201_CREATED,
)
def create_quick_reply(
    ws_id: str,
    body: QuickReplyCreate,
    current_user: User = Depends(require_permission("workspaces.manage")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> QuickReplyItem:
    from ..services.message_service import MessageService, ShortcutConflict

    try:
        return MessageService(db).create_quick_reply(
            ws_id, current_user.tenant_id, body, actor_user_id=actor_user_id
        )
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    except ShortcutConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "That shortcut is already in use.")


@router.patch("/{ws_id}/quick-replies/{qr_id}", response_model=QuickReplyItem)
def update_quick_reply(
    ws_id: str,
    qr_id: str,
    body: QuickReplyUpdate,
    current_user: User = Depends(require_permission("workspaces.manage")),
    db: Session = Depends(get_db),
) -> QuickReplyItem:
    from ..services.message_service import (
        MessageService,
        QuickReplyNotFound,
        ShortcutConflict,
    )

    try:
        return MessageService(db).update_quick_reply(
            qr_id, ws_id, current_user.tenant_id, body
        )
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    except QuickReplyNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quick reply not found.")
    except ShortcutConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "That shortcut is already in use.")


@router.delete(
    "/{ws_id}/quick-replies/{qr_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_quick_reply(
    ws_id: str,
    qr_id: str,
    current_user: User = Depends(require_permission("workspaces.manage")),
    db: Session = Depends(get_db),
) -> Response:
    from ..services.message_service import MessageService, QuickReplyNotFound

    try:
        MessageService(db).delete_quick_reply(qr_id, ws_id, current_user.tenant_id)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    except QuickReplyNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quick reply not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
