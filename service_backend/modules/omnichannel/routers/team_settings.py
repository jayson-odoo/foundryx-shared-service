"""Per-team assignment-strategy routes (plan 28 S2, AC-TEM-28) - HTTP +
Pydantic only. Mounted under `/omnichannel/workspaces/{ws_id}/team-settings`
(manifest router entry, prefix `/omnichannel/workspaces`, sibling of
`close_reasons`/`inbox_views`). Reading rides `conversations.read`, writing
`conversations.assign` (D-A8-14 - no dedicated `team_assignment.manage` key).
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User

from ..rbac import require_any_permission
from ..schemas import TeamAssignmentSettingItem, TeamAssignmentSettingUpdate
from ..services import team_assignment_service, team_directory
from ..services.workspace_service import WorkspaceService

router = APIRouter()


def _to_item(row, team_name) -> TeamAssignmentSettingItem:
    return TeamAssignmentSettingItem(
        teamId=row.team_id,
        teamName=team_name,
        strategy=row.strategy,
        lastAssignedUserId=row.last_assigned_user_id,
        updatedAt=row.updated_at,
        isConfigured=True,
    )


def _display_item(d: dict) -> TeamAssignmentSettingItem:
    return TeamAssignmentSettingItem(
        teamId=d["team_id"],
        teamName=d["team_name"],
        strategy=d["strategy"],
        lastAssignedUserId=d["last_assigned_user_id"],
        updatedAt=d["updated_at"],
        isConfigured=d["is_configured"],
    )


@router.get("/{ws_id}/team-settings", response_model=List[TeamAssignmentSettingItem])
def list_team_settings(
    ws_id: str,
    current_user: User = Depends(require_any_permission("conversations.read")),
    db: Session = Depends(get_db),
) -> List[TeamAssignmentSettingItem]:
    """One row per ACTIVE core team (review round 1, finding 4/5/6, amended
    from "every configured-or-assigned-to row"): resolved through
    `team_directory.list_active` (capability `teams.list@1`, no `teams.read`
    permission needed) and merged with this workspace's `TeamAssignmentSetting`
    rows - a never-configured team defaults to `round_robin`/`isConfigured:
    false`. There is no GET-one route, only this list and the PUT below; this
    list is now effectively the ACTIVE team catalog for this purpose (unlike
    `GET /teams`, which is gated `teams.read` and includes inactive teams)."""
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    rows = team_assignment_service.list_settings_for_display(db, current_user.tenant_id, ws_id)
    return [_display_item(r) for r in rows]


@router.put("/{ws_id}/team-settings/{team_id}", response_model=TeamAssignmentSettingItem)
def update_team_settings(
    ws_id: str,
    team_id: str,
    body: TeamAssignmentSettingUpdate,
    current_user: User = Depends(require_any_permission("conversations.assign")),
    db: Session = Depends(get_db),
) -> TeamAssignmentSettingItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    if body.strategy not in team_assignment_service.STRATEGIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"fieldErrors": {"strategy": "Unknown strategy."}},
        )
    # AC-TEM-28 - a team id that fails `team.resolve@1` (unknown, foreign-
    # tenant, deleted, or the capability not registered) is a 404 here, never
    # a settings row for a team that doesn't exist.
    team = team_directory.resolve(db, current_user.tenant_id, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
    row = team_assignment_service.set_strategy(
        db, current_user.tenant_id, ws_id, team_id, body.strategy
    )
    return _to_item(row, team.get("name"))
