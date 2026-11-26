"""The ONE function that decides what a hub customer sees of an item.

Rules (owner rulings 26 Nov ~21:27, frozen with the CRM feed contract #2801):
- in_stock = SUM of ``available_qty`` (on hand minus reserved) over the
  customer's chosen locations > 0; a location outside the policy never counts;
- incoming = any not-yet-arrived line with an outstanding allocation to one of
  the customer's locations, OR a line not yet allocated to any location (crew
  Q-A (a)); yes/no only, no date or quantity in S1;
- brands: only items whose brand the customer may see (a new customer sees
  nothing until the admin picks);
- price: only when the HUB's Show price switch is on (default OFF).

Hub-facing row: ``{code, name, brand_name, in_stock, incoming}`` (+
``list_price`` / ``currency`` behind the switch).

Pure: no DB, no I/O, so preview, the hub read API, the webhook and the tests
share it exactly.
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
    locations: List[Dict[str, Any]]  # [{code, available}]
    incoming: List[Dict[str, Any]]  # [{eta, qty, locations: [{code, qty}]}]


def _num(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        return Decimal(0)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)
    return number if number.is_finite() else Decimal(0)


def make_policy(location_codes: Iterable[str], brand_codes: Iterable[str], expose_price: bool) -> Policy:
    return Policy(frozenset(location_codes or ()), frozenset(brand_codes or ()), bool(expose_price))


def visible(item: ItemFacts, policy: Policy) -> bool:
    return bool(item.brand_code) and item.brand_code in policy.brand_codes


def in_stock(item: ItemFacts, policy: Policy) -> bool:
    total = sum(
        (_num(loc.get("available")) for loc in item.locations or () if loc.get("code") in policy.location_codes),
        Decimal(0),
    )
    return total > 0


def incoming(item: ItemFacts, policy: Policy) -> bool:
    for line in item.incoming or ():
        allocations = line.get("locations") or []
        if not allocations:
            if _num(line.get("qty")) > 0:
                return True  # not yet allocated to any location
            continue
        for alloc in allocations:
            if alloc.get("code") in policy.location_codes and _num(alloc.get("qty")) > 0:
                return True
    return False


def money(value: Decimal) -> str:
    """At least 2 decimals, no trailing storage zeros (120.0000 -> "120.00")."""
    amount = Decimal(str(value))
    cents = amount.quantize(Decimal("0.01"))
    return str(cents) if cents == amount else format(amount.normalize(), "f")


def view_for(item: ItemFacts, policy: Policy) -> Optional[Dict[str, Any]]:
    """The hub-facing row for this customer, or None when it is hidden."""
    if not visible(item, policy):
        return None
    view: Dict[str, Any] = {
        "code": item.code,
        "name": item.name,
        "brand_name": item.brand_name or item.brand_code,
        "in_stock": in_stock(item, policy),
        "incoming": incoming(item, policy),
    }
    if policy.expose_price and item.price is not None:
        view["list_price"] = money(item.price)
        view["currency"] = item.currency
    return view


def view_hash(view: Optional[Dict[str, Any]]) -> str:
    """Stable fingerprint of a view (``None`` = hidden)."""
    raw = json.dumps(view, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
