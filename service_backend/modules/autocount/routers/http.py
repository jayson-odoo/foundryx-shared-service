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
    HttpPreviewColumnOut,
    HttpPreviewColumnsRequest,
    HttpPreviewRequest,
    HttpPreviewResponse,
    LookupPreviewCountOut,
    PreviewColumnsResponse,
)
from ..services import AutocountServiceError, EtlService, EtlValidationError
from ..provider import auth_mode
from ..http_client import get_http_transport
from .companies import _field_errors, _raise, _task_response

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


@router.post("/preview", response_model=HttpPreviewResponse)
def preview_http(
    body: HttpPreviewRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
    transport: Optional[Any] = Depends(get_http_transport),
):
    """Page-1 sample against an open (no-auth) connection (AC-08-14). A bad
    connection or a bad path is a 422 naming the field.

    ``task`` (sprint-5/08 review round 7) echoes the task AFTER stamping when
    the request named both ``companyId``/``entityType`` - the SAME shape
    every lifecycle route returns, built through the ONE ``_task_response``
    converter - so the Source tab's Test button can adopt the freshly-stamped
    ``lastPreviewAt``/``resultColumns`` directly, with no second GET to race
    a concurrent Save.

    A ``companyId`` naming another tenant's company (or a company that does
    not exist) raises ``CompanyNotFound`` from the service's tenant-scope
    guard - reused through the SAME ``_raise`` translator ``routers/
    companies.py`` uses (404, no leak) rather than a bare 500 (review
    round 8).
    """
    try:
        result, task_view = EtlService(db).preview_http(
            current_user.tenant_id,
            body.connectionId,
            body.path,
            distinct_of=body.distinctOf,
            lookups=body.lookups,
            combine=body.combine,
            company_id=body.companyId,
            entity_type=body.entityType,
            transport=transport,
        )
    except EtlValidationError as exc:
        return _field_errors(exc.field_errors, exc.message)
    except AutocountServiceError as exc:
        _raise(exc)
    funnel = result.combine_funnel or {}
    return HttpPreviewResponse(
        envelope=result.envelope,
        totalCount=result.total_count,
        columns=[
            HttpPreviewColumnOut(
                name=name,
                sample=(str(result.rows[0][name]) if result.rows and name in result.rows[0] else None),
            )
            for name in result.columns
        ],
        rows=result.rows,
        durationMs=result.duration_ms,
        task=_task_response(task_view) if task_view is not None else None,
        lookups=[
            LookupPreviewCountOut(alias=entry.alias, matched=entry.matched, missed=entry.missed)
            for entry in result.lookups
        ],
        # sprint-5/10 S5a follow-up (AC-10-82) - present ONLY when the
        # request carried a `combine` block (`EtlService.preview_http`
        # leaves `combine_funnel` `None` otherwise).
        rowsIn=funnel.get("rowsIn"),
        excludedCount=funnel.get("excludedCount"),
        groups=funnel.get("groups"),
        droppedByRule=funnel.get("droppedByRule"),
        rowsOut=funnel.get("rowsOut"),
        roundedCount=funnel.get("roundedCount"),
        # review round 5 (R5-A) - `None` unless the request carried a
        # `combine` block (`EtlService.preview_http` leaves
        # `pre_combine_columns` `None` otherwise, same gate as the funnel).
        preCombineColumns=result.pre_combine_columns,
    )
