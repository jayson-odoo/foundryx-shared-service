"""Hub connector S1, shared-service side (AC-12..AC-19).

The CRM side is the frozen connector feed (sorento-crm #2801): GET
/locations, /brands, /products, /availability with X-API-Key + ?company=.
Here a fake CRM answers those routes through an httpx MockTransport, and a
stub hub receives the signed webhooks. No real network.
"""
from __future__ import annotations

import copy
import csv
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.hub_connector import crm_feed
from modules.hub_connector.models import DELIVERY_FAILED, DELIVERY_SUCCESS, HcDelivery, HcHub
from modules.hub_connector.services import availability, delivery_service
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.meetings_helpers import make_admin_user, make_tenant

ROOT = Path(__file__).resolve().parents[2]
TENANT_B = "tenant-hub-b"
HUB_URL = "https://hub.example/webhooks/availability"
CRM_URL = "https://crm.example"
CRM_KEY = "crm-connector-key-123"


# ── AC-15 / AC-16 / AC-14: the one shared rule (pure) ──────────────────────

def _facts(**kw) -> availability.ItemFacts:
    base = dict(
        code="SR-1", name="Item one", brand_code="BR-A", brand_name="Brand A",
        price=Decimal("12.50"), currency="MYR", locations=[], incoming=[],
    )
    base.update(kw)
    return availability.ItemFacts(**base)


def _policy(locs=("WH-1", "WH-2"), brands=("BR-A",), price=False):
    return availability.make_policy(locs, brands, price)


@pytest.mark.parametrize(
    "locations,expected",
    [
        ([{"code": "WH-1", "available": 0}], False),
        ([{"code": "WH-1", "available": 3}], True),
        ([{"code": "WH-9", "available": 50}], False),  # outside the policy
        # SUM over chosen locations: a negative and a positive cancel out.
        ([{"code": "WH-1", "available": -2}, {"code": "WH-2", "available": 2}], False),
        ([{"code": "WH-1", "available": -1}, {"code": "WH-2", "available": 2}], True),
        ([{"code": "WH-1", "available": None}], False),
    ],
)
def test_in_stock_is_the_sum_over_chosen_locations(locations, expected):
    assert availability.in_stock(_facts(locations=locations), _policy()) is expected


@pytest.mark.parametrize(
    "lines,expected",
    [
        ([{"eta": "2026-12-15", "qty": 40, "locations": [{"code": "WH-1", "qty": 25}]}], True),
        ([{"eta": None, "qty": 40, "locations": [{"code": "WH-9", "qty": 40}]}], False),  # another location
        ([{"eta": None, "qty": 40, "locations": []}], True),  # not yet allocated (crew Q-A (a))
        ([{"eta": None, "qty": 0, "locations": []}], False),
        ([{"eta": None, "qty": 5, "locations": [{"code": "WH-1", "qty": 0}]}], False),
        ([], False),
    ],
)
def test_incoming_counts_allocated_to_chosen_or_unallocated(lines, expected):
    assert availability.incoming(_facts(incoming=lines), _policy()) is expected


def test_hub_row_shape_brand_filter_and_price_switch():
    assert availability.view_for(_facts(brand_code="BR-B"), _policy()) is None
    assert availability.view_for(_facts(brand_code=None), _policy()) is None
    assert availability.view_for(_facts(), _policy()) == {
        "code": "SR-1", "name": "Item one", "brand_name": "Brand A", "in_stock": False, "incoming": False,
    }
    shown = availability.view_for(_facts(), _policy(price=True))
    assert shown["list_price"] == "12.50" and shown["currency"] == "MYR"
    assert "list_price" not in availability.view_for(_facts(price=None), _policy(price=True))


# ── fake CRM feed + stub hub ────────────────────────────────────────────────

LOCATIONS = [
    {"code": "WH-N", "name": "North warehouse", "sellable": True},
    {"code": "WH-S", "name": "South warehouse", "sellable": True},
]
BRANDS = [{"code": "BR-A", "name": "Brand A"}, {"code": "BR-B", "name": "Brand B"}]


def _product(code, name, brand, price):
    return {
        "code": code, "name": name, "brand_code": brand, "brand_name": f"Brand {brand[-1]}",
        "category_code": None, "category_name": None, "description": None,
        "length_mm": None, "width_mm": None, "height_mm": None, "uom": "UNIT",
        "thumbnail_url": None, "image_urls": [], "list_price": price, "currency": "MYR",
        "model": {"available": False, "formats": []}, "updated_at": "2026-11-26T19:10:00+08:00",
    }


