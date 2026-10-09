"""Connector admin API (session JWT, module-gated, perm-gated). HTTP only."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..schemas import (
    Activity,
    BulkRevokeRequest,
    BulkRevokeResult,
    GrantItem,
    GrantPage,
    ProductItem,
    ProductList,
)
from ..services.grant_admin_service import GrantAdminService, NotFound

router = APIRouter()

_READ = require_permission("connector.read")
_MANAGE = require_permission("connector.manage")


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
