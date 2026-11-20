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

S2 added `GET .../reports/{reportKey}` - the seven report builders +
`groupBy` + pagination, on top of S1's dashboard + `reports/meta`. S3 (this
file) adds the export routes: `POST .../reports/{reportKey}/export` creates
a `background_jobs` row (`omnichannel.report_export`) and `GET .../reports/
{reportKey}/export/{jobId}/file` is the authed download - a byte-for-byte
copy of `routers/contacts.py download_contacts_export`'s guard set (tenant +
workspace + type + report key + DONE + fileKey, uniform 404, CSP sandbox,
nosniff, no-store, presigned redirect), gated by the SAME `reports.export`
key for the SAME reason documented above."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.background_job import JOB_DONE
from app.models.user import User
from app.jobs.service import JobService
from app.services.storage import storage_for_tenant

from ..schemas import DashboardResponse, ReportExportRequest, ReportMetaResponse, ReportResponse
from ..services import report_service
from ..services.report_export_service import (
    REPORT_EXPORT_JOB_TYPE,
    ReportExportRowCapExceeded,
    create_report_export_job,
)
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
    page: Optional[int] = Query(None),
    pageSize: Optional[int] = Query(None),
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


# ── Slice S3 - export (plan §5.1/§5.4, AC-RPT-33..40) ────────────────────────
@router.post(
    "/{ws_id}/reports/{report_key}/export", response_model=dict, status_code=status.HTTP_201_CREATED
)
def export_report(
    ws_id: str,
    report_key: str,
    body: ReportExportRequest,
    current_user: User = Depends(require_permission("reports.export")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> dict:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        job = create_report_export_job(
            db, current_user.tenant_id, ws_id, actor_user_id, report_key, body
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
    except ReportExportRowCapExceeded as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"This export would include {exc.count} rows, over the {exc.cap}-row limit. "
            "Narrow the filter or date range and try again.",
        ) from exc
    return {"jobId": job.id}


@router.get("/{ws_id}/reports/{report_key}/export/{job_id}/file")
def download_report_export(
    ws_id: str,
    report_key: str,
    job_id: str,
    current_user: User = Depends(require_permission("reports.export")),
    db: Session = Depends(get_db),
):
    """Authed streaming download - a byte-for-byte copy of `routers/
    contacts.py download_contacts_export`'s guard set (AC-RPT-34): reaching
    this route always requires the caller's bearer + `reports.export`.
    Uniform 404 unless the job belongs to THIS caller's tenant AND workspace
    AND report key AND is of THIS job type AND has finished; never
    immutable-cached, CSP-sandboxed + nosniff. A presigned/URL storage
    connection 307-redirects (Meta/AWS's own short-lived capability link,
    not ours)."""
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    job = JobService(db).get(current_user.tenant_id, job_id)
    if (
        job is None
        or job.type != REPORT_EXPORT_JOB_TYPE
        or (job.payload_json or {}).get("workspaceId") != ws_id
        or (job.payload_json or {}).get("reportKey") != report_key
        or job.status != JOB_DONE
        or not (job.result_json or {}).get("fileKey")
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found.")

    try:
        location, value = storage_for_tenant(db, current_user.tenant_id).resolve(
            job.result_json["fileKey"]
        )
    except Exception:  # noqa: BLE001 - unresolvable key (connection gone)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found.")

    filename = f"{report_key}-report-{job.created_at:%Y%m%d-%H%M%S}.csv"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=0, no-store",
    }
    if location in ("presigned", "url"):
        return RedirectResponse(value, headers=headers)
    return FileResponse(value, media_type="text/csv", headers=headers)