class FakeCrm:
    def __init__(self):
        self.locations = copy.deepcopy(LOCATIONS)
        self.brands = copy.deepcopy(BRANDS)
        self.products = [
            _product("SR-1001", "Basin mixer", "BR-A", "120.00"),
            _product("SR-1002", "Shower set", "BR-B", "300.00"),
        ]
        self.availability = {
            "SR-1001": {
                "code": "SR-1001",
                "locations": [{"code": "WH-N", "available_qty": 0}, {"code": "WH-S", "available_qty": 3}],
                "incoming_lines": [{"eta": None, "qty": 6, "locations": []}],
                "as_of": "2026-11-26T19:05:00+08:00",
            },
            "SR-1002": {
                "code": "SR-1002",
                "locations": [{"code": "WH-N", "available_qty": 2}, {"code": "WH-S", "available_qty": 0}],
                "incoming_lines": [{"eta": "2026-12-15", "qty": 1, "locations": [{"code": "WH-S", "qty": 1}]}],
                "as_of": None,
            },
        }
        self.status = 200
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.headers["X-API-Key"] == CRM_KEY
        assert request.url.params["company"] == "CO-1"
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "no"}, headers={"Retry-After": "30"})
        path = request.url.path.split("/connector/v1", 1)[1]
        if path == "/locations":
            return httpx.Response(200, json={"data": self.locations})
        if path == "/brands":
            return httpx.Response(200, json={"data": self.brands})
        if path == "/products":
            limit, offset = int(request.url.params["limit"]), int(request.url.params["offset"])
            page = self.products[offset: offset + limit]
            return httpx.Response(200, json={"data": page, "total": len(self.products), "limit": limit, "offset": offset})
        if path == "/availability":
            codes = request.url.params["codes"].split(",")
            assert len(codes) <= 200
            data = [self.availability[c] for c in codes if c in self.availability]
            return httpx.Response(200, json={"data": data, "missing": [c for c in codes if c not in self.availability]})
        return httpx.Response(404, json={})


