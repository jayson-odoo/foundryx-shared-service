"""Open REST API routes (sprint-5/08, AC-08-14/15). Thin: HTTP + Pydantic
only.

No DB query and no raw SQL lives here (code-review hard-fail). The tenant
comes from the authenticated user - NEVER from client input - and every
handler hands off to ``EtlService``. Reuses the EXISTING
``autocount.companies.{read,manage}`` keys (no new permission, no grant
sweep needed for existing tenants).
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import HttpConnectionItem, HttpPreviewColumnOut, HttpPreviewRequest, HttpPreviewResponse
from ..services import EtlService, EtlValidationError
from ..provider import auth_mode
from .companies import _field_errors

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


@router.post("/preview", response_model=HttpPreviewResponse)
def preview_http(
    body: HttpPreviewRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
):
    """Page-1 sample against an open (no-auth) connection (AC-08-14). A bad
    connection or a bad path is a 422 naming the field."""
    try:
        result = EtlService(db).preview_http(
            current_user.tenant_id,
            body.connectionId,
            body.path,
            distinct_of=body.distinctOf,
            company_id=body.companyId,
            entity_type=body.entityType,
        )
    except EtlValidationError as exc:
        return _field_errors(exc.field_errors, exc.message)
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
    )
