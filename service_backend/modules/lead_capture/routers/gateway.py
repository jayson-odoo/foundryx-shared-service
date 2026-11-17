"""Public consumer gateway ``/api/v1/lead-capture`` (plan 64 section 5).

Bearer ``fxl_live_...`` gateway key (``gateway_auth``); errors use core's
``{"error": {"code", "message"}}`` envelope. Contract of record:
``documentation/lead-capture/consumer-integration-guide.md`` - a change here
without a guide change fails review (AC-64-66).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from .. import schemas
from ..gateway_auth import AuditedRoute, LeadGatewayKey, get_lead_gateway_key
from ..services import connect_service, delivery_service, field_service, form_service, key_service, read_service

router = APIRouter(route_class=AuditedRoute)


def _api(exc) -> ApiError:
    return ApiError(exc.status_code, exc.code, exc.message)


@router.get("/sources", response_model=schemas.SourceList)
def list_sources(key: LeadGatewayKey = Depends(get_lead_gateway_key), db: Session = Depends(get_db)) -> schemas.SourceList:
    rows = connect_service.list_sources(db, key.tenant_id)
    return schemas.SourceList(data=[read_service.source_item(r) for r in rows])


@router.get("/settings", response_model=schemas.SettingsItem)
def get_settings(key: LeadGatewayKey = Depends(get_lead_gateway_key), db: Session = Depends(get_db)) -> schemas.SettingsItem:
    return read_service.settings_item(db, key.tenant_id)


@router.put("/settings", response_model=schemas.SettingsItem)
def put_settings(
    body: schemas.SettingsUpdate,
    key: LeadGatewayKey = Depends(get_lead_gateway_key),
    db: Session = Depends(get_db),
) -> schemas.SettingsItem:
    connect_service.set_allow_shared_pages(db, key.tenant_id, body.allowSharedPages, None)
    return read_service.settings_item(db, key.tenant_id)


@router.get("/keys", response_model=schemas.KeyList)
def list_keys(key: LeadGatewayKey = Depends(get_lead_gateway_key), db: Session = Depends(get_db)) -> schemas.KeyList:
    return schemas.KeyList(data=[read_service.key_item(r) for r in key_service.list_keys(db, key.tenant_id)])


@router.post("/keys", response_model=schemas.KeyCreated, status_code=201)
def create_key(
    body: schemas.KeyCreate,
    key: LeadGatewayKey = Depends(get_lead_gateway_key),
    db: Session = Depends(get_db),
) -> schemas.KeyCreated:
    row, full_key = key_service.issue(db, key.tenant_id, name=body.name, created_by=None)
    return schemas.KeyCreated(**read_service.key_item(row).model_dump(), key=full_key)


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(
    key_id: str, key: LeadGatewayKey = Depends(get_lead_gateway_key), db: Session = Depends(get_db)
) -> Response:
    try:
        key_service.revoke(db, key.tenant_id, key_id, calling_key_id=key.key_id)
    except key_service.KeyNotFound:
        raise ApiError(404, "key_not_found", "Key not found.") from None
    except key_service.KeyInUse:
        raise ApiError(409, "key_in_use", "This request uses that key. Revoke it with another key.") from None
    return Response(status_code=204)


@router.get("/webhooks", response_model=schemas.WebhookList)
def list_webhooks(key: LeadGatewayKey = Depends(get_lead_gateway_key), db: Session = Depends(get_db)) -> schemas.WebhookList:
    rows = delivery_service.list_endpoints(db, key.tenant_id)
    return schemas.WebhookList(data=[read_service.webhook_item(r) for r in rows])


@router.post("/webhooks", response_model=schemas.WebhookCreated, status_code=201)
def create_webhook(
    body: schemas.WebhookCreate,
    key: LeadGatewayKey = Depends(get_lead_gateway_key),
    db: Session = Depends(get_db),
) -> schemas.WebhookCreated:
    try:
        row, secret = delivery_service.create_endpoint(db, key.tenant_id, body.url, body.events)
    except delivery_service.DeliveryError as exc:
        raise _api(exc)
    return schemas.WebhookCreated(**read_service.webhook_item(row).model_dump(), secret=secret)


@router.delete("/webhooks/{endpoint_id}", status_code=204)
def delete_webhook(
    endpoint_id: str, key: LeadGatewayKey = Depends(get_lead_gateway_key), db: Session = Depends(get_db)
) -> Response:
    try:
        delivery_service.delete_endpoint(db, key.tenant_id, endpoint_id)
    except delivery_service.DeliveryError as exc:
        raise _api(exc)
    return Response(status_code=204)


@router.post("/webhooks/{endpoint_id}/test", response_model=schemas.DeliveryItem, status_code=202)
def test_webhook(
    endpoint_id: str, key: LeadGatewayKey = Depends(get_lead_gateway_key), db: Session = Depends(get_db)
) -> schemas.DeliveryItem:
    try:
        row = delivery_service.send_test_push(db, key.tenant_id, endpoint_id)
    except delivery_service.DeliveryError as exc:
        raise _api(exc)
    return read_service.delivery_item(row)


@router.get("/leads", response_model=schemas.LeadPage)
def pull_leads(
    since: Optional[str] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=read_service.MAX_PAGE),
    key: LeadGatewayKey = Depends(get_lead_gateway_key),
    db: Session = Depends(get_db),
) -> schemas.LeadPage:
    try:
        return read_service.pull_leads(db, key.tenant_id, since=since, cursor=cursor, source_id=source, limit=limit)
    except read_service.ReadError as exc:
        raise _api(exc)


@router.post("/deliveries/{delivery_id}/redeliver", response_model=schemas.DeliveryItem)
def redeliver(
    delivery_id: str, key: LeadGatewayKey = Depends(get_lead_gateway_key), db: Session = Depends(get_db)
) -> schemas.DeliveryItem:
    try:
        row = delivery_service.redeliver(db, key.tenant_id, delivery_id)
    except delivery_service.DeliveryError as exc:
        raise _api(exc)
    return read_service.delivery_item(row)


@router.get("/fields", response_model=schemas.ConsumerFieldList)
def get_fields(key: LeadGatewayKey = Depends(get_lead_gateway_key), db: Session = Depends(get_db)) -> schemas.ConsumerFieldList:
    return read_service.fields_item(db, key.tenant_id)


@router.put("/fields", response_model=schemas.ConsumerFieldList)
def put_fields(
    body: List[schemas.ConsumerField],
    key: LeadGatewayKey = Depends(get_lead_gateway_key),
    db: Session = Depends(get_db),
) -> schemas.ConsumerFieldList:
    try:
        field_service.set_fields(db, key.tenant_id, [f.model_dump() for f in body])
    except field_service.FieldError as exc:
        raise _api(exc)
    return read_service.fields_item(db, key.tenant_id)


@router.put("/sources/{source_id}/field-map", response_model=schemas.SourceItem)
def put_field_map(
    source_id: str,
    body: schemas.FieldMapUpdate,
    key: LeadGatewayKey = Depends(get_lead_gateway_key),
    db: Session = Depends(get_db),
) -> schemas.SourceItem:
    try:
        row = field_service.set_field_map(db, key.tenant_id, source_id, body.formId, body.map)
    except field_service.FieldError as exc:
        raise _api(exc)
    return read_service.source_item(row)


@router.get("/sources/{source_id}/forms/{form_id}/questions", response_model=schemas.FormQuestionList)
def form_questions(
    source_id: str,
    form_id: str,
    key: LeadGatewayKey = Depends(get_lead_gateway_key),
    db: Session = Depends(get_db),
) -> schemas.FormQuestionList:
    try:
        return schemas.FormQuestionList(**form_service.form_questions(db, key.tenant_id, source_id, form_id))
    except form_service.FormError as exc:
        raise _api(exc)


@router.post("/sources/{source_id}/test-lead", response_model=schemas.TestLeadAccepted, status_code=202)
def send_test_lead(
    source_id: str,
    body: schemas.TestLeadRequest,
    key: LeadGatewayKey = Depends(get_lead_gateway_key),
    db: Session = Depends(get_db),
) -> schemas.TestLeadAccepted:
    try:
        return schemas.TestLeadAccepted(**form_service.send_test_lead(db, key.tenant_id, source_id, body.formId))
    except form_service.FormError as exc:
        raise _api(exc)
