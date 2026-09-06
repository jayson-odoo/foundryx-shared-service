"""Dashboard + reports routes (plan 30, roadmap A9, slice S1). Mounted under
`/omnichannel/workspaces/{ws_id}/...` (manifest router entry, prefix
`/omnichannel/workspaces`). HTTP + Pydantic only, no DB/business logic here
(Router -> Service -> Repository).

Gated by the CORE `reports.read`/`reports.export` permission keys - the
module deliberately does NOT declare its own `conversation_reports.*` rows
(see the plan's flagged decision, §8.1 item 1): core already owns
`reports.read`/`reports.export` globally-uniquely and `PermissionRepository.
sync` is delete-by-module, so a module CSV row of the same name would collide
at install and delete core's grants at uninstall. Every tenant Admin already
holds both core keys.

S2 adds `GET .../reports/{reportKey}` (the seven report builders); this file
only ships the dashboard + the report catalog (`reports/meta`)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import DashboardResponse, ReportMetaResponse
from ..services import report_service
from ..services.report_filters import ReportValidationError
from ..services.report_queries import SampleCapExceeded
from ..services.workspace_service import WorkspaceService

router = APIRouter()


def _field_error(exc: ReportValidationError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": {exc.field: exc.message}}
    )


@router.get("/{ws_id}/dashboard", response_model=DashboardResponse)
def get_dashboard(
    ws_id: str,
    current_user: User = Depends(require_permission("reports.read")),
    db: Session = Depends(get_db),
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    tz: str = Query(...),
    granularity: Optional[str] = Query(None),
    userId: Optional[str] = Query(None),
    channelId: Optional[str] = Query(None),
    teamId: Optional[str] = Query(None),
) -> DashboardResponse:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        return report_service.dashboard(
            db,
            tenant_id=current_user.tenant_id,
            workspace_id=ws_id,
            from_=from_,
            to=to,
            tz=tz,
            granularity=granularity,
            user_id=userId,
            channel_id=channelId,
            team_id=teamId,
        )
    except ReportValidationError as exc:
        raise _field_error(exc) from exc
    except SampleCapExceeded as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/{ws_id}/reports/meta", response_model=ReportMetaResponse)
def get_reports_meta(
    ws_id: str,
    current_user: User = Depends(require_permission("reports.read")),
    db: Session = Depends(get_db),
) -> ReportMetaResponse:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    return report_service.reports_meta()
