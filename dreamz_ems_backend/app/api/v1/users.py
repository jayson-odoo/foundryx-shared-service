"""User management routes. Thin: validate, delegate to UserService, shape HTTP.
No DB queries or business rules here. All routes tenant-scoped via the JWT user.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User
from app.schemas.account import AvatarOut
from app.services.avatar_service import AVATAR_MAX_BYTES, AvatarError, AvatarService
from app.schemas.user import (
    ExportRequest,
    FilterGroup,
    IdsRequest,
    NeighborResponse,
    UserCreate,
    UserItem,
    UserListResponse,
    UserUpdate,
)
from app.services.filter_translator import FilterError
from app.services.user_service import (
    EmailExists,
    SelfEmailChange,
    UserNotFound,
    UserService,
)

router = APIRouter()


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


def _item(user: User) -> UserItem:
    return UserItem.model_validate(user)


@router.get("", response_model=UserListResponse)
def list_users(
    current_user: User = Depends(require_permission("users.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: str = Query("active", pattern="^(active|trashed)$"),
    filter: Optional[str] = None,
) -> UserListResponse:
    service = UserService(db)
    try:
        rows, total = service.list(
            current_user.tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
            status_view=status_view,
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return UserListResponse(data=[_item(u) for u in rows], total=total, page=page)


@router.get("/at", response_model=NeighborResponse)
def user_at(
    current_user: User = Depends(require_permission("users.read")),
    db: Session = Depends(get_db),
    index: int = Query(0, ge=0),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: str = Query("active", pattern="^(active|trashed)$"),
    filter: Optional[str] = None,
) -> NeighborResponse:
    service = UserService(db)
    try:
        user, total = service.get_at(
            index,
            current_user.tenant_id,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
            status_view=status_view,
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return NeighborResponse(user=_item(user) if user else None, total=total)


@router.post("", response_model=UserItem, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    current_user: User = Depends(require_permission("users.create")),
    db: Session = Depends(get_db),
) -> UserItem:
    service = UserService(db)
    try:
        user = service.create(
            payload.name, payload.email, payload.roleIds, payload.status, current_user.tenant_id
        )
    except EmailExists:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")
    return _item(user)


@router.post("/trash", status_code=status.HTTP_204_NO_CONTENT)
def trash_users(
    payload: IdsRequest,
    current_user: User = Depends(require_permission("users.delete")),
    db: Session = Depends(get_db),
) -> Response:
    UserService(db).trash(payload.ids, current_user.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_users(
    payload: IdsRequest,
    current_user: User = Depends(require_permission("users.delete")),
    db: Session = Depends(get_db),
) -> Response:
    UserService(db).restore(payload.ids, current_user.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invite")
def invite_users(
    payload: IdsRequest,
    current_user: User = Depends(require_permission("users.create")),
    db: Session = Depends(get_db),
) -> dict:
    sent = UserService(db).invite(payload.ids, current_user.tenant_id)
    return {"sent": sent}


@router.post("/export", response_class=PlainTextResponse)
def export_users(
    payload: ExportRequest,
    current_user: User = Depends(require_permission("users.read")),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    service = UserService(db)
    try:
        csv_text = service.export_csv(
            payload.columns,
            current_user.tenant_id,
            ids=payload.ids,
            search=payload.search,
            sort_by=payload.sortBy,
            sort_dir=payload.sortDir or "asc",
            filter_group=payload.filter,
            status_view=payload.statusView,
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


@router.get("/{user_id}", response_model=UserItem)
def get_user(
    user_id: str,
    current_user: User = Depends(require_permission("users.read")),
    db: Session = Depends(get_db),
) -> UserItem:
    try:
        user = UserService(db).get(user_id, current_user.tenant_id)
    except UserNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return _item(user)


@router.patch("/{user_id}", response_model=UserItem)
def update_user(
    user_id: str,
    payload: UserUpdate,
    current_user: User = Depends(require_permission("users.update")),
    # The REAL admin while impersonating (impersonation invariant: actor =
    # real user) — keying the self-email guard on the effective user would
    # wrongly 409 an impersonating admin editing the target's email.
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> UserItem:
    try:
        user = UserService(db).update(
            user_id,
            current_user.tenant_id,
            name=payload.name,
            email=payload.email,
            role_ids=payload.roleIds,
            status=payload.status,
            actor_id=actor_id,
        )
    except UserNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    except SelfEmailChange:
        # No self-bypass (plan sprint-2/04): own email rides the ceremony.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Change your own email from My Account — it needs confirmation from both mailboxes.",
        )
    except EmailExists:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A user with this email already exists."
        )
    return _item(user)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: str,
    current_user: User = Depends(require_permission("users.update")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        UserService(db).reset_password(user_id, current_user.tenant_id)
    except UserNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
def resend_verification(
    user_id: str,
    current_user: User = Depends(require_permission("users.update")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        UserService(db).resend_verification(user_id, current_user.tenant_id)
    except UserNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/avatar", response_model=AvatarOut)
async def set_user_avatar(
    user_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("users.update")),
    db: Session = Depends(get_db),
) -> AvatarOut:
    """Admin avatar path (plan 06 D5) — same sniff gate as /me/avatar."""
    try:
        target = UserService(db).get(user_id, current_user.tenant_id)
    except UserNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    # Cap the read — a full read() buffers an arbitrary-size body in RAM
    # before any size check (review finding). One byte past the cap is
    # enough for the service's too-large 422.
    content = await file.read(AVATAR_MAX_BYTES + 1)
    try:
        target = AvatarService(db).set_avatar(target, content)
    except AvatarError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return AvatarOut(avatar=target.avatar)


@router.delete("/{user_id}/avatar", response_model=AvatarOut)
def remove_user_avatar(
    user_id: str,
    current_user: User = Depends(require_permission("users.update")),
    db: Session = Depends(get_db),
) -> AvatarOut:
    try:
        target = UserService(db).get(user_id, current_user.tenant_id)
    except UserNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    target = AvatarService(db).remove_avatar(target)
    return AvatarOut(avatar=target.avatar)
