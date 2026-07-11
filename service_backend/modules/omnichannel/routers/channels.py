"""Channel routes — thin; gated by omnichannel `channels.*` permissions.
Channels are CREATED via onboarding (Embedded Signup), not here."""
import csv
import io
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from ..schemas import (
    ChannelItem,
    ChannelListResponse,
    ChannelNeighborResponse,
    ChannelProfileOut,
    ChannelProfileUpdate,
    ChannelUpdate,
    ExportRequest,
    IdsRequest,
    TestConnectionResult,
)
from ..services.channel_profile_service import ChannelProfileService
from ..services.channel_service import ChannelNotFound, ChannelService

router = APIRouter()


@router.get("", response_model=ChannelListResponse)
def list_channels(
    current_user: User = Depends(require_permission("channels.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: str = Query("active"),
) -> ChannelListResponse:
    items, total = ChannelService(db).list(
        current_user.tenant_id, page=page, page_size=page_size, search=search,
        sort_by=sort_by, sort_dir=sort_dir, status_view=status_view,
    )
    return ChannelListResponse(data=items, total=total, page=page)


@router.get("/at", response_model=ChannelNeighborResponse)
def channel_at(
    current_user: User = Depends(require_permission("channels.read")),
    db: Session = Depends(get_db),
    index: int = Query(..., ge=0),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: str = Query("active"),
) -> ChannelNeighborResponse:
    ch, total = ChannelService(db).get_at(
        index, current_user.tenant_id, status_view=status_view,
        search=search, sort_by=sort_by, sort_dir=sort_dir,
    )
    return ChannelNeighborResponse(channel=ch, total=total)


@router.get("/by-workspace/{ws_id}", response_model=List[ChannelItem])
def channels_by_workspace(
    ws_id: str,
    current_user: User = Depends(require_permission("channels.read")),
    db: Session = Depends(get_db),
) -> List[ChannelItem]:
    return ChannelService(db).list_by_workspace(ws_id, current_user.tenant_id)


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_channels(
    body: IdsRequest,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> Response:
    ChannelService(db).disconnect(body.ids, current_user.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_channels(
    body: IdsRequest,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> Response:
    ChannelService(db).restore(body.ids, current_user.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_channels(
    body: IdsRequest,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> Response:
    ChannelService(db).remove(body.ids, current_user.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/export", response_class=PlainTextResponse)
def export_channels(
    body: ExportRequest,
    current_user: User = Depends(require_permission("channels.read")),
    db: Session = Depends(get_db),
) -> str:
    items, _ = ChannelService(db).list(
        current_user.tenant_id, page=0, page_size=10_000, search=body.search,
        sort_by=body.sortBy, sort_dir=body.sortDir or "asc", status_view=body.statusView or "active",
    )
    if body.ids:
        keep = set(body.ids)
        items = [c for c in items if c.id in keep]
    col_value = {
        "name": lambda c: c.name,
        "channelType": lambda c: c.channelType,
        "phone": lambda c: c.displayPhoneNumber or "",
        "status": lambda c: c.status,
        "created": lambda c: c.createdAt.isoformat(),
    }
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(body.columns)
    for c in items:
        writer.writerow([col_value.get(col, lambda _c: "")(c) for col in body.columns])
    return buf.getvalue()


@router.get("/{channel_id}", response_model=ChannelItem)
def get_channel(
    channel_id: str,
    current_user: User = Depends(require_permission("channels.read")),
    db: Session = Depends(get_db),
) -> ChannelItem:
    try:
        return ChannelService(db).get(channel_id, current_user.tenant_id)
    except ChannelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")


@router.patch("/{channel_id}", response_model=ChannelItem)
def update_channel(
    channel_id: str,
    body: ChannelUpdate,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> ChannelItem:
    try:
        return ChannelService(db).update(channel_id, body, current_user.tenant_id)
    except ChannelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")


@router.post("/{channel_id}/test", response_model=TestConnectionResult)
def test_channel(
    channel_id: str,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> TestConnectionResult:
    try:
        return ChannelService(db).test_connection(channel_id, current_user.tenant_id)
    except ChannelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")


# ── WABA configuration + WhatsApp Business Profile (plan 06 Slice A) ──────────
@router.post("/{channel_id}/sync-config", response_model=ChannelItem)
def sync_channel_config(
    channel_id: str,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> ChannelItem:
    """Pull live phone + WABA identity from Meta into the local mirror."""
    try:
        return ChannelProfileService(db).sync_config(channel_id, current_user.tenant_id)
    except ChannelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")


@router.get("/{channel_id}/profile", response_model=ChannelProfileOut)
def get_channel_profile(
    channel_id: str,
    current_user: User = Depends(require_permission("channels.read")),
    db: Session = Depends(get_db),
) -> ChannelProfileOut:
    try:
        return ChannelProfileService(db).get_profile(channel_id, current_user.tenant_id)
    except ChannelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")


@router.patch("/{channel_id}/profile", response_model=ChannelProfileOut)
def update_channel_profile(
    channel_id: str,
    body: ChannelProfileUpdate,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> ChannelProfileOut:
    """Validate → write-through to Meta → refresh local on success."""
    try:
        return ChannelProfileService(db).save_profile(channel_id, body, current_user.tenant_id)
    except ChannelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")


@router.post("/{channel_id}/profile/sync", response_model=ChannelProfileOut)
def sync_channel_profile(
    channel_id: str,
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> ChannelProfileOut:
    try:
        return ChannelProfileService(db).sync_profile(channel_id, current_user.tenant_id)
    except ChannelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")


# NOTE: ``GET /{channel_id}/templates`` (composer send-picker) moved to the
# PUBLIC ``embed_reads`` router so BOTH the native session AND an embed access
# token reach it (workspace-scoped for embed). Native perm ``conversations.reply``
# is preserved there.
