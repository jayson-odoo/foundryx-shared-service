"""Hub Connector staff API (session JWT, module-gated, permission-gated).
HTTP only; every call is tenant-scoped from the signed-in user."""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from .. import schemas
from ..models import HcHub, HcHubCustomer
from ..services import delivery_service, hub_service, key_service, sync_service
from ..services.hub_service import HubError

router = APIRouter()

_VIEW = require_permission("hub_connector.view")
_MANAGE = require_permission("hub_connector.manage")
_KEYS = require_permission("hub_connector.keys.manage")


def _http(exc: HubError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


def _hub_item(hub: HcHub, count: int = 0) -> schemas.HubItem:
    return schemas.HubItem(
        id=hub.id,
        name=hub.name,
        code=hub.code,
        callbackUrl=hub.callback_url,
        exposePrice=bool(hub.expose_price),
        active=bool(hub.active),
        customerCount=count,
        lastSuccessAt=hub.last_success_at,
        createdAt=hub.created_at,
        updatedAt=hub.updated_at,
    )


def _customer_item(row: HcHubCustomer, locations: Dict[str, str], brands: Dict[str, str]) -> schemas.HubCustomerItem:
    locs = list(row.location_codes_json or [])
    brs = list(row.brand_codes_json or [])
    return schemas.HubCustomerItem(
        id=row.id,
        hubId=row.hub_id,
        customerCode=row.customer_code,
        customerName=row.customer_name,
        locationCodes=locs,
        brandCodes=brs,
        locations=[schemas.Option(code=c, name=locations.get(c, c)) for c in locs],
        brands=[schemas.Option(code=c, name=brands.get(c, c)) for c in brs],
        active=bool(row.active),
        updatedAt=row.updated_at,
    )


def _one_customer(db: Session, tenant_id: str, row: HcHubCustomer) -> schemas.HubCustomerItem:
    locations, brands = hub_service.name_maps(db, tenant_id)
    return _customer_item(row, locations, brands)


# ── hubs ────────────────────────────────────────────────────────────────────

@router.get("/hubs", response_model=schemas.HubPage)
def list_hubs(
    search: Optional[str] = Query(default=None, max_length=200),
    sort: Optional[str] = Query(default=None, max_length=32),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    page: int = Query(default=0, ge=0),
    pageSize: int = Query(default=25, ge=1, le=200),
    user: User = Depends(_VIEW),
    db: Session = Depends(get_db),
) -> schemas.HubPage:
    rows, counts, total = hub_service.list_hubs(
        db, user.tenant_id, search=search, sort=sort, order=order, page=page, page_size=pageSize
    )
    return schemas.HubPage(data=[_hub_item(h, counts.get(h.id, 0)) for h in rows], total=total)


@router.post("/hubs", response_model=schemas.HubCreated, status_code=201)
def create_hub(body: schemas.HubCreate, user: User = Depends(_MANAGE), db: Session = Depends(get_db)) -> schemas.HubCreated:
    try:
        hub, secret = hub_service.create_hub(
            db, user.tenant_id, name=body.name, code=body.code, callback_url=body.callbackUrl, expose_price=body.exposePrice
        )
    except HubError as exc:
        raise _http(exc)
    return schemas.HubCreated(hub=_hub_item(hub), signingSecret=secret)


@router.get("/hubs/{hub_id}", response_model=schemas.HubItem)
def get_hub(hub_id: str, user: User = Depends(_VIEW), db: Session = Depends(get_db)) -> schemas.HubItem:
    try:
        hub = hub_service.get_hub(db, user.tenant_id, hub_id)
    except HubError as exc:
        raise _http(exc)
    return _hub_item(hub, hub_service.customer_counts(db, user.tenant_id, [hub.id]).get(hub.id, 0))


@router.patch("/hubs/{hub_id}", response_model=schemas.HubItem)
def update_hub(
    hub_id: str, body: schemas.HubUpdate, user: User = Depends(_MANAGE), db: Session = Depends(get_db)
) -> schemas.HubItem:
    try:
        hub, resync = hub_service.update_hub(db, user.tenant_id, hub_id, body.model_dump(exclude_unset=True), commit=False)
        ids = delivery_service.resync_hub(db, user.tenant_id, hub.id) if resync and hub.active and hub.callback_url else []
    except HubError as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    db.refresh(hub)
    delivery_service.enqueue(ids)
    return _hub_item(hub, hub_service.customer_counts(db, user.tenant_id, [hub.id]).get(hub.id, 0))


@router.post("/hubs/{hub_id}/rotate-secret", response_model=schemas.SecretOut)
def rotate_secret(hub_id: str, user: User = Depends(_MANAGE), db: Session = Depends(get_db)) -> schemas.SecretOut:
    try:
        return schemas.SecretOut(signingSecret=hub_service.rotate_secret(db, user.tenant_id, hub_id))
    except HubError as exc:
        raise _http(exc)


@router.post("/hubs/{hub_id}/resync", response_model=schemas.QueuedOut)
def resync_hub(hub_id: str, user: User = Depends(_MANAGE), db: Session = Depends(get_db)) -> schemas.QueuedOut:
    try:
        ids = delivery_service.resync_hub(db, user.tenant_id, hub_id)
    except HubError as exc:
        raise _http(exc)
    db.commit()
    delivery_service.enqueue(ids)
    return schemas.QueuedOut(queued=len(ids))


@router.delete("/hubs/{hub_id}", status_code=204)
def delete_hub(hub_id: str, user: User = Depends(_MANAGE), db: Session = Depends(get_db)) -> Response:
    try:
        hub_service.delete_hub(db, user.tenant_id, hub_id)
    except HubError as exc:
        raise _http(exc)
    return Response(status_code=204)


# ── hub customers ───────────────────────────────────────────────────────────

@router.get("/hubs/{hub_id}/customers", response_model=schemas.HubCustomerPage)
def list_customers(
    hub_id: str,
    search: Optional[str] = Query(default=None, max_length=200),
    sort: Optional[str] = Query(default=None, max_length=32),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    page: int = Query(default=0, ge=0),
    pageSize: int = Query(default=25, ge=1, le=200),
    user: User = Depends(_VIEW),
    db: Session = Depends(get_db),
) -> schemas.HubCustomerPage:
    try:
        rows, total = hub_service.list_customers(
            db, user.tenant_id, hub_id, search=search, sort=sort, order=order, page=page, page_size=pageSize
        )
    except HubError as exc:
        raise _http(exc)
    locations, brands = hub_service.name_maps(db, user.tenant_id)
    return schemas.HubCustomerPage(data=[_customer_item(r, locations, brands) for r in rows], total=total)


@router.post("/hubs/{hub_id}/customers", response_model=schemas.HubCustomerItem, status_code=201)
def add_customer(
    hub_id: str, body: schemas.HubCustomerCreate, user: User = Depends(_MANAGE), db: Session = Depends(get_db)
) -> schemas.HubCustomerItem:
    try:
        row = hub_service.add_customer(
            db,
            user.tenant_id,
            hub_id,
            customer_code=body.customerCode,
            customer_name=body.customerName,
            location_codes=body.locationCodes,
            brand_codes=body.brandCodes,
            commit=False,
        )
        hub = hub_service.get_hub(db, user.tenant_id, hub_id)
    except HubError as exc:
        db.rollback()
        raise _http(exc)
    delivery_id = delivery_service.resync_customer(db, hub, row)
    db.commit()
    db.refresh(row)
    delivery_service.enqueue([delivery_id] if delivery_id else [])
    return _one_customer(db, user.tenant_id, row)


@router.patch("/hubs/{hub_id}/customers/{hub_customer_id}", response_model=schemas.HubCustomerItem)
def update_customer(
    hub_id: str,
    hub_customer_id: str,
    body: schemas.HubCustomerUpdate,
    user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> schemas.HubCustomerItem:
    try:
        row = hub_service.update_customer(
            db, user.tenant_id, hub_id, hub_customer_id, body.model_dump(exclude_unset=True), commit=False
        )
        hub = hub_service.get_hub(db, user.tenant_id, hub_id)
    except HubError as exc:
        db.rollback()
        raise _http(exc)
    delivery_id = delivery_service.resync_customer(db, hub, row) if row.active else delivery_service.hide_customer(db, hub, row)
    db.commit()
    db.refresh(row)
    delivery_service.enqueue([delivery_id] if delivery_id else [])
    return _one_customer(db, user.tenant_id, row)


@router.delete("/hubs/{hub_id}/customers/{hub_customer_id}", status_code=204)
def remove_customer(
    hub_id: str, hub_customer_id: str, user: User = Depends(_MANAGE), db: Session = Depends(get_db)
) -> Response:
    try:
        delivery_service.remove_customer(db, user.tenant_id, hub_id, hub_customer_id)
    except HubError as exc:
        db.rollback()
        raise _http(exc)
    return Response(status_code=204)


@router.get("/hubs/{hub_id}/customers/{hub_customer_id}/preview", response_model=schemas.PreviewOut)
def preview(
    hub_id: str, hub_customer_id: str, user: User = Depends(_VIEW), db: Session = Depends(get_db)
) -> schemas.PreviewOut:
    try:
        return schemas.PreviewOut(items=hub_service.preview(db, user.tenant_id, hub_id, hub_customer_id))
    except HubError as exc:
        raise _http(exc)


# ── deliveries ──────────────────────────────────────────────────────────────

@router.get("/hubs/{hub_id}/deliveries", response_model=schemas.DeliveryPage)
def list_deliveries(
    hub_id: str,
    status: Optional[List[str]] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=200),
    sort: Optional[str] = Query(default=None, max_length=32),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=0, ge=0),
    pageSize: int = Query(default=25, ge=1, le=200),
    user: User = Depends(_VIEW),
    db: Session = Depends(get_db),
) -> schemas.DeliveryPage:
    try:
        rows, total = delivery_service.list_deliveries(
            db, user.tenant_id, hub_id, statuses=status, search=search, sort=sort, order=order, page=page, page_size=pageSize
        )
    except HubError as exc:
        raise _http(exc)
    return schemas.DeliveryPage(
        data=[
            schemas.DeliveryItem(
                id=d.id,
                event=d.event,
                customerCode=d.customer_code,
                customerName=d.customer_name,
                itemCount=d.item_count or 0,
                status=d.status,
                attempt=d.attempt,
                lastCode=d.last_code,
                lastError=d.last_error,
                createdAt=d.created_at,
                lastAttemptAt=d.last_attempt_at,
            )
            for d in rows
        ],
        total=total,
    )


