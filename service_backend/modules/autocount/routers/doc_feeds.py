"""Document feed routes (sprint-5/14) - thin: HTTP + Pydantic only.

No DB query and no raw SQL lives here (code-review hard-fail). Every handler
takes the tenant from the authenticated user - NEVER from client input - and
hands off to ``DocFeedService``.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..http_client import get_http_transport
from ..schemas import (
    DocFeedBackfillOut,
    DocFeedBackfillStartIn,
    DocFeedIssueListOut,
    DocFeedItemOut,
    DocFeedRunListOut,
    DocFeedRunStartIn,
    DocFeedsViewOut,
    DocFeedUpdateIn,
)
from ..services.company_service import CompanyNotFound
from ..services.doc_feed_service import (
    DocFeedConflictError,
    DocFeedService,
    DocFeedValidationError,
)

router = APIRouter()


def _field_error(field: str, message: str) -> JSONResponse:
    """AC-14-01..06's own literal wording (``fieldErrors.connectionId`` /
    ``fieldErrors.mode``) - a TOP-LEVEL ``fieldErrors`` key, distinct from
    the sibling ``companies.py`` router's ``detail.fieldErrors`` nesting
    (that convention predates this AC text and is untouched elsewhere)."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"fieldErrors": {field: message}, "message": message},
    )


def _conflict(exc: DocFeedConflictError) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": exc.message},
    )


@router.get("/{company_id}", response_model=DocFeedsViewOut)
def get_doc_feeds(
    company_id: str,
    current_user: User = Depends(require_permission("autocount.companies.read")),
    db: Session = Depends(get_db),
):
    try:
        return DocFeedService(db).view(current_user.tenant_id, company_id)
    except CompanyNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


@router.put("/{company_id}/{feed}")
def put_doc_feed(
    company_id: str,
    feed: str,
    body: DocFeedUpdateIn,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
):
    try:
        return DocFeedService(db).update(
            current_user.tenant_id, company_id, feed,
            connection_id=body.connectionId, mode=body.mode,
        )
    except CompanyNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    except DocFeedValidationError as exc:
        return _field_error(exc.field, exc.message)


@router.post("/{company_id}/{feed}/run", status_code=status.HTTP_202_ACCEPTED)
def post_doc_feed_run(
    company_id: str,
    feed: str,
    body: DocFeedRunStartIn,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    db: Session = Depends(get_db),
    actor_user_id: Optional[str] = Depends(get_actor_user_id),
    transport=Depends(get_http_transport),
):
    try:
        job_id = DocFeedService(db).run_feed(
            current_user.tenant_id, company_id, feed, body.kind,
            actor_user_id=actor_user_id, transport=transport,
        )
    except CompanyNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    except DocFeedValidationError as exc:
        return _field_error(exc.field, exc.message)
    except DocFeedConflictError as exc:
        _conflict(exc)
    return {"jobId": job_id}


@router.get("/{company_id}/runs", response_model=DocFeedRunListOut)
def get_doc_feed_runs(
    company_id: str,
    feed: Optional[str] = Query(default=None),
    page: int = Query(default=0, ge=0),
    pageSize: int = Query(default=25, ge=1, le=200),
    current_user: User = Depends(require_permission("autocount.sync.read")),
    db: Session = Depends(get_db),
):
    try:
        return DocFeedService(db).list_runs(
            current_user.tenant_id, company_id, feed=feed, page=page, page_size=pageSize,
        )
    except CompanyNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


@router.get("/{company_id}/issues", response_model=DocFeedIssueListOut)
def get_doc_feed_issues(
    company_id: str,
    feed: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    page: int = Query(default=0, ge=0),
    pageSize: int = Query(default=25, ge=1, le=200),
    current_user: User = Depends(require_permission("autocount.sync.read")),
    db: Session = Depends(get_db),
):
    try:
        return DocFeedService(db).list_issues(
            current_user.tenant_id, company_id, feed=feed, kind=kind, search=search,
            page=page, page_size=pageSize,
        )
    except CompanyNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


@router.post("/{company_id}/{feed}/backfill", status_code=status.HTTP_202_ACCEPTED)
def post_doc_feed_backfill(
    company_id: str,
    feed: str,
    body: DocFeedBackfillStartIn,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    db: Session = Depends(get_db),
    actor_user_id: Optional[str] = Depends(get_actor_user_id),
    transport=Depends(get_http_transport),
):
    from_day: Optional[date] = date.fromisoformat(body.fromDay) if body.fromDay else None
    to_day: Optional[date] = date.fromisoformat(body.toDay) if body.toDay else None
    try:
        backfill = DocFeedService(db).start_backfill(
            current_user.tenant_id, company_id, feed, dry_run=body.dryRun,
            from_day=from_day, to_day=to_day, actor_user_id=actor_user_id,
            transport=transport,
        )
    except CompanyNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    except DocFeedValidationError as exc:
        return _field_error(exc.field, exc.message)
    except DocFeedConflictError as exc:
        _conflict(exc)
    return {"backfillId": backfill.id, "jobId": backfill.job_id}


@router.post("/{company_id}/{feed}/backfill/stop", response_model=DocFeedBackfillOut)
def post_doc_feed_backfill_stop(
    company_id: str,
    feed: str,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    db: Session = Depends(get_db),
):
    try:
        return DocFeedService(db).stop_backfill(current_user.tenant_id, company_id, feed)
    except CompanyNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    except DocFeedValidationError as exc:
        return _field_error(exc.field, exc.message)


@router.post("/{company_id}/{feed}/backfill/resume", response_model=DocFeedBackfillOut)
def post_doc_feed_backfill_resume(
    company_id: str,
    feed: str,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    db: Session = Depends(get_db),
):
    try:
        return DocFeedService(db).resume_backfill(current_user.tenant_id, company_id, feed)
    except CompanyNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    except DocFeedValidationError as exc:
        return _field_error(exc.field, exc.message)


@router.post("/{company_id}/{feed}/backfill/discard", response_model=DocFeedBackfillOut)
def post_doc_feed_backfill_discard(
    company_id: str,
    feed: str,
    current_user: User = Depends(require_permission("autocount.sync.run")),
    db: Session = Depends(get_db),
):
    try:
        return DocFeedService(db).discard_backfill(current_user.tenant_id, company_id, feed)
    except CompanyNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    except DocFeedValidationError as exc:
        return _field_error(exc.field, exc.message)
