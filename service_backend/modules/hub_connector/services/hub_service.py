"""Hub registry + per (hub, customer company) transparency policy (AC-12..14).

Every query is tenant-scoped from the caller; a stored code is resolved inside
the tenant (polymorphic-target_id rule). Policy edits never commit half: the
mutating functions take ``commit=False`` so the router queues the customer's
resync in the SAME transaction and commits once.
"""
from __future__ import annotations

import re
import secrets as pysecrets
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.secrets import encrypt_secret
from app.services.url_guard import UnparseableUrlError, UrlGuardError, validate_public_https_url

from ..models import HcCustomer, HcHub, HcHubCustomer, HcItem
from . import availability

SECRET_SCHEME = "whsec_"
MAX_PAGE_SIZE = 200
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")


class HubError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _page(page: int, page_size: int) -> Tuple[int, int]:
    size = max(1, min(int(page_size or 25), MAX_PAGE_SIZE))
    return max(0, int(page or 0)) * size, size


def _like(value: str) -> str:
    escaped = value.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _clean_url(url: Optional[str]) -> Optional[str]:
    if url is None or not str(url).strip():
        return None
    try:
        return validate_public_https_url(str(url).strip(), strict_dns=False, subject="The receiver URL")
    except UnparseableUrlError:
        raise HubError(422, "invalid_url", "Enter a valid receiver URL.") from None
    except UrlGuardError as exc:
        raise HubError(422, "invalid_url", str(exc)) from None


def _codes(values: Optional[Sequence[str]]) -> List[str]:
    return list(dict.fromkeys(str(v).strip() for v in values or [] if isinstance(v, str) and v.strip()))


def _finish(db: Session, row: Any, commit: bool) -> None:
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()


# ── hubs ────────────────────────────────────────────────────────────────────

def new_secret() -> str:
    return SECRET_SCHEME + pysecrets.token_urlsafe(32)


