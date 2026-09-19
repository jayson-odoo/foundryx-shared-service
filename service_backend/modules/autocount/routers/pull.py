"""Human-invoked pull - authed OPERATOR routes (sprint-5/10 §2.6, AC-10-37).

Thin: HTTP + Pydantic only, no DB query and no raw SQL here (code-review
hard-fail) - every handler hands off to ``PullService``/``SnapshotService``.
The tenant comes from the authenticated user, NEVER from client input, and
every read is additionally scoped by it (``PullSnapshotRepository`` never
resolves an id unscoped - the polymorphic-target_id leak class).

NOT the public gateway's Appendix A3 shapes (``snapshotId``/
``entity: 'products'``/top-level ``companyCode`` are the S4 gateway ONLY,
X-API-Key authed, under ``/api/v1/autocount``). These routes are the
Phase-1 frontend contract already shipped on this branch
(``service_frontend/services/autocount-service.real.ts``): internal ids/
entity keys, camelCase envelope + row keys, session auth.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..schemas import (
    PullSnapshotBuildRequest,
    PullSnapshotListResponse,
    PullSnapshotOut,
    PullSnapshotRowsPageOut,
)
from ..services.company_service import AutocountServiceError
from ..services.pull_service import (
    PullBuildCooldownError,
    PullService,
    PullSnapshotNotFound,
    snapshot_header,
)

router = APIRouter()


def _raise(exc: AutocountServiceError) -> None:
    """ONE translator for this router's service errors -> HTTP."""
    if isinstance(exc, PullSnapshotNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    if isinstance(exc, PullBuildCooldownError):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.message,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc


@router.get("/snapshots", response_model=PullSnapshotListResponse)
def list_pull_snapshots(
    current_user: User = Depends(require_permission("autocount.pull.read")),
    db: Session = Depends(get_db),
    company_id: Optional[str] = Query(default=None, alias="companyId"),
    entity_type: Optional[str] = Query(default=None, alias="entityType"),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
) -> PullSnapshotListResponse:
    rows, total = PullService(db).list_snapshots(
        current_user.tenant_id,
        company_id=company_id,
        entity_type=entity_type,
        page=page,
        page_size=page_size,
    )
    return PullSnapshotListResponse(
        data=[PullSnapshotOut(**snapshot_header(row)) for row in rows],
        total=total,
        page=page,
    )


@router.get("/snapshots/{snapshot_id}", response_model=PullSnapshotOut)
def get_pull_snapshot(
    snapshot_id: str,
    current_user: User = Depends(require_permission("autocount.pull.read")),
    db: Session = Depends(get_db),
) -> PullSnapshotOut:
    try:
        snapshot = PullService(db).get_snapshot(current_user.tenant_id, snapshot_id)
    except AutocountServiceError as exc:
        _raise(exc)
    return PullSnapshotOut(**snapshot_header(snapshot))


@router.get("/snapshots/{snapshot_id}/rows", response_model=PullSnapshotRowsPageOut)
def get_pull_snapshot_rows(
    snapshot_id: str,
    current_user: User = Depends(require_permission("autocount.pull.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, alias="pageSize"),
) -> PullSnapshotRowsPageOut:
    """``page`` is 1-BASED (AC-10-33) - a page past ``totalPages`` returns an
    empty ``rows`` array with the same header echo, never a 404."""
    try:
        snapshot, rows, total = PullService(db).snapshot_rows_page(
            current_user.tenant_id, snapshot_id, page=page, page_size=page_size
        )
    except AutocountServiceError as exc:
        _raise(exc)
    clamped_size = min(page_size, 1000)
    total_pages = (total + clamped_size - 1) // clamped_size if clamped_size else 0
    return PullSnapshotRowsPageOut(
        snapshotId=snapshot.id,
        page=page,
        pageSize=clamped_size,
        totalPages=total_pages,
        recordCount=total,
        rows=[row.payload_json for row in rows],
    )


@router.post(
    "/snapshots", response_model=PullSnapshotOut, status_code=status.HTTP_202_ACCEPTED
)
def build_pull_snapshot(
    body: PullSnapshotBuildRequest,
    current_user: User = Depends(require_permission("autocount.pull.manage")),
    # The REAL user under impersonation - writes/activity are never
    # attributed to the target, same dependency every other write route uses.
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> PullSnapshotOut:
    """Build a snapshot AS THE OPERATOR (``requested_via='operator'``) - the
    SAME ``PullService.request_build`` the public gateway (S4) calls."""
    try:
        snapshot = PullService(db).request_build(
            current_user.tenant_id,
            body.companyId,
            body.entityType,
            requested_via="operator",
            requested_by=actor_id,
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return PullSnapshotOut(**snapshot_header(snapshot))
