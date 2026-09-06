"""Broadcast builder routes (plan 29 S1, roadmap A4). Mounted under
`/omnichannel/workspaces/{ws_id}/broadcasts` (manifest router entry, prefix
`/omnichannel/workspaces`). HTTP + Pydantic only, no DB/business logic here
(Router -> Service -> Repository).

Reads gated `broadcasts.read`; create/update/delete/duplicate gated
`broadcasts.manage`; send/schedule/cancel/test-send gated `broadcasts.send`.
Every route is tenant + workspace scoped; an unknown workspace/broadcast/
segment/contact/channel/template is a uniform 404 (never 403, never a peek
at another tenant's data, AC-BRD-24).

Deviation from plan §5.1 (flagged, see the S1 report): the audience preview
is `POST .../broadcasts/audience-preview` with the full `BroadcastAudience`
object in the body, not `GET ...?segmentId=|filter=` - the frontend's real
`audiencePreview(workspaceId, audience)` (built in S0,
`services/broadcast-service.ts`) always sends the WHOLE audience object
(including `contactIds`, which a GET query string handles awkwardly), and its
return type is `{count: number}` only (no `sample` - the S0 contract never
asks for one).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User
from app.services.filter_translator import FilterError

from ..schemas import (
    AudiencePreviewRequest,
    AudiencePreviewResponse,
    BroadcastCreate,
    BroadcastItem,
    BroadcastListResponse,
    BroadcastRecipientListResponse,
    BroadcastSendRequest,
    BroadcastTestSendRequest,
    BroadcastTestSendResponse,
    BroadcastUpdate,
)
from ..services.broadcast_service import (
    BroadcastNotFound,
    BroadcastService,
    BroadcastStatusConflict,
    BroadcastValidationError,
)
from ..services.contact_segment_service import SegmentNotFound
from ..services.workspace_service import WorkspaceService
from .contacts import _parse_filter

router = APIRouter()


@router.get("/{ws_id}/broadcasts", response_model=BroadcastListResponse)
def list_broadcasts(
    ws_id: str,
    current_user: User = Depends(require_permission("broadcasts.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200, alias="pageSize"),
    search: Optional[str] = None,
    sort_by: Optional[str] = Query(None, alias="sortBy"),
    sort_dir: str = Query("desc", alias="sortDir", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
    segment: Optional[str] = None,
) -> BroadcastListResponse:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        items, total = BroadcastService(db).list(
            current_user.tenant_id, ws_id,
            search=search, filter_group=_parse_filter(filter), segment=segment,
            sort_by=sort_by, sort_dir=sort_dir, page=page, page_size=page_size,
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return BroadcastListResponse(data=items, total=total, page=page)


@router.post("/{ws_id}/broadcasts/audience-preview", response_model=AudiencePreviewResponse)
def audience_preview(
    ws_id: str,
    body: AudiencePreviewRequest,
    current_user: User = Depends(require_permission("broadcasts.read")),
    db: Session = Depends(get_db),
) -> AudiencePreviewResponse:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        count = BroadcastService(db).audience_preview(current_user.tenant_id, ws_id, body.audience)
    except SegmentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment not found.")
    except BroadcastValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return AudiencePreviewResponse(count=count)


@router.post("/{ws_id}/broadcasts", response_model=BroadcastItem, status_code=status.HTTP_201_CREATED)
def create_broadcast(
    ws_id: str,
    body: BroadcastCreate,
    current_user: User = Depends(require_permission("broadcasts.manage")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> BroadcastItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        return BroadcastService(db).create(
            current_user.tenant_id, ws_id, body, actor_user_id=actor_user_id
        )
    except BroadcastValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})


@router.get("/{ws_id}/broadcasts/{broadcast_id}", response_model=BroadcastItem)
def get_broadcast(
    ws_id: str,
    broadcast_id: str,
    current_user: User = Depends(require_permission("broadcasts.read")),
    db: Session = Depends(get_db),
) -> BroadcastItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        return BroadcastService(db).get(broadcast_id, current_user.tenant_id, ws_id)
    except BroadcastNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Broadcast not found.")


@router.patch("/{ws_id}/broadcasts/{broadcast_id}", response_model=BroadcastItem)
def update_broadcast(
    ws_id: str,
    broadcast_id: str,
    body: BroadcastUpdate,
    current_user: User = Depends(require_permission("broadcasts.manage")),
    db: Session = Depends(get_db),
) -> BroadcastItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        return BroadcastService(db).update(broadcast_id, current_user.tenant_id, ws_id, body)
    except BroadcastNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Broadcast not found.")
    except BroadcastValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})
    except BroadcastStatusConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"reason": exc.reason})


@router.delete("/{ws_id}/broadcasts/{broadcast_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_broadcast(
    ws_id: str,
    broadcast_id: str,
    current_user: User = Depends(require_permission("broadcasts.manage")),
    db: Session = Depends(get_db),
) -> Response:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        BroadcastService(db).delete(broadcast_id, current_user.tenant_id, ws_id)
    except BroadcastNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Broadcast not found.")
    except BroadcastStatusConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"reason": exc.reason})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{ws_id}/broadcasts/{broadcast_id}/duplicate",
    response_model=BroadcastItem,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_broadcast(
    ws_id: str,
    broadcast_id: str,
    current_user: User = Depends(require_permission("broadcasts.manage")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> BroadcastItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        return BroadcastService(db).duplicate(
            broadcast_id, current_user.tenant_id, ws_id, actor_user_id=actor_user_id
        )
    except BroadcastNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Broadcast not found.")


@router.post("/{ws_id}/broadcasts/{broadcast_id}/send", response_model=BroadcastItem)
def send_broadcast(
    ws_id: str,
    broadcast_id: str,
    body: BroadcastSendRequest,
    current_user: User = Depends(require_permission("broadcasts.send")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> BroadcastItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        return BroadcastService(db).send(
            broadcast_id, current_user.tenant_id, ws_id, body, actor_user_id=actor_user_id
        )
    except BroadcastNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Broadcast not found.")
    except BroadcastValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})
    except BroadcastStatusConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"reason": exc.reason})


@router.post("/{ws_id}/broadcasts/{broadcast_id}/test-send", response_model=BroadcastTestSendResponse)
def test_send_broadcast(
    ws_id: str,
    broadcast_id: str,
    body: BroadcastTestSendRequest,
    current_user: User = Depends(require_permission("broadcasts.send")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> BroadcastTestSendResponse:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        message_id = BroadcastService(db).test_send(
            broadcast_id, current_user.tenant_id, ws_id, body.contactId, actor_user_id=actor_user_id
        )
    except BroadcastNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Broadcast or contact not found.")
    except BroadcastValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})
    return BroadcastTestSendResponse(messageId=message_id)


@router.post("/{ws_id}/broadcasts/{broadcast_id}/cancel", response_model=BroadcastItem)
def cancel_broadcast(
    ws_id: str,
    broadcast_id: str,
    current_user: User = Depends(require_permission("broadcasts.send")),
    db: Session = Depends(get_db),
) -> BroadcastItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        return BroadcastService(db).cancel(broadcast_id, current_user.tenant_id, ws_id)
    except BroadcastNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Broadcast not found.")
    except BroadcastStatusConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"reason": exc.reason})


@router.get("/{ws_id}/broadcasts/{broadcast_id}/recipients", response_model=BroadcastRecipientListResponse)
def list_broadcast_recipients(
    ws_id: str,
    broadcast_id: str,
    current_user: User = Depends(require_permission("broadcasts.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200, alias="pageSize"),
    state: Optional[str] = None,
    search: Optional[str] = None,
) -> BroadcastRecipientListResponse:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        items, total = BroadcastService(db).recipients(
            broadcast_id, current_user.tenant_id, ws_id,
            state=state, search=search, page=page, page_size=page_size,
        )
    except BroadcastNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Broadcast not found.")
    return BroadcastRecipientListResponse(data=items, total=total, page=page)