def create_hub(
    db: Session, tenant_id: str, *, name: str, code: str, callback_url: Optional[str], expose_price: bool = False
) -> Tuple[HcHub, str]:
    clean_name = (name or "").strip()[:200]
    if not clean_name:
        raise HubError(422, "invalid_name", "Enter a name.")
    clean_code = (code or "").strip().lower()
    if not CODE_RE.match(clean_code):
        raise HubError(422, "invalid_code", "Use 2-63 lowercase letters, digits, - or _ for the code.")
    if db.query(HcHub.id).filter(HcHub.tenant_id == tenant_id, HcHub.code == clean_code).first():
        raise HubError(409, "hub_code_taken", "Another hub already uses this code.")
    secret = new_secret()
    row = HcHub(
        tenant_id=tenant_id,
        name=clean_name,
        code=clean_code,
        callback_url=_clean_url(callback_url),
        secret_encrypted=encrypt_secret({"secret": secret}),
        expose_price=bool(expose_price),
        active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, secret


def get_hub(db: Session, tenant_id: str, hub_id: str) -> HcHub:
    row = db.query(HcHub).filter(HcHub.id == hub_id, HcHub.tenant_id == tenant_id).first()
    if row is None:
        raise HubError(404, "hub_not_found", "This hub does not exist.")
    return row


def customer_counts(db: Session, tenant_id: str, hub_ids: Sequence[str]) -> Dict[str, int]:
    if not hub_ids:
        return {}
    rows = (
        db.query(HcHubCustomer.hub_id, func.count(HcHubCustomer.id))
        .filter(HcHubCustomer.tenant_id == tenant_id, HcHubCustomer.hub_id.in_(list(hub_ids)))
        .group_by(HcHubCustomer.hub_id)
        .all()
    )
    return {hub_id: int(n) for hub_id, n in rows}


_HUB_SORT = {
    "name": HcHub.name,
    "code": HcHub.code,
    "callbackUrl": HcHub.callback_url,
    "exposePrice": HcHub.expose_price,
    "active": HcHub.active,
    "lastSuccessAt": HcHub.last_success_at,
    "createdAt": HcHub.created_at,
}


def list_hubs(
    db: Session,
    tenant_id: str,
    *,
    search: Optional[str] = None,
    sort: Optional[str] = None,
    order: str = "asc",
    page: int = 0,
    page_size: int = 25,
) -> Tuple[List[HcHub], Dict[str, int], int]:
    counts_sq = (
        db.query(HcHubCustomer.hub_id.label("hub_id"), func.count(HcHubCustomer.id).label("n"))
        .filter(HcHubCustomer.tenant_id == tenant_id)
        .group_by(HcHubCustomer.hub_id)
        .subquery()
    )
    n = func.coalesce(counts_sq.c.n, 0)
    q = db.query(HcHub, n.label("n")).outerjoin(counts_sq, counts_sq.c.hub_id == HcHub.id).filter(
        HcHub.tenant_id == tenant_id
    )
    if search and search.strip():
        pattern = _like(search.strip())
        q = q.filter(or_(func.lower(HcHub.name).like(pattern, escape="\\"), func.lower(HcHub.code).like(pattern, escape="\\")))
    total = q.count()
    offset, size = _page(page, page_size)
    column = n if sort == "customerCount" else _HUB_SORT.get(sort or "", HcHub.name)
    primary = column.desc() if order == "desc" else column.asc()
    rows = q.order_by(primary, HcHub.id.asc()).offset(offset).limit(size).all()
    return [h for h, _ in rows], {h.id: int(c or 0) for h, c in rows}, total


def update_hub(
    db: Session, tenant_id: str, hub_id: str, changes: Dict[str, Any], *, commit: bool = True
) -> Tuple[HcHub, bool]:
    """Returns ``(hub, resync_needed)`` - a price switch or reactivation
    changes every customer's view."""
    hub = get_hub(db, tenant_id, hub_id)
    resync = False
    if "name" in changes and changes["name"] is not None:
        clean = str(changes["name"]).strip()[:200]
        if not clean:
            raise HubError(422, "invalid_name", "Enter a name.")
        hub.name = clean
    if "callbackUrl" in changes:
        new_url = _clean_url(changes["callbackUrl"])
        if new_url != hub.callback_url:
            hub.callback_url = new_url
            resync = resync or new_url is not None
    if "exposePrice" in changes and changes["exposePrice"] is not None:
        if bool(changes["exposePrice"]) != bool(hub.expose_price):
            hub.expose_price = bool(changes["exposePrice"])
            resync = True
    if "active" in changes and changes["active"] is not None:
        if bool(changes["active"]) != bool(hub.active):
            hub.active = bool(changes["active"])
            resync = resync or hub.active
    _finish(db, hub, commit)
    return hub, resync


def rotate_secret(db: Session, tenant_id: str, hub_id: str) -> str:
    hub = get_hub(db, tenant_id, hub_id)
    secret = new_secret()
    hub.secret_encrypted = encrypt_secret({"secret": secret})
    db.commit()
    return secret


def delete_hub(db: Session, tenant_id: str, hub_id: str) -> None:
    from ..models import HcDelivery, HcSentView

    hub = get_hub(db, tenant_id, hub_id)
    customer_ids = [
        cid for (cid,) in db.query(HcHubCustomer.id).filter(HcHubCustomer.hub_id == hub.id, HcHubCustomer.tenant_id == tenant_id)
    ]
    if customer_ids:
        db.query(HcSentView).filter(HcSentView.tenant_id == tenant_id, HcSentView.hub_customer_id.in_(customer_ids)).delete(
            synchronize_session=False
        )
    db.query(HcDelivery).filter(HcDelivery.tenant_id == tenant_id, HcDelivery.hub_id == hub.id).delete(synchronize_session=False)
    db.query(HcHubCustomer).filter(HcHubCustomer.tenant_id == tenant_id, HcHubCustomer.hub_id == hub.id).delete(
        synchronize_session=False
    )
    db.delete(hub)
    db.commit()


# ── hub customers (the policy) ──────────────────────────────────────────────

def _known_codes(db: Session, tenant_id: str) -> Tuple[set, set]:
    """Location + brand codes the CRM has pushed for this tenant."""
    locations, brands = set(), set()
    for locs, brand in db.query(HcItem.locations_json, HcItem.brand_code).filter(HcItem.tenant_id == tenant_id):
        for loc in locs or []:
            if isinstance(loc, dict) and loc.get("code"):
                locations.add(loc["code"])
        if brand:
            brands.add(brand)
    return locations, brands


def _validate_policy(
    db: Session,
    tenant_id: str,
    location_codes: List[str],
    brand_codes: List[str],
    *,
    kept_locations: Sequence[str] = (),
    kept_brands: Sequence[str] = (),
) -> None:
    """Only offer valid options: a code the CRM never pushed is refused. Codes
    the policy already held are kept even if the CRM stopped sending them, so
    an unrelated edit (e.g. pausing) never trips on them."""
    known_locations, known_brands = _known_codes(db, tenant_id)
    known_locations |= set(kept_locations)
    known_brands |= set(kept_brands)
    bad_loc = [c for c in location_codes if c not in known_locations]
    if bad_loc:
        raise HubError(422, "unknown_location", f"Unknown location: {bad_loc[0]}.")
    bad_brand = [c for c in brand_codes if c not in known_brands]
    if bad_brand:
        raise HubError(422, "unknown_brand", f"Unknown brand: {bad_brand[0]}.")


def get_hub_customer(db: Session, tenant_id: str, hub_id: str, hub_customer_id: str) -> HcHubCustomer:
    row = (
        db.query(HcHubCustomer)
        .filter(
            HcHubCustomer.id == hub_customer_id,
            HcHubCustomer.hub_id == hub_id,
            HcHubCustomer.tenant_id == tenant_id,
        )
        .first()
    )
    if row is None:
        raise HubError(404, "customer_not_found", "This customer is not on this hub.")
    return row


def add_customer(
    db: Session,
    tenant_id: str,
    hub_id: str,
    *,
    customer_code: str,
    location_codes: Sequence[str],
    brand_codes: Sequence[str],
    commit: bool = True,
) -> HcHubCustomer:
    hub = get_hub(db, tenant_id, hub_id)
    code = (customer_code or "").strip()
    customer = db.query(HcCustomer).filter(HcCustomer.tenant_id == tenant_id, HcCustomer.code == code).first()
    if customer is None:
        raise HubError(422, "unknown_customer", "Choose a customer company.")
    if (
        db.query(HcHubCustomer.id)
        .filter(HcHubCustomer.tenant_id == tenant_id, HcHubCustomer.hub_id == hub.id, HcHubCustomer.customer_code == code)
        .first()
    ):
        raise HubError(409, "customer_exists", "This customer is already on this hub.")
    locs, brands = _codes(location_codes), _codes(brand_codes)
    _validate_policy(db, tenant_id, locs, brands)
    row = HcHubCustomer(
        tenant_id=tenant_id,
        hub_id=hub.id,
        customer_code=code,
        location_codes_json=locs,
        brand_codes_json=brands,
        active=True,
    )
    db.add(row)
    _finish(db, row, commit)
    return row


def update_customer(
    db: Session, tenant_id: str, hub_id: str, hub_customer_id: str, changes: Dict[str, Any], *, commit: bool = True
) -> HcHubCustomer:
    row = get_hub_customer(db, tenant_id, hub_id, hub_customer_id)
    old_locs, old_brands = list(row.location_codes_json or []), list(row.brand_codes_json or [])
    locs = _codes(changes["locationCodes"]) if changes.get("locationCodes") is not None else old_locs
    brands = _codes(changes["brandCodes"]) if changes.get("brandCodes") is not None else old_brands
    _validate_policy(db, tenant_id, locs, brands, kept_locations=old_locs, kept_brands=old_brands)
    row.location_codes_json = locs
    row.brand_codes_json = brands
    if changes.get("active") is not None:
        row.active = bool(changes["active"])
    _finish(db, row, commit)
    return row


def remove_customer(
    db: Session, tenant_id: str, hub_id: str, hub_customer_id: str, *, commit: bool = True
) -> HcHubCustomer:
    """Removed customers get nothing more; the hub is told to drop every item
    the customer could see (queued by the caller before the row goes)."""
    from ..models import HcSentView

    row = get_hub_customer(db, tenant_id, hub_id, hub_customer_id)
    db.query(HcSentView).filter(HcSentView.tenant_id == tenant_id, HcSentView.hub_customer_id == row.id).delete(
        synchronize_session=False
    )
    db.delete(row)
    if commit:
        db.commit()
    else:
        db.flush()
    return row


_CUSTOMER_SORT = {
    "customerCode": HcHubCustomer.customer_code,
    "customerName": HcCustomer.name,
    "active": HcHubCustomer.active,
    "updatedAt": HcHubCustomer.updated_at,
}


def list_customers(
    db: Session,
    tenant_id: str,
    hub_id: str,
    *,
    search: Optional[str] = None,
    sort: Optional[str] = None,
    order: str = "asc",
    page: int = 0,
    page_size: int = 25,
) -> Tuple[List[Tuple[HcHubCustomer, Optional[str]]], int]:
    get_hub(db, tenant_id, hub_id)
    q = (
        db.query(HcHubCustomer, HcCustomer.name)
        .outerjoin(HcCustomer, (HcCustomer.code == HcHubCustomer.customer_code) & (HcCustomer.tenant_id == tenant_id))
        .filter(HcHubCustomer.tenant_id == tenant_id, HcHubCustomer.hub_id == hub_id)
    )
    if search and search.strip():
        pattern = _like(search.strip())
        q = q.filter(
            or_(
                func.lower(HcHubCustomer.customer_code).like(pattern, escape="\\"),
                func.lower(func.coalesce(HcCustomer.name, "")).like(pattern, escape="\\"),
            )
        )
    total = q.count()
    offset, size = _page(page, page_size)
    column = _CUSTOMER_SORT.get(sort or "", HcCustomer.name)
    primary = column.desc() if order == "desc" else column.asc()
    rows = q.order_by(primary, HcHubCustomer.id.asc()).offset(offset).limit(size).all()
    return [(r, name) for r, name in rows], total


def customer_name(db: Session, tenant_id: str, code: str) -> Optional[str]:
    row = db.query(HcCustomer.name).filter(HcCustomer.tenant_id == tenant_id, HcCustomer.code == code).first()
    return row[0] if row else None


def name_maps(db: Session, tenant_id: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Location + brand code -> name, from the pushed facts (display only)."""
    locations: Dict[str, str] = {}
    brands: Dict[str, str] = {}
    for locs, bcode, bname in db.query(HcItem.locations_json, HcItem.brand_code, HcItem.brand_name).filter(
        HcItem.tenant_id == tenant_id
    ):
        for loc in locs or []:
            if isinstance(loc, dict) and loc.get("code"):
                locations.setdefault(loc["code"], loc.get("name") or loc["code"])
        if bcode:
            brands.setdefault(bcode, bname or bcode)
    return locations, brands


# ── facts -> view ───────────────────────────────────────────────────────────

def item_facts(row: HcItem) -> availability.ItemFacts:
    return availability.ItemFacts(
        code=row.code,
        name=row.name,
        brand_code=row.brand_code,
        brand_name=row.brand_name,
        price=row.price,
        currency=row.currency,
        locations=list(row.locations_json or []),
        incoming=list(row.incoming_json or []),
    )


def policy_for(hub: HcHub, customer: HcHubCustomer) -> availability.Policy:
    return availability.make_policy(customer.location_codes_json or [], customer.brand_codes_json or [], hub.expose_price)


def preview(db: Session, tenant_id: str, hub_id: str, hub_customer_id: str) -> List[Dict[str, Any]]:
    """What this customer sees right now - the same function the webhook uses."""
    hub = get_hub(db, tenant_id, hub_id)
    customer = get_hub_customer(db, tenant_id, hub_id, hub_customer_id)
    policy = policy_for(hub, customer)
    brands = list(policy.brand_codes)
    if not brands:
        return []
    rows = (
        db.query(HcItem)
        .filter(HcItem.tenant_id == tenant_id, HcItem.brand_code.in_(brands))
        .order_by(HcItem.name.asc(), HcItem.code.asc())
        .all()
    )
    return [v for v in (availability.view_for(item_facts(r), policy) for r in rows) if v is not None]


# ── picker options (fed by what the CRM pushed) ─────────────────────────────

OPTION_LIMIT = 50


def _filter_options(pairs: Dict[str, str], search: Optional[str]) -> List[Dict[str, str]]:
    needle = (search or "").strip().lower()
    out = [
        {"code": code, "name": name}
        for code, name in pairs.items()
        if not needle or needle in code.lower() or needle in (name or "").lower()
    ]
    out.sort(key=lambda o: ((o["name"] or "").lower(), o["code"]))
    return out[:OPTION_LIMIT] if needle else out


def options(db: Session, tenant_id: str, kind: str, search: Optional[str] = None) -> List[Dict[str, str]]:
    if kind == "customers":
        q = db.query(HcCustomer.code, HcCustomer.name).filter(HcCustomer.tenant_id == tenant_id)
        if search and search.strip():
            pattern = _like(search.strip())
            q = q.filter(or_(func.lower(HcCustomer.code).like(pattern, escape="\\"), func.lower(HcCustomer.name).like(pattern, escape="\\")))
        return [{"code": c, "name": n} for c, n in q.order_by(HcCustomer.name.asc(), HcCustomer.code.asc()).limit(OPTION_LIMIT)]
    locations, brands = name_maps(db, tenant_id)
    if kind == "locations":
        return _filter_options(locations, search)
    if kind == "brands":
        return _filter_options(brands, search)
    raise HubError(404, "unknown_option", "Unknown list.")
