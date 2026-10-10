"""Connector admin API (session JWT, module-gated, perm-gated). HTTP only."""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import effective_permission_keys, get_actor_user_id, require_permission
from app.models.user import User

from ..schemas import (
    Activity,
    BulkRevokeRequest,
    BulkRevokeResult,
    GrantItem,
    GrantPage,
    ProductDelete,
    ProductItem,
    ProductList,
    ProductSettings,
    ProductSettingsCreate,
    ProductSettingsUpdate,
    SettingsAuditList,
    TenantSettings,
    TenantSettingsUpdate,
)
from ..services import settings_service as ss
from ..services.grant_admin_service import GrantAdminService, NotFound

router = APIRouter()

_READ = require_permission("connector.read")
_MANAGE = require_permission("connector.manage")
_SETTINGS = require_permission("connector.settings")


def _svc(db: Session, user: User) -> GrantAdminService:
    slug = user.tenant.slug if user.tenant else ""
    return GrantAdminService(db, user.tenant_id, slug)


def _missing() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found")


@router.get("/grants", response_model=GrantPage)
def list_grants(
    status: Optional[str] = None,
    product: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    page_size_camel: Optional[int] = Query(None, alias="pageSize", ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(_READ),
) -> GrantPage:
    return _svc(db, user).list(status=status, product=product, search=search, page=page,
                               page_size=page_size_camel or page_size)


@router.post("/grants/bulk-revoke", response_model=BulkRevokeResult)
def bulk_revoke(body: BulkRevokeRequest, db: Session = Depends(get_db),
                user: User = Depends(_MANAGE),
                actor: str = Depends(get_actor_user_id)) -> BulkRevokeResult:
    return BulkRevokeResult(revoked=_svc(db, user).bulk_revoke(body.ids, actor))


@router.get("/grants/{grant_id}", response_model=GrantItem)
def get_grant(grant_id: str, db: Session = Depends(get_db), user: User = Depends(_READ)) -> GrantItem:
    try:
        return _svc(db, user).get(grant_id)
    except NotFound:
        raise _missing() from None


@router.get("/grants/{grant_id}/activity", response_model=Activity)
def grant_activity(grant_id: str, db: Session = Depends(get_db),
                   user: User = Depends(_READ)) -> Activity:
    try:
        return _svc(db, user).activity(grant_id)
    except NotFound:
        raise _missing() from None


@router.post("/grants/{grant_id}/revoke")
def revoke_grant(grant_id: str, db: Session = Depends(get_db), user: User = Depends(_MANAGE),
                 actor: str = Depends(get_actor_user_id)) -> dict:
    try:
        _svc(db, user).revoke(grant_id, actor)
    except NotFound:
        raise _missing() from None
    return {"ok": True}


@router.get("/products", response_model=ProductList)
def list_products(db: Session = Depends(get_db), user: User = Depends(_READ)) -> ProductList:
    return ProductList(data=_svc(db, user).products())


@router.post("/products/{key}/refresh-manifest", response_model=ProductItem)
def refresh_manifest(key: str, db: Session = Depends(get_db),
                     user: User = Depends(_MANAGE)) -> ProductItem:
    try:
        return _svc(db, user).refresh_manifest(key)
    except NotFound:
        raise _missing() from None


# --- settings in the database (lane SETTINGS-IN-DB-SS) ---------------------------------


def _settings(db: Session, user: User) -> ss.SettingsService:
    # the secret hint ("****" + last 4) is for editors only, never read-only users
    return ss.SettingsService(db, user.tenant_id, user.tenant.slug if user.tenant else "",
                              show_secret_hint="connector.settings" in effective_permission_keys(user))


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, ss.NotFound):
        return _missing()
    if isinstance(exc, ss.Conflict):
        return HTTPException(status_code=409, detail=exc.message)
    if isinstance(exc, ss.Invalid):
        return HTTPException(status_code=422, detail={"fieldErrors": exc.errors})
    raise exc


_SETTINGS_ERRORS = (ss.NotFound, ss.Conflict, ss.Invalid)


@router.get("/settings", response_model=TenantSettings)
def get_settings(db: Session = Depends(get_db), user: User = Depends(_READ)) -> TenantSettings:
    return _settings(db, user).get_tenant()


@router.put("/settings", response_model=TenantSettings)
def put_settings(body: TenantSettingsUpdate, db: Session = Depends(get_db),
                 user: User = Depends(_SETTINGS),
                 actor: str = Depends(get_actor_user_id)) -> TenantSettings:
    try:
        return _settings(db, user).update_tenant(body, actor)
    except _SETTINGS_ERRORS as exc:
        raise _translate(exc) from None


@router.get("/settings/audit", response_model=SettingsAuditList)
def settings_audit(db: Session = Depends(get_db), user: User = Depends(_READ)) -> SettingsAuditList:
    return SettingsAuditList(data=_settings(db, user).audit())


@router.post("/products", response_model=ProductSettings, status_code=201)
def create_product(body: ProductSettingsCreate, db: Session = Depends(get_db),
                   user: User = Depends(_SETTINGS),
                   actor: str = Depends(get_actor_user_id)) -> ProductSettings:
    try:
        return _settings(db, user).create_product(body, actor)
    except _SETTINGS_ERRORS as exc:
        raise _translate(exc) from None


@router.get("/products/{key}/settings", response_model=ProductSettings)
def get_product_settings(key: str, db: Session = Depends(get_db),
                         user: User = Depends(_READ)) -> ProductSettings:
    try:
        return _settings(db, user).get_product(key)
    except _SETTINGS_ERRORS as exc:
        raise _translate(exc) from None


@router.put("/products/{key}/settings", response_model=ProductSettings)
def put_product_settings(key: str, body: ProductSettingsUpdate, db: Session = Depends(get_db),
                         user: User = Depends(_SETTINGS),
                         actor: str = Depends(get_actor_user_id)) -> ProductSettings:
    try:
        return _settings(db, user).update_product(key, body, actor)
    except _SETTINGS_ERRORS as exc:
        raise _translate(exc) from None


@router.delete("/products/{key}")
def delete_product(key: str, body: ProductDelete, db: Session = Depends(get_db),
                   user: User = Depends(_SETTINGS),
                   actor: str = Depends(get_actor_user_id)) -> dict:
    try:
        _settings(db, user).delete_product(key, body.confirmKey, actor)
    except _SETTINGS_ERRORS as exc:
        raise _translate(exc) from None
    return {"ok": True}