@router.post("/deliveries/{delivery_id}/redeliver", response_model=schemas.QueuedOut)
def redeliver(delivery_id: str, user: User = Depends(_MANAGE), db: Session = Depends(get_db)) -> schemas.QueuedOut:
    try:
        new_id = delivery_service.redeliver(db, user.tenant_id, delivery_id)
    except HubError as exc:
        raise _http(exc)
    return schemas.QueuedOut(queued=1 if new_id else 0)


# ── picker options ──────────────────────────────────────────────────────────

@router.get("/options/{kind}", response_model=schemas.OptionList)
def options(
    kind: str,
    search: Optional[str] = Query(default=None, max_length=200),
    user: User = Depends(_VIEW),
    db: Session = Depends(get_db),
) -> schemas.OptionList:
    try:
        return schemas.OptionList(data=hub_service.options(db, user.tenant_id, kind, search))
    except HubError as exc:
        raise _http(exc)


# ── CRM feed sync ───────────────────────────────────────────────────────────

def _sync_out(db: Session, tenant_id: str) -> schemas.SyncStateOut:
    try:
        configured = sync_service.feed_config(db, tenant_id) is not None
    except Exception:  # noqa: BLE001 - a stored-but-unreadable key still counts as configured
        configured = True
    state = sync_service.get_state(db, tenant_id)
    if state is None:
        return schemas.SyncStateOut(configured=configured)
    return schemas.SyncStateOut(
        configured=configured,
        lastRunAt=state.last_run_at,
        lastSuccessAt=state.last_success_at,
        lastError=state.last_error,
        products=state.products or 0,
        queued=state.queued or 0,
    )


