"""Direct-DB ETL routes - SQL connections, schema browse, query preview
(plan 22 S1, AC-22-05/06). Thin: HTTP + Pydantic only.

No DB query and no raw SQL lives here (code-review hard-fail). The tenant
comes from the authenticated user - NEVER from client input - and every
handler hands off to ``EtlService``. All three reuse
``autocount.companies.manage`` (the "configure the company" authority) so no
new permission needs a grant sweep for existing tenants.

Error classes → HTTP (the frontend contract in ``autocount-service.ts``):
  guard rejection (not one SELECT)      422  before the source is touched
  the source rejected the query         400  sanitised driver message
  could not connect / open a session    502  sanitised, never a DSN
  connection not this tenant's / not
  ``sql_database``                      404
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import (
    SqlColumnOut,
    SqlConnectionItem,
    SqlPreviewRequest,
    SqlPreviewResponse,
    SqlSchemaNodeOut,
    SqlSchemaResponse,
    SqlTableOut,
)
from ..services import AutocountServiceError, ConnectionNotFound, EtlService
from ..sql_source.errors import SqlConnectError, SqlGuardError, SqlQueryError

router = APIRouter()


def raise_sql_error(exc: Exception) -> None:
    """ONE translator for every SQL-source / service error → HTTP. Messages
    are already operator-safe (no stack traces, no credentials, no DSN)."""
    if isinstance(exc, ConnectionNotFound):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    if isinstance(exc, SqlGuardError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    if isinstance(exc, SqlQueryError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    if isinstance(exc, SqlConnectError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    if isinstance(exc, AutocountServiceError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    raise exc


@router.get("/connections", response_model=list[SqlConnectionItem])
def list_sql_connections(
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> list[SqlConnectionItem]:
    """The tenant's ``sql_database`` connections - the task editor's ONLY valid
    picker options (tenant + provider scoped, never a bare connections fetch)."""
    return [
        SqlConnectionItem.model_validate(view)
        for view in EtlService(db).list_connections(current_user.tenant_id)
    ]


@router.get("/connections/{connection_id}/schema", response_model=SqlSchemaResponse)
def get_sql_schema(
    connection_id: str,
    refresh: bool = Query(False),
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> SqlSchemaResponse:
    """Schemas → tables → columns, cached per connection server-side;
    ``refresh=true`` busts the cache (AC-22-05)."""
    try:
        view = EtlService(db).schema(current_user.tenant_id, connection_id, refresh=refresh)
    except Exception as exc:  # noqa: BLE001 - translated, never a 500 with a DSN
        raise_sql_error(exc)
    return SqlSchemaResponse(
        connectionId=view.connection_id,
        dialect=view.dialect,
        database=view.database,
        schemas=[
            SqlSchemaNodeOut(
                name=schema.name,
                tables=[
                    SqlTableOut(
                        name=table.name,
                        columns=[SqlColumnOut.model_validate(c) for c in table.columns],
                    )
                    for table in schema.tables
                ],
            )
            for schema in view.tree.schemas
        ],
        introspectedAt=view.tree.introspected_at,
    )


@router.post("/preview", response_model=SqlPreviewResponse)
def preview_sql(
    body: SqlPreviewRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> SqlPreviewResponse:
    """Run a candidate SELECT capped at 100 rows (AC-22-06). Non-SELECT /
    multi-statement = 422 before the source; a failing query = 400 sanitised."""
    try:
        result = EtlService(db).preview(current_user.tenant_id, body.connectionId, body.query)
    except Exception as exc:  # noqa: BLE001 - translated, never a 500 with a DSN
        raise_sql_error(exc)
    return SqlPreviewResponse(
        columns=[SqlColumnOut.model_validate(c) for c in result.columns],
        rows=result.rows,
        rowCount=result.row_count,
        truncated=result.truncated,
        durationMs=result.duration_ms,
    )
