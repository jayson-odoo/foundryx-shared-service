"""Workspace lifecycle-graph read (plan 25 S2) - HTTP + Pydantic only. Mounted
under `/omnichannel/workspaces/{ws_id}/lifecycle` (manifest router entry,
prefix `/omnichannel/workspaces`, sibling of `contact_fields`/`contact_tags`).

Read-only: the lifecycle CANVAS itself (add/rename/reorder/delete a stage,
add/remove an edge) is edited on the EXISTING core status-engine canvas
(`GET/POST/PATCH /api/v1/statuses?entityType=omnichannel_contact_lifecycle&
scopeId=<workspaceId>`, gated `statuses.manage` per D10) - this route just
gives the workspace form a simple list to render the current stage badges."""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User

from ..rbac import require_any_permission
from ..schemas import LifecycleStageItem
from ..services.lifecycle_service import stages_for_workspace
from ..services.workspace_service import WorkspaceService

router = APIRouter()


@router.get("/{ws_id}/lifecycle", response_model=List[LifecycleStageItem])
def get_workspace_lifecycle(
    ws_id: str,
    current_user: User = Depends(require_any_permission("conversations.read", "contacts.read")),
    db: Session = Depends(get_db),
) -> List[LifecycleStageItem]:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    rows = stages_for_workspace(db, current_user.tenant_id, ws_id)
    return [
        LifecycleStageItem(
            statusId=s.id,
            key=s.key,
            label=s.label,
            color=s.color,
            sortOrder=s.sort_order,
            isInitial=bool(s.is_initial),
            isWon=bool(s.is_terminal),
            isLost=bool(s.is_archived),
            isActive=not (s.is_terminal or s.is_archived),
        )
        for s in rows
    ]
