"""Open REST API routes (sprint-5/08, AC-08-14/15). Thin: HTTP + Pydantic
only.

No DB query and no raw SQL lives here (code-review hard-fail). The tenant
comes from the authenticated user - NEVER from client input - and every
handler hands off to ``EtlService``. Reuses the EXISTING
``autocount.companies.{read,manage}`` keys (no new permission, no grant
sweep needed for existing tenants).
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import (
    HttpConnectionItem,
    HttpPreviewColumnsRequest,
    HttpPreviewRequest,
    PreviewColumnsResponse,
    PreviewJobStartOut,
)
from ..services import AutocountServiceError, EtlService, EtlValidationError
from ..services.preview_job_service import PreviewJobService
from ..provider import auth_mode
from ..http_client import get_http_transport
from .companies import _field_errors, _raise

router = APIRouter()


@router.get("/connections", response_model=list[HttpConnectionItem])
def list_http_connections(
    current_user: User = Depends(require_permission("autocount.companies.read")),
    db: Session = Depends(get_db),
) -> list[HttpConnectionItem]:
    """Every tenant ``autocount`` connection, both auths badged (AC-08-15) -
    the Source tab's API picker and the derived-impl logic read this."""
    connections = EtlService(db).list_http_connections(current_user.tenant_id)
    return [
        HttpConnectionItem(
            id=conn.id,
            name=conn.name,
            baseUrl=str((conn.config_json or {}).get("baseUrl") or ""),
            auth=auth_mode(conn.config_json or {}),
        )
        for conn in connections
    ]


@router.post("/preview-columns", response_model=PreviewColumnsResponse)
def preview_http_columns(
    body: HttpPreviewColumnsRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
    transport: Optional[Any] = Depends(get_http_transport),
):
    """The Lookups editor's own probe (AC-10-05): just the first page's
    column names against ANY endpoint on an open connection, reusing the
    SAME connection + path rules ``/preview`` already applies - the editor
    can never reach an endpoint the main path could not."""
    try:
        columns = EtlService(db).preview_http_columns(
            current_user.tenant_id, body.connectionId, body.path, transport=transport,
        )
    except EtlValidationError as exc:
        return _field_errors(exc.field_errors, exc.message)
    except AutocountServiceError as exc:
        _raise(exc)
    return PreviewColumnsResponse(columns=columns)


@router.post("/preview", response_model=PreviewJobStartOut, status_code=status.HTTP_202_ACCEPTED)
def preview_http(
    body: HttpPreviewRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
    transport: Optional[Any] = Depends(get_http_transport),
):
    """sprint-5/11 (AC-11-21/22) - starts the ``sample``-scope
    ``autocount_source_preview`` job and returns 202 ``{jobId, status}``; no
    extraction happens in THIS request. A bad connection or a bad path is
    still a 422 naming the field, BEFORE any job row is ever created
    (``PreviewJobService.start_sample``'s own pre-flight). Poll
    ``GET /autocount/previews/{jobId}`` for the landed result - the SAME
    ``HttpPreviewResponse`` shape this route used to return synchronously,
    now the job's ``result.preview``.

    A ``companyId`` naming another tenant's company (or a company that does
    not exist) raises ``CompanyNotFound`` from the service's tenant-scope
    guard - reused through the SAME ``_raise`` translator ``routers/
    companies.py`` uses (404, no leak) rather than a bare 500 (review
    round 8).
    """
    try:
        job_id, wire_status = PreviewJobService(db).start_sample(
            current_user.tenant_id,
            company_id=body.companyId or "",
            entity_type=body.entityType or "",
            connection_id=body.connectionId,
            path=body.path,
            distinct_of=body.distinctOf,
            lookups=body.lookups,
            combine=body.combine,
            transport=transport,
        )
    except EtlValidationError as exc:
        return _field_errors(exc.field_errors, exc.message)
    except AutocountServiceError as exc:
        _raise(exc)
    return PreviewJobStartOut(jobId=job_id, status=wire_status)
