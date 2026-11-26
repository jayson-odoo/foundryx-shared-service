"""The ONE function that decides what a hub customer sees of an item.

Owner rulings (26 Nov ~21:27):
- got stock = on hand minus reserved > 0 in at least one of the customer's
  allowed locations (a location outside the policy never counts);
- got incoming = any not-yet-arrived remainder > 0, in an allowed location OR on
  a line not yet allocated to any location (crew Q-A (a));
- brands: only items whose brand the customer may see;
- price: only when the HUB's expose switch is on (default OFF).

Pure: no DB, no I/O, so preview, webhook and tests share it exactly.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class Policy:
    location_codes: frozenset
    brand_codes: frozenset
    expose_price: bool


@dataclass(frozen=True)
class ItemFacts:
    code: str
    name: str
    brand_code: Optional[str]
    brand_name: Optional[str]
    price: Optional[Decimal]
    currency: Optional[str]
    locations: List[Dict[str, Any]]
    incoming: List[Dict[str, Any]]


def _num(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def make_policy(location_codes: Iterable[str], brand_codes: Iterable[str], expose_price: bool) -> Policy:
    return Policy(frozenset(location_codes or ()), frozenset(brand_codes or ()), bool(expose_price))


def visible(item: ItemFacts, policy: Policy) -> bool:
    return bool(item.brand_code) and item.brand_code in policy.brand_codes


def got_stock(item: ItemFacts, policy: Policy) -> bool:
    for loc in item.locations or ():
        if loc.get("code") in policy.location_codes and _num(loc.get("onHand")) - _num(loc.get("reserved")) > 0:
            return True
    return False


def got_incoming(item: ItemFacts, policy: Policy) -> bool:
    for line in item.incoming or ():
        if _num(line.get("remaining")) <= 0:
            continue
        loc = line.get("locationCode")
        if loc is None or loc == "" or loc in policy.location_codes:
            return True
    return False


def money(value: Decimal) -> str:
    """At least 2 decimals, no trailing storage zeros (120.0000 -> "120.00")."""
    amount = Decimal(str(value))
    cents = amount.quantize(Decimal("0.01"))
    return str(cents) if cents == amount else format(amount.normalize(), "f")


def view_for(item: ItemFacts, policy: Policy) -> Optional[Dict[str, Any]]:
    """The item as this customer sees it, or None when it is hidden."""
    if not visible(item, policy):
        return None
    view: Dict[str, Any] = {
        "code": item.code,
        "name": item.name,
        "brand": {"code": item.brand_code, "name": item.brand_name or item.brand_code},
        "gotStock": got_stock(item, policy),
        "gotIncoming": got_incoming(item, policy),
    }
    if policy.expose_price and item.price is not None:
        view["price"] = money(item.price)
        view["currency"] = item.currency
    return view


def view_hash(view: Optional[Dict[str, Any]]) -> str:
    """Stable fingerprint of a view (``None`` = hidden)."""
    raw = json.dumps(view, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
