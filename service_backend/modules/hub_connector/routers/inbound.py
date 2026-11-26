"""CRM -> shared service push API ``/api/v1/hub-connector`` (AC-17).

Bearer ``fxh_live_...`` key (``gateway_auth``); errors use core's
``{"error": {"code", "message"}}`` envelope. HTTP only - the services own the
logic and the transaction.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db

from .. import schemas
from ..gateway_auth import HubPushKey, get_hub_push_key
from ..services import catalog_service, delivery_service

router = APIRouter()


@router.put("/items", response_model=schemas.PushResult)
def push_items(
    body: schemas.ItemsPush,
    key: HubPushKey = Depends(get_hub_push_key),
    db: Session = Depends(get_db),
) -> schemas.PushResult:
    stored, skipped, delivery_ids = catalog_service.push_items(db, key.tenant_id, body.items)
    delivery_service.enqueue(delivery_ids)
    return schemas.PushResult(stored=stored, skipped=skipped, queued=len(delivery_ids))


@router.put("/customers", response_model=schemas.PushResult)
def push_customers(
    body: schemas.CustomersPush,
    key: HubPushKey = Depends(get_hub_push_key),
    db: Session = Depends(get_db),
) -> schemas.PushResult:
    stored, skipped = catalog_service.push_customers(db, key.tenant_id, body.customers)
    return schemas.PushResult(stored=stored, skipped=skipped)
