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
from typing import List, NoReturn, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..schemas import (
    PullApiKeyCreateInput,
    PullApiKeyIssuedOut,
    PullApiKeyOut,
    PullSnapshotBuildRequest,
    PullSnapshotListResponse,
    PullSnapshotOut,
    PullSnapshotRowsPageOut,
)
from ..services.company_service import AutocountServiceError
from ..services.pull_key_service import (
    PullKeyNotFound,
    PullKeyService,
    PullKeyValidationError,
)
from ..services.pull_service import (
    PullBuildCooldownError,
    PullPushActiveError,
    PullService,
    PullSnapshotNotFound,
    snapshot_header,
)

router = APIRouter()


def _snapshot_out(service: PullService, tenant_id: str, snapshot) -> PullSnapshotOut:
    """sprint-5/11 S5 (AC-11-42) - ``snapshot_header``'s own dict PLUS
    ``progress`` when the SERVICE's own status-gated projection has one;
    every route below builds its ``PullSnapshotOut`` through this ONE
    helper so the two can never drift. ``response_model_exclude_none=True``
    on every route decorator is what actually OMITS the key on the wire
    when it is ``None`` (never a bare ``null``)."""
    header = snapshot_header(snapshot)
    progress = service.snapshot_progress(tenant_id, snapshot)
    if progress is not None:
        header["progress"] = progress
    return PullSnapshotOut(**header)


def _raise(exc: AutocountServiceError) -> NoReturn:
    """ONE translator for this router's service errors -> HTTP. Typed
    ``NoReturn`` (review round 2, item 6) so every call site's own
    subsequent code is never flagged as reachable with an unbound variable -
    this function always raises, in every branch."""
    if isinstance(exc, (PullSnapshotNotFound, PullKeyNotFound)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    if isinstance(exc, PullBuildCooldownError):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.message,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    if isinstance(exc, PullPushActiveError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc


def _field_errors(field_errors: dict, message: str) -> JSONResponse:
    """Mirrors ``routers/companies.py``'s own helper - ONE per-field 422
    shape for every surface that has one."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": {"fieldErrors": field_errors}, "message": message},
    )


# ── pull API keys (sprint-5/10 S4, AC-10-36/37) - ALL gated `.manage`, ──────
# never `.read`: a key is a live secret-bearing credential, not read-only
# reporting data like a snapshot.


@router.get("/keys", response_model=List[PullApiKeyOut])
def list_pull_keys(
    current_user: User = Depends(require_permission("autocount.pull.manage")),
    db: Session = Depends(get_db),
) -> List[PullApiKeyOut]:
    keys = PullKeyService(db).list_for_tenant(current_user.tenant_id)
    return [PullApiKeyOut.model_validate(key) for key in keys]


@router.post(
    "/keys", response_model=PullApiKeyIssuedOut, status_code=status.HTTP_201_CREATED
)
def issue_pull_key(
    body: PullApiKeyCreateInput,
    current_user: User = Depends(require_permission("autocount.pull.manage")),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
):
    try:
        key, plaintext = PullKeyService(db).issue(
            current_user.tenant_id,
            name=body.name,
            company_ids=body.companyIds,
            created_by=actor_id,
        )
    except PullKeyValidationError as exc:
        return _field_errors(exc.field_errors, exc.message)
    return PullApiKeyIssuedOut(key=PullApiKeyOut.model_validate(key), plaintext=plaintext)


@router.post("/keys/{key_id}/revoke", response_model=PullApiKeyOut)
def revoke_pull_key(
    key_id: str,
    current_user: User = Depends(require_permission("autocount.pull.manage")),
    db: Session = Depends(get_db),
) -> PullApiKeyOut:
    try:
        key = PullKeyService(db).revoke(current_user.tenant_id, key_id)
    except AutocountServiceError as exc:
        _raise(exc)
    return PullApiKeyOut.model_validate(key)


@router.get(
    "/snapshots", response_model=PullSnapshotListResponse, response_model_exclude_none=True
)
def list_pull_snapshots(
    current_user: User = Depends(require_permission("autocount.pull.read")),
    db: Session = Depends(get_db),
    company_id: Optional[str] = Query(default=None, alias="companyId"),
    entity_type: Optional[str] = Query(default=None, alias="entityType"),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
) -> PullSnapshotListResponse:
    service = PullService(db)
    rows, total = service.list_snapshots(
        current_user.tenant_id,
        company_id=company_id,
        entity_type=entity_type,
        page=page,
        page_size=page_size,
    )
    return PullSnapshotListResponse(
        data=[_snapshot_out(service, current_user.tenant_id, row) for row in rows],
        total=total,
        page=page,
    )


@router.get(
    "/snapshots/{snapshot_id}", response_model=PullSnapshotOut, response_model_exclude_none=True
)
def get_pull_snapshot(
    snapshot_id: str,
    current_user: User = Depends(require_permission("autocount.pull.read")),
    db: Session = Depends(get_db),
) -> PullSnapshotOut:
    service = PullService(db)
    try:
        snapshot = service.get_snapshot(current_user.tenant_id, snapshot_id)
    except AutocountServiceError as exc:
        _raise(exc)
    return _snapshot_out(service, current_user.tenant_id, snapshot)


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
    "/snapshots",
    response_model=PullSnapshotOut,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
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
    service = PullService(db)
    try:
        snapshot = service.request_build(
            current_user.tenant_id,
            body.companyId,
            body.entityType,
            requested_via="operator",
            requested_by=actor_id,
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return _snapshot_out(service, current_user.tenant_id, snapshot)
