"""Contacts-module routes (plan 26, roadmap A2). Mounted under
`/omnichannel/workspaces/{ws_id}/contacts` (manifest router entry, prefix
`/omnichannel/workspaces`) - separate from the Inbox thread list
(`/omnichannel/contacts`, unchanged). HTTP + Pydantic only, no DB/business
logic here (Router -> Service -> Repository).

S1 ships the list read (AC-CTM-14..23); S2 adds create + the three bulk routes
on this SAME router file (plan §4)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from app.schemas.filters import FilterGroup
from app.services.filter_translator import FilterError

from ..schemas import ContactListResponse
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
