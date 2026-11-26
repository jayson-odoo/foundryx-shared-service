"""Hub connector S1, shared-service side (AC-12..AC-19).

No real hub and no real network: the outbound POST is replaced by a stub hub
that verifies the signature and records what it was told.
"""
from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.hub_connector.models import DELIVERY_FAILED, DELIVERY_SUCCESS, HcDelivery, HcHub
from modules.hub_connector.services import availability, delivery_service
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.meetings_helpers import make_admin_user, make_tenant

ROOT = Path(__file__).resolve().parents[2]
TENANT_B = "tenant-hub-b"
HUB_URL = "https://hub.example/webhooks/availability"


# ── AC-15 / AC-16 / AC-14: the one shared rule (pure) ──────────────────────

def _facts(**kw) -> availability.ItemFacts:
    base = dict(
        code="I-1",
        name="Item one",
        brand_code="BR-A",
        brand_name="Brand A",
        price=Decimal("12.50"),
        currency="MYR",
        locations=[],
        incoming=[],
    )
    base.update(kw)
    return availability.ItemFacts(**base)


def _policy(locs=("WH-1",), brands=("BR-A",), price=False):
    return availability.make_policy(locs, brands, price)


@pytest.mark.parametrize(
    "locations,expected",
    [
        ([{"code": "WH-1", "onHand": 5, "reserved": 5}], False),  # on hand minus reserved = 0
        ([{"code": "WH-1", "onHand": 5, "reserved": 4}], True),
        ([{"code": "WH-2", "onHand": 50, "reserved": 0}], False),  # location not in the policy
        ([{"code": "WH-1", "onHand": 1, "reserved": 3}, {"code": "WH-2", "onHand": 9, "reserved": 0}], False),
        ([{"code": "WH-1", "onHand": "2.5", "reserved": "2"}], True),
        ([{"code": "WH-1", "onHand": None, "reserved": None}], False),
    ],
)
def test_got_stock_counts_only_allowed_locations(locations, expected):
    assert availability.got_stock(_facts(locations=locations), _policy()) is expected


@pytest.mark.parametrize(
    "incoming,expected",
    [
        ([{"ref": "PO-1", "locationCode": "WH-1", "remaining": 3}], True),
        ([{"ref": "PO-1", "locationCode": "WH-2", "remaining": 3}], False),  # another customer's location
        ([{"ref": "PO-1", "locationCode": None, "remaining": 3}], True),  # not yet allocated (crew Q-A (a))
        ([{"ref": "PO-1", "locationCode": None, "remaining": 0}], False),  # fully arrived
        ([], False),
    ],
)
def test_got_incoming_includes_unallocated_lines(incoming, expected):
    assert availability.got_incoming(_facts(incoming=incoming), _policy()) is expected


def test_brand_filter_and_price_switch():
    assert availability.view_for(_facts(brand_code="BR-B"), _policy()) is None
    assert availability.view_for(_facts(brand_code=None), _policy()) is None
    hidden_price = availability.view_for(_facts(), _policy(price=False))
    assert "price" not in hidden_price and "currency" not in hidden_price
    shown = availability.view_for(_facts(), _policy(price=True))
    assert shown["price"] == "12.50" and shown["currency"] == "MYR"


# ── fixtures ────────────────────────────────────────────────────────────────

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
    """The hub's receiver: verifies the signature, keeps what it was told."""

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
        if 200 <= self.status < 300:  # a refused POST is not something the hub holds
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


def _login(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, slug=None) -> dict:
    body = {"email": email, "password": password}
    if slug:
        body["tenantSlug"] = slug
    res = client.post("/auth/login", json=body)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _crm_key(client, headers) -> dict:
    res = client.post("/hub-connector/keys", json={"name": "CRM"}, headers=headers)
    assert res.status_code == 201, res.text
    assert res.json()["key"].startswith("fxh_live_")
    return {"Authorization": f"Bearer {res.json()['key']}"}


