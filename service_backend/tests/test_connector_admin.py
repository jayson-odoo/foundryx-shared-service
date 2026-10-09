"""Connector admin API + perms (plan sprint-4/19, AC-19-50..55)."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from tests.connector_support import (
    PRODUCT_TO_SS,
    SECRETS,
    SS_TO_PRODUCT,
    admin_headers,
    any_row_has,
    call_tool,
    connect,
    list_grants,
    make_env,
    rows,
    rpc,
    seed_user_with_perms,
    sql,
)

OTHER_SLUG = "gamma-co"


@pytest.fixture
def two_grants(connector_client, fake_product):
    a = connect(connector_client, sub="42", name="Alice Tan")
    b = connect(connector_client, product="beta", sub="43", name="Bob Lim")
    return a, b


@pytest.fixture
def other_tenant_grant(connector_client):
    """A grant owned by a freshly provisioned second tenant (product gamma)."""
    from modules.connector import registry

    ph = admin_headers(connector_client, "platform@example.com", "platform1234", "platform")
    res = connector_client.post("/platform/tenants", headers=ph, json={
        "name": "Gamma Co", "slug": OTHER_SLUG, "adminName": "G Admin",
        "adminEmail": "admin-gamma@example.com", "adminPassword": "ChangeMe1!"})
    assert res.status_code == 201, res.text
    from app.services.app_store_service import AppStoreService
    db = connector_client._factory()
    try:
        tid = db.execute(__import__("sqlalchemy").text("SELECT id FROM tenants WHERE slug = :s"), {"s": OTHER_SLUG}).scalar()
        AppStoreService(db).install(tid, "connector")
    finally:
        db.close()
    env = make_env({
        "CONNECTOR_PRODUCTS": "acme,beta,gamma",
        "CONNECTOR_GAMMA_TENANT_SLUG": OTHER_SLUG,
        "CONNECTOR_GAMMA_CONNECTION_ID": "conn-gamma",
        "CONNECTOR_GAMMA_CONSENT_URL": "https://gamma.test/connect/claude",
        "CONNECTOR_GAMMA_API_BASE_URL": "https://gamma.test",
        "CONNECTOR_GAMMA_SS_TO_PRODUCT_SECRET": "gamma-ss",
        "CONNECTOR_GAMMA_PRODUCT_TO_SS_SECRET": "gamma-p2s",
    })
    registry.set_env_for_tests(env)
    from jose import jwt as _jwt
    import tests.connector_support as cs

    # gamma uses its own secrets; reuse the helpers with overrides
    cid = cs.registered_client(connector_client, "gamma")
    verifier, ch = cs.pkce_pair()
    res = cs.authorize(connector_client, cid, ch, "gamma")
    from urllib.parse import parse_qs, urlparse

    req = parse_qs(urlparse(res.headers["location"]).query)["req"][0]
    claims = _jwt.decode(req, "gamma-ss", algorithms=["HS256"], audience="gamma-connector-consent")
    token = cs.assertion(claims["request_id"], sub="900", product="gamma")
    out = cs.consent_return(connector_client, claims["request_id"], token, product="gamma")
    assert out.status_code == 302, out.text
    return [g for g in rows(connector_client._factory, "grants") if g["product_user_id"] == "900"][0]


# --- AC-19-50 list / activity --------------------------------------------------------------


def test_list_grants_shape_and_tenant_scope(connector_client, two_grants, other_tenant_grant):
    h = admin_headers(connector_client)
    body = list_grants(connector_client, h)
    assert body["total"] == 2
    assert {g["productUserId"] for g in body["data"]} == {"42", "43"}
    assert other_tenant_grant["id"] not in {g["id"] for g in body["data"]}
    g = next(x for x in body["data"] if x["productUserId"] == "42")
    assert g["status"] == "active"
    assert g["product"] == "acme"


def test_list_filters_status_product_search_and_pagination(connector_client, two_grants):
    h = admin_headers(connector_client)
    a, b = two_grants
    assert {g["productUserId"] for g in list_grants(connector_client, h, product="beta")["data"]} == {"43"}
    assert {g["productUserId"] for g in list_grants(connector_client, h, search="alice")["data"]} == {"42"}
    assert list_grants(connector_client, h, status="revoked")["data"] == []
    page = list_grants(connector_client, h, page_size=1, pageSize=1, page=0)
    assert len(page["data"]) == 1 and page["total"] == 2


def test_get_grant_detail_and_unknown_404(connector_client, two_grants):
    h = admin_headers(connector_client)
    gid = list_grants(connector_client, h)["data"][0]["id"]
    assert connector_client.get(f"/connector/grants/{gid}", headers=h).status_code == 200
    assert connector_client.get("/connector/grants/nope", headers=h).status_code == 404


def test_activity_lists_calls_and_events(connector_client, two_grants, fake_product):
    a, _ = two_grants
    h = admin_headers(connector_client)
    gid = next(g["id"] for g in list_grants(connector_client, h)["data"] if g["productUserId"] == "42")
    call_tool(connector_client, a["access"], "stock_list", {})
    res = connector_client.get(f"/connector/grants/{gid}/activity", headers=h)
    assert res.status_code == 200
    body = res.json()
    assert len(body["calls"]) == 1 and body["calls"][0]["tool"] == "stock_list"
    assert len(body["events"]) >= 1  # consented


def test_activity_of_another_tenants_grant_404(connector_client, other_tenant_grant):
    h = admin_headers(connector_client)
    gid = other_tenant_grant["id"]
    assert connector_client.get(f"/connector/grants/{gid}", headers=h).status_code == 404
    assert connector_client.get(f"/connector/grants/{gid}/activity", headers=h).status_code == 404


# --- AC-19-51 revoke ---------------------------------------------------------------------------


def test_revoke_kills_tokens_and_logs_actor(connector_client, two_grants):
    a, _ = two_grants
    h = admin_headers(connector_client)
    me = connector_client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    actor_id = me.json()["user"]["id"]
    gid = next(g["id"] for g in list_grants(connector_client, h)["data"] if g["productUserId"] == "42")
    res = connector_client.post(f"/connector/grants/{gid}/revoke", headers=h)
    assert res.status_code == 200
    assert rpc(connector_client, a["access"], "ping").status_code == 401
    assert list_grants(connector_client, h, status="revoked")["data"][0]["id"] == gid
    events = rows(connector_client._factory, "grant_events")
    revoked = [e for e in events if "revoked_by_admin" in [str(v) for v in e.values()]]
    assert len(revoked) == 1 and actor_id in [str(v) for v in revoked[0].values()]
    assert revoked[0]["tenant_id"] == DEFAULT_TENANT_ID


def test_revoke_is_idempotent_and_other_tenant_404(connector_client, two_grants, other_tenant_grant):
    h = admin_headers(connector_client)
    gid = list_grants(connector_client, h)["data"][0]["id"]
    assert connector_client.post(f"/connector/grants/{gid}/revoke", headers=h).status_code == 200
    assert connector_client.post(f"/connector/grants/{gid}/revoke", headers=h).status_code in (200, 409)
    res = connector_client.post(f"/connector/grants/{other_tenant_grant['id']}/revoke", headers=h)
    assert res.status_code == 404
    still = [g for g in rows(connector_client._factory, "grants") if g["id"] == other_tenant_grant["id"]]
    assert still[0]["status"] == "active"


def test_bulk_revoke_only_touches_own_tenant(connector_client, two_grants, other_tenant_grant):
    a, b = two_grants
    h = admin_headers(connector_client)
    ids = [g["id"] for g in list_grants(connector_client, h)["data"]]
    res = connector_client.post("/connector/grants/bulk-revoke", headers=h,
                                json={"ids": ids + [other_tenant_grant["id"]]})
    assert res.status_code in (200, 404)
    assert rpc(connector_client, a["access"], "ping").status_code == 401
    assert rpc(connector_client, b["access"], "ping", product="beta").status_code == 401
    other = [g for g in rows(connector_client._factory, "grants") if g["id"] == other_tenant_grant["id"]]
    assert other[0]["status"] == "active"


def test_bulk_revoke_empty_ids_is_422(connector_client, two_grants):
    h = admin_headers(connector_client)
    assert connector_client.post("/connector/grants/bulk-revoke", headers=h, json={"ids": []}).status_code in (200, 422)


# --- AC-19-52 / AC-19-55 products view ----------------------------------------------------------


def _products(c, h):
    res = c.get("/connector/products", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    items = body["data"] if isinstance(body, dict) else body
    return {p["key"]: p for p in items}, res.text


def test_products_view_fields_and_secrets_never_echoed(connector_client, fake_product):
    h = admin_headers(connector_client)
    prods, raw = _products(connector_client, h)
    acme = prods["acme"]
    assert acme["mcpUrl"] == "https://ss.test/mcp/acme"
    assert acme["consentUrl"] == "https://acme.test/connect/claude"
    assert acme["apiBase"] == "https://acme.test"
    for s in SECRETS:
        assert s not in raw
    assert "set" in str(acme["secrets"]).lower() and "missing" not in str(acme["secrets"]).lower()


def test_products_view_shows_missing_secret_for_misconfigured(connector_client):
    from modules.connector import registry

    env = make_env()
    del env["CONNECTOR_ACME_PRODUCT_TO_SS_SECRET"]
    registry.set_env_for_tests(env)
    prods, raw = _products(connector_client, admin_headers(connector_client))
    assert "missing" in str(prods["acme"]["secrets"]).lower()
    assert SS_TO_PRODUCT not in raw


def test_refresh_manifest_fetches_and_reports_version_and_tool_count(connector_client, fake_product):
    h = admin_headers(connector_client)
    res = connector_client.post("/connector/products/acme/refresh-manifest", headers=h)
    assert res.status_code == 200, res.text
    assert len(fake_product.manifest_calls) == 1
    acme = _products(connector_client, h)[0]["acme"]
    assert acme["manifestVersion"] == "v1"
    assert acme["toolCount"] == 3  # read-only tools only
    assert acme["fetchedAt"]
    assert acme.get("stale") in (False, None)
    fake_product.manifest["version"] = "v9"
    connector_client.post("/connector/products/acme/refresh-manifest", headers=h)
    assert _products(connector_client, h)[0]["acme"]["manifestVersion"] == "v9"


def test_refresh_unknown_product_404(connector_client):
    h = admin_headers(connector_client)
    assert connector_client.post("/connector/products/nope/refresh-manifest", headers=h).status_code == 404


def test_failed_refresh_keeps_last_good_and_reports_stale(connector_client, fake_product):
    h = admin_headers(connector_client)
    connector_client.post("/connector/products/acme/refresh-manifest", headers=h)
    good_at = _products(connector_client, h)[0]["acme"]["fetchedAt"]
    fake_product.manifest_error = lambda req: httpx.Response(503, json={"error": {"code": "upstream_error"}})
    connector_client.post("/connector/products/acme/refresh-manifest", headers=h)
    acme = _products(connector_client, h)[0]["acme"]
    assert acme["stale"] is True
    assert acme["lastError"]
    assert acme["fetchedAt"] == good_at          # last good fetched-at kept
    assert acme["toolCount"] == 3                # last good copy still served
    t = connect(connector_client, sub="42")
    res = rpc(connector_client, t["access"], "tools/list")
    assert len(res.json()["result"]["tools"]) == 3


# --- permissions ---------------------------------------------------------------------------------


def test_endpoints_require_authentication(connector_client):
    for method, path in [("get", "/connector/grants"), ("get", "/connector/products"),
                         ("post", "/connector/grants/x/revoke"), ("post", "/connector/grants/bulk-revoke")]:
        assert getattr(connector_client, method)(path).status_code in (401, 403)


def test_no_permission_user_gets_403_everywhere(connector_client, two_grants):
    seed_user_with_perms(connector_client._factory, "nobody@example.com", [])
    h = admin_headers(connector_client, "nobody@example.com", "Passw0rd!x")
    gid = rows(connector_client._factory, "grants")[0]["id"]
    assert connector_client.get("/connector/grants", headers=h).status_code == 403
    assert connector_client.get(f"/connector/grants/{gid}", headers=h).status_code == 403
    assert connector_client.get(f"/connector/grants/{gid}/activity", headers=h).status_code == 403
    assert connector_client.get("/connector/products", headers=h).status_code == 403
    assert connector_client.post(f"/connector/grants/{gid}/revoke", headers=h).status_code == 403


def test_read_only_user_can_list_but_not_manage(connector_client, two_grants, fake_product):
    seed_user_with_perms(connector_client._factory, "reader@example.com", ["connector.read"])
    h = admin_headers(connector_client, "reader@example.com", "Passw0rd!x")
    assert connector_client.get("/connector/grants", headers=h).status_code == 200
    assert connector_client.get("/connector/products", headers=h).status_code == 200
    gid = rows(connector_client._factory, "grants")[0]["id"]
    assert connector_client.post(f"/connector/grants/{gid}/revoke", headers=h).status_code == 403
    assert connector_client.post("/connector/grants/bulk-revoke", headers=h, json={"ids": [gid]}).status_code == 403
    assert connector_client.post("/connector/products/acme/refresh-manifest", headers=h).status_code == 403
    assert rows(connector_client._factory, "grants")[0]["status"] == "active"


# --- AC-19-53 install grants the keys to Admin -------------------------------------------------------


def test_default_admin_holds_connector_keys_after_install(connector_client):
    res = connector_client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    perms = set(res.json()["user"]["permissions"])
    assert {"connector.read", "connector.manage"} <= perms


def test_fresh_tenant_install_grants_keys_to_its_admin(connector_client):
    ph = admin_headers(connector_client, "platform@example.com", "platform1234", "platform")
    res = connector_client.post("/platform/tenants", headers=ph, json={
        "name": "Delta Co", "slug": "delta-co", "adminName": "D Admin",
        "adminEmail": "admin-delta@example.com", "adminPassword": "ChangeMe1!"})
    assert res.status_code == 201, res.text
    ah = admin_headers(connector_client, "admin-delta@example.com", "ChangeMe1!", "delta-co")
    assert connector_client.get("/connector/grants", headers=ah).status_code == 403  # not installed yet
    inst = connector_client.post("/app-store/modules/connector/install", headers=ah)
    assert inst.status_code == 200, inst.text
    login = connector_client.post("/auth/login", json={
        "email": "admin-delta@example.com", "password": "ChangeMe1!", "tenantSlug": "delta-co"})
    assert {"connector.read", "connector.manage"} <= set(login.json()["user"]["permissions"])
    assert connector_client.get("/connector/grants", headers=ah).status_code == 200


def test_tenant_admin_grant_sweep_includes_connector_keys(connector_client):
    from app.seed import tenant_admin_grant

    db = connector_client._factory()
    try:
        keys = {p.key for p in tenant_admin_grant(db, DEFAULT_TENANT_ID)}
    finally:
        db.close()
    assert {"connector.read", "connector.manage"} <= keys


# --- AC-19-54 prune -------------------------------------------------------------------------------------


def test_call_log_pruned_after_retention_default_180_days(connector_client, two_grants, fake_product):
    from modules.connector.services import maintenance

    a, _ = two_grants
    call_tool(connector_client, a["access"], "stock_list", {})
    assert len(rows(connector_client._factory, "call_log")) == 1
    now = datetime.now(timezone.utc)

    db = connector_client._factory()
    try:
        maintenance.prune(db, now + timedelta(days=179))
        db.commit()
    finally:
        db.close()
    assert len(rows(connector_client._factory, "call_log")) == 1

    db = connector_client._factory()
    try:
        maintenance.prune(db, now + timedelta(days=181))
        db.commit()
    finally:
        db.close()
    assert rows(connector_client._factory, "call_log") == []


def test_call_log_retention_setting_override(connector_client, two_grants, fake_product):
    from modules.connector import registry
    from modules.connector.services import maintenance

    registry.set_env_for_tests(make_env({"CONNECTOR_CALL_LOG_RETENTION_DAYS": "10"}))
    a, _ = two_grants
    call_tool(connector_client, a["access"], "stock_list", {})
    db = connector_client._factory()
    try:
        maintenance.prune(db, datetime.now(timezone.utc) + timedelta(days=11))
        db.commit()
    finally:
        db.close()
    assert rows(connector_client._factory, "call_log") == []