@router.get("/sync", response_model=schemas.SyncStateOut)
def sync_state(user: User = Depends(_VIEW), db: Session = Depends(get_db)) -> schemas.SyncStateOut:
    return _sync_out(db, user.tenant_id)


@router.post("/sync", response_model=schemas.SyncStateOut)
def sync_now(user: User = Depends(_MANAGE), db: Session = Depends(get_db)) -> schemas.SyncStateOut:
    try:
        sync_service.sync_tenant(db, user.tenant_id)
    except HubError as exc:
        raise _http(exc)
    return _sync_out(db, user.tenant_id)


# ── hub read-API keys (one hub per key) ─────────────────────────────────────

def _key_item(row) -> schemas.KeyItem:
    return schemas.KeyItem(
        id=row.id,
        name=row.name,
        masked=key_service.masked(row),
        createdAt=row.created_at,
        lastUsedAt=row.last_used_at,
        revokedAt=row.revoked_at,
    )


@router.get("/hubs/{hub_id}/keys", response_model=schemas.KeyList)
def list_keys(hub_id: str, user: User = Depends(_KEYS), db: Session = Depends(get_db)) -> schemas.KeyList:
    try:
        hub_service.get_hub(db, user.tenant_id, hub_id)
    except HubError as exc:
        raise _http(exc)
    return schemas.KeyList(data=[_key_item(r) for r in key_service.list_keys(db, user.tenant_id, hub_id)])


@router.post("/hubs/{hub_id}/keys", response_model=schemas.KeyCreated, status_code=201)
def create_key(
    hub_id: str,
    body: schemas.KeyCreate,
    user: User = Depends(_KEYS),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.KeyCreated:
    try:
        hub_service.get_hub(db, user.tenant_id, hub_id)
    except HubError as exc:
        raise _http(exc)
    row, full_key = key_service.issue(db, user.tenant_id, hub_id, name=body.name, created_by=actor_id)
    return schemas.KeyCreated(**_key_item(row).model_dump(), key=full_key)


@router.delete("/hubs/{hub_id}/keys/{key_id}", response_model=schemas.KeyItem)
def revoke_key(hub_id: str, key_id: str, user: User = Depends(_KEYS), db: Session = Depends(get_db)) -> schemas.KeyItem:
    rows = [k for k in key_service.list_keys(db, user.tenant_id, hub_id) if k.id == key_id]
    if not rows:
        raise HTTPException(status_code=404, detail={"code": "key_not_found", "message": "This key does not exist."})
    return _key_item(key_service.revoke(db, user.tenant_id, key_id))