@pytest.fixture
def crm(monkeypatch):
    fake = FakeCrm()
    monkeypatch.setattr(crm_feed, "_http", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    return fake


@pytest.fixture
def hc(session_factory, monkeypatch):
    """Hub Connector installed for the default tenant; workers use the test DB."""
    import app.database as database
    from app.services.app_store_service import AppStoreService

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    db = session_factory()
    try:
        AppStoreService(db).install(DEFAULT_TENANT_ID, "hub_connector")
        db.commit()
    finally:
        db.close()
    return session_factory


class StubHub:
    """The hub's receiver: verifies the signature, keeps what it accepted."""

    def __init__(self):
        self.secret = None
        self.received = []
        self.status = 200
        self.bad_signatures = 0

    def post(self, url, *, content, headers, timeout):
        if isinstance(self.status, Exception):
            raise self.status
        if self.secret is not None and not delivery_service.verify(self.secret, headers["X-Hub-Connector-Signature"], content):
            self.bad_signatures += 1
            return delivery_service.webhook_post.PostReply(401)
        if 200 <= self.status < 300:
            self.received.append({"url": url, "headers": dict(headers), "body": json.loads(content)})
        return delivery_service.webhook_post.PostReply(self.status)

    def by_customer(self, code):
        return [r["body"]["data"] for r in self.received if r["body"]["data"]["customer"]["code"] == code]


@pytest.fixture
def stub_hub(monkeypatch):
    hub = StubHub()
    monkeypatch.setattr(delivery_service, "_post", hub.post)
    monkeypatch.setattr(delivery_service, "_assert_deliverable", lambda url: None)
    return hub


def _login(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _connect_feed(client, headers):
    res = client.post(
        "/integrations/connections",
        json={
            "provider": crm_feed.PROVIDER_KEY,
            "name": "CRM stock feed",
            "config": {"baseUrl": CRM_URL, "company": "CO-1"},
            "credentials": {"apiKey": CRM_KEY},
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _sync(client, headers):
    res = client.post("/hub-connector/sync", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _hub(client, headers, **kw):
    body = {"name": "EcoHub", "code": "ecohub", "callbackUrl": HUB_URL}
    body.update(kw)
    res = client.post("/hub-connector/hubs", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _add_customer(client, headers, hub_id, code, name, locs, brands):
    res = client.post(
        f"/hub-connector/hubs/{hub_id}/customers",
        json={"customerCode": code, "customerName": name, "locationCodes": locs, "brandCodes": brands},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _ready(client, crm_unused=None):
    headers = _login(client)
    _connect_feed(client, headers)
    _sync(client, headers)
    return headers


def _force_due(db, delivery_id):
    db.query(HcDelivery).filter(HcDelivery.id == delivery_id).update(
        {"next_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
    )
    db.commit()


# ── module + permissions ────────────────────────────────────────────────────

def test_manifest_permissions_and_revision():
    manifest = json.loads((ROOT / "service_backend/modules/hub_connector/manifest.json").read_text())
    assert manifest["schema"] == "app_hub_connector"
    routers = {r["name"]: r for r in manifest["routers"]}
    assert routers["inbound"]["public"] is True and not routers["staff"].get("public")

    def keys(path):
        with open(path, newline="") as fh:
            return {f"{r['resource']}.{r['action']}" for r in csv.DictReader(fh)}

    ours = keys(ROOT / "service_backend/modules/hub_connector/permissions/permissions.csv")
    assert ours == {"hub_connector.view", "hub_connector.manage", "hub_connector.keys.manage"}
    others = set()
    for path in (ROOT / "service_backend").glob("**/permissions*.csv"):
        if "hub_connector" in str(path) or ".venv" in str(path):
            continue
        others |= keys(path)
    assert not ours & others
    text = (ROOT / "service_backend/modules/hub_connector/alembic/versions/0001_hub_connector_init.py").read_text()
    assert len(text.split('revision = "', 1)[1].split('"', 1)[0]) <= 32


def test_install_grants_admin_and_module_gate(client, hc):
    headers = _login(client)
    perms = set(client.get("/auth/me", headers=headers).json()["permissions"])
    assert {"hub_connector.view", "hub_connector.manage", "hub_connector.keys.manage"} <= perms
    assert client.get("/hub-connector/hubs", headers=headers).status_code == 200


def test_not_installed_is_refused(client):
    headers = _login(client)
    assert client.get("/hub-connector/hubs", headers=headers).status_code == 403


# ── AC-17 the CRM feed pull ─────────────────────────────────────────────────

def test_feed_provider_is_on_the_integrations_screen_and_tests(client, hc, crm):
    headers = _login(client)
    providers = client.get("/integrations/providers", headers=headers).json()
    keys = {p.get("provider") or p.get("key") for p in (providers.get("data", providers) if isinstance(providers, dict) else providers)}
    assert crm_feed.PROVIDER_KEY in keys
    conn = _connect_feed(client, headers)
    res = client.post(f"/integrations/connections/{conn['id']}/test", json={}, headers=headers)
    assert res.status_code == 200 and res.json()["ok"] is True, res.text
    crm.status = 403
    res = client.post(f"/integrations/connections/{conn['id']}/test", json={}, headers=headers)
    assert res.json()["ok"] is False and "grant" in res.json()["message"]


def test_sync_without_a_feed_says_so(client, hc):
    headers = _login(client)
    res = client.post("/hub-connector/sync", headers=headers)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "no_feed"
    assert client.get("/hub-connector/sync", headers=headers).json()["configured"] is False


def test_sync_pulls_catalogues_products_and_availability(client, hc, crm):
    headers = _login(client)
    _connect_feed(client, headers)
    state = _sync(client, headers)
    assert state["configured"] is True and state["products"] == 2 and state["lastError"] is None
    locs = client.get("/hub-connector/options/locations", headers=headers).json()["data"]
    assert locs == [{"code": "WH-N", "name": "North warehouse"}, {"code": "WH-S", "name": "South warehouse"}]
    brands = client.get("/hub-connector/options/brands", params={"search": "brand b"}, headers=headers).json()["data"]
    assert brands == [{"code": "BR-B", "name": "Brand B"}]
    paths = {c.url.path.rsplit("/", 1)[1] for c in crm.calls}
    assert paths == {"locations", "brands", "products", "availability"}


def test_products_page_and_availability_chunks(client, hc, crm, monkeypatch):
    monkeypatch.setattr(crm_feed, "PAGE_LIMIT", 2)
    monkeypatch.setattr(crm_feed, "CODES_PER_CALL", 2)
    crm.products += [_product(f"SR-2{i:03d}", f"Extra {i}", "BR-A", None) for i in range(3)]
    headers = _login(client)
    _connect_feed(client, headers)
    assert _sync(client, headers)["products"] == 5
    product_calls = [c for c in crm.calls if c.url.path.endswith("/products")]
    avail_calls = [c for c in crm.calls if c.url.path.endswith("/availability")]
    assert len(product_calls) == 3 and len(avail_calls) == 3


def test_feed_failure_changes_nothing_and_is_shown(client, hc, crm):
    headers = _ready(client)
    crm.status = 429
    state = _sync(client, headers)
    assert state["lastError"] == "The CRM rate limit was reached." and state["products"] == 2
    assert len(client.get("/hub-connector/options/locations", headers=headers).json()["data"]) == 2


# ── AC-12 hub registry ──────────────────────────────────────────────────────

def test_create_hub_shows_secret_once_and_lists(client, hc):
    headers = _login(client)
    created = _hub(client, headers)
    assert created["signingSecret"].startswith("whsec_")
    hub = created["hub"]
    assert hub["exposePrice"] is False and hub["active"] is True
    got = client.get(f"/hub-connector/hubs/{hub['id']}", headers=headers).json()
    assert "signingSecret" not in got and got["code"] == "ecohub"
    dup = client.post("/hub-connector/hubs", json={"name": "Again", "code": "ecohub"}, headers=headers)
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "hub_code_taken"
    _hub(client, headers, name="Another hub", code="another", callbackUrl=None)
    page = client.get("/hub-connector/hubs", params={"sort": "name", "order": "desc"}, headers=headers).json()
    assert page["total"] == 2 and [h["name"] for h in page["data"]] == ["EcoHub", "Another hub"]
    page = client.get("/hub-connector/hubs", params={"search": "anoth"}, headers=headers).json()
    assert [h["code"] for h in page["data"]] == ["another"]
    page = client.get("/hub-connector/hubs", params={"page": 1, "pageSize": 1, "sort": "name"}, headers=headers).json()
    assert [h["name"] for h in page["data"]] == ["EcoHub"]


@pytest.mark.parametrize("url", ["http://hub.example/x", "https://127.0.0.1/x", "https://localhost/x", "not a url"])
def test_receiver_url_must_be_public_https(client, hc, url):
    headers = _login(client)
    res = client.post("/hub-connector/hubs", json={"name": "Bad", "code": "bad", "callbackUrl": url}, headers=headers)
    assert res.status_code == 422 and res.json()["detail"]["code"] == "invalid_url"


def test_hubs_are_tenant_scoped(client, hc):
    from app.services.app_store_service import AppStoreService
    from modules.hub_connector.services import hub_service

    headers = _login(client)
    hub = _hub(client, headers)["hub"]
    db = hc()
    try:
        make_tenant(db, TENANT_B, "Hub B")
        make_admin_user(db, TENANT_B, "admin@hub-b.example")
        AppStoreService(db).install(TENANT_B, "hub_connector")
        db.commit()
        with pytest.raises(hub_service.HubError):
            hub_service.get_hub(db, TENANT_B, hub["id"])
        assert hub_service.list_hubs(db, TENANT_B)[2] == 0
    finally:
        db.close()


# ── AC-13 policy, AC-18/19 webhooks + hub API ───────────────────────────────

def test_end_to_end_two_customers_different_views(client, hc, crm, stub_hub):
    """AC-19: two customers on one hub with different locations and brands;
    price absent while the switch is OFF; the stub hub verifies signatures."""
    headers = _ready(client)
    created = _hub(client, headers)
    stub_hub.secret = created["signingSecret"]
    hub_id = created["hub"]["id"]

    # New customer: nothing until picked.
    nothing = _add_customer(client, headers, hub_id, "C-NEW", "New customer", [], [])
    prev = client.get(f"/hub-connector/hubs/{hub_id}/customers/{nothing['id']}/preview", headers=headers).json()
    assert prev["items"] == []

    m = _add_customer(client, headers, hub_id, "C-M", "Customer M", ["WH-N"], ["BR-A"])
    assert m["locations"] == [{"code": "WH-N", "name": "North warehouse"}]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A", "BR-B"])

    [mv] = stub_hub.by_customer("C-M")
    assert mv["full"] is True and mv["customer"] == {"code": "C-M", "name": "Customer M"}
    assert mv["items"] == [
        {"code": "SR-1001", "name": "Basin mixer", "brand_name": "Brand A", "in_stock": False, "incoming": True}
    ]
    [tv] = stub_hub.by_customer("C-T")
    by_code = {i["code"]: i for i in tv["items"]}
    assert by_code["SR-1001"]["in_stock"] is True and by_code["SR-1001"]["incoming"] is True
    assert by_code["SR-1002"]["in_stock"] is False and by_code["SR-1002"]["incoming"] is True
    assert all("list_price" not in i for i in mv["items"] + tv["items"])
    assert stub_hub.received[0]["headers"]["X-Hub-Connector-Event"] == "availability.updated"

    # A sync that changes nothing sends nothing.
    before = len(stub_hub.received)
    _sync(client, headers)
    assert len(stub_hub.received) == before

    # Stock arrives in north: only customer M's view changes.
    crm.availability["SR-1001"]["locations"][0]["available_qty"] = 12
    assert _sync(client, headers)["queued"] == 1
    m2 = stub_hub.by_customer("C-M")[-1]
    assert m2["full"] is False and m2["items"][0]["in_stock"] is True
    assert len(stub_hub.by_customer("C-T")) == 1

    # The product disappears from the feed: hubs are told to drop it.
    crm.products = [p for p in crm.products if p["code"] != "SR-1002"]
    _sync(client, headers)
    t2 = stub_hub.by_customer("C-T")[-1]
    assert t2["items"] == [] and t2["removed"] == ["SR-1002"]

    # Show price ON: every customer's full view, with price.
    assert client.patch(f"/hub-connector/hubs/{hub_id}", json={"exposePrice": True}, headers=headers).status_code == 200
    m3 = stub_hub.by_customer("C-M")[-1]
    assert m3["full"] is True and m3["items"][0]["list_price"] == "120.00"

    # Policy change: drop brand A for M -> the hub is told to remove SR-1001.
    res = client.patch(f"/hub-connector/hubs/{hub_id}/customers/{m['id']}", json={"brandCodes": []}, headers=headers)
    assert res.status_code == 200, res.text
    m4 = stub_hub.by_customer("C-M")[-1]
    assert m4["items"] == [] and m4["removed"] == ["SR-1001"]

    deliveries = client.get(f"/hub-connector/hubs/{hub_id}/deliveries", headers=headers).json()
    assert deliveries["total"] == len(stub_hub.received)
    assert {d["status"] for d in deliveries["data"]} == {DELIVERY_SUCCESS}
    assert {d["customerName"] for d in deliveries["data"]} <= {"Customer M", "Customer T", "New customer"}
    assert stub_hub.bad_signatures == 0


def test_hub_read_api_serves_one_customer_of_its_own_hub(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    other_id = _hub(client, headers, name="Other", code="other", callbackUrl=None)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A", "BR-B"])
    _add_customer(client, headers, other_id, "C-X", "Other customer", ["WH-N"], ["BR-A"])
    res = client.post(f"/hub-connector/hubs/{hub_id}/keys", json={"name": "EcoHub"}, headers=headers)
    assert res.status_code == 201 and res.json()["key"].startswith("fxh_live_")
    key = {"Authorization": f"Bearer {res.json()['key']}"}

    page = client.get("/api/v1/hub-connector/products", params={"customer": "C-T"}, headers=key).json()
    assert page["total"] == 2 and [r["code"] for r in page["data"]] == ["SR-1001", "SR-1002"]
    assert page["data"][0] == {"code": "SR-1001", "name": "Basin mixer", "brand_name": "Brand A", "in_stock": True, "incoming": True}
    one = client.get("/api/v1/hub-connector/products", params={"customer": "C-T", "codes": "SR-1002", "limit": 1}, headers=key).json()
    assert [r["code"] for r in one["data"]] == ["SR-1002"]
    # Another hub's customer and an unknown one look the same.
    for code in ("C-X", "NOPE"):
        res = client.get("/api/v1/hub-connector/products", params={"customer": code}, headers=key)
        assert res.status_code == 404 and res.json()["error"]["code"] == "customer_not_found"
    assert client.get("/api/v1/hub-connector/products", params={"customer": "C-T"}).status_code == 401
    # Hub switched off: its key stops working.
    client.patch(f"/hub-connector/hubs/{hub_id}", json={"active": False}, headers=headers)
    assert client.get("/api/v1/hub-connector/products", params={"customer": "C-T"}, headers=key).status_code == 403


def test_hub_key_has_a_request_budget_and_can_be_revoked(client, hc, crm, monkeypatch):
    from app.config import settings

    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])
    created = client.post(f"/hub-connector/hubs/{hub_id}/keys", json={"name": "EcoHub"}, headers=headers).json()
    key = {"Authorization": f"Bearer {created['key']}"}
    monkeypatch.setattr(settings, "throttle_hub_api_key_max_requests", 2)
    codes = [client.get("/api/v1/hub-connector/products", params={"customer": "C-T"}, headers=key).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert client.delete(f"/hub-connector/hubs/{hub_id}/keys/{created['id']}", headers=headers).status_code == 200
    assert client.get("/api/v1/hub-connector/products", params={"customer": "C-T"}, headers=key).status_code == 401


def test_policy_refuses_codes_the_crm_never_listed(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    res = client.post(
        f"/hub-connector/hubs/{hub_id}/customers",
        json={"customerCode": "C-T", "customerName": "Customer T", "locationCodes": ["WH-X"], "brandCodes": []},
        headers=headers,
    )
    assert res.status_code == 422 and res.json()["detail"]["code"] == "unknown_location"
    res = client.post(
        f"/hub-connector/hubs/{hub_id}/customers",
        json={"customerCode": "C-T", "customerName": " ", "locationCodes": [], "brandCodes": []},
        headers=headers,
    )
    assert res.status_code == 422
    _add_customer(client, headers, hub_id, "C-T", "Customer T", [], [])
    res = client.post(
        f"/hub-connector/hubs/{hub_id}/customers",
        json={"customerCode": "C-T", "customerName": "Again", "locationCodes": [], "brandCodes": []},
        headers=headers,
    )
    assert res.status_code == 409


def test_pausing_a_customer_keeps_codes_the_crm_stopped_listing(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    cid = _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])["id"]
    crm.locations = [loc for loc in crm.locations if loc["code"] != "WH-S"]
    _sync(client, headers)
    res = client.patch(f"/hub-connector/hubs/{hub_id}/customers/{cid}", json={"active": False}, headers=headers)
    assert res.status_code == 200, res.text
    last = stub_hub.by_customer("C-T")[-1]
    assert last["items"] == [] and last["removed"] == ["SR-1001"]
    res = client.patch(f"/hub-connector/hubs/{hub_id}/customers/{cid}", json={"locationCodes": ["WH-Z"]}, headers=headers)
    assert res.status_code == 422


def test_removing_a_customer_tells_the_hub_to_drop_everything(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    cid = _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A", "BR-B"])["id"]
    assert client.delete(f"/hub-connector/hubs/{hub_id}/customers/{cid}", headers=headers).status_code == 204
    last = stub_hub.by_customer("C-T")[-1]
    assert last["items"] == [] and last["removed"] == ["SR-1001", "SR-1002"]


def test_price_switch_off_drops_price_again(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers, exposePrice=True)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])
    assert stub_hub.by_customer("C-T")[-1]["items"][0]["list_price"] == "120.00"
    client.patch(f"/hub-connector/hubs/{hub_id}", json={"exposePrice": False}, headers=headers)
    last = stub_hub.by_customer("C-T")[-1]
    assert last["full"] is True and "list_price" not in last["items"][0]


def test_failed_delivery_retries_then_fails_recovers_and_can_be_sent_again(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])
    stub_hub.status = 500
    crm.availability["SR-1001"]["locations"][1]["available_qty"] = 0
    assert _sync(client, headers)["queued"] == 1
    db = hc()
    try:
        row = db.query(HcDelivery).filter(HcDelivery.hub_id == hub_id, HcDelivery.full.is_(False)).one()
        assert row.status == "PENDING" and row.attempt == 1 and row.last_code == 500
        for _ in range(delivery_service.MAX_ATTEMPTS - 1):
            _force_due(db, row.id)
            delivery_service.dispatch(db, row.id)
        db.expire_all()
        row = db.query(HcDelivery).filter(HcDelivery.id == row.id).one()
        assert row.status == DELIVERY_FAILED and row.attempt == delivery_service.MAX_ATTEMPTS
        recovery = db.query(HcDelivery).filter(HcDelivery.hub_id == hub_id, HcDelivery.seq > row.seq).one()
        assert recovery.full is True and recovery.status == "PENDING"
        stub_hub.status = 200
        _force_due(db, recovery.id)
        assert delivery_service.dispatch(db, recovery.id) == "success"
        dead_id = row.id
    finally:
        db.close()
    last = stub_hub.by_customer("C-T")[-1]
    assert last["full"] is True and last["items"][0]["in_stock"] is False
    res = client.post(f"/hub-connector/deliveries/{dead_id}/redeliver", headers=headers)
    assert res.status_code == 200 and res.json()["queued"] == 1
    again = stub_hub.by_customer("C-T")[-1]
    assert again["full"] is True and again["sequence"] > last["sequence"]


def test_a_newer_delivery_waits_for_an_older_retry(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])
    stub_hub.status = 500
    crm.availability["SR-1001"]["locations"][1]["available_qty"] = 0
    _sync(client, headers)
    stub_hub.status = 200
    crm.availability["SR-1001"]["locations"][1]["available_qty"] = 9
    _sync(client, headers)
    db = hc()
    try:
        older, newer = (
            db.query(HcDelivery).filter(HcDelivery.hub_id == hub_id, HcDelivery.full.is_(False)).order_by(HcDelivery.seq).all()
        )
        assert newer.status == "PENDING" and newer.attempt == 0
        _force_due(db, older.id)
        assert delivery_service.dispatch(db, older.id) == "success"
        _force_due(db, newer.id)
        assert delivery_service.dispatch(db, newer.id) == "success"
    finally:
        db.close()
    sent = stub_hub.by_customer("C-T")
    assert [d["items"][0]["in_stock"] for d in sent] == [True, False, True]
    assert [d["sequence"] for d in sent] == sorted(d["sequence"] for d in sent)


def test_receiver_is_rechecked_before_every_attempt(client, hc, crm, monkeypatch):
    from app.services.url_guard import UrlGuardError

    calls = []

    def refuse(url):
        raise UrlGuardError("The receiver URL points to a private address.")

    monkeypatch.setattr(delivery_service, "_assert_deliverable", refuse)
    monkeypatch.setattr(delivery_service, "_post", lambda *a, **kw: calls.append(1))
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])
    assert calls == []
    db = hc()
    try:
        row = db.query(HcDelivery).filter(HcDelivery.hub_id == hub_id).one()
        assert row.status == "PENDING" and row.last_error
    finally:
        db.close()


def test_hub_switched_off_sends_nothing(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])
    assert client.patch(f"/hub-connector/hubs/{hub_id}", json={"active": False}, headers=headers).status_code == 200
    before = len(stub_hub.received)
    crm.availability["SR-1001"]["locations"][1]["available_qty"] = 0
    _sync(client, headers)
    assert len(stub_hub.received) == before
    assert client.post(f"/hub-connector/hubs/{hub_id}/resync", headers=headers).status_code == 409
    db = hc()
    try:
        assert db.query(HcHub).filter(HcHub.id == hub_id).one().active is False
    finally:
        db.close()


# ── grace-window deletes (the screens' Delete / Remove / Revoke) ────────────

def _park_and_lapse(db, action_key, entity_type, entity_id, payload=None):
    from app.deferred_actions.service import PendingActionService
    from app.models import User
    from app.models.pending_action import PendingAction

    admin = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
    svc = PendingActionService(db)
    row = svc.park(
        tenant_id=DEFAULT_TENANT_ID, actor=admin, requested_by_id=admin.id,
        action_key=action_key, entity_type=entity_type, entity_id=entity_id, payload=payload,
    )
    pa = db.get(PendingAction, row.id)
    pa.commit_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    return svc.commit_one(row)


def test_deferred_actions_registered_with_route_permissions():
    from app.deferred_actions.registry import deferred_action_for

    assert deferred_action_for("hub_connector_hubs.delete").permission == "hub_connector.manage"
    assert deferred_action_for("hub_connector_customers.remove").permission == "hub_connector.manage"
    assert deferred_action_for("hub_connector_keys.revoke").permission == "hub_connector.keys.manage"


def test_deferred_remove_customer_tells_the_hub_and_delete_hub_and_revoke(client, hc, crm, stub_hub):
    from modules.hub_connector.models import HcApiKey, HcHubCustomer

    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    cid = _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])["id"]
    key_id = client.post(f"/hub-connector/hubs/{hub_id}/keys", json={"name": "EcoHub"}, headers=headers).json()["id"]
    db = hc()
    try:
        result = _park_and_lapse(db, "hub_connector_keys.revoke", "hub_connector_key", key_id)
        assert result.status == "committed", result.error_text
        db.expire_all()
        assert db.get(HcApiKey, key_id).revoked_at is not None
        result = _park_and_lapse(db, "hub_connector_customers.remove", "hub_connector_customer", cid, {"hubId": hub_id})
        assert result.status == "committed", result.error_text
        assert db.query(HcHubCustomer).filter(HcHubCustomer.id == cid).first() is None
        last = stub_hub.by_customer("C-T")[-1]
        assert last["items"] == [] and last["removed"] == ["SR-1001"]
        result = _park_and_lapse(db, "hub_connector_hubs.delete", "hub_connector_hub", hub_id)
        assert result.status == "committed", result.error_text
        assert db.query(HcHub).filter(HcHub.id == hub_id).first() is None
    finally:
        db.close()


