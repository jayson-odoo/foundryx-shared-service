"""Lead Capture staff API (session JWT, module-gated, permission-gated).
HTTP only; every call is tenant-scoped from the signed-in user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from .. import schemas
from ..services import connect_service, delivery_service, key_service, read_service

router = APIRouter()

_VIEW = require_permission("lead_capture.view")
_MANAGE = require_permission("lead_capture.manage")
_KEYS = require_permission("lead_capture.keys.manage")


@router.post("/sources/facebook", response_model=schemas.SourceItem, status_code=201)
def connect_facebook(
    body: schemas.ConnectFacebookRequest,
    user: User = Depends(_MANAGE),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.SourceItem:
    try:
        row = connect_service.connect_facebook(
            db,
            user.tenant_id,
            page_id=body.pageId,
            system_user_token=body.systemUserToken,
            forms_mode=body.formsMode,
            user_id=actor_id,
        )
    except connect_service.ConnectError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})
    return read_service.source_item(row)


@router.get("/sources", response_model=schemas.SourceList)
def list_sources(user: User = Depends(_VIEW), db: Session = Depends(get_db)) -> schemas.SourceList:
    rows = connect_service.list_sources(db, user.tenant_id)
    return schemas.SourceList(data=[read_service.source_item(r) for r in rows])


@router.get("/settings", response_model=schemas.SettingsItem)
def get_settings(user: User = Depends(_VIEW), db: Session = Depends(get_db)) -> schemas.SettingsItem:
    return read_service.settings_item(db, user.tenant_id)


@router.put("/settings", response_model=schemas.SettingsItem)
def put_settings(
    body: schemas.SettingsUpdate,
    user: User = Depends(_MANAGE),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.SettingsItem:
    connect_service.set_allow_shared_pages(db, user.tenant_id, body.allowSharedPages, actor_id)
    return read_service.settings_item(db, user.tenant_id)


@router.post("/keys", response_model=schemas.KeyCreated, status_code=201)
def create_key(
    body: schemas.KeyCreate,
    user: User = Depends(_KEYS),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.KeyCreated:
    row, full_key = key_service.issue(db, user.tenant_id, name=body.name, created_by=actor_id)
    return schemas.KeyCreated(**read_service.key_item(row).model_dump(), key=full_key)


@router.get("/keys", response_model=schemas.KeyList)
def list_keys(user: User = Depends(_KEYS), db: Session = Depends(get_db)) -> schemas.KeyList:
    return schemas.KeyList(data=[read_service.key_item(r) for r in key_service.list_keys(db, user.tenant_id)])


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: str, user: User = Depends(_KEYS), db: Session = Depends(get_db)) -> Response:
    try:
        key_service.revoke(db, user.tenant_id, key_id)
    except key_service.KeyNotFound:
        raise HTTPException(status_code=404, detail="Key not found.")
    return Response(status_code=204)


@router.post("/deliveries/{delivery_id}/redeliver", response_model=schemas.DeliveryItem)
def redeliver(delivery_id: str, user: User = Depends(_MANAGE), db: Session = Depends(get_db)) -> schemas.DeliveryItem:
    try:
        row = delivery_service.redeliver(db, user.tenant_id, delivery_id)
    except delivery_service.DeliveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return read_service.delivery_item(row)
