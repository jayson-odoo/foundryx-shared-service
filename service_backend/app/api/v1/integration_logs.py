"""Developer Logs / Integration Activity console read API (sprint-4/12 Slice 1).

Thin HTTP/Pydantic layer only — all logic lives in ``ActivityLogService`` (no DB
access here). ``GET /integration-logs`` + ``/{id}`` are tenant-scoped and gated
by the core ``integration_logs.read`` permission.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.activity_log.service import ActivityLogService
from app.dependencies import get_db, require_permission
from app.models.user import User
from app.schemas.filters import FilterGroup
from app.schemas.integration_activity import (
    IntegrationActivityDetail,
    IntegrationActivityItem,
    IntegrationActivityListResponse,
    IntegrationActivityTraceResponse,
)
from app.services.filter_translator import FilterError

router = APIRouter()

_READ = "integration_logs.read"


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter."
        ) from exc


@router.get("", response_model=IntegrationActivityListResponse)
def list_integration_logs(
    current_user: User = Depends(require_permission(_READ)),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> IntegrationActivityListResponse:
    try:
        rows, total = ActivityLogService(db).list(
            current_user.tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return IntegrationActivityListResponse(
        data=[IntegrationActivityItem.model_validate(r) for r in rows],
        total=total,
        page=page,
    )


@router.get("/trace/{trace_id}", response_model=IntegrationActivityTraceResponse)
def get_integration_log_trace(
    trace_id: str,
    current_user: User = Depends(require_permission(_READ)),
    db: Session = Depends(get_db),
) -> IntegrationActivityTraceResponse:
    """Ordered legs of ONE consumption (inbound API → outbound Meta → webhook),
    tenant-scoped. Empty legs for an unknown trace (never leaks another tenant's
    rows)."""
    rows = ActivityLogService(db).list_by_trace(current_user.tenant_id, trace_id)
    return IntegrationActivityTraceResponse(
        traceId=trace_id,
        legs=[IntegrationActivityItem.model_validate(r) for r in rows],
    )


@router.get("/{log_id}", response_model=IntegrationActivityDetail)
def get_integration_log(
    log_id: str,
    current_user: User = Depends(require_permission(_READ)),
    db: Session = Depends(get_db),
) -> IntegrationActivityDetail:
    row = ActivityLogService(db).get(current_user.tenant_id, log_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Log not found.")
    return IntegrationActivityDetail.model_validate(row)