# ── feed hardening (security review) ────────────────────────────────────────

def test_an_empty_feed_never_wipes_what_hubs_see(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])
    before = len(stub_hub.received)
    crm.products = []
    state = _sync(client, headers)
    assert state["lastError"] == "The CRM listed no products or no locations; nothing was changed."
    assert state["products"] == 2 and len(stub_hub.received) == before


def test_a_feed_that_never_stops_paging_is_cut_off(client, hc, crm, monkeypatch):
    monkeypatch.setattr(crm_feed, "PAGE_LIMIT", 1)
    monkeypatch.setattr(crm_feed, "MAX_PAGES", 3)
    original = crm.handler

    def endless(request):
        if request.url.path.endswith("/products"):
            return httpx.Response(200, json={"data": [_product("SR-9", "Loop", "BR-A", None)]})
        return original(request)

    monkeypatch.setattr(crm_feed, "_http", lambda: httpx.Client(transport=httpx.MockTransport(endless)))
    headers = _login(client)
    _connect_feed(client, headers)
    assert _sync(client, headers)["lastError"] == "The CRM lists more products than one sync can read."


def test_an_oversized_feed_answer_is_refused(client, hc, crm, monkeypatch):
    monkeypatch.setattr(crm_feed, "MAX_RESPONSE_BYTES", 200)
    headers = _login(client)
    _connect_feed(client, headers)
    assert _sync(client, headers)["lastError"] == "The CRM answer was too large."


