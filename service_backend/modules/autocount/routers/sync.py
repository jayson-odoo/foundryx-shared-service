"""Sync routes — trigger, review, approve, discard. HTTP + Pydantic only.

"Sync now" is MANUAL this slice (no scheduling, no beat entry) — see
``services/sync_service.py`` for why.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..schemas import (
    ApprovalResponse,
    PreviewResponse,
    StagedListResponse,
    StagedRecordItem,
    SyncJobBatchItem,
    SyncJobItem,
    SyncJobListResponse,
    SyncNowRequest,
    SyncRunItem,
    SyncRunListResponse,
)
from ..services import (
    AutocountServiceError,
    CompanyNotFound,
    EntityNotConfigured,
    JobNotFound,
    NotAwaitingApproval,
    PreviewFailed,
    PushFailed,
    SyncService,
)

router = APIRouter()


def _raise(exc: AutocountServiceError) -> None:
    if isinstance(exc, (CompanyNotFound, JobNotFound)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    if isinstance(exc, NotAwaitingApproval):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    if isinstance(exc, (PushFailed, PreviewFailed)):
        # An UPSTREAM fault, not bad client input — 422 would tell the operator
        # they sent something wrong when in fact the consumer broke. A push is
        # back in review and re-approvable; a preview failure just means the
        # gate cannot offer approval yet. Both say so in the message.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
        )
    if isinstance(exc, EntityNotConfigured):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        )
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
    )


@router.post(
    "/companies/{company_id}/sync",
    response_model=SyncJobItem,
    status_code=status.HTTP_202_ACCEPTED,
)
def sync_now(
    company_id: str,
    body: SyncNowRequest,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    db: Session = Depends(get_db),
    actor_user_id: str = Depends(get_actor_user_id),
) -> SyncJobItem:
    try:
        job = SyncService(db).sync_now(
            current_user.tenant_id,
            company_id,
            body.entityType,
            actor_user_id=actor_user_id,
        )
    except AutocountServiceError as exc:
        _raise(exc)
    db.refresh(job)
    return SyncJobItem.model_validate(job)


@router.get("/companies/{company_id}/runs", response_model=SyncRunListResponse)
def list_runs(
    company_id: str,
    current_user: User = Depends(require_permission("autocount.sync.read")),
    db: Session = Depends(get_db),
    entity_type: str = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
) -> SyncRunListResponse:
    try:
        rows, total = SyncService(db).runs_for_company(
            current_user.tenant_id,
            company_id,
            entity_type=entity_type,
            page=page,
            page_size=page_size,
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return SyncRunListResponse(
        data=[SyncRunItem.model_validate(row) for row in rows], total=total, page=page
    )


@router.get("/jobs", response_model=SyncJobListResponse)
def list_jobs(
    current_user: User = Depends(require_permission("autocount.sync.read")),
    db: Session = Depends(get_db),
    status_filter: str = Query("all", alias="status"),
    entity_type: str = Query(None, alias="entityType"),
    search: str = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
) -> SyncJobListResponse:
    """The Review list — sync batches for the caller's tenant, newest first
    (AC-15-02). Server-paginated + status/entity/label filtered; NEVER an
    unbounded fetch."""
    try:
        batches, total = SyncService(db).list_jobs(
            current_user.tenant_id,
            status=status_filter,
            entity_type=entity_type,
            search=search,
            page=page,
            page_size=page_size,
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return SyncJobListResponse(
        data=[SyncJobBatchItem.model_validate(b) for b in batches],
        total=total,
        page=page,
    )


@router.get("/jobs/{job_id}/staged", response_model=StagedListResponse)
def list_staged(
    job_id: str,
    current_user: User = Depends(require_permission("autocount.sync.read")),
    db: Session = Depends(get_db),
    changed: bool = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
) -> StagedListResponse:
    """Staged records + their per-record diffs (AC-13-12, AC-15-10/11). Nothing
    here has been pushed — this is the review surface. Server-paginated with an
    optional ``changed``-only filter; the response carries the batch total + the
    no-change count so the FE collapses no-op re-fetches without fetching them."""
    try:
        job, rows, total, filtered_total, no_change = SyncService(db).staged_page(
            current_user.tenant_id,
            job_id,
            changed=changed,
            page=page,
            page_size=page_size,
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return StagedListResponse(
        job=SyncJobItem.model_validate(job),
        data=[StagedRecordItem.model_validate(row) for row in rows],
        total=total,
        page=page,
        filteredTotal=filtered_total,
        noChangeCount=no_change,
    )


@router.post("/jobs/{job_id}/preview", response_model=PreviewResponse)
def preview(
    job_id: str,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    db: Session = Depends(get_db),
) -> PreviewResponse:
    """Dry-run the staged batch against the consumer and return its prediction
    (AC-14-20/21). Writes NOTHING — the prediction is Sorento's own rolled-back
    resolution, never a local reconstruction. Gated by the run permission
    because it is the step immediately before approval."""
    try:
        result = SyncService(db).preview(current_user.tenant_id, job_id)
    except AutocountServiceError as exc:
        _raise(exc)
    return PreviewResponse(jobId=job_id, preview=result)


@router.post("/jobs/{job_id}/approve", response_model=ApprovalResponse)
def approve(
    job_id: str,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    db: Session = Depends(get_db),
    actor_user_id: str = Depends(get_actor_user_id),
) -> ApprovalResponse:
    """Approve the batch. IDEMPOTENT (AC-13-13): a second call is a no-op that
    returns the original result, so a double-click never double-pushes."""
    try:
        result = SyncService(db).approve(
            current_user.tenant_id, job_id, actor_user_id=actor_user_id
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return ApprovalResponse(jobId=job_id, result=result)


@router.post("/jobs/{job_id}/discard", response_model=ApprovalResponse)
def discard(
    job_id: str,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    db: Session = Depends(get_db),
    actor_user_id: str = Depends(get_actor_user_id),
) -> ApprovalResponse:
    """Close the job without pushing. Staged rows are marked discarded, never
    deleted — the raw payloads stay for audit (AC-13-07)."""
    try:
        result = SyncService(db).discard(
            current_user.tenant_id, job_id, actor_user_id=actor_user_id
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return ApprovalResponse(jobId=job_id, result=result)
