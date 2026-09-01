"""Email log endpoints (plan 07 D14) - gated emails.read / emails.manage."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_permission
from app.models.user import User
from app.schemas.email_log import (
    EmailLogDetail,
    EmailLogItem,
    EmailLogListResponse,
    EmailLogNeighborResponse,
)
from app.schemas.filters import FilterGroup
from app.services.email_log_service import (
    EmailLogConflict,
    EmailLogError,
    EmailLogNotFound,
    EmailLogService,
)
from app.services.filter_translator import FilterError

router = APIRouter()


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


@router.get("", response_model=EmailLogListResponse)
def list_emails(
    current_user: User = Depends(require_permission("emails.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
    segment: Optional[str] = None,
) -> EmailLogListResponse:
    service = EmailLogService(db)
    try:
        rows, total = service.list(
            current_user.tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
            segment=segment,
        )
    except (FilterError, EmailLogError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return EmailLogListResponse(
        data=[EmailLogItem.from_row(r) for r in rows], total=total, page=page
    )


@router.get("/at", response_model=EmailLogNeighborResponse)
def email_at(
    current_user: User = Depends(require_permission("emails.read")),
    db: Session = Depends(get_db),
    index: int = Query(0, ge=0),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
    segment: Optional[str] = None,
) -> EmailLogNeighborResponse:
    service = EmailLogService(db)
    try:
        row, total = service.get_at(
            index,
            current_user.tenant_id,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
            segment=segment,
        )
    except (FilterError, EmailLogError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return EmailLogNeighborResponse(email=EmailLogItem.from_row(row) if row else None, total=total)


@router.get("/{email_id}", response_model=EmailLogDetail)
def get_email(
    email_id: str,
    current_user: User = Depends(require_permission("emails.read")),
    db: Session = Depends(get_db),
) -> EmailLogDetail:
    try:
        row = EmailLogService(db).get(email_id, current_user.tenant_id)
    except EmailLogNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email not found.")
    return EmailLogDetail.from_row(row)


@router.post("/{email_id}/retry", response_model=EmailLogItem)
def retry_email(
    email_id: str,
    current_user: User = Depends(require_permission("emails.manage")),
    db: Session = Depends(get_db),
) -> EmailLogItem:
    try:
        row = EmailLogService(db).retry(email_id, current_user.tenant_id)
    except EmailLogNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email not found.")
    except EmailLogError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return EmailLogItem.from_row(row)


@router.post("/{email_id}/cancel", response_model=EmailLogItem)
def cancel_email(
    email_id: str,
    current_user: User = Depends(require_permission("emails.manage")),
    db: Session = Depends(get_db),
) -> EmailLogItem:
    try:
        row = EmailLogService(db).cancel(email_id, current_user.tenant_id)
    except EmailLogNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email not found.")
    except EmailLogConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return EmailLogItem.from_row(row)