def test_plain_http_crm_address_is_refused_outside_development(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(crm_feed.FeedError):
        crm_feed.config_from({"baseUrl": "http://crm.example", "company": "CO-1"}, {"apiKey": "k"})
    assert crm_feed.config_from({"baseUrl": "https://crm.example", "company": "CO-1"}, {"apiKey": "k"}).company == "CO-1"


# ── standing rules: filters, history, scheduled tasks, assistant actions ───

def test_lists_filter_on_the_server(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    _hub(client, headers, name="Priced", code="priced", exposePrice=True, callbackUrl=None)
    off = _hub(client, headers, name="Off", code="off", callbackUrl=None)["hub"]["id"]
    client.patch(f"/hub-connector/hubs/{off}", json={"active": False}, headers=headers)
    names = lambda res: sorted(h["name"] for h in res.json()["data"])  # noqa: E731
    assert names(client.get("/hub-connector/hubs", params={"status": "inactive"}, headers=headers)) == ["Off"]
    assert names(client.get("/hub-connector/hubs", params={"showPrice": "yes"}, headers=headers)) == ["Priced"]
    both = client.get("/hub-connector/hubs", params=[("status", "active"), ("status", "inactive")], headers=headers)
    assert names(both) == ["EcoHub", "Off", "Priced"]
    combined = client.get("/hub-connector/hubs", params={"status": "active", "showPrice": "no"}, headers=headers)
    assert names(combined) == ["EcoHub"]
    paused = _add_customer(client, headers, hub_id, "C-P", "Paused one", [], [])["id"]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])
    client.patch(f"/hub-connector/hubs/{hub_id}/customers/{paused}", json={"active": False}, headers=headers)
    res = client.get(f"/hub-connector/hubs/{hub_id}/customers", params={"status": "inactive"}, headers=headers)
    assert [c["customerCode"] for c in res.json()["data"]] == ["C-P"]


