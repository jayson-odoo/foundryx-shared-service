"""respond.io migration routes - thin, HTTP + Pydantic only (plan 33).

S1 shipped ``GET .../preflight`` only (AC-MIG-14). S2 adds job create/list/
detail/cancel and the failure-CSV download to this SAME router (manifest
prefix ``/omnichannel/migration``) - never a second router file for one
feature. Every mutating route is gated ``omnichannel_migration.manage``;
reads are gated ``.read`` (AC-MIG-50).
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..schemas import (
    MigrationJobCreate,
    MigrationJobItem,
    MigrationJobListResponse,
    MigrationPreflight,
    MigrationUploadResult,
)
from ..services.migration_service import (
    MIGRATION_UPLOAD_MAX_BYTES,
    MigrationJobConflict,
    MigrationJobValidationError,
    MigrationPreflightService,
    MigrationService,
)

router = APIRouter()


_UPLOAD_KINDS = ("contacts", "snippets")


@router.post("/uploads", response_model=MigrationUploadResult, status_code=status.HTTP_201_CREATED)
async def upload_csv(
    file: UploadFile = File(...),
    kind: str = Form(...),
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    db: Session = Depends(get_db),
) -> MigrationUploadResult:
    """S5 (AC-MIG-46/47, D-A6-25) - the real-upload-route replacement for S4's
    `snippetsCsvBase64` JSON stopgap, generalized to also cover the CSV-mode
    contacts file (`kind=contacts` / `kind=snippets`). Sniff-gated: content
    is read up to `MIGRATION_UPLOAD_MAX_BYTES + 1` so an oversize file is
    rejected without buffering an unbounded body (`app/uploads.py`'s own
    capped-read convention)."""
    if kind not in _UPLOAD_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"kind must be one of {_UPLOAD_KINDS}.")
    content = await file.read(MIGRATION_UPLOAD_MAX_BYTES + 1)
    if len(content) > MIGRATION_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {MIGRATION_UPLOAD_MAX_BYTES // (1024 * 1024)} MB limit.",
        )
    try:
        return MigrationService(db).upload_csv(current_user.tenant_id, kind, content)
    except MigrationJobValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})


@router.get("/preflight", response_model=MigrationPreflight)
def preflight(
    connectionId: str = Query(...),
    workspaceId: str = Query(...),
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    db: Session = Depends(get_db),
) -> MigrationPreflight:
    return MigrationPreflightService(db).preflight(current_user.tenant_id, connectionId, workspaceId)


# ── S2 - migration jobs (AC-MIG-19..21, 28) ─────────────────────────────────


@router.post("/jobs", response_model=MigrationJobItem, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: MigrationJobCreate,
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> MigrationJobItem:
    try:
        return MigrationService(db).create_job(current_user.tenant_id, actor_id, payload)
    except MigrationJobValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"fieldErrors": exc.errors})
    except MigrationJobConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"reason": exc.reason})


@router.get("/jobs", response_model=MigrationJobListResponse)
def list_jobs(
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200, alias="pageSize"),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, alias="sortBy"),
    sort_dir: Optional[str] = Query(None, alias="sortDir"),
    filter_raw: Optional[str] = Query(None, alias="filter"),
    current_user: User = Depends(require_permission("omnichannel_migration.read")),
    db: Session = Depends(get_db),
) -> MigrationJobListResponse:
    return MigrationService(db).list_jobs(
        current_user.tenant_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        search=search,
        sort_by=sort_by,
        sort_desc=(sort_dir != "asc"),
        filter_raw=filter_raw,
    )


@router.get("/jobs/{job_id}", response_model=MigrationJobItem)
def get_job(
    job_id: str,
    current_user: User = Depends(require_permission("omnichannel_migration.read")),
    db: Session = Depends(get_db),
) -> MigrationJobItem:
    return MigrationService(db).get_job(current_user.tenant_id, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=MigrationJobItem)
def cancel_job(
    job_id: str,
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    db: Session = Depends(get_db),
) -> MigrationJobItem:
    try:
        return MigrationService(db).cancel_job(current_user.tenant_id, job_id)
    except MigrationJobConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"reason": exc.reason})


@router.get("/jobs/{job_id}/failures.csv")
def download_failures_csv(
    job_id: str,
    current_user: User = Depends(require_permission("omnichannel_migration.read")),
    db: Session = Depends(get_db),
) -> Response:
    """Authed streaming download, never a signed capability URL (D-A6-23) -
    the file carries contact names, phones and emails."""
    csv_text = MigrationService(db).failures_csv(current_user.tenant_id, job_id)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="migration-{job_id}-failures.csv"',
            "Cache-Control": "private, no-store",
            # PII-egress precedent shared with `contacts.py download_contacts_
            # export`/`documents.py` - the file carries contact names, phones
            # and emails (D-A6-23).
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )
