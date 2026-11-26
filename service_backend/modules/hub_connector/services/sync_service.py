"""Pull the CRM connector feed into this tenant's facts (AC-17).

One run: ``/locations`` + ``/brands`` (catalogues for the policy pickers),
every ``/products`` page, then ``/availability`` for those codes in chunks of
200. Products the feed no longer lists are removed (hubs are told to drop
them). Afterwards every hub customer whose view changed gets one webhook.

One bad row never fails the run: it is skipped and counted. A feed error
(401/403/429/unreachable) stops the run with a plain reason on the sync state
and changes nothing - the next tick tries again. Everything is written in ONE
transaction under the tenant lock.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.repositories.connection_repository import ConnectionRepository
from app.repositories.module_repository import ModuleRepository
from app.secrets import decrypt_secret

from .. import crm_feed
from ..models import HcBrand, HcItem, HcLocation, HcSyncState
from . import delivery_service
from .hub_service import HubError

logger = logging.getLogger(__name__)

MODULE_NAME = "hub_connector"
MAX_QTY = Decimal("1e12")
MAX_PRICE = Decimal("1e14")  # Numeric(18, 4)


def _text(value: Any, limit: int) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    clean = str(value).strip()
    return clean[:limit] if clean else None


def _qty(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return 0.0
    if not number.is_finite() or abs(number) >= MAX_QTY:
        return 0.0
    return float(number)


def _price(value: Any) -> Optional[Decimal]:
    """``list_price`` is a string; zero / unknown = null (contract)."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number <= 0 or number >= MAX_PRICE:
        return None
    return number.quantize(Decimal("0.0001"))