def test_hub_history_records_who_what_old_and_new(client, hc, crm, stub_hub):
    headers = _ready(client)
    hub_id = _hub(client, headers)["hub"]["id"]
    cid = _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A"])["id"]
    client.patch(f"/hub-connector/hubs/{hub_id}", json={"exposePrice": True}, headers=headers)
    client.patch(f"/hub-connector/hubs/{hub_id}/customers/{cid}", json={"locationCodes": ["WH-N", "WH-S"]}, headers=headers)
    key_id = client.post(f"/hub-connector/hubs/{hub_id}/keys", json={"name": "EcoHub"}, headers=headers).json()["id"]
    client.delete(f"/hub-connector/hubs/{hub_id}/keys/{key_id}", headers=headers)
    client.delete(f"/hub-connector/hubs/{hub_id}/customers/{cid}", headers=headers)
    rows = client.get(f"/hub-connector/hubs/{hub_id}/history", headers=headers).json()["data"]
    by_action = {r["action"]: r for r in rows}
    assert by_action["Show price changed"]["from"] == "No" and by_action["Show price changed"]["to"] == "Yes"
    loc = by_action["Customer locations changed: C-T"]
    assert loc["from"] == "South warehouse" and loc["to"] == "North warehouse, South warehouse"
    assert {"Hub created", "Customer added", "Hub key created", "Hub key revoked", "Customer removed"} <= set(by_action)
    assert all(r["who"] and r["at"].endswith("Z") for r in rows)
    assert all(r["onBehalfOf"] is None for r in rows)
    assert rows[0]["action"] == "Customer removed"  # newest first


