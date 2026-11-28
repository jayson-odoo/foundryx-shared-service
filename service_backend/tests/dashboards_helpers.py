"""Shared builders for the dashboards suite (AI dashboard builder, slice 1, SS lane).

Contract: documentation/plans/ai-builder/SS-dashboards-contract.md (THE wire contract). Everything here
is fake-but-stable data: users u-owner-1 / u-viewer-1 / u-other-1, fake customer names, no real people.
The module under test (modules.dashboards) is imported lazily inside helpers and fixtures so a missing
module fails each test, not the whole collection.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from app.ai.stub import StubResponse
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD  # noqa: F401
from tests.meetings_helpers import make_admin_user, make_tenant

BASE = "/api/v1/dashboards"
TENANT_B = "tenant-dash-b"
TENANT_B_NAME = "Dash B"
TENANT_B_SLUG = "dash-b"  # make_tenant derives the slug from the name
TENANT_C = "tenant-dash-c"
TENANT_C_NAME = "Dash C"
DEFAULT_SLUG = "default"

OWNER = "u-owner-1"
VIEWER = "u-viewer-1"
OTHER = "u-other-1"

NOT_YET = "This chart type is not available yet."
FORBIDDEN = "Only names and values can be used in a chart, not code or links."

# Words that would mean a validator error leaked through unrendered (the contract: reasons are plain words).
JARGON = (
    "field required", "extra_forbidden", "value_error", "pydantic", "validation error", "input should",
    "extra inputs", "traceback", "jsonschema", "additional properties", "type_error", "string_too",
    "literal_error", "none is not a valid",
)


# -- the contract's section-4 catalogue --------------------------------------------------------------

CATALOGUE: Dict[str, Any] = {
    "version": 2,
    "draws": ["number", "line", "bar", "table"],
    "index": [
        {"entity": "billing_document", "label": "Billing documents (invoices, cash sales, debit and credit notes)",
         "module": "finance"},
        {"entity": "customer", "label": "Customers", "module": "sales"},
        {"entity": "support_ticket", "label": "Support tickets", "module": "support"},
        {"entity": "sales_order", "label": "Sales orders", "module": "sales"},
    ],
    "entities": [
        {
            "entity": "billing_document",
            "label": "Billing documents (invoices, cash sales, debit and credit notes)",
            "only_own_rows": False,
            "totals_allowed": True,
            "period_field": "doc_date",
            "show": ["number", "line", "bar", "table"],
            "fields": [
                {"field": "doc_date", "label": "Document date", "type": "date",
                 "note": "The date sales are counted by."},
                {"field": "customer_name", "label": "Customer", "type": "text"},
                {"field": "sales_amount", "label": "Sales (RM)", "type": "number",
                 "note": "THE sales figure."},
            ],
            "relations": [
                {"name": "customer", "entity": "customer",
                 "fields": [{"field": "name", "label": "Name", "type": "text"}]},
            ],
            "default_note": "Cancelled documents excluded.",
        },
        {
            "entity": "customer",
            "label": "Customers",
            "only_own_rows": False,
            "totals_allowed": True,
            "period_field": "created_on",
            "show": ["number", "bar", "table"],
            "fields": [
                {"field": "name", "label": "Name", "type": "text"},
                {"field": "created_on", "label": "Created on", "type": "date"},
                {"field": "region", "label": "Region", "type": "text"},
            ],
            "relations": [],
        },
        {
            "entity": "support_ticket",
            "label": "Support tickets",
            "only_own_rows": True,
            "totals_allowed": False,
            "period_field": None,
            "show": ["table"],
            "fields": [
                {"field": "subject", "label": "Subject", "type": "text"},
                {"field": "opened_on", "label": "Opened on", "type": "date"},
            ],
            "relations": [],
        },
    ],
    "buckets": ["day", "week", "month", "quarter", "year"],
    "aggregates": ["count", "count_distinct", "sum", "avg", "min", "max"],
    "limits": {"tiles": 12, "rows": 50, "groups": 200},
}


def catalogue(**overrides) -> Dict[str, Any]:
    cat = copy.deepcopy(CATALOGUE)
    cat.update(overrides)
    return cat


def catalogue_without(entity: str) -> Dict[str, Any]:
    cat = copy.deepcopy(CATALOGUE)
    cat["entities"] = [e for e in cat["entities"] if e["entity"] != entity]
    return cat


SALES_ORDER_ENTITY: Dict[str, Any] = {
    "entity": "sales_order", "label": "Sales orders", "only_own_rows": False, "totals_allowed": True,
    "period_field": "order_date", "show": ["number", "line", "bar", "table"],
    "fields": [
        {"field": "order_date", "label": "Order date", "type": "date"},
        {"field": "order_total", "label": "Total (RM)", "type": "number"},
    ],
    "relations": [],
}


def catalogue_entity(cat: Dict[str, Any], entity: str) -> Dict[str, Any]:
    return next(e for e in cat["entities"] if e["entity"] == entity)


# -- the F1 tiles (contract section 8) ---------------------------------------------------------------

F1_TILES: List[Dict[str, Any]] = [
    {"id": "t1", "title": "Invoiced sales by month", "show": "line",
     "source": {"kind": "query", "spec": {
         "entity": "billing_document",
         "group_by": [{"field": "doc_date", "bucket": "month"}],
         "aggregates": [{"fn": "sum", "field": "sales_amount"}]}}},
    {"id": "t2", "title": "Top 10 customers", "show": "table",
     "source": {"kind": "query", "spec": {
         "entity": "billing_document",
         "group_by": ["customer_name"], "aggregates": [{"fn": "sum", "field": "sales_amount"}],
         "sort": [{"field": "sum_sales_amount", "dir": "desc"}], "limit": 10}}},
]


def f1_tiles() -> List[Dict[str, Any]]:
    return copy.deepcopy(F1_TILES)


def empty_draft(title: str = "New dashboard", period: Any = "this_year") -> Dict[str, Any]:
    return {"version": 1, "title": title, "period": period, "tiles": []}


def f1_spec(title: str = "Sales overview") -> Dict[str, Any]:
    return {"version": 1, "title": title, "period": "this_year", "tiles": f1_tiles()}


def without_id(tile: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(tile)
    out.pop("id", None)
    return out


def with_id(tile: Dict[str, Any], tile_id: str) -> Dict[str, Any]:
    out = copy.deepcopy(tile)
    out["id"] = tile_id
    return out


def add_op(tile: Dict[str, Any], model_id: str = "t7") -> Dict[str, Any]:
    """An add_tile op as a model would emit it (it sends an id; SS must ignore it)."""
    return {"op": "add_tile", "tile": with_id(tile, model_id)}


def ops_out(reply: str, *operations: Dict[str, Any], tokens_in: int = 100, tokens_out: int = 40) -> StubResponse:
    return StubResponse(structured={"reply": reply, "operations": list(operations)},
                        tokens_in=tokens_in, tokens_out=tokens_out)


# -- plain-words check -------------------------------------------------------------------------------

def assert_plain(problems: List[Dict[str, Any]]) -> None:
    assert problems, "expected at least one problem"
    for p in problems:
        assert isinstance(p, dict) and isinstance(p.get("path"), str), p
        reason = p.get("reason")
        assert isinstance(reason, str) and reason.strip(), p
        low = reason.lower()
        for word in JARGON:
            assert word not in low, f"jargon {word!r} leaked into reason: {reason!r}"


# -- request helpers ---------------------------------------------------------------------------------

def hdr(key: Optional[str]) -> Dict[str, str]:
    return {"X-API-Key": key} if key else {}


def new_idem() -> str:
    return str(uuid.uuid4())


def save(client, key, actor, name, spec, *, dashboard_id=None, base_version=None, idempotency_key=None, **extra):
    body = {"actor_ref": actor, "dashboard_id": dashboard_id, "name": name, "spec": spec,
            "base_version": base_version, "idempotency_key": idempotency_key or new_idem()}
    body.update(extra)
    return client.post(f"{BASE}/save", json=body, headers=hdr(key))


def create_dash(client, key, actor=OWNER, name="Sales overview", spec=None) -> Dict[str, Any]:
    res = save(client, key, actor, name, spec if spec is not None else f1_spec())
    assert res.status_code == 200, res.text
    return res.json()


def get(client, key, actor, did, **params):
    return client.get(f"{BASE}/{did}", params={"actor_ref": actor, **params}, headers=hdr(key))


def versions(client, key, actor, did, **params):
    return client.get(f"{BASE}/{did}/versions", params={"actor_ref": actor, **params}, headers=hdr(key))


def share(client, key, actor, did, refs, **extra):
    body = {"actor_ref": actor, "shared_with": [{"user_ref": r} for r in refs]}
    body.update(extra)
    return client.post(f"{BASE}/{did}/share", json=body, headers=hdr(key))


def delete(client, key, actor, did, **extra):
    return client.post(f"{BASE}/{did}/delete", json={"actor_ref": actor, **extra}, headers=hdr(key))


def listing(client, key, actor, **params):
    return client.get(BASE, params={"actor_ref": actor, **params}, headers=hdr(key))


def png_b64(n: int = 8) -> str:
    import base64

    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * n).decode()


def image(media_type: str = "image/png", size: int = 8, name: str = "mockup.png") -> Dict[str, Any]:
    import base64

    return {"name": name, "media_type": media_type, "data_base64": base64.b64encode(b"x" * size).decode()}


def need_out(*entities: str, tokens_in: int = 90, tokens_out: int = 10) -> StubResponse:
    return StubResponse(structured={"need_entities": list(entities), "reply": None, "operations": []},
                        tokens_in=tokens_in, tokens_out=tokens_out)


def turn(client, key, actor, message, *, draft=None, catalogue_=None, dashboard_id=None, **extra):
    body = {"actor_ref": actor, "dashboard_id": dashboard_id,
            "draft": draft if draft is not None else empty_draft(), "message": message,
            "catalogue": catalogue_ if catalogue_ is not None else copy.deepcopy(CATALOGUE),
            "turn_id": new_idem(), "refusals": [], "history": []}
    body.update(extra)
    return client.post(f"{BASE}/builder/turn", json=body, headers=hdr(key))


def error_code(res) -> Optional[str]:
    body = res.json()
    return body.get("error") if isinstance(body, dict) else None


def assert_flat_error(res, status: int, code: str) -> Dict[str, Any]:
    assert res.status_code == status, res.text
    body = res.json()
    assert body.get("error") == code, body
    assert isinstance(body.get("message"), str) and body["message"].strip(), body
    assert "detail" not in body, f"error body must be flat, got {body}"
    return body


def versions_items(client, key, actor, did) -> List[Dict[str, Any]]:
    res = versions(client, key, actor, did)
    assert res.status_code == 200, res.text
    return res.json()["items"]


# -- DB peeks ----------------------------------------------------------------------------------------

def usage_rows(sf):
    from modules.dashboards.models import DashUsage

    db = sf()
    try:
        rows = db.query(DashUsage).all()
        db.expunge_all()
        return rows
    finally:
        db.close()


def count_model(sf, model_name: str) -> int:
    import modules.dashboards.models as m

    db = sf()
    try:
        return db.query(getattr(m, model_name)).count()
    finally:
        db.close()


# -- fixtures ----------------------------------------------------------------------------------------

@dataclass
class Dash:
    sf: Any
    sorento: str = ""        # tenant A (default), product sorento_crm
    ecohub: str = ""         # tenant A (default), product ecohub
    b_sorento: str = ""      # tenant B, product sorento_crm
    key_ids: Dict[str, str] = field(default_factory=dict)
    tenant_a: str = DEFAULT_TENANT_ID
    tenant_a_slug: str = DEFAULT_SLUG
    tenant_b: str = TENANT_B
    tenant_b_slug: str = TENANT_B_SLUG


def issue_key(db, tenant_id: str, product: str, name: str = "CRM"):
    from modules.dashboards.services import key_service

    row, full = key_service.issue(db, tenant_id, product=product, name=name, created_by=None)
    db.commit()
    assert full.startswith("fxd_live_"), full
    return row, full


@pytest.fixture
def dash(session_factory, monkeypatch):
    """dashboards installed for the default tenant and tenant B; keys (A, sorento_crm), (A, ecohub),
    (B, sorento_crm) issued."""
    import app.database as database
    from app.services.app_store_service import AppStoreService

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    db = session_factory()
    try:
        AppStoreService(db).install(DEFAULT_TENANT_ID, "dashboards")
        make_tenant(db, TENANT_B, TENANT_B_NAME)
        make_admin_user(db, TENANT_B, "admin@dash-b.example")
        AppStoreService(db).install(TENANT_B, "dashboards")
        db.commit()
        d = Dash(sf=session_factory)
        for attr, tenant, product in (("sorento", DEFAULT_TENANT_ID, "sorento_crm"),
                                      ("ecohub", DEFAULT_TENANT_ID, "ecohub"),
                                      ("b_sorento", TENANT_B, "sorento_crm")):
            row, full = issue_key(db, tenant, product)
            setattr(d, attr, full)
            d.key_ids[attr] = row.id
    finally:
        db.close()
    return d


@pytest.fixture
def dstaff(client, dash):
    """Staff bearer headers for the default tenant Admin (holds dashboards.keys.manage after install)."""
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@dataclass
class LlmCounter:
    n: int = 0
    calls: List[Dict[str, Any]] = field(default_factory=list)

    def prompt_text(self, call: int = 0) -> str:
        c = self.calls[call]
        return str(c.get("system", "")) + " " + str(c.get("messages", ""))


@pytest.fixture
def llm(monkeypatch):
    """Counts AiClient.complete calls (wraps the original, so the stub still answers)."""
    from app.ai.client import AiClient

    counter = LlmCounter()
    original = AiClient.complete

    def counting(self, *args, **kwargs):
        counter.n += 1
        counter.calls.append(kwargs)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AiClient, "complete", counting)
    return counter
