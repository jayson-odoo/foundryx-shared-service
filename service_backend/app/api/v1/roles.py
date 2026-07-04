"""Role management routes. Thin: validate, delegate to RoleService, shape HTTP.
All routes tenant-scoped via the JWT user and gated by `roles.*` permissions.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.role import Role
from app.models.user import User
from app.schemas.role import (
    AssignableUserItem,
    AssignUsersRequest,
    RoleCreate,
    RoleDetail,
    RoleExportRequest,
    RoleItem,
    RoleListResponse,
    RoleNeighborResponse,
    RoleOut,
    RoleUpdate,
    RoleUserItem,
)
from app.schemas.filters import FilterGroup
from app.services.filter_translator import FilterError
from app.services.role_service import (
    RoleNameExists,
    RoleNotFound,
    RoleService,
    SystemRoleProtected,
)

router = APIRouter()


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


def _item(role: Role, user_count: int) -> RoleItem:
    return RoleItem(
        id=role.id,
        name=role.name,
        description=role.description,
        isSystem=role.is_system,
        userCount=user_count,
        permissionCount=len(role.permissions),
        createdAt=role.created_at,
    )


def _detail(role: Role, user_count: int) -> RoleDetail:
    return RoleDetail(
        id=role.id,
        name=role.name,
        description=role.description,
        isSystem=role.is_system,
        userCount=user_count,
        permissionCount=len(role.permissions),
        createdAt=role.created_at,
        permissionKeys=[p.key for p in role.permissions],
    )


# ---- list / neighbour / export ----


@router.get("", response_model=RoleListResponse)
def list_roles(
    current_user: User = Depends(require_permission("roles.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> RoleListResponse:
    service = RoleService(db)
    try:
        rows, total = service.list(
            current_user.tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    counts = service.user_counts([r.id for r in rows], current_user.tenant_id)
    return RoleListResponse(
        data=[_item(r, counts.get(r.id, 0)) for r in rows], total=total, page=page
    )


@router.get("/options", response_model=List[RoleOut])
def role_options(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[RoleOut]:
    """Lightweight (id, name) list for the user-form role picker. Authenticated
    only — assigning roles to a user shouldn't require the roles.* management
    permissions."""
    roles = RoleService(db).repo.list(current_user.tenant_id)
    return [RoleOut.model_validate(r) for r in roles]


@router.get("/at", response_model=RoleNeighborResponse)
def role_at(
    current_user: User = Depends(require_permission("roles.read")),
    db: Session = Depends(get_db),
    index: int = Query(0, ge=0),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> RoleNeighborResponse:
    service = RoleService(db)
    try:
        role, total = service.get_at(
            index,
            current_user.tenant_id,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if role is None:
        return RoleNeighborResponse(role=None, total=total)
    return RoleNeighborResponse(
        role=_detail(role, service.user_count(role.id, current_user.tenant_id)), total=total
    )


@router.post("/export", response_class=PlainTextResponse)
def export_roles(
    payload: RoleExportRequest,
    current_user: User = Depends(require_permission("roles.read")),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    service = RoleService(db)
    try:
        csv_text = service.export_csv(
            payload.columns,
            current_user.tenant_id,
            ids=payload.ids,
            search=payload.search,
            sort_by=payload.sortBy,
            sort_dir=payload.sortDir or "asc",
            filter_group=payload.filter,
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=roles.csv"},
    )


# ---- assigned users (sub-resource) ----


@router.get("/{role_id}/users", response_model=List[RoleUserItem])
def assigned_users(
    role_id: str,
    current_user: User = Depends(require_permission("roles.read")),
    db: Session = Depends(get_db),
    search: Optional[str] = None,
) -> List[RoleUserItem]:
    try:
        rows = RoleService(db).get_assigned_users(role_id, current_user.tenant_id, search)
    except RoleNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found.")
    return [
        RoleUserItem(
            id=u.id,
            name=u.name,
            email=u.email,
            avatar=u.avatar,
            status=u.status,
            assignedAt=assigned_at,
        )
        for u, assigned_at in rows
    ]


@router.get("/{role_id}/assignable", response_model=List[AssignableUserItem])
def assignable_users(
    role_id: str,
    current_user: User = Depends(require_permission("roles.read")),
    db: Session = Depends(get_db),
    search: Optional[str] = None,
) -> List[AssignableUserItem]:
    try:
        users = RoleService(db).list_assignable(role_id, current_user.tenant_id, search)
    except RoleNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found.")
    return [
        AssignableUserItem(id=u.id, name=u.name, email=u.email, avatar=u.avatar, status=u.status)
        for u in users
    ]


@router.post("/{role_id}/users", status_code=status.HTTP_204_NO_CONTENT)
def assign_users(
    role_id: str,
    payload: AssignUsersRequest,
    current_user: User = Depends(require_permission("roles.update")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        RoleService(db).assign_users(role_id, payload.userIds, current_user.tenant_id)
    except RoleNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{role_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user(
    role_id: str,
    user_id: str,
    current_user: User = Depends(require_permission("roles.update")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        RoleService(db).remove_user(role_id, user_id, current_user.tenant_id)
    except RoleNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- create / get / update / delete ----


@router.post("", response_model=RoleDetail, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate,
    current_user: User = Depends(require_permission("roles.create")),
    db: Session = Depends(get_db),
) -> RoleDetail:
    service = RoleService(db)
    try:
        role = service.create(
            payload.name,
            current_user.tenant_id,
            description=payload.description,
            permission_keys=payload.permissionKeys,
            is_system=payload.isSystem,
        )
    except RoleNameExists:
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with this name already exists.")
    return _detail(role, 0)


@router.get("/{role_id}", response_model=RoleDetail)
def get_role(
    role_id: str,
    current_user: User = Depends(require_permission("roles.read")),
    db: Session = Depends(get_db),
) -> RoleDetail:
    service = RoleService(db)
    try:
        role = service.get(role_id, current_user.tenant_id)
    except RoleNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found.")
    return _detail(role, service.user_count(role_id, current_user.tenant_id))


@router.patch("/{role_id}", response_model=RoleDetail)
def update_role(
    role_id: str,
    payload: RoleUpdate,
    current_user: User = Depends(require_permission("roles.update")),
    db: Session = Depends(get_db),
) -> RoleDetail:
    service = RoleService(db)
    try:
        role = service.update(
            role_id,
            current_user.tenant_id,
            name=payload.name,
            description=payload.description,
            permission_keys=payload.permissionKeys,
            is_system=payload.isSystem,
            description_set="description" in payload.model_fields_set,
        )
    except RoleNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found.")
    except RoleNameExists:
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with this name already exists.")
    return _detail(role, service.user_count(role_id, current_user.tenant_id))


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: str,
    current_user: User = Depends(require_permission("roles.delete")),
    db: Session = Depends(get_db),
) -> Response:
    try:
        RoleService(db).delete(role_id, current_user.tenant_id)
    except RoleNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found.")
    except SystemRoleProtected:
        raise HTTPException(status.HTTP_409_CONFLICT, "System roles cannot be deleted.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