def test_scheduled_tasks_show_last_run_error_and_run_now(client, hc, crm, stub_hub):
    headers = _login(client)
    tasks = client.get("/hub-connector/scheduled-tasks", headers=headers).json()["data"]
    assert [t["key"] for t in tasks] == ["crm-sync", "delivery-retries"]
    assert tasks[0]["lastRunAt"] is None and tasks[0]["schedule"] == "Every 10 minutes"
    _connect_feed(client, headers)
    crm.status = 403
    res = client.post("/hub-connector/scheduled-tasks/crm-sync/run", headers=headers)
    assert res.status_code == 200
    sync = res.json()["data"][0]
    assert sync["lastRunAt"] and "grant" in sync["lastError"]
    crm.status = 200
    sync = client.post("/hub-connector/scheduled-tasks/crm-sync/run", headers=headers).json()["data"][0]
    assert sync["lastError"] is None
    db = hc()
    try:
        delivery_service.run_due(db)  # the beat tick stamps the platform task
    finally:
        db.close()
    retries = client.get("/hub-connector/scheduled-tasks", headers=headers).json()["data"][1]
    assert retries["lastRunAt"] and retries["lastError"] is None
    assert client.post("/hub-connector/scheduled-tasks/delivery-retries/run", headers=headers).status_code == 200
    assert client.post("/hub-connector/scheduled-tasks/nope/run", headers=headers).status_code == 404


