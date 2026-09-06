"""respond.io migration routes - thin, HTTP + Pydantic only (plan 33).

S1 ships ``GET .../preflight`` only (AC-MIG-14). S2 adds job create/list/
detail and the failure-CSV download to this SAME router (manifest prefix
``/omnichannel/migration``) - never a second router file for one feature.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import MigrationPreflight
from ..services.migration_service import MigrationPreflightService

router = APIRouter()


@router.get("/preflight", response_model=MigrationPreflight)
def preflight(
    connectionId: str = Query(...),
    workspaceId: str = Query(...),
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    db: Session = Depends(get_db),
) -> MigrationPreflight:
    return MigrationPreflightService(db).preflight(current_user.tenant_id, connectionId, workspaceId)
