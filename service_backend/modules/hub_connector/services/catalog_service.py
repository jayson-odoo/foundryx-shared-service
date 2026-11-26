"""CRM -> shared service pushes (AC-17): items with their availability facts,
and the customer company catalogue the admin picks hub customers from.

One bad entry never fails the batch: the rest are stored, the skipped ones are
named in the reply. Everything is scoped to the key's tenant.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from ..models import HcCustomer, HcItem
from . import delivery_service

MAX_BATCH = 1000


class Skip(Exception):
    pass


def _text(value: Any, field: str, limit: int, required: bool = True) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise Skip(f"{field} is missing")
        return None
    if not isinstance(value, (str, int)):
        raise Skip(f"{field} is not text")
    clean = str(value).strip()
    if len(clean) > limit:
        raise Skip(f"{field} is too long")
    return clean


def _qty(value: Any, field: str) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise Skip(f"{field} is not a number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise Skip(f"{field} is not a number") from None
    if not number.is_finite():
        raise Skip(f"{field} is not a number")
    return float(number)


def _price(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise Skip("price is not a number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise Skip("price is not a number") from None
    if not number.is_finite() or number < 0:
        raise Skip("price is not a valid amount")
    return number


def _clean_item(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise Skip("not an object")
    brand = raw.get("brand") or {}
    if not isinstance(brand, dict):
        raise Skip("brand is not an object")
    locations: List[Dict[str, Any]] = []
    seen = set()
    for loc in raw.get("locations") or []:
        if not isinstance(loc, dict):
            raise Skip("a location is not an object")
        code = _text(loc.get("code"), "location code", 64)
        if code in seen:
            raise Skip(f"location {code} is listed twice")
        seen.add(code)
        locations.append(
            {
                "code": code,
                "name": _text(loc.get("name"), "location name", 200, required=False) or code,
                "onHand": _qty(loc.get("onHand"), "on hand"),
                "reserved": _qty(loc.get("reserved"), "reserved"),
            }
        )
    incoming: List[Dict[str, Any]] = []
    for line in raw.get("incoming") or []:
        if not isinstance(line, dict):
            raise Skip("an incoming line is not an object")
        incoming.append(
            {
                "ref": _text(line.get("ref"), "incoming ref", 100, required=False),
                "locationCode": _text(line.get("locationCode"), "incoming location", 64, required=False),
                "remaining": _qty(line.get("remaining"), "incoming remaining"),
            }
        )
    return {
        "code": _text(raw.get("code"), "code", 64),
        "name": _text(raw.get("name"), "name", 300),
        "brand_code": _text(brand.get("code"), "brand code", 64, required=False),
        "brand_name": _text(brand.get("name"), "brand name", 200, required=False),
        "price": _price(raw.get("price")),
        "currency": _text(raw.get("currency"), "currency", 8, required=False),
        "locations": locations,
        "incoming": incoming,
    }


def _ref(raw: Any) -> str:
    if isinstance(raw, dict) and isinstance(raw.get("code"), (str, int)):
        return str(raw["code"])[:64]
    return "(no code)"


def push_items(db: Session, tenant_id: str, raw_items: Sequence[Any]) -> Tuple[int, List[Dict[str, str]], List[str]]:
    """Upsert the items; returns ``(stored, skipped, delivery_ids)``. Commits once."""
    skipped: List[Dict[str, str]] = []
    clean: Dict[str, Dict[str, Any]] = {}
    for raw in list(raw_items)[:MAX_BATCH]:
        try:
            item = _clean_item(raw)
        except Skip as exc:
            skipped.append({"code": _ref(raw), "reason": str(exc)})
            continue
        clean[item["code"]] = item  # the last copy of a code in one batch wins
    for raw in list(raw_items)[MAX_BATCH:]:
        skipped.append({"code": _ref(raw), "reason": f"more than {MAX_BATCH} items in one call"})
    existing = {
        row.code: row
        for row in db.query(HcItem).filter(HcItem.tenant_id == tenant_id, HcItem.code.in_(list(clean))).all()
    } if clean else {}
    now = datetime.now(timezone.utc)
    for code, item in clean.items():
        row = existing.get(code)
        if row is None:
            row = HcItem(tenant_id=tenant_id, code=code)
            db.add(row)
        row.name = item["name"]
        row.brand_code = item["brand_code"]
        row.brand_name = item["brand_name"]
        row.price = item["price"]
        row.currency = item["currency"]
        row.locations_json = item["locations"]
        row.incoming_json = item["incoming"]
        row.updated_at = now
    db.flush()
    delivery_ids = delivery_service.queue_item_changes(db, tenant_id, list(clean))
    db.commit()
    return len(clean), skipped, delivery_ids


def push_customers(db: Session, tenant_id: str, raw_customers: Sequence[Any]) -> Tuple[int, List[Dict[str, str]]]:
    skipped: List[Dict[str, str]] = []
    clean: Dict[str, str] = {}
    for raw in list(raw_customers)[:MAX_BATCH]:
        try:
            if not isinstance(raw, dict):
                raise Skip("not an object")
            code = _text(raw.get("code"), "code", 64)
            clean[code] = _text(raw.get("name"), "name", 300)
        except Skip as exc:
            skipped.append({"code": _ref(raw), "reason": str(exc)})
    for raw in list(raw_customers)[MAX_BATCH:]:
        skipped.append({"code": _ref(raw), "reason": f"more than {MAX_BATCH} customers in one call"})
    existing = {
        row.code: row
        for row in db.query(HcCustomer).filter(HcCustomer.tenant_id == tenant_id, HcCustomer.code.in_(list(clean))).all()
    } if clean else {}
    for code, name in clean.items():
        row = existing.get(code)
        if row is None:
            db.add(HcCustomer(tenant_id=tenant_id, code=code, name=name))
        else:
            row.name = name
    db.commit()
    return len(clean), skipped