def test_assistant_can_read_a_customer_view_and_run_a_sync(client, hc, crm, stub_hub):
    """The workflow actions behind "what does Customer T see?" and "sync the
    hub stock now" on WhatsApp (AI Agent -> action -> reply)."""
    from app.workflow_engine.registry import get_action
    from modules.hub_connector import workflow_nodes

    workflow_nodes.register_workflow_nodes()
    headers = _ready(client)
    hub_id = _hub(client, headers, exposePrice=True)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-T", "Customer T", ["WH-S"], ["BR-A", "BR-B"])
    view = get_action("hub_connector.customer_view")
    assert view.module == "hub_connector" and view.permission == "hub_connector.view"
    db = hc()
    try:
        # Eval prompt 1: "what does Customer T see on EcoHub?"
        out = view.executor(db, DEFAULT_TENANT_ID, {"hubCode": "{{ trigger.hub }}", "customerCode": "{{ trigger.customer }}"},
                            {"trigger.hub": "ECOHUB", "trigger.customer": "C-T"})
        assert out["customerName"] == "Customer T" and out["total"] == 2 and out["inStockCount"] == 1
        assert out["summary"].splitlines()[:5] == ["SR-1001", "Name: Basin mixer", "Brand: Brand A", "In stock: Yes", "Incoming: Yes"]
        assert "Price: MYR 120.00" in out["summary"] and "·" not in out["summary"]
        # Eval prompt 2: "is SR-1002 in stock for Customer T?"
        one = view.executor(db, DEFAULT_TENANT_ID, {"hubCode": "ecohub", "customerCode": "C-T", "productCodes": "SR-1002"}, {})
        assert [r["code"] for r in one["rows"]] == ["SR-1002"] and one["rows"][0]["in_stock"] is False
        with pytest.raises(workflow_nodes.ActionError, match="Couldn't find that customer"):
            view.executor(db, DEFAULT_TENANT_ID, {"hubCode": "ecohub", "customerCode": "NOPE"}, {})
        synced = get_action("hub_connector.sync_now").executor(db, DEFAULT_TENANT_ID, {}, {})
        assert synced["products"] == 2
    finally:
        db.close()


def test_summary_caps_with_a_more_line():
    from modules.hub_connector.workflow_nodes import summary

    rows = [{"code": f"SR-{i}", "name": f"P{i}", "brand_name": "B", "in_stock": True, "incoming": False} for i in range(12)]
    text = summary(rows, 12, limit=10)
    assert text.endswith('Reply "more" to see the next 2.') and "SR-10" not in text
    assert summary([], 0) == "No products to show for this customer."
