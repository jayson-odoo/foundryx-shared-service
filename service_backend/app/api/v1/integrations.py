"""Integration endpoints (plan 09 §6; Resource-list contract since plan 06 D6)
- tenant-scoped, RBAC-gated.

Credentials are write-only: requests may carry them, responses never do.

Cluster F slice 3 (sprint-4/07) adds the PUBLIC payment-webhook receiver
``POST /integrations/webhooks/{provider}/{connection_id}`` - unauthenticated,
tenant resolved from the connection id, fast-ACK + Celery.
"""
import base64
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from app.schemas.integration import (
    ConnectionCreateRequest,
    ConnectionListResponse,
    ConnectionNeighborResponse,
    ConnectionOut,
    ConnectionUpdateRequest,
    ProviderOut,
    TestRequest,
    TestResultOut,
)
from app.schemas.user import FilterGroup
from app.services.filter_translator import FilterError
from app.services.integration_service import IntegrationService

router = APIRouter()


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


@router.get("/providers", response_model=List[ProviderOut])
def list_providers(
    user: User = Depends(require_permission("integrations.read")),
    db: Session = Depends(get_db),
) -> List[ProviderOut]:
    return IntegrationService(db).providers()


@router.get("/connections", response_model=ConnectionListResponse)
def list_connections(
    user: User = Depends(require_permission("integrations.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> ConnectionListResponse:
    service = IntegrationService(db)
    try:
        rows, total = service.list(
            user.tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return ConnectionListResponse(data=rows, total=total, page=page)


# Literal routes BEFORE /connections/{connection_id} - route order matters.
@router.get("/connections/at", response_model=ConnectionNeighborResponse)
def connection_at(
    user: User = Depends(require_permission("integrations.read")),
    db: Session = Depends(get_db),
    index: int = Query(0, ge=0),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> ConnectionNeighborResponse:
    service = IntegrationService(db)
    try:
        connection, total = service.get_at(
            user.tenant_id,
            index,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return ConnectionNeighborResponse(connection=connection, total=total)


@router.get("/connections/export", response_class=PlainTextResponse)
def export_connections(
    user: User = Depends(require_permission("integrations.read")),
    db: Session = Depends(get_db),
    columns: str = Query(..., min_length=1),
    ids: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> str:
    service = IntegrationService(db)
    try:
        return service.export_csv(
            user.tenant_id,
            [c.strip() for c in columns.split(",") if c.strip()],
            ids=[i.strip() for i in ids.split(",") if i.strip()] if ids else None,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.post("/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
def create_connection(
    payload: ConnectionCreateRequest,
    user: User = Depends(require_permission("integrations.manage")),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    return IntegrationService(db).create(user.tenant_id, payload)


@router.get("/connections/{connection_id}", response_model=ConnectionOut)
def get_connection(
    connection_id: str,
    user: User = Depends(require_permission("integrations.read")),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    return IntegrationService(db).get(user.tenant_id, connection_id)


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
def update_connection(
    connection_id: str,
    payload: ConnectionUpdateRequest,
    user: User = Depends(require_permission("integrations.manage")),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    return IntegrationService(db).update(user.tenant_id, connection_id, payload)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    connection_id: str,
    user: User = Depends(require_permission("integrations.manage")),
    db: Session = Depends(get_db),
) -> None:
    IntegrationService(db).delete(user.tenant_id, connection_id)


@router.post("/connections/{connection_id}/activate", response_model=ConnectionOut)
def activate_connection(
    connection_id: str,
    user: User = Depends(require_permission("integrations.manage")),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    """Make this STORAGE connection the tenant's active write-target."""
    return IntegrationService(db).set_active(user.tenant_id, connection_id)


@router.post("/connections/{connection_id}/test", response_model=TestResultOut)
def test_connection(
    connection_id: str,
    payload: TestRequest,
    user: User = Depends(require_permission("integrations.manage")),
    db: Session = Depends(get_db),
) -> TestResultOut:
    return IntegrationService(db).test(user.tenant_id, connection_id, payload.target)


# ── PUBLIC payment-webhook receiver (Cluster F slice 3, AC-07-28) ────────────
# Unauthenticated by design: the gateway calls it. Trust = signature verify in
# the provider adapter + tenant resolved FROM the connection row. Fast-ACK +
# Celery (mirrors omnichannel). Body size guarded.
webhooks_router = APIRouter()

_MAX_WEBHOOK_BYTES = 1_000_000


@webhooks_router.post("/{provider}/{connection_id}")
async def receive_payment_webhook(
    provider: str,
    connection_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    body = await request.body()
    if len(body) > _MAX_WEBHOOK_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Payload too large")
    headers = {k.lower(): v for k, v in request.headers.items()}

    if settings.celery_task_always_eager:
        # Eager (tests / no-worker dev): run inline on the request session so the
        # test DB is the one mutated (the Celery task would open its own
        # SessionLocal against the real DATABASE_URL).
        from app.services.payment_gateway_service import PaymentGatewayService, RetryableWebhook

        try:
            return PaymentGatewayService(db).ingest_webhook(provider, connection_id, body, headers)
        except RetryableWebhook:
            # No worker to retry in eager mode - surface 202 so the gateway
            # re-delivers later (idempotent ingest makes the re-delivery safe).
            return {"status": "retry"}

    from app.services.payment_worker import process_payment_webhook

    process_payment_webhook.delay(provider, connection_id, base64.b64encode(body).decode(), headers)
    return {"status": "queued"}
