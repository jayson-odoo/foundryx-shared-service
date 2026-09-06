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
holds both core keys. S3's export routes will use the same `reports.export`
key for the same reason.

S2 (this file) adds `GET .../reports/{reportKey}` - the seven report
builders + `groupBy` + pagination, on top of S1's dashboard + `reports/meta`."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import DashboardResponse, ReportMetaResponse, ReportResponse
from ..services import report_service
from ..services.report_filters import ReportValidationError
from ..services.report_queries import SampleCapExceeded
from ..services.report_service import GroupByNotSupported, ReportKeyNotFound
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


# NOTE: this route MUST stay registered AFTER `/reports/meta` above - a
# literal path segment matches before a param route only because Starlette
# evaluates routes in registration order (the workflow-settings precedent).
@router.get("/{ws_id}/reports/{report_key}", response_model=ReportResponse)
def get_report(
    ws_id: str,
    report_key: str,
    current_user: User = Depends(require_permission("reports.read")),
    db: Session = Depends(get_db),
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    tz: str = Query(...),
    granularity: Optional[str] = Query(None),
    userId: Optional[str] = Query(None),
    channelId: Optional[str] = Query(None),
    teamId: Optional[str] = Query(None),
    groupBy: Optional[str] = Query(None),
    page: int = Query(0),
    pageSize: int = Query(report_service.DEFAULT_PAGE_SIZE),
) -> ReportResponse:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        return report_service.report(
            db,
            report_key,
            tenant_id=current_user.tenant_id,
            workspace_id=ws_id,
            from_=from_,
            to=to,
            tz=tz,
            granularity=granularity,
            user_id=userId,
            channel_id=channelId,
            team_id=teamId,
            group_by=groupBy,
            page=page,
            page_size=pageSize,
        )
    except ReportKeyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found.") from exc
    except GroupByNotSupported as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"fieldErrors": {"groupBy": f"Must be one of {exc.allowed}."}},
        ) from exc
    except ReportValidationError as exc:
        raise _field_error(exc) from exc
    except SampleCapExceeded as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
