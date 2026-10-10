"""Connector settings in the database (lane SETTINGS-IN-DB-SS).

Precedence is per field: a non-blank database value wins, else the environment
(only for the tenant the environment assigns the product to), else the default.
Secrets are Fernet-encrypted at rest and never returned. Saves apply on the
next request (no restart). Editing needs ``connector.settings``.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from modules.connector import registry
from tests.connector_support import (
    CONSENT_URL,
    PRODUCT_TO_SS,
    REDIRECT,
    SS_TO_PRODUCT,
    admin_headers,
    any_row_has,
    authorize,
    connect,
    consent_claims,
    make_env,
    pkce_pair,
    registered_client,
    rows,
    seed_user_with_perms,
)

TUNNEL = "https://db-tunnel.example"
OUTSIDE_IP = "203.0.113.5"
CLAUDE_IP = "160.79.105.9"
CIDR = "160.79.104.0/21"

NEW_PRODUCT = {
    "key": "delta",
    "displayName": "Delta ERP",
    "connectionId": "conn-delta",
    "consentUrl": "https://delta.test/connect/claude",
    "apiBaseUrl": "https://delta.test/",
    "ssToProductSecret": "delta-ss-secret-0001",
    "productToSsSecret": "delta-p2s-secret",
}


@pytest.fixture
def h(connector_client):
    return admin_headers(connector_client)


def _create(c, h, **over):
    body = {**NEW_PRODUCT, **over}
    return c.post("/connector/products", json=body, headers=h)


def _settings(c, h, key):
    res = c.get(f"/connector/products/{key}/settings", headers=h)
    assert res.status_code == 200, res.text
    return res.json()


# ---- products: create, resolve, precedence ---------------------------------------


def test_db_only_product_resolves_without_any_env(connector_client, h):
    registry.set_env_for_tests({})
    assert connector_client.get("/.well-known/oauth-authorization-server/mcp/delta").status_code == 404
    res = _create(connector_client, h)
    assert res.status_code == 201, res.text
    doc = connector_client.get("/.well-known/oauth-authorization-server/mcp/delta")
    assert doc.status_code == 200  # live on the next request, no restart
    assert doc.json()["issuer"] == "https://ss.test/mcp/delta"
    item = next(p for p in connector_client.get("/connector/products", headers=h).json()["data"]
                if p["key"] == "delta")
    assert item["status"] == "ok" and item["apiBase"] == "https://delta.test"


def test_db_field_wins_blank_falls_back_to_env(connector_client, h):
    # display name is cosmetic: it may override the environment on its own
    res = connector_client.put("/connector/products/acme/settings", headers=h,
                               json={"displayName": "Acme Prod"})
    assert res.status_code == 200, res.text
    assert _settings(connector_client, h, "acme")["secrets"]["ssToProduct"]["source"] == "environment"
    # a URL decides where operator-signed traffic goes: the secrets must come along
    res = connector_client.put("/connector/products/acme/settings", headers=h,
                               json={"consentUrl": "https://acme.test/db-consent"})
    assert res.status_code == 422
    assert set(res.json()["detail"]["fieldErrors"]) == {"ssToProductSecret", "productToSsSecret"}
    res = connector_client.put("/connector/products/acme/settings", headers=h,
                               json={"consentUrl": "https://acme.test/db-consent",
                                     "ssToProductSecret": SS_TO_PRODUCT,
                                     "productToSsSecret": PRODUCT_TO_SS})
    assert res.status_code == 200, res.text
    s = _settings(connector_client, h, "acme")
    assert s["fields"]["consentUrl"] == {"value": "https://acme.test/db-consent", "source": "database"}
    assert s["fields"]["apiBaseUrl"]["source"] == "environment"
    assert s["fields"]["issuer"] == {"value": "acme", "source": "default"}
    cid = registered_client(connector_client)
    _, challenge = pkce_pair()
    loc = authorize(connector_client, cid, challenge).headers["location"]
    assert loc.startswith("https://acme.test/db-consent?req=")
    # clearing the field returns it to the environment value
    res = connector_client.put("/connector/products/acme/settings", headers=h,
                               json={"consentUrl": "", "clearSecrets": ["ssToProduct", "productToSs"]})
    assert res.status_code == 200
    assert _settings(connector_client, h, "acme")["fields"]["consentUrl"] == {
        "value": CONSENT_URL, "source": "environment"}


def test_env_of_another_tenant_never_applies_and_key_cannot_be_taken(connector_client, h):
    registry.set_env_for_tests(make_env({"CONNECTOR_PRODUCTS": "acme,beta,delta",
                                         "CONNECTOR_DELTA_TENANT_SLUG": "someone-else",
                                         "CONNECTOR_DELTA_API_BASE_URL": "https://evil.test"}))
    assert _create(connector_client, h).status_code == 409


def test_duplicate_key_and_bad_values_rejected(connector_client, h):
    assert _create(connector_client, h).status_code == 201
    assert _create(connector_client, h).status_code == 409
    assert _create(connector_client, h, key="Bad Key").status_code == 422
    assert _create(connector_client, h, key="eps", consentUrl="javascript:alert(1)").status_code == 422
    same = _create(connector_client, h, key="zeta", productToSsSecret=NEW_PRODUCT["ssToProductSecret"])
    assert same.status_code == 422


def test_foreign_tenant_cannot_see_or_edit_product(connector_client, h):
    from tests.test_connector_admin import OTHER_SLUG  # noqa: F401 - slug only
    assert _create(connector_client, h).status_code == 201
    ph = admin_headers(connector_client, "platform@example.com", "platform1234", "platform")
    res = connector_client.post("/platform/tenants", headers=ph, json={
        "name": "Eta Co", "slug": "eta-co", "adminName": "E", "adminEmail": "admin-eta@example.com",
        "adminPassword": "ChangeMe1!"})
    assert res.status_code == 201, res.text
    db = connector_client._factory()
    try:
        from sqlalchemy import text

        from app.services.app_store_service import AppStoreService
        tid = db.execute(text("SELECT id FROM tenants WHERE slug='eta-co'")).scalar()
        AppStoreService(db).install(tid, "connector")
        db.commit()
    finally:
        db.close()
    eh = admin_headers(connector_client, "admin-eta@example.com", "ChangeMe1!", "eta-co")
    assert connector_client.get("/connector/products/delta/settings", headers=eh).status_code == 404
    assert connector_client.put("/connector/products/delta/settings", headers=eh,
                                json={"displayName": "x"}).status_code == 404
    assert connector_client.get("/connector/products", headers=eh).json()["data"] == []


# ---- secrets ---------------------------------------------------------------------


def test_secrets_encrypted_at_rest_and_never_returned(connector_client, h):
    assert _create(connector_client, h).status_code == 201
    raw = rows(connector_client._factory, "product_settings")
    assert raw and not any_row_has(connector_client._factory, "product_settings", "delta-ss-secret-0001")
    assert all("delta-ss-secret-0001" not in str(v) for r in raw for v in r.values())
    for path in ("/connector/products/delta/settings", "/connector/products", "/connector/settings"):
        body = connector_client.get(path, headers=h).text
        assert "delta-ss-secret-0001" not in body and "delta-p2s-secret" not in body
    s = _settings(connector_client, h, "delta")
    assert s["secrets"]["ssToProduct"] == {"state": "set", "source": "database"}


def test_blank_secret_keeps_clear_falls_back(connector_client, h, fake_product):
    res = connector_client.put("/connector/products/acme/settings", headers=h,
                               json={"ssToProductSecret": "", "displayName": "Acme"})
    assert res.status_code == 200
    s = _settings(connector_client, h, "acme")
    assert s["secrets"]["ssToProduct"] == {"state": "set", "source": "environment"}
    res = connector_client.put("/connector/products/acme/settings", headers=h,
                               json={"ssToProductSecret": "rotated-db-secret"})
    assert res.status_code == 200
    assert _settings(connector_client, h, "acme")["secrets"]["ssToProduct"]["source"] == "database"
    cid = registered_client(connector_client)
    _, challenge = pkce_pair()
    claims = consent_claims(authorize(connector_client, cid, challenge), secret="rotated-db-secret")
    assert claims["aud"] == "acme-connector-consent"
    res = connector_client.put("/connector/products/acme/settings", headers=h,
                               json={"clearSecrets": ["ssToProduct"]})
    assert res.status_code == 200
    assert _settings(connector_client, h, "acme")["secrets"]["ssToProduct"]["source"] == "environment"
    consent_claims(authorize(connector_client, cid, challenge), secret=SS_TO_PRODUCT)


def test_secret_equal_to_the_other_rejected_on_update(connector_client, h):
    res = connector_client.put("/connector/products/acme/settings", headers=h,
                               json={"ssToProductSecret": PRODUCT_TO_SS})
    assert res.status_code == 422


def test_unreadable_secret_is_misconfigured_not_500(connector_client, h):
    assert _create(connector_client, h).status_code == 201
    from tests.connector_support import sql
    sql(connector_client._factory,
        "UPDATE connector.product_settings SET secrets_encrypted='not-a-fernet-token'")
    s = _settings(connector_client, h, "delta")
    assert s["secrets"]["ssToProduct"]["state"] == "unreadable"
    assert s["status"] == "misconfigured"
    assert connector_client.get("/.well-known/oauth-authorization-server/mcp/delta").status_code == 404


# ---- delete --------------------------------------------------------------------------


def test_delete_needs_typed_key_and_no_active_grants(connector_client, h, fake_product):
    assert connector_client.put("/connector/products/acme/settings", headers=h,
                                json={"displayName": "Acme DB"}).status_code == 200
    connect(connector_client)
    bad = connector_client.request("DELETE", "/connector/products/acme", headers=h,
                                   json={"confirmKey": "nope"})
    assert bad.status_code == 422
    busy = connector_client.request("DELETE", "/connector/products/acme", headers=h,
                                    json={"confirmKey": "acme"})
    assert busy.status_code == 409
    assert _create(connector_client, h).status_code == 201
    ok = connector_client.request("DELETE", "/connector/products/delta", headers=h,
                                  json={"confirmKey": "delta"})
    assert ok.status_code == 200
    assert connector_client.get("/.well-known/oauth-authorization-server/mcp/delta").status_code == 404
    # env-only product has no row to delete
    gone = connector_client.request("DELETE", "/connector/products/beta", headers=h,
                                    json={"confirmKey": "beta"})
    assert gone.status_code == 404


# ---- tenant-level settings ------------------------------------------------------------


def test_tenant_settings_sources_and_public_base_url(connector_client, h, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    s = connector_client.get("/connector/settings", headers=h).json()
    assert s["publicBaseUrl"] == {"value": "https://ss.test", "source": "default"}
    assert s["redirectAllowlist"] == {"value": REDIRECT, "source": "environment"}
    assert s["callTimeoutSeconds"] == {"value": "15", "source": "default"}
    assert s["forwardedForWarning"] is True  # issue #118: until lane SS-118-XFF merges
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    assert connector_client.get("/connector/settings", headers=h).json()["forwardedForWarning"] is False
    res = connector_client.put("/connector/settings", headers=h,
                               json={"publicBaseUrl": TUNNEL + "/", "callTimeoutSeconds": 20})
    assert res.status_code == 200, res.text
    assert res.json()["publicBaseUrl"] == {"value": TUNNEL, "source": "database"}
    doc = connector_client.get("/.well-known/oauth-authorization-server/mcp/acme").json()
    assert doc["issuer"] == f"{TUNNEL}/mcp/acme"
    item = next(p for p in connector_client.get("/connector/products", headers=h).json()["data"]
                if p["key"] == "acme")
    assert item["mcpUrl"] == f"{TUNNEL}/mcp/acme"
    res = connector_client.put("/connector/settings", headers=h, json={"publicBaseUrl": None})
    assert res.json()["publicBaseUrl"]["source"] == "default"


def test_tenant_settings_validation(connector_client, h):
    for body in ({"allowedClientCidrs": "10.0.0.0/8, nonsense"}, {"publicBaseUrl": "ftp://x"},
                 {"redirectAllowlist": "not a url"}, {"callTimeoutSeconds": 0},
                 {"manifestTtlSeconds": -1}, {"callLogRetentionDays": 0}):
        assert connector_client.put("/connector/settings", headers=h, json=body).status_code == 422, body


def test_db_cidrs_gate_claude_facing_endpoints(connector_client, h, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    res = connector_client.put("/connector/settings", headers=h, json={"allowedClientCidrs": CIDR})
    assert res.status_code == 200, res.text
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    with TestClient(app, base_url="https://testserver", client=(OUTSIDE_IP, 5000)) as c:
        assert c.post("/mcp/acme", json=ping).status_code == 403
    with TestClient(app, base_url="https://testserver", client=(CLAUDE_IP, 5000)) as c:
        assert c.post("/mcp/acme", json=ping).status_code == 401


def test_db_redirect_allowlist_applies(connector_client, h):
    other = "https://other.example/cb"
    res = connector_client.put("/connector/settings", headers=h,
                               json={"redirectAllowlist": f"{REDIRECT}, {other}"})
    assert res.status_code == 200, res.text
    registered_client(connector_client, redirect=other)


# ---- permissions + audit ---------------------------------------------------------------


def test_read_perm_cannot_edit(connector_client):
    seed_user_with_perms(connector_client._factory, "reader@example.com", ["connector.read"])
    rh = admin_headers(connector_client, "reader@example.com", "Passw0rd!x")
    assert connector_client.get("/connector/settings", headers=rh).status_code == 200
    assert connector_client.get("/connector/products/acme/settings", headers=rh).status_code == 200
    assert connector_client.put("/connector/settings", headers=rh, json={}).status_code == 403
    assert connector_client.put("/connector/products/acme/settings", headers=rh,
                                json={}).status_code == 403
    assert connector_client.post("/connector/products", headers=rh, json=NEW_PRODUCT).status_code == 403


def test_admin_holds_connector_settings(connector_client, h):
    me = connector_client.get("/auth/me", headers=h).json()
    assert "connector.settings" in me["permissions"]


def test_changes_are_audited_by_field_name_only(connector_client, h):
    assert _create(connector_client, h).status_code == 201
    connector_client.put("/connector/products/delta/settings", headers=h,
                         json={"ssToProductSecret": "another-secret-00001", "displayName": "D2"})
    connector_client.put("/connector/settings", headers=h, json={"callTimeoutSeconds": 30})
    audit = rows(connector_client._factory, "settings_audit")
    assert len(audit) == 3
    text_all = " ".join(str(v) for r in audit for v in r.values())
    assert "another-secret-00001" not in text_all and "delta-ss-secret-0001" not in text_all
    assert "ssToProductSecret" in text_all and "callTimeoutSeconds" in text_all
    res = connector_client.get("/connector/settings/audit", headers=h)
    assert res.status_code == 200 and len(res.json()["data"]) == 3


def test_sweep_grants_settings_to_admin_roles_holding_manage(connector_session_factory):
    from sqlalchemy import select

    from app.models import Role
    from app.models.permission import Permission, role_permissions
    from modules.connector.bootstrap import sweep_settings_grant

    db = connector_session_factory()
    try:
        pid = db.execute(select(Permission.id).where(Permission.key == "connector.settings")).scalar()
        db.execute(role_permissions.delete().where(role_permissions.c.permission_id == pid))
        db.commit()
        sweep_settings_grant(db)
        db.commit()
        holders = db.execute(select(Role.name).join(
            role_permissions, role_permissions.c.role_id == Role.id).where(
            role_permissions.c.permission_id == pid)).scalars().all()
        assert holders and set(holders) == {"Admin"}
    finally:
        db.close()


# ---- retention ------------------------------------------------------------------------


def test_retention_is_per_tenant(connector_client, h, fake_product):
    from datetime import datetime, timedelta, timezone

    from modules.connector.services import maintenance
    from tests.connector_support import call_tool, sql

    g = connect(connector_client)
    call_tool(connector_client, g["access"], "stock_list", {})
    sql(connector_client._factory, "UPDATE connector.call_log SET created_at=:t",
        t=(datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S.000000"))
    db = connector_client._factory()
    try:
        maintenance.prune(db, datetime.now(timezone.utc))
        db.commit()
    finally:
        db.close()
    assert rows(connector_client._factory, "call_log")  # 180-day default keeps it
    connector_client.put("/connector/settings", headers=h, json={"callLogRetentionDays": 7})
    db = connector_client._factory()
    try:
        maintenance.prune(db, datetime.now(timezone.utc))
        db.commit()
    finally:
        db.close()
    assert rows(connector_client._factory, "call_log") == []


def test_env_added_later_for_another_tenant_does_not_bleed_into_db_product(connector_client, h):
    assert _create(connector_client, h, apiBaseUrl="").status_code == 201
    registry.set_env_for_tests(make_env({"CONNECTOR_PRODUCTS": "acme,beta,delta",
                                         "CONNECTOR_DELTA_TENANT_SLUG": "someone-else",
                                         "CONNECTOR_DELTA_API_BASE_URL": "https://evil.test"}))
    s = _settings(connector_client, h, "delta")
    assert s["fields"]["apiBaseUrl"] == {"value": None, "source": "unset"}
    assert s["status"] == "misconfigured"



# ---- security review fixes ------------------------------------------------------------


def test_env_secrets_never_follow_a_tenant_set_binding_field(connector_client, h):
    """Even if a row is planted directly, environment secrets drop once a URL or
    claim is saved here: the product is misconfigured, never operator-signed."""
    from tests.connector_support import sql
    assert connector_client.put("/connector/products/acme/settings", headers=h,
                                json={"displayName": "Acme"}).status_code == 200
    sql(connector_client._factory,
        "UPDATE connector.product_settings SET api_base_url='https://attacker.example' WHERE key='acme'")
    s = _settings(connector_client, h, "acme")
    assert s["secrets"]["ssToProduct"]["state"] == "missing"
    assert s["status"] == "misconfigured"
    assert connector_client.get("/.well-known/oauth-authorization-server/mcp/acme").status_code == 404


@pytest.mark.parametrize("url", ["http://delta.test", "https://127.0.0.1", "https://169.254.169.254",
                                 "https://10.0.0.5", "https://localhost:8001", "https://u:p@delta.test",
                                 "https://delta.test/\tx"])
def test_api_base_url_rejects_internal_and_odd_targets(connector_client, h, url):
    res = _create(connector_client, h, apiBaseUrl=url)
    assert res.status_code == 422, (url, res.text)


def test_outbound_call_rechecks_tenant_set_base_url(connector_client, h, monkeypatch):
    """DNS can be re-pointed after save: the guard runs again before every call."""
    import httpx

    from app.services import url_guard
    from modules.connector.services import product_client

    assert _create(connector_client, h).status_code == 201
    product = registry.get_product("delta", connector_client._factory())
    assert product is not None and product.guard_outbound
    monkeypatch.setattr(url_guard.socket, "getaddrinfo",
                        lambda *a, **k: [(None, None, None, None, ("169.254.169.254", 0))])
    sent = []
    product_client.TRANSPORT = httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200))
    with pytest.raises(httpx.TransportError):
        product_client.send(product, method="GET", raw_path="/x", query="", body=b"", sub="",
                            grant_id="", consented_at=0, tool="")
    assert sent == []
    env_product = registry.get_product("acme", connector_client._factory())
    assert env_product is not None and not env_product.guard_outbound


def test_operator_env_assignment_beats_a_squatted_db_key(connector_client, h):
    assert _create(connector_client, h).status_code == 201
    env = make_env({"CONNECTOR_PRODUCTS": "acme,beta,delta",
                    "CONNECTOR_DELTA_TENANT_SLUG": "someone-else",
                    "CONNECTOR_DELTA_CONNECTION_ID": "conn-op",
                    "CONNECTOR_DELTA_CONSENT_URL": "https://op.test/c",
                    "CONNECTOR_DELTA_API_BASE_URL": "https://op.test",
                    "CONNECTOR_DELTA_SS_TO_PRODUCT_SECRET": "op-ss-secret-00000001",
                    "CONNECTOR_DELTA_PRODUCT_TO_SS_SECRET": "op-p2s-secret-0000001"})
    registry.set_env_for_tests(env)
    live = registry.resolve_product(connector_client._factory(), "delta")
    assert live.product is not None and live.product.api_base_url == "https://op.test"
    assert _settings(connector_client, h, "delta")["status"] == "misconfigured"
    keys = [p["key"] for p in connector_client.get("/connector/products", headers=h).json()["data"]]
    assert "delta" not in keys


def test_cidr_answer_is_uniform_for_unusable_products(connector_client, h, monkeypatch):
    """A tenant allow-list never applies to an unknown or misconfigured product,
    so an outside caller cannot tell which keys exist."""
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    assert connector_client.put("/connector/settings", headers=h,
                                json={"allowedClientCidrs": CIDR}).status_code == 200
    assert _create(connector_client, h, consentUrl="").status_code == 201  # misconfigured
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    with TestClient(app, base_url="https://testserver", client=(OUTSIDE_IP, 5000)) as c:
        assert c.post("/mcp/nosuch", json=ping).status_code == 404
        assert c.post("/mcp/delta", json=ping).status_code == 404
        assert c.post("/mcp/acme", json=ping).status_code == 403


def test_api_base_url_change_drops_cached_manifest(connector_client, h, fake_product):
    from tests.connector_support import sql
    assert _create(connector_client, h).status_code == 201
    sql(connector_client._factory,
        "INSERT INTO connector.manifest_cache (id, tenant_id, product, version) "
        "SELECT 'm1', tenant_id, 'delta', 'v1' FROM connector.product_settings WHERE key='delta'")
    assert rows(connector_client._factory, "manifest_cache")
    res = connector_client.put("/connector/products/delta/settings", headers=h,
                               json={"apiBaseUrl": "https://delta2.test"})
    assert res.status_code == 200, res.text
    assert [r for r in rows(connector_client._factory, "manifest_cache") if r["product"] == "delta"] == []
