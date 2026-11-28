"""Dashboards staff API (session JWT, module-gated, permission-gated): issue, list and revoke the
gateway keys a product backend calls with. HTTP only; every call is tenant-scoped from the signed-in user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from .. import schemas
from ..services import key_service

router = APIRouter()

_KEYS = require_permission("dashboards.keys.manage")


def _item(row) -> schemas.KeyItem:
    return schemas.KeyItem(
        id=row.id, name=row.name, product=row.product, masked=key_service.masked(row),
        created_at=row.created_at, last_used_at=row.last_used_at, revoked_at=row.revoked_at,
    )


@router.get("/keys", response_model=schemas.KeyList)
def list_keys(user: User = Depends(_KEYS), db: Session = Depends(get_db)) -> schemas.KeyList:
    return schemas.KeyList(data=[_item(r) for r in key_service.list_keys(db, user.tenant_id)])


@router.post("/keys", response_model=schemas.KeyCreated, status_code=201)
def create_key(
    body: schemas.KeyCreate,
    user: User = Depends(_KEYS),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.KeyCreated:
    row, full_key = key_service.issue(db, user.tenant_id, product=body.product, name=body.name, created_by=actor_id)
    return schemas.KeyCreated(**_item(row).model_dump(), key=full_key)


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: str, user: User = Depends(_KEYS), db: Session = Depends(get_db)) -> Response:
    try:
        key_service.revoke(db, user.tenant_id, key_id)
    except key_service.KeyNotFound:
        raise HTTPException(status_code=404, detail="Key not found.")
    return Response(status_code=204)
