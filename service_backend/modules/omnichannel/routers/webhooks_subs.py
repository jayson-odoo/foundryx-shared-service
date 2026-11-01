"""Consumer webhook endpoint management (Slice 4, internal session-authed).

Register/rotate/enable/disable a channel's consumer webhook endpoints + inspect
the delivery log. Gated by the module `webhooks.read` / `webhooks.manage`
permissions. The signing secret is returned ONCE on create + rotate.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..models import WebhookDelivery, WebhookEndpoint
from ..schemas import (
    WebhookDeliveryItem,
    WebhookDeliveryListResponse,
    WebhookEndpointCreateRequest,
    WebhookEndpointItem,
    WebhookEndpointMintResponse,
    WebhookEndpointStaffItem,
    WebhookEndpointStaffListResponse,
    WebhookEndpointUpdateRequest,
    WebhookSecretResponse,
)
from ..services.api_key_service import ApiKeyService
from ..services.webhook_service import WebhookError, WebhookNotFound, WebhookService

router = APIRouter()


def _to_item(row: WebhookEndpoint) -> WebhookEndpointItem:
    """Shared mapper - defined in the service layer so the public gateway and
    this operator router cannot drift (and don't import each other)."""
    from ..services.webhook_service import webhook_endpoint_item

    return webhook_endpoint_item(row)


def _to_staff_items(
    db: Session, tenant_id: str, rows: List[WebhookEndpoint]
) -> WebhookEndpointStaffListResponse:
    """Rows with the name of the API key that registered each, one lookup per list."""
    keys = ApiKeyService(db).names_for_creators(tenant_id, (r.created_by for r in rows))
    items = []
    for r in rows:
        key_workspace, key_name = keys.get(r.created_by, (None, None))
        items.append(
            WebhookEndpointStaffItem(
                **_to_item(r).model_dump(),
                registeredByKeyName=key_name if key_workspace == r.workspace_id else None,
            )
        )
    return WebhookEndpointStaffListResponse(data=items)


def _to_delivery(row: WebhookDelivery) -> WebhookDeliveryItem:
    return WebhookDeliveryItem(
        id=row.id,
        eventId=row.event_id,
        eventType=row.event_type,
        status=row.status,
        attemptCount=row.attempt_count,
        responseStatus=row.response_status,
        responseMs=row.response_ms,
        error=row.error,
        lastAttemptAt=row.last_attempt_at,
        nextAttemptAt=row.next_attempt_at,
        createdAt=row.created_at,
    )


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# ── Per-channel: list + create ───────────────────────────────────────────────
@router.get("/channels/{channel_id}/webhooks", response_model=WebhookEndpointStaffListResponse)
def list_webhooks(
    channel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("webhooks.read")),
) -> WebhookEndpointStaffListResponse:
    try:
        rows = WebhookService(db).list_for_channel(user.tenant_id, channel_id)
    except WebhookError as exc:
        raise _bad(exc)
    return _to_staff_items(db, user.tenant_id, rows)


@router.get("/workspaces/{workspace_id}/webhooks", response_model=WebhookEndpointStaffListResponse)
def list_workspace_webhooks(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("webhooks.read")),
) -> WebhookEndpointStaffListResponse:
    """The all-channels endpoints of a workspace; needs no live channel."""
    try:
        rows = WebhookService(db).list_all_channels_for_workspace(user.tenant_id, workspace_id)
    except WebhookNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return _to_staff_items(db, user.tenant_id, rows)


@router.post(
    "/channels/{channel_id}/webhooks",
    response_model=WebhookEndpointMintResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_webhook(
    channel_id: str,
    payload: WebhookEndpointCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("webhooks.manage")),
    actor_id: str = Depends(get_actor_user_id),
) -> WebhookEndpointMintResponse:
    try:
        row, secret = WebhookService(db).create(
            user.tenant_id, channel_id, payload.name, payload.url, payload.events, actor_id
        )
    except WebhookError as exc:
        raise _bad(exc)
    return WebhookEndpointMintResponse(endpoint=_to_item(row), signingSecret=secret)


# ── Endpoint-level ops ───────────────────────────────────────────────────────
@router.patch("/webhooks/{endpoint_id}", response_model=WebhookEndpointItem)
def update_webhook(
    endpoint_id: str,
    payload: WebhookEndpointUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("webhooks.manage")),
) -> WebhookEndpointItem:
    try:
        row = WebhookService(db).update(
            user.tenant_id, endpoint_id, payload.name, payload.url, payload.events
        )
    except WebhookNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except WebhookError as exc:
        raise _bad(exc)
    return _to_item(row)


@router.post("/webhooks/{endpoint_id}/rotate", response_model=WebhookSecretResponse)
def rotate_secret(
    endpoint_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("webhooks.manage")),
) -> WebhookSecretResponse:
    try:
        _, secret = WebhookService(db).rotate_secret(user.tenant_id, endpoint_id)
    except WebhookNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return WebhookSecretResponse(signingSecret=secret)


@router.post("/webhooks/{endpoint_id}/enable", response_model=WebhookEndpointItem)
def enable_webhook(
    endpoint_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("webhooks.manage")),
) -> WebhookEndpointItem:
    try:
        row = WebhookService(db).set_status(user.tenant_id, endpoint_id, True)
    except WebhookNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return _to_item(row)


@router.post("/webhooks/{endpoint_id}/disable", response_model=WebhookEndpointItem)
def disable_webhook(
    endpoint_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("webhooks.manage")),
) -> WebhookEndpointItem:
    try:
        row = WebhookService(db).set_status(user.tenant_id, endpoint_id, False)
    except WebhookNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return _to_item(row)


@router.delete("/webhooks/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(
    endpoint_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("webhooks.manage")),
) -> None:
    try:
        WebhookService(db).delete(user.tenant_id, endpoint_id)
    except WebhookNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


@router.get(
    "/webhooks/{endpoint_id}/deliveries", response_model=WebhookDeliveryListResponse
)
def list_deliveries(
    endpoint_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("webhooks.read")),
) -> WebhookDeliveryListResponse:
    try:
        rows = WebhookService(db).list_deliveries(user.tenant_id, endpoint_id)
    except WebhookNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return WebhookDeliveryListResponse(data=[_to_delivery(r) for r in rows])