ITEMS = [
    {
        "code": "I-1",
        "name": "Basin mixer",
        "brand": {"code": "BR-A", "name": "Brand A"},
        "price": "120.00",
        "currency": "MYR",
        "locations": [
            {"code": "WH-N", "name": "North warehouse", "onHand": 10, "reserved": 10},
            {"code": "WH-S", "name": "South warehouse", "onHand": 4, "reserved": 1},
        ],
        "incoming": [{"ref": "PO-1", "locationCode": None, "remaining": 6}],
    },
    {
        "code": "I-2",
        "name": "Shower set",
        "brand": {"code": "BR-B", "name": "Brand B"},
        "price": "300.00",
        "currency": "MYR",
        "locations": [{"code": "WH-N", "name": "North warehouse", "onHand": 2, "reserved": 0}],
        "incoming": [{"ref": "PO-2", "locationCode": "WH-S", "remaining": 1}],
    },
]
CUSTOMERS = [{"code": "C-MURO", "name": "Customer M"}, {"code": "C-TOUCH", "name": "Customer T"}]


def _seed_facts(client, crm):
    assert client.put("/api/v1/hub-connector/customers", json={"customers": CUSTOMERS}, headers=crm).status_code == 200
    res = client.put("/api/v1/hub-connector/items", json={"items": ITEMS}, headers=crm)
    assert res.status_code == 200, res.text
    return res.json()