def _availability(row: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    if not row:
        return [], [], None
    locations = []
    for loc in row.get("locations") or []:
        code = _text(loc.get("code"), 64) if isinstance(loc, dict) else None
        if code:
            locations.append({"code": code, "available": _qty(loc.get("available_qty"))})
    incoming = []
    for line in row.get("incoming_lines") or []:
        if not isinstance(line, dict):
            continue
        allocations = []
        for alloc in line.get("locations") or []:
            code = _text(alloc.get("code"), 64) if isinstance(alloc, dict) else None
            if code:
                allocations.append({"code": code, "qty": _qty(alloc.get("qty"))})
        incoming.append({"eta": _text(line.get("eta"), 40), "qty": _qty(line.get("qty")), "locations": allocations})
    return locations, incoming, _text(row.get("as_of"), 40)


def feed_config(db: Session, tenant_id: str) -> Optional[crm_feed.FeedConfig]:
    """The tenant's own CRM feed connection (never the platform's)."""
    conn = ConnectionRepository(db).get_by_type(tenant_id, crm_feed.CONNECTION_TYPE)
    if conn is None or conn.provider != crm_feed.PROVIDER_KEY:
        return None
    try:
        credentials = decrypt_secret(conn.credentials_json) or {}
    except Exception:  # noqa: BLE001 - undecryptable = not configured
        raise crm_feed.FeedError("The stored CRM key can no longer be read. Enter it again.") from None
    return crm_feed.config_from(conn.config_json or {}, credentials)


def _state(db: Session, tenant_id: str) -> HcSyncState:
    row = db.get(HcSyncState, tenant_id)
    if row is None:
        row = HcSyncState(tenant_id=tenant_id, products=0, queued=0)
        db.add(row)
    return row


def _upsert_catalog(db: Session, model, tenant_id: str, rows: List[Dict[str, Any]], extra=None) -> None:
    existing = {r.code: r for r in db.query(model).filter(model.tenant_id == tenant_id).all()}
    seen = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        code = _text(raw.get("code"), 64)
        if not code or code in seen:
            continue
        seen.add(code)
        row = existing.get(code)
        if row is None:
            row = model(tenant_id=tenant_id, code=code)
            db.add(row)
        row.name = _text(raw.get("name"), 300) or code
        if extra:
            extra(row, raw)
    for code, row in existing.items():
        if code not in seen:
            db.delete(row)


def sync_tenant(db: Session, tenant_id: str, *, client: Optional[crm_feed.FeedClient] = None) -> HcSyncState:
    """One full run. Raises ``HubError`` 409 when no feed is configured."""
    try:
        cfg = feed_config(db, tenant_id)
    except crm_feed.FeedError as exc:
        return _record_failure(db, tenant_id, exc.message)
    if cfg is None and client is None:
        raise HubError(409, "no_feed", "Connect the CRM stock feed in Settings, Integrations first.")
    feed = client or crm_feed.FeedClient(cfg)
    started = datetime.now(timezone.utc)
    try:
        locations = feed.locations()
        brands = feed.brands()
        products = feed.products()
        codes = list(dict.fromkeys(c for c in (_text(p.get("code"), 64) for p in products if isinstance(p, dict)) if c))
        availability = feed.availability(codes) if codes else {}
    except crm_feed.FeedError as exc:
        return _record_failure(db, tenant_id, exc.message, started=started)

    # An empty list where there was data is far more likely a wrong company code
    # or a CRM misconfiguration than a real "everything is gone": refuse it, so
    # hubs never see all stock vanish. (Starting from nothing, empty is fine.)
    had_items = db.query(HcItem.id).filter(HcItem.tenant_id == tenant_id).first() is not None
    had_locations = db.query(HcLocation.id).filter(HcLocation.tenant_id == tenant_id).first() is not None
    if (had_items and not codes) or (had_locations and not locations):
        return _record_failure(
            db, tenant_id, "The CRM listed no products or no locations; nothing was changed.", started=started
        )

    delivery_service.tenant_lock(db, tenant_id)
    _upsert_catalog(db, HcLocation, tenant_id, locations, extra=lambda row, raw: setattr(row, "sellable", raw.get("sellable") is not False))
    _upsert_catalog(db, HcBrand, tenant_id, brands)

    existing = {r.code: r for r in db.query(HcItem).filter(HcItem.tenant_id == tenant_id).all()}
    seen = set()
    for raw in products:
        if not isinstance(raw, dict):
            continue
        code = _text(raw.get("code"), 64)
        if not code or code in seen:
            continue
        seen.add(code)
        row = existing.get(code)
        if row is None:
            row = HcItem(tenant_id=tenant_id, code=code)
            db.add(row)
        row.name = _text(raw.get("name"), 300) or code
        row.brand_code = _text(raw.get("brand_code"), 64)
        row.brand_name = _text(raw.get("brand_name"), 200)
        row.price = _price(raw.get("list_price"))
        row.currency = _text(raw.get("currency"), 8)
        row.locations_json, row.incoming_json, row.as_of = _availability(availability.get(code))
        row.updated_at = started
    removed = [code for code in existing if code not in seen]
    for code in removed:
        db.delete(existing[code])
    db.flush()
    delivery_ids = delivery_service.queue_item_changes(db, tenant_id, list(seen), removed_codes=removed)
    state = _state(db, tenant_id)
    state.last_run_at = started
    state.last_success_at = datetime.now(timezone.utc)
    state.last_error = None
    state.products = len(seen)
    state.queued = len(delivery_ids)
    db.commit()
    delivery_service.enqueue(delivery_ids)
    db.refresh(state)
    return state


def _record_failure(db: Session, tenant_id: str, message: str, *, started: Optional[datetime] = None) -> HcSyncState:
    db.rollback()
    state = _state(db, tenant_id)
    state.last_run_at = started or datetime.now(timezone.utc)
    state.last_error = message[:500]
    db.commit()
    db.refresh(state)
    return state


def get_state(db: Session, tenant_id: str) -> Optional[HcSyncState]:
    return db.get(HcSyncState, tenant_id)


def run_due(db: Session) -> int:
    """Beat tick: one run per tenant with the module ACTIVE and a feed
    connection. One tenant's failure never stops the others."""
    from app.models.connection import Connection

    tenant_ids = [
        t for (t,) in db.query(Connection.tenant_id)
        .filter(Connection.provider == crm_feed.PROVIDER_KEY, Connection.is_active.is_(True))
        .distinct()
        .all()
    ]
    ran = 0
    for tenant_id in tenant_ids:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None or not tenant.signin_allowed or not ModuleRepository(db).is_active(tenant_id, MODULE_NAME):
            continue
        try:
            sync_tenant(db, tenant_id)
            ran += 1
        except Exception:  # noqa: BLE001 - one tenant never stops the rest
            logger.exception("hub_connector sync failed for tenant %s", tenant_id)
            db.rollback()
    return ran
