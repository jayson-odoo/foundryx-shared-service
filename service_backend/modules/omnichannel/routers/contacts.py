"""Contacts-module routes (plan 26, roadmap A2). Mounted under
`/omnichannel/workspaces/{ws_id}/contacts` (manifest router entry, prefix
`/omnichannel/workspaces`) - separate from the Inbox thread list
(`/omnichannel/contacts`, unchanged). HTTP + Pydantic only, no DB/business
logic here (Router -> Service -> Repository).

S1 shipped the list read (AC-CTM-14..23); S2 adds create + the three bulk
routes on this SAME router file (plan §4, AC-CTM-24..33) - reads stay gated
`contacts.read`, writes `contacts.manage`."""
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.jobs.service import JobService
from app.models.background_job import JOB_DONE
from app.models.user import User
from app.schemas.filters import FilterGroup
from app.services.filter_translator import FilterError
from app.services.storage import storage_for_tenant

from ..schemas import (
    BulkAssignRequest,
    BulkLifecycleRequest,
    BulkResult,
    BulkTagsRequest,
    ContactCreate,
    ContactExportRequest,
    ContactListItem,
    ContactListResponse,
)
from ..services.contact_admin_service import (
    BulkValidationError,
    ContactAdminService,
    ContactCreateError,
)
from ..services.contact_export_service import EXPORT_JOB_TYPE, create_export_job
from ..services.contact_list_service import DEFAULT_PAGE_SIZE, ContactListService
from ..services.contact_segment_service import SegmentNotFound
from ..services.workspace_service import WorkspaceService

router = APIRouter()


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


@router.get("/{ws_id}/contacts", response_model=ContactListResponse)
def list_contacts(
    ws_id: str,
    current_user: User = Depends(require_permission("contacts.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=200, alias="pageSize"),
    search: Optional[str] = None,
    sort_by: Optional[str] = Query(None, alias="sortBy"),
    sort_dir: str = Query("desc", alias="sortDir", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
    segment: Optional[str] = None,
) -> ContactListResponse:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    service = ContactListService(db)
    try:
        rows, total = service.list(
            current_user.tenant_id,
            ws_id,
            search=search,
            filter_group=_parse_filter(filter),
            segment_id=segment,
            sort_by=sort_by,
            sort_dir=sort_dir,
            page=page,
            page_size=page_size,
        )
    except SegmentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment not found.")
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return ContactListResponse(data=rows, total=total, page=page)


@router.post(
    "/{ws_id}/contacts", response_model=ContactListItem, status_code=status.HTTP_201_CREATED
)
def create_contact(
    ws_id: str,
    body: ContactCreate,
    current_user: User = Depends(require_permission("contacts.manage")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> ContactListItem:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        return ContactAdminService(db).create(
            current_user.tenant_id, ws_id, body, actor=current_user, actor_id=actor_user_id
        )
    except ContactCreateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})


@router.post("/{ws_id}/contacts/bulk/assign", response_model=BulkResult)
def bulk_assign_contacts(
    ws_id: str,
    body: BulkAssignRequest,
    current_user: User = Depends(require_permission("contacts.manage")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> BulkResult:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    return ContactAdminService(db).bulk_assign(
        current_user.tenant_id,
        ws_id,
        body.ids,
        body.assigneeUserId,
        actor=current_user,
        actor_id=actor_user_id,
    )


@router.post("/{ws_id}/contacts/bulk/tags", response_model=BulkResult)
def bulk_tag_contacts(
    ws_id: str,
    body: BulkTagsRequest,
    current_user: User = Depends(require_permission("contacts.manage")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> BulkResult:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        return ContactAdminService(db).bulk_tags(
            current_user.tenant_id,
            ws_id,
            body.ids,
            body.mode,
            body.tagIds,
            actor=current_user,
            actor_id=actor_user_id,
        )
    except BulkValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})


@router.post("/{ws_id}/contacts/bulk/lifecycle", response_model=BulkResult)
def bulk_lifecycle_contacts(
    ws_id: str,
    body: BulkLifecycleRequest,
    current_user: User = Depends(require_permission("contacts.manage")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> BulkResult:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    return ContactAdminService(db).bulk_lifecycle(
        current_user.tenant_id,
        ws_id,
        body.ids,
        body.toStatusId,
        actor=current_user,
        actor_id=actor_user_id,
    )


# ── Export (plan 26 S3, D-A2-6a/6b, AC-CTM-39..42) ──────────────────────────
@router.post("/{ws_id}/contacts/export", response_model=dict, status_code=status.HTTP_201_CREATED)
def export_contacts(
    ws_id: str,
    body: ContactExportRequest,
    current_user: User = Depends(require_permission("contacts.export")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> dict:
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    try:
        job = create_export_job(db, current_user.tenant_id, ws_id, actor_user_id, body)
    except SegmentNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segment not found.")
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return {"jobId": job.id}


@router.get("/{ws_id}/contacts/export/{job_id}/file")
def download_contacts_export(
    ws_id: str,
    job_id: str,
    current_user: User = Depends(require_permission("contacts.export")),
    db: Session = Depends(get_db),
):
    """Authed streaming download (D-A2-6b - never a bearer-less signed URL for
    a CSV of an entire contact database). Uniform 404 unless the job belongs
    to THIS caller's tenant AND workspace AND is of THIS type AND has finished
    (AC-CTM-41) - never immutable-cached, CSP-sandboxed + nosniff (the PII-
    egress precedent shared with the form-submission file route)."""
    WorkspaceService(db).get_or_404(ws_id, current_user.tenant_id)
    job = JobService(db).get(current_user.tenant_id, job_id)
    if (
        job is None
        or job.type != EXPORT_JOB_TYPE
        or (job.payload_json or {}).get("workspaceId") != ws_id
        or job.status != JOB_DONE
        or not (job.result_json or {}).get("fileKey")
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found.")

    store = storage_for_tenant(db, current_user.tenant_id)
    kind, value = store.resolve(job.result_json["fileKey"])
    if kind == "path":
        with open(value, "rb") as fh:
            content = fh.read()
    else:
        import urllib.request

        content = urllib.request.urlopen(value).read()  # noqa: S310 (own storage)

    filename = f"contacts-export-{job.created_at:%Y%m%d-%H%M%S}.csv"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=0, no-store",
    }
    return StreamingResponse(io.BytesIO(content), media_type="text/csv", headers=headers)
