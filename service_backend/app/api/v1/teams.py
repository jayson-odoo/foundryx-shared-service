"""Team management routes (plan 28 S1). Thin: validate, delegate to
TeamService, shape HTTP. No DB queries or business rules here. Every route is
tenant-scoped via the JWT user - never a query param or body value.

`GET /teams/mine` is declared BEFORE `/{team_id}` so the literal path wins.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_permission
from app.models.team import Team
from app.models.user import User
from app.schemas.filters import FilterGroup
from app.schemas.team import (
    MyTeamItem,
    MyTeamMemberRef,
    TeamCreate,
    TeamItem,
    TeamListResponse,
    TeamMemberRef,
    TeamNeighborResponse,
    TeamUpdate,
)
from app.services.filter_translator import FilterError
from app.services.team_service import (
    TeamInUse,
    TeamNotFound,
    TeamService,
    TeamValidationError,
)

router = APIRouter()


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


def _item(team: Team) -> TeamItem:
    members = [
        TeamMemberRef(
            userId=m.user_id,
            name=(m.user.name or m.user.email) if m.user else "",
            email=m.user.email if m.user else "",
            role=m.role,
        )
        for m in team.members
    ]
    return TeamItem(
        id=team.id,
        name=team.name,
        description=team.description,
        isActive=team.is_active,
        sortOrder=team.sort_order,
        members=members,
        memberCount=len(members),
        createdAt=team.created_at,
        updatedAt=team.updated_at,
    )


def _field_errors(exc: TeamValidationError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"fieldErrors": exc.field_errors}
    )


@router.get("", response_model=TeamListResponse)
def list_teams(
    current_user: User = Depends(require_permission("teams.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> TeamListResponse:
    service = TeamService(db)
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
    return TeamListResponse(data=[_item(t) for t in rows], total=total, page=page)


@router.get("/at", response_model=TeamNeighborResponse)
def team_at(
    current_user: User = Depends(require_permission("teams.read")),
    db: Session = Depends(get_db),
    index: int = Query(0, ge=0),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> TeamNeighborResponse:
    service = TeamService(db)
    try:
        team, total = service.get_at(
            index,
            current_user.tenant_id,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return TeamNeighborResponse(team=_item(team) if team else None, total=total)


def _my_item(team: Team) -> MyTeamItem:
    """Trimmed shape (review round 1, finding 7) - no email, no description/
    sortOrder/timestamps. `/teams/mine` is authenticated-only (no
    `teams.read`), so it must never leak teammates' email addresses to every
    signed-in user."""
    members = [
        MyTeamMemberRef(
            userId=m.user_id,
            name=(m.user.name or m.user.email) if m.user else "",
            role=m.role,
        )
        for m in team.members
    ]
    return MyTeamItem(
        id=team.id,
        name=team.name,
        isActive=team.is_active,
        memberCount=len(members),
        members=members,
    )


@router.get("/mine", response_model=List[MyTeamItem])
def my_teams(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[MyTeamItem]:
    """AC-TEM-08/16 - only the caller's own teams; authenticated-only (no
    `teams.read`) so an inbox agent can render the Team rail."""
    service = TeamService(db)
    return [_my_item(t) for t in service.mine(current_user)]


@router.get("/{team_id}", response_model=TeamItem)
def get_team(
    team_id: str,
    current_user: User = Depends(require_permission("teams.read")),
    db: Session = Depends(get_db),
) -> TeamItem:
    service = TeamService(db)
    try:
        team = service.get(team_id, current_user.tenant_id)
    except TeamNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
    return _item(team)


@router.post("", response_model=TeamItem, status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamCreate,
    current_user: User = Depends(require_permission("teams.manage")),
    db: Session = Depends(get_db),
) -> TeamItem:
    service = TeamService(db)
    try:
        team = service.create(
            current_user.tenant_id,
            name=payload.name,
            description=payload.description,
            is_active=payload.isActive,
            sort_order=payload.sortOrder,
            members=payload.members,
        )
    except TeamValidationError as exc:
        raise _field_errors(exc)
    return _item(team)


@router.patch("/{team_id}", response_model=TeamItem)
def update_team(
    team_id: str,
    payload: TeamUpdate,
    current_user: User = Depends(require_permission("teams.manage")),
    db: Session = Depends(get_db),
) -> TeamItem:
    service = TeamService(db)
    try:
        team = service.update(
            team_id,
            current_user.tenant_id,
            name=payload.name,
            description=payload.description,
            is_active=payload.isActive,
            sort_order=payload.sortOrder,
            members=payload.members,
        )
    except TeamNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
    except TeamValidationError as exc:
        raise _field_errors(exc)
    return _item(team)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: str,
    current_user: User = Depends(require_permission("teams.manage")),
    db: Session = Depends(get_db),
) -> Response:
    service = TeamService(db)
    try:
        service.delete(team_id, current_user.tenant_id)
    except TeamNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
    except TeamInUse as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error": "team_in_use", "counts": exc.counts},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