def _hub(client, headers, **kw):
    body = {"name": "EcoHub", "code": "ecohub", "callbackUrl": HUB_URL}
    body.update(kw)
    res = client.post("/hub-connector/hubs", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _add_customer(client, headers, hub_id, code, locs, brands):
    res = client.post(
        f"/hub-connector/hubs/{hub_id}/customers",
        json={"customerCode": code, "locationCodes": locs, "brandCodes": brands},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


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
    _hub(client, headers, name="Another hub", code="another")
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
    headers = _login(client)
    hub = _hub(client, headers)["hub"]
    db = hc()
    try:
        from app.services.app_store_service import AppStoreService

        make_tenant(db, TENANT_B, "Hub B")
        make_admin_user(db, TENANT_B, "admin@hub-b.example")
        AppStoreService(db).install(TENANT_B, "hub_connector")
        db.commit()
    finally:
        db.close()
    db = hc()
    try:
        from modules.hub_connector.services import hub_service

        with pytest.raises(hub_service.HubError):
            hub_service.get_hub(db, TENANT_B, hub["id"])
        assert hub_service.list_hubs(db, TENANT_B)[2] == 0
    finally:
        db.close()


# ── AC-17 inbound API ───────────────────────────────────────────────────────

def test_inbound_requires_a_valid_key(client, hc):
    res = client.put("/api/v1/hub-connector/items", json={"items": []})
    assert res.status_code == 401
    res = client.put("/api/v1/hub-connector/items", json={"items": []}, headers={"Authorization": "Bearer fxh_live_nope00000000"})
    assert res.status_code == 401
    headers = _login(client)
    crm = _crm_key(client, headers)
    assert client.put("/api/v1/hub-connector/items", json={"items": []}, headers=crm).status_code == 200
    key_id = client.get("/hub-connector/keys", headers=headers).json()["data"][0]["id"]
    assert client.delete(f"/hub-connector/keys/{key_id}", headers=headers).status_code == 200
    assert client.put("/api/v1/hub-connector/items", json={"items": []}, headers=crm).status_code == 401


def test_inbound_refused_when_module_inactive(client, hc):
    headers = _login(client)
    crm = _crm_key(client, headers)
    db = hc()
    try:
        from app.services.app_store_service import AppStoreService

        AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "hub_connector")
        db.commit()
    finally:
        db.close()
    assert client.put("/api/v1/hub-connector/items", json={"items": []}, headers=crm).status_code == 403


def test_one_bad_item_never_fails_the_batch(client, hc):
    headers = _login(client)
    crm = _crm_key(client, headers)
    items = [
        ITEMS[0],
        {"code": "I-BAD", "name": "Broken", "locations": [{"code": "WH-N", "onHand": "lots"}]},
        {"name": "No code"},
        "not an object",
    ]
    res = client.put("/api/v1/hub-connector/items", json={"items": items}, headers=crm)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stored"] == 1
    assert {s["code"] for s in body["skipped"]} == {"I-BAD", "(no code)"} and len(body["skipped"]) == 3
    assert [o["code"] for o in client.get("/hub-connector/options/brands", headers=headers).json()["data"]] == ["BR-A"]


def test_options_come_from_pushed_facts(client, hc):
    headers = _login(client)
    _seed_facts(client, _crm_key(client, headers))
    locs = client.get("/hub-connector/options/locations", headers=headers).json()["data"]
    assert locs == [{"code": "WH-N", "name": "North warehouse"}, {"code": "WH-S", "name": "South warehouse"}]
    found = client.get("/hub-connector/options/customers", params={"search": "touch"}, headers=headers).json()["data"]
    assert found == [{"code": "C-TOUCH", "name": "Customer T"}]


# ── AC-13 policy, AC-18/19 webhooks with a stub hub ─────────────────────────

def test_end_to_end_two_customers_different_views(client, hc, stub_hub):
    """AC-19: two customers on one hub, different locations + brands; price
    absent while the switch is OFF; the stub hub verifies every signature."""
    headers = _login(client)
    crm = _crm_key(client, headers)
    _seed_facts(client, crm)
    created = _hub(client, headers)
    stub_hub.secret = created["signingSecret"]
    hub_id = created["hub"]["id"]

    # Customer M: north only, brand A. Customer T: south only, brands A + B.
    muro = _add_customer(client, headers, hub_id, "C-MURO", ["WH-N"], ["BR-A"])
    assert muro["customerName"] == "Customer M"
    assert muro["locations"] == [{"code": "WH-N", "name": "North warehouse"}]
    _add_customer(client, headers, hub_id, "C-TOUCH", ["WH-S"], ["BR-A", "BR-B"])

    assert stub_hub.bad_signatures == 0
    [m] = stub_hub.by_customer("C-MURO")
    assert m["full"] is True
    assert m["items"] == [
        {"code": "I-1", "name": "Basin mixer", "brand": {"code": "BR-A", "name": "Brand A"}, "gotStock": False, "gotIncoming": True}
    ]
    [t] = stub_hub.by_customer("C-TOUCH")
    by_code = {i["code"]: i for i in t["items"]}
    assert by_code["I-1"]["gotStock"] is True and by_code["I-1"]["gotIncoming"] is True
    assert by_code["I-2"]["gotStock"] is False and by_code["I-2"]["gotIncoming"] is True
    assert all("price" not in i for i in m["items"] + t["items"])
    headers_sent = stub_hub.received[0]["headers"]
    assert headers_sent["X-Hub-Connector-Event"] == "availability.updated"
    assert stub_hub.received[0]["url"] == HUB_URL

    # A push that changes nothing sends nothing.
    before = len(stub_hub.received)
    _seed_facts(client, crm)
    assert len(stub_hub.received) == before

    # Stock arrives in north: only customer M's view changes.
    moved = json.loads(json.dumps(ITEMS[0]))
    moved["locations"][0]["onHand"] = 12
    res = client.put("/api/v1/hub-connector/items", json={"items": [moved]}, headers=crm).json()
    assert res["queued"] == 1
    m2 = stub_hub.by_customer("C-MURO")[-1]
    assert m2["full"] is False and m2["items"][0]["gotStock"] is True
    assert len(stub_hub.by_customer("C-TOUCH")) == 1

    # Preview = the same view.
    cid = client.get(f"/hub-connector/hubs/{hub_id}/customers", params={"search": "C-MURO"}, headers=headers).json()["data"][0]["id"]
    prev = client.get(f"/hub-connector/hubs/{hub_id}/customers/{cid}/preview", headers=headers).json()["items"]
    assert prev == m2["items"]

    # Show price ON: every customer gets its full view with price.
    assert client.patch(f"/hub-connector/hubs/{hub_id}", json={"exposePrice": True}, headers=headers).status_code == 200
    m3 = stub_hub.by_customer("C-MURO")[-1]
    assert m3["full"] is True and m3["items"][0]["price"] == "120.00" and m3["items"][0]["currency"] == "MYR"

    # Policy change: drop brand A for M -> the hub is told to remove I-1.
    res = client.patch(f"/hub-connector/hubs/{hub_id}/customers/{cid}", json={"brandCodes": []}, headers=headers)
    assert res.status_code == 200, res.text
    m4 = stub_hub.by_customer("C-MURO")[-1]
    assert m4["items"] == [] and m4["removed"] == ["I-1"]

    deliveries = client.get(f"/hub-connector/hubs/{hub_id}/deliveries", headers=headers).json()
    assert deliveries["total"] == len(stub_hub.received)
    assert {d["status"] for d in deliveries["data"]} == {DELIVERY_SUCCESS}
    assert stub_hub.bad_signatures == 0


def test_policy_refuses_codes_the_crm_never_pushed(client, hc, stub_hub):
    headers = _login(client)
    _seed_facts(client, _crm_key(client, headers))
    hub_id = _hub(client, headers)["hub"]["id"]
    res = client.post(
        f"/hub-connector/hubs/{hub_id}/customers",
        json={"customerCode": "C-MURO", "locationCodes": ["WH-X"], "brandCodes": []},
        headers=headers,
    )
    assert res.status_code == 422 and res.json()["detail"]["code"] == "unknown_location"
    res = client.post(
        f"/hub-connector/hubs/{hub_id}/customers",
        json={"customerCode": "NOPE", "locationCodes": [], "brandCodes": []},
        headers=headers,
    )
    assert res.status_code == 422
    _add_customer(client, headers, hub_id, "C-MURO", [], [])
    res = client.post(
        f"/hub-connector/hubs/{hub_id}/customers",
        json={"customerCode": "C-MURO", "locationCodes": [], "brandCodes": []},
        headers=headers,
    )
    assert res.status_code == 409


def test_removing_a_customer_tells_the_hub_to_drop_everything(client, hc, stub_hub):
    headers = _login(client)
    _seed_facts(client, _crm_key(client, headers))
    hub_id = _hub(client, headers)["hub"]["id"]
    cid = _add_customer(client, headers, hub_id, "C-TOUCH", ["WH-S"], ["BR-A", "BR-B"])["id"]
    assert client.delete(f"/hub-connector/hubs/{hub_id}/customers/{cid}", headers=headers).status_code == 204
    last = stub_hub.by_customer("C-TOUCH")[-1]
    assert last["items"] == [] and last["removed"] == ["I-1", "I-2"]


def _force_due(db, delivery_id):
    from datetime import datetime, timedelta, timezone

    db.query(HcDelivery).filter(HcDelivery.id == delivery_id).update(
        {"next_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
    )
    db.commit()


def test_failed_delivery_retries_then_fails_recovers_and_can_be_sent_again(client, hc, stub_hub):
    headers = _login(client)
    crm = _crm_key(client, headers)
    _seed_facts(client, crm)
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-TOUCH", ["WH-S"], ["BR-A"])
    stub_hub.status = 500
    moved = json.loads(json.dumps(ITEMS[0]))
    moved["locations"][1]["onHand"] = 1  # south: 1 - 1 = 0, no stock
    assert client.put("/api/v1/hub-connector/items", json={"items": [moved]}, headers=crm).json()["queued"] == 1
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
        # The change never arrived: the customer's FULL view is queued once.
        recovery = db.query(HcDelivery).filter(HcDelivery.hub_id == hub_id, HcDelivery.seq > row.seq).one()
        assert recovery.full is True and recovery.status == "PENDING"
        stub_hub.status = 200
        _force_due(db, recovery.id)
        assert delivery_service.dispatch(db, recovery.id) == "success"
        dead_id = row.id
    finally:
        db.close()
    last = stub_hub.by_customer("C-TOUCH")[-1]
    assert last["full"] is True and last["items"][0]["gotStock"] is False
    # "Send again" sends the CURRENT full view, not the old body.
    res = client.post(f"/hub-connector/deliveries/{dead_id}/redeliver", headers=headers)
    assert res.status_code == 200 and res.json()["queued"] == 1
    again = stub_hub.by_customer("C-TOUCH")[-1]
    assert again["full"] is True and again["sequence"] > last["sequence"]
    page = client.get(f"/hub-connector/hubs/{hub_id}/deliveries", params={"status": ["FAILED"]}, headers=headers).json()
    assert page["total"] == 1


def test_a_newer_delivery_waits_for_an_older_retry(client, hc, stub_hub):
    """A late retry can never overwrite newer state at the hub."""
    headers = _login(client)
    crm = _crm_key(client, headers)
    _seed_facts(client, crm)
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-TOUCH", ["WH-S"], ["BR-A"])
    stub_hub.status = 500
    first = json.loads(json.dumps(ITEMS[0]))
    first["locations"][1]["onHand"] = 1
    client.put("/api/v1/hub-connector/items", json={"items": [first]}, headers=crm)
    stub_hub.status = 200
    second = json.loads(json.dumps(ITEMS[0]))
    second["locations"][1]["onHand"] = 9
    client.put("/api/v1/hub-connector/items", json={"items": [second]}, headers=crm)
    db = hc()
    try:
        older, newer = db.query(HcDelivery).filter(HcDelivery.hub_id == hub_id, HcDelivery.full.is_(False)).order_by(HcDelivery.seq).all()
        assert newer.status == "PENDING" and newer.attempt == 0  # held back
        _force_due(db, older.id)
        assert delivery_service.dispatch(db, older.id) == "success"
        _force_due(db, newer.id)
        assert delivery_service.dispatch(db, newer.id) == "success"
    finally:
        db.close()
    sent = stub_hub.by_customer("C-TOUCH")
    assert [d["items"][0]["gotStock"] for d in sent] == [True, False, True]
    assert [d["sequence"] for d in sent] == sorted(d["sequence"] for d in sent)


def test_discontinued_item_is_removed_at_the_hub(client, hc, stub_hub):
    headers = _login(client)
    crm = _crm_key(client, headers)
    _seed_facts(client, crm)
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-TOUCH", ["WH-S"], ["BR-A", "BR-B"])
    res = client.put("/api/v1/hub-connector/items", json={"items": [{"code": "I-2", "active": False}]}, headers=crm).json()
    assert res["stored"] == 1 and res["queued"] == 1
    last = stub_hub.by_customer("C-TOUCH")[-1]
    assert last["items"] == [] and last["removed"] == ["I-2"]


@pytest.mark.parametrize(
    "bad",
    [
        {"code": "I-X", "name": "Huge", "locations": [{"code": "WH-N", "onHand": "1E400"}]},
        {"code": "I-X", "name": "Rich", "price": "1E30"},
        {"code": True, "name": "Bool code"},
        {"code": "I-X", "name": "Many", "locations": [{"code": f"L{i}"} for i in range(501)]},
    ],
)
def test_out_of_range_values_skip_only_that_item(client, hc, bad):
    headers = _login(client)
    crm = _crm_key(client, headers)
    res = client.put("/api/v1/hub-connector/items", json={"items": [ITEMS[0], bad]}, headers=crm)
    assert res.status_code == 200, res.text
    assert res.json()["stored"] == 1 and len(res.json()["skipped"]) == 1


def test_pausing_a_customer_keeps_codes_the_crm_stopped_sending(client, hc, stub_hub):
    headers = _login(client)
    crm = _crm_key(client, headers)
    _seed_facts(client, crm)
    hub_id = _hub(client, headers)["hub"]["id"]
    cid = _add_customer(client, headers, hub_id, "C-TOUCH", ["WH-S"], ["BR-A"])["id"]
    gone = json.loads(json.dumps(ITEMS))
    for item in gone:
        item["locations"] = [loc for loc in item["locations"] if loc["code"] != "WH-S"]
    client.put("/api/v1/hub-connector/items", json={"items": gone}, headers=crm)
    res = client.patch(f"/hub-connector/hubs/{hub_id}/customers/{cid}", json={"active": False}, headers=headers)
    assert res.status_code == 200, res.text
    last = stub_hub.by_customer("C-TOUCH")[-1]
    assert last["items"] == [] and last["removed"] == ["I-1"]
    res = client.patch(f"/hub-connector/hubs/{hub_id}/customers/{cid}", json={"locationCodes": ["WH-Z"]}, headers=headers)
    assert res.status_code == 422


def test_price_switch_off_drops_price_again(client, hc, stub_hub):
    headers = _login(client)
    _seed_facts(client, _crm_key(client, headers))
    hub_id = _hub(client, headers, exposePrice=True)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-TOUCH", ["WH-S"], ["BR-A"])
    assert stub_hub.by_customer("C-TOUCH")[-1]["items"][0]["price"] == "120.00"
    client.patch(f"/hub-connector/hubs/{hub_id}", json={"exposePrice": False}, headers=headers)
    last = stub_hub.by_customer("C-TOUCH")[-1]
    assert last["full"] is True and "price" not in last["items"][0]


def test_push_key_has_a_request_budget(client, hc, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "throttle_hub_push_key_max_requests", 2)
    headers = _login(client)
    crm = _crm_key(client, headers)
    codes = [client.put("/api/v1/hub-connector/items", json={"items": []}, headers=crm).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_receiver_is_rechecked_before_every_attempt(client, hc, monkeypatch):
    """A receiver that resolves to an internal address is refused at send time."""
    from app.services.url_guard import UrlGuardError

    calls = []

    def refuse(url):
        raise UrlGuardError("The receiver URL points to a private address.")

    monkeypatch.setattr(delivery_service, "_assert_deliverable", refuse)
    monkeypatch.setattr(delivery_service, "_post", lambda *a, **kw: calls.append(1))
    headers = _login(client)
    _seed_facts(client, _crm_key(client, headers))
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-TOUCH", ["WH-S"], ["BR-A"])
    assert calls == []
    db = hc()
    try:
        row = db.query(HcDelivery).filter(HcDelivery.hub_id == hub_id).one()
        assert row.status == "PENDING" and row.last_error
    finally:
        db.close()


def test_hub_switched_off_sends_nothing(client, hc, stub_hub):
    headers = _login(client)
    crm = _crm_key(client, headers)
    _seed_facts(client, crm)
    hub_id = _hub(client, headers)["hub"]["id"]
    _add_customer(client, headers, hub_id, "C-TOUCH", ["WH-S"], ["BR-A"])
    assert client.patch(f"/hub-connector/hubs/{hub_id}", json={"active": False}, headers=headers).status_code == 200
    before = len(stub_hub.received)
    moved = json.loads(json.dumps(ITEMS[0]))
    moved["locations"][1]["onHand"] = 0
    client.put("/api/v1/hub-connector/items", json={"items": [moved]}, headers=crm)
    assert len(stub_hub.received) == before
    assert client.post(f"/hub-connector/hubs/{hub_id}/resync", headers=headers).status_code == 409
    db = hc()
    try:
        assert db.query(HcHub).filter(HcHub.id == hub_id).one().active is False
    finally:
        db.close()


# ── grace-window deletes (the screens' Delete / Remove / Revoke) ────────────

def _park_and_lapse(db, action_key, entity_type, entity_id, payload=None):
    from datetime import datetime, timedelta, timezone

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


def test_deferred_remove_customer_tells_the_hub_and_delete_hub_and_revoke(client, hc, stub_hub):
    from modules.hub_connector.models import HcApiKey, HcHubCustomer

    headers = _login(client)
    _seed_facts(client, _crm_key(client, headers))
    hub_id = _hub(client, headers)["hub"]["id"]
    cid = _add_customer(client, headers, hub_id, "C-TOUCH", ["WH-S"], ["BR-A"])["id"]
    db = hc()
    try:
        result = _park_and_lapse(db, "hub_connector_customers.remove", "hub_connector_customer", cid, {"hubId": hub_id})
        assert result.status == "committed", result.error_text
        assert db.query(HcHubCustomer).filter(HcHubCustomer.id == cid).first() is None
        last = stub_hub.by_customer("C-TOUCH")[-1]
        assert last["items"] == [] and last["removed"] == ["I-1"]
        result = _park_and_lapse(db, "hub_connector_hubs.delete", "hub_connector_hub", hub_id)
        assert result.status == "committed", result.error_text
        assert db.query(HcHub).filter(HcHub.id == hub_id).first() is None
        key_id = db.query(HcApiKey.id).filter(HcApiKey.tenant_id == DEFAULT_TENANT_ID).first()[0]
        result = _park_and_lapse(db, "hub_connector_keys.revoke", "hub_connector_key", key_id)
        assert result.status == "committed", result.error_text
        db.expire_all()
        assert db.get(HcApiKey, key_id).revoked_at is not None
    finally:
        db.close()
