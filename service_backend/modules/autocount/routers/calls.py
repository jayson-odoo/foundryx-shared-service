"""AutoCount calls view (plan 63 section 3.4) - authed operator routes, read only.

Thin: HTTP + Pydantic only; every handler hands off to ``CallLogService``. The tenant
comes from the authenticated user, never from client input.
"""
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..repositories.call_log_repository import CallFilters
from ..schemas import CallDetailOut, CallFilterOptionsOut, CallListResponse, CallRowOut, CallSortField
from ..services.call_log_service import CallLogService

router = APIRouter()

READ = "autocount.sync.read"


@router.get("", response_model=CallListResponse)
def list_calls(
    company_id: Optional[List[str]] = Query(None, alias="companyId"),
    book: Optional[List[str]] = Query(None),
    doc_type: Optional[List[str]] = Query(None, alias="docType"),
    outcome: Optional[List[str]] = Query(None),
    person: Optional[List[str]] = Query(None),
    date_from: Optional[datetime] = Query(None, alias="dateFrom"),
    date_to: Optional[datetime] = Query(None, alias="dateTo"),
    search: Optional[str] = Query(None, max_length=200),
    sort: CallSortField = Query("createdAt"),
    order: Literal["asc", "desc"] = Query("desc"),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200, alias="pageSize"),
    current_user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
) -> CallListResponse:
    filters = CallFilters(
        company_ids=company_id or [], books=book or [], doc_types=doc_type or [], outcomes=outcome or [],
        persons=person or [], date_from=date_from, date_to=date_to, search=(search or "").strip() or None,
    )
    rows, total = CallLogService(db).list_calls(
        current_user.tenant_id, filters, sort=sort, order=order, page=page, page_size=page_size
    )
    return CallListResponse(data=[CallRowOut.model_validate(r) for r in rows], total=total, page=page)


@router.get("/filter-options", response_model=CallFilterOptionsOut)
def filter_options(
    current_user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
) -> CallFilterOptionsOut:
    return CallFilterOptionsOut(**CallLogService(db).filter_options(current_user.tenant_id))


@router.get("/{call_id}", response_model=CallDetailOut)
def get_call(
    call_id: str,
    current_user: User = Depends(require_permission(READ)),
    db: Session = Depends(get_db),
) -> CallDetailOut:
    found = CallLogService(db).detail(current_user.tenant_id, call_id)
    if found is None:
        raise HTTPException(status_code=404, detail={"code": "CALL_NOT_FOUND", "message": "Call not found."})
    return CallDetailOut.model_validate(found)
