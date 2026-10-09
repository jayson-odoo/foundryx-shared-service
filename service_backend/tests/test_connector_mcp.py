"""Connector MCP endpoint (plan sprint-4/19, AC-19-40..48).

The product is emulated through ``product_client.TRANSPORT`` (httpx.MockTransport).
``FakeProduct`` recomputes ``request_hash`` from every received request with an inline
reference implementation and records any mismatch in ``fp.invalid``.
"""

import json
import re
import time
from urllib.parse import parse_qsl, unquote

import httpx
import pytest

from tests.connector_support import (
    LONG_AGO,
    VISIBLE_TOOLS,
    FakeProduct,
    admin_headers,
    any_row_has,
    call_tool,
    connect,
    err_response,
    grant_ids,
    is_tool_error,
    list_grants,
    make_env,
    rows,
    rpc,
    sql,
    tool_text,
    values_of,
)


@pytest.fixture
def conn(connector_client, fake_product):
    """A connected user (sub 42) on product acme."""
    t = connect(connector_client, sub="42", name="Alice Tan")
    t["grant_id"] = grant_ids(connector_client, admin_headers(connector_client))[0]
    return t


def _payload_calls(fp: FakeProduct):
    assert fp.invalid == [], fp.invalid
    return fp.calls


# --- AC-19-40 protocol basics -------------------------------------------------------


def test_initialize(connector_client, conn):
    res = rpc(connector_client, conn["access"], "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "claude", "version": "1"},
    })
    assert res.status_code == 200
    body = res.json()
    assert body["jsonrpc"] == "2.0" and body["id"] == 1
    r = body["result"]
    assert r["serverInfo"]["name"]
    assert "tools" in r["capabilities"]
    assert r["protocolVersion"]


def test_ping(connector_client, conn):
    res = rpc(connector_client, conn["access"], "ping")
    assert res.status_code == 200 and res.json()["result"] == {}


def test_initialized_notification_is_202(connector_client, conn):
    res = rpc(connector_client, conn["access"], "notifications/initialized", notification=True)
    assert res.status_code == 202


@pytest.mark.parametrize("method", ["resources/list", "prompts/list", "tools/delete", "bogus"])
def test_unknown_method_is_32601(connector_client, conn, method):
    res = rpc(connector_client, conn["access"], method, id=7)
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == 7 and body["error"]["code"] == -32601


# --- AC-19-41 tools/list --------------------------------------------------------------


def test_tools_list_returns_only_read_only_non_destructive_tools(connector_client, conn, fake_product):
    res = rpc(connector_client, conn["access"], "tools/list")
    tools = res.json()["result"]["tools"]
    assert [t["name"] for t in tools] == VISIBLE_TOOLS
    t0 = tools[0]
    assert set(t0) >= {"name", "title", "description", "inputSchema", "annotations"}
    assert t0["inputSchema"]["properties"]["limit"] == {"type": "string"}
    assert t0["annotations"]["readOnlyHint"] is True
    assert "write_thing" not in json.dumps(tools) and "risky_read" not in json.dumps(tools)


def test_manifest_fetched_with_signed_call_empty_tool_and_sub(connector_client, conn, fake_product):
    rpc(connector_client, conn["access"], "tools/list")
    assert fake_product.invalid == []
    assert len(fake_product.manifest_calls) == 1
    m = fake_product.manifest_calls[0]
    assert m["method"] == "GET" and m["path"] == "/api/v1/connector/manifest"
    assert m["claims"]["tool"] == "" and m["claims"]["sub"] == ""
    assert m["headers"]["authorization"].startswith("Connector ")


def test_manifest_cached(connector_client, conn, fake_product):
    rpc(connector_client, conn["access"], "tools/list")
    rpc(connector_client, conn["access"], "tools/list")
    assert len(fake_product.manifest_calls) == 1


def test_manifest_refetched_after_ttl(connector_client, conn, fake_product):
    rpc(connector_client, conn["access"], "tools/list")
    sql(connector_client._factory, "UPDATE connector.manifest_cache SET fetched_at = :t", t=LONG_AGO)
    fake_product.manifest["version"] = "v2"
    rpc(connector_client, conn["access"], "tools/list")
    assert len(fake_product.manifest_calls) == 2


def test_last_good_manifest_served_when_product_down(connector_client, conn, fake_product):
    rpc(connector_client, conn["access"], "tools/list")
    sql(connector_client._factory, "UPDATE connector.manifest_cache SET fetched_at = :t", t=LONG_AGO)
    fake_product.manifest_error = lambda req: (_ for _ in ()).throw(httpx.ConnectError("down"))
    res = rpc(connector_client, conn["access"], "tools/list")
    assert [t["name"] for t in res.json()["result"]["tools"]] == VISIBLE_TOOLS


# --- AC-19-42 argument validation -----------------------------------------------------


@pytest.mark.parametrize("name,args", [
    ("stock_list", {"limit": "5", "bogus": "x"}),          # extra property
    ("stock_list", {"limit": 5}),                          # wrong type
    ("item_get", {}),                                      # missing required
    ("item_get", {"item_code": ["a"]}),                    # wrong type
    ("chat_query", {"group_by": "month"}),                 # missing required
])
def test_invalid_args_32602_and_nothing_sent(connector_client, conn, fake_product, name, args):
    res = call_tool(connector_client, conn["access"], name, args)
    assert res.status_code == 200
    assert res.json()["error"]["code"] == -32602
    assert _payload_calls(fake_product) == []


def test_unknown_or_hidden_tool_is_not_callable(connector_client, conn, fake_product):
    for name in ("write_thing", "risky_read", "no_such_tool"):
        res = call_tool(connector_client, conn["access"], name, {})
        body = res.json()
        assert "error" in body or body["result"].get("isError") is True, name
    assert _payload_calls(fake_product) == []


# --- AC-19-43 request construction --------------------------------------------------------


def test_get_call_url_query_and_signed_claims(connector_client, conn, fake_product):
    res = call_tool(connector_client, conn["access"], "stock_list", {"search": "a b/c", "limit": "5"})
    assert res.status_code == 200 and not is_tool_error(res)
    (call,) = _payload_calls(fake_product)
    assert call["method"] == "GET"
    assert call["path"] == "/api/v1/stock/"  # trailing slash kept verbatim
    assert call["url"].startswith("https://acme.test/api/v1/stock/?")
    # only manifest query params, in MANIFEST order (limit before search) - arg order was reversed
    assert parse_qsl(call["query"], keep_blank_values=True) == [("limit", "5"), ("search", "a b/c")]
    assert call["body"] == b""
    c = call["claims"]
    assert c["tool"] == "stock_list" and c["sub"] == "42" and c["grant_id"] == conn["grant_id"]
    assert c["typ"] == "connector_call" and c["iss"] == "foundryx-ss"
    assert c["aud"] == "acme-connector-api" and c["connection_id"] == "conn-acme"
    assert c["exp"] - c["iat"] == 60


def test_optional_params_omitted_when_not_supplied(connector_client, conn, fake_product):
    call_tool(connector_client, conn["access"], "stock_list", {"search": "x"})
    (call,) = _payload_calls(fake_product)
    assert parse_qsl(call["query"]) == [("search", "x")]
    call_tool(connector_client, conn["access"], "stock_list", {})
    assert fake_product.calls[1]["query"] == ""


def test_path_params_percent_encoded_safe_empty(connector_client, conn, fake_product):
    call_tool(connector_client, conn["access"], "item_get", {"item_code": "A/B 1?x#y", "expand": "z"})
    (call,) = _payload_calls(fake_product)
    assert call["path"] == "/api/v1/items/A%2FB%201%3Fx%23y/detail"
    assert unquote(call["path"]) == "/api/v1/items/A/B 1?x#y/detail"
    assert parse_qsl(call["query"]) == [("expand", "z")]


def test_post_body_is_remaining_args_as_json(connector_client, conn, fake_product):
    res = call_tool(connector_client, conn["access"], "chat_query", {"set_key": "k", "group_by": "month"})
    assert not is_tool_error(res)
    (call,) = _payload_calls(fake_product)
    assert call["method"] == "POST" and call["path"] == "/api/v1/connector/query"
    assert call["query"] == ""
    assert json.loads(call["body"]) == {"set_key": "k", "group_by": "month"}
    assert call["headers"]["content-type"].startswith("application/json")
    assert call["claims"]["tool"] == "chat_query"


def test_consented_at_claim_equals_grant_consented_at(connector_client, fake_product):
    iat = int(time.time()) - 60  # exp-iat must stay within the assertion max lifetime
    t = connect(connector_client, sub="77", iat=iat, exp=iat + 120)
    call_tool(connector_client, t["access"], "stock_list", {})
    assert _payload_calls(fake_product)[0]["claims"]["consented_at"] == iat


def test_each_call_gets_fresh_jti(connector_client, conn, fake_product):
    call_tool(connector_client, conn["access"], "stock_list", {})
    call_tool(connector_client, conn["access"], "stock_list", {})
    a, b = _payload_calls(fake_product)
    assert a["claims"]["jti"] != b["claims"]["jti"]


# --- AC-19-44 result mapping and caps -------------------------------------------------------


def test_json_200_becomes_text_content(connector_client, conn, fake_product):
    fake_product.responder = lambda req, c: httpx.Response(200, json={"rows": [{"id": 1}], "marker": "M"})
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    body = res.json()["result"]
    assert body.get("isError") in (None, False)
    assert body["content"][0]["type"] == "text"
    assert json.loads(body["content"][0]["text"]) == {"rows": [{"id": 1}], "marker": "M"}


def _norm(text):
    return re.sub(r"\s+", "", text)


def test_text_over_120000_chars_is_cut_and_marked(connector_client, conn, fake_product):
    raw = json.dumps({"blob": "x" * 200_000}).encode()
    fake_product.responder = lambda req, c: httpx.Response(200, content=raw, headers={"content-type": "application/json"})
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    assert not is_tool_error(res)
    text = tool_text(res)
    assert len(text) <= 125_000
    assert '"truncated":true' in _norm(text)
    assert str(len(raw)) in text  # original size reported


def test_list_over_1000_rows_is_cut_and_marked(connector_client, conn, fake_product):
    data = [{"id": i} for i in range(1500)]
    fake_product.responder = lambda req, c: httpx.Response(200, json=data)
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    assert not is_tool_error(res)
    text = tool_text(res)
    assert '"truncated":true' in _norm(text)
    assert "1500" in text
    assert text.count('"id"') <= 1000


def test_small_result_not_marked_truncated(connector_client, conn, fake_product):
    fake_product.responder = lambda req, c: httpx.Response(200, json=[{"id": i} for i in range(10)])
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    assert "truncated" not in tool_text(res)


# --- AC-19-45 error mapping ------------------------------------------------------------------


def test_401_retried_once_with_fresh_token_then_succeeds(connector_client, conn, fake_product):
    state = {"n": 0}

    def responder(req, claims):
        state["n"] += 1
        if state["n"] == 1:
            return err_response(401, "token_expired")
        return httpx.Response(200, json={"ok": True})

    fake_product.responder = responder
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    assert not is_tool_error(res)
    a, b = fake_product.calls
    assert a["claims"]["jti"] != b["claims"]["jti"]
    assert len(fake_product.calls) == 2


@pytest.mark.parametrize("code", ["invalid_signature", "token_expired", "replayed", "wrong_audience"])
def test_persistent_401_gives_tool_error_after_one_retry(connector_client, conn, fake_product, code):
    fake_product.responder = lambda req, c: err_response(401, code)
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    assert is_tool_error(res)
    assert len(fake_product.calls) == 2
    assert any_row_has(connector_client._factory, "call_log", "upstream_auth")
    assert list_grants(connector_client, admin_headers(connector_client))["data"][0]["status"] == "active"


@pytest.mark.parametrize("code", ["connector_access_removed", "user_inactive", "reconsent_required"])
def test_403_removal_codes_revoke_grant(connector_client, conn, fake_product, code):
    fake_product.responder = lambda req, c: err_response(403, code, "Your access was removed.")
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    assert is_tool_error(res)
    assert len(fake_product.calls) == 1  # no retry on 403
    h = admin_headers(connector_client)
    assert list_grants(connector_client, h)["data"][0]["status"] == "revoked"
    assert any_row_has(connector_client._factory, "grants", code)  # revoked_reason = the code
    nxt = call_tool(connector_client, conn["access"], "stock_list", {})
    assert nxt.status_code == 401


@pytest.mark.parametrize("status,code,msg", [
    (403, "chat_history_not_permitted", "You do not have permission to view chat history."),
    (403, "route_not_allowed", "That route is not allowed."),
    (403, "permission_required", "You lack the permission."),
    (403, "param_not_allowed", "That parameter is not allowed."),
    (404, "not_found", "No such record."),
    (422, "validation_error", "Bad value."),
])
def test_other_4xx_tool_error_with_product_message_grant_stays(connector_client, conn, fake_product,
                                                               status, code, msg):
    fake_product.responder = lambda req, c: err_response(status, code, msg)
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    assert is_tool_error(res)
    assert msg in tool_text(res)
    assert list_grants(connector_client, admin_headers(connector_client))["data"][0]["status"] == "active"
    ok = call_tool(connector_client, conn["access"], "stock_list", {})
    assert ok.status_code == 200


@pytest.mark.parametrize("status", [413, 429, 500, 502, 503])
def test_413_429_5xx_tool_error_grant_stays(connector_client, conn, fake_product, status):
    fake_product.responder = lambda req, c: err_response(status, "upstream_error")
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    assert is_tool_error(res)
    assert "PRODUCT-DATA" not in tool_text(res)
    assert list_grants(connector_client, admin_headers(connector_client))["data"][0]["status"] == "active"


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused"),
                                 httpx.ConnectTimeout("slow")])
def test_timeout_and_refused_are_upstream_unavailable(connector_client, conn, fake_product, exc):
    def responder(req, claims):
        raise exc

    fake_product.responder = responder
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    assert is_tool_error(res)
    assert any_row_has(connector_client._factory, "call_log", "upstream_unavailable")
    assert list_grants(connector_client, admin_headers(connector_client))["data"][0]["status"] == "active"


# --- AC-19-46 audit, fail-closed -----------------------------------------------------------------


def test_each_tool_call_writes_exactly_one_committed_call_log_row(connector_client, conn, fake_product):
    assert rows(connector_client._factory, "call_log") == []
    res = call_tool(connector_client, conn["access"], "stock_list", {"search": "needle"})
    assert not is_tool_error(res)
    log = rows(connector_client._factory, "call_log")  # read via a fresh session => committed
    assert len(log) == 1
    vals = values_of(log[0])
    assert "stock_list" in vals and conn["grant_id"] in vals and "42" in vals
    assert any("needle" in v for v in vals)  # args recorded
    assert log[0]["tenant_id"] == "00000000-0000-0000-0000-000000000001"
    # non-tool-call methods do not write rows
    rpc(connector_client, conn["access"], "ping")
    rpc(connector_client, conn["access"], "tools/list")
    assert len(rows(connector_client._factory, "call_log")) == 1
    call_tool(connector_client, conn["access"], "stock_list", {})
    assert len(rows(connector_client._factory, "call_log")) == 2


def test_call_log_args_capped_4kb_and_no_tokens(connector_client, conn, fake_product):
    huge = "q" * 20_000
    call_tool(connector_client, conn["access"], "stock_list", {"search": huge})
    (row,) = rows(connector_client._factory, "call_log")
    for v in values_of(row):
        assert len(v) <= 4200
    blob = " ".join(values_of(row))
    assert conn["access"] not in blob and conn["refresh"] not in blob
    assert huge not in blob


def test_audit_write_failure_is_fail_closed(connector_client, conn, fake_product, monkeypatch):
    from modules.connector.services import audit

    def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(audit, "write_call_log", boom)
    res = call_tool(connector_client, conn["access"], "stock_list", {})
    assert res.status_code == 200
    assert is_tool_error(res)
    text = tool_text(res)
    assert "PRODUCT-DATA" not in text
    assert "could not be recorded" in text
    assert rows(connector_client._factory, "call_log") == []


# --- AC-19-47 token scoping, last_used, idle expiry ----------------------------------------------


def test_token_of_product_a_rejected_on_product_b(connector_client, conn, fake_product):
    res = rpc(connector_client, conn["access"], "ping", product="beta")
    assert res.status_code == 401
    assert rpc(connector_client, conn["access"], "ping").status_code == 200


def test_beta_token_works_on_beta(connector_client, fake_product):
    t = connect(connector_client, product="beta", sub="9")
    assert rpc(connector_client, t["access"], "ping", product="beta").status_code == 200
    assert rpc(connector_client, t["access"], "ping").status_code == 401


def test_revoked_or_expired_grant_token_is_401(connector_client, conn, fake_product):
    h = admin_headers(connector_client)
    connector_client.post(f"/connector/grants/{conn['grant_id']}/revoke", headers=h)
    assert rpc(connector_client, conn["access"], "ping").status_code == 401


def test_last_used_at_updates_on_use(connector_client, conn, fake_product):
    before = rows(connector_client._factory, "grants")[0]["last_used_at"]
    call_tool(connector_client, conn["access"], "stock_list", {})
    after = rows(connector_client._factory, "grants")[0]["last_used_at"]
    assert after is not None and (before is None or str(after) >= str(before))


def test_grant_idle_90_days_expired_by_prune_and_tokens_die(connector_client, conn, fake_product):
    from datetime import datetime, timedelta, timezone

    from modules.connector.services import maintenance

    db = connector_client._factory()
    try:
        maintenance.prune(db, datetime.now(timezone.utc) + timedelta(days=91))
        db.commit()
    finally:
        db.close()
    g = list_grants(connector_client, admin_headers(connector_client), status="expired")["data"]
    assert [x["id"] for x in g] == [conn["grant_id"]]
    assert rpc(connector_client, conn["access"], "ping").status_code == 401


def test_recently_used_grant_not_expired_by_prune(connector_client, conn, fake_product):
    from datetime import datetime, timedelta, timezone

    from modules.connector.services import maintenance

    call_tool(connector_client, conn["access"], "stock_list", {})
    db = connector_client._factory()
    try:
        maintenance.prune(db, datetime.now(timezone.utc) + timedelta(days=30))
        db.commit()
    finally:
        db.close()
    assert list_grants(connector_client, admin_headers(connector_client))["data"][0]["status"] == "active"


# --- AC-19-48 throttle ------------------------------------------------------------------------


def test_tools_call_throttled_per_grant(connector_client, conn, fake_product):
    statuses = []
    for _ in range(600):
        r = call_tool(connector_client, conn["access"], "stock_list", {})
        statuses.append(r.status_code)
        if r.status_code == 429:
            assert "retry-after" in r.headers
            break
    assert 429 in statuses
    other = connect(connector_client, sub="99")  # a different grant is not throttled
    assert call_tool(connector_client, other["access"], "stock_list", {}).status_code == 200


def test_product_whose_tenant_has_not_installed_module_404s(connector_client):
    """Fail closed: the connector module must be ACTIVE for the product's owning
    tenant, else /mcp/{p} and the well-known endpoints are a uniform 404."""
    from app.models import DEFAULT_TENANT_ID
    from modules.connector import registry

    ph = admin_headers(connector_client, "platform@example.com", "platform1234", "platform")
    res = connector_client.post("/platform/tenants", headers=ph, json={
        "name": "Delta Co", "slug": "delta-co", "adminName": "D Admin",
        "adminEmail": "admin-delta@example.com", "adminPassword": "ChangeMe1!"})
    assert res.status_code == 201, res.text
    registry.set_env_for_tests(make_env({
        "CONNECTOR_PRODUCTS": "acme,beta,delta",
        "CONNECTOR_DELTA_TENANT_SLUG": "delta-co",
        "CONNECTOR_DELTA_CONNECTION_ID": "conn-delta",
        "CONNECTOR_DELTA_CONSENT_URL": "https://delta.test/connect/claude",
        "CONNECTOR_DELTA_API_BASE_URL": "https://delta.test",
        "CONNECTOR_DELTA_SS_TO_PRODUCT_SECRET": "delta-ss",
        "CONNECTOR_DELTA_PRODUCT_TO_SS_SECRET": "delta-p2s",
    }))
    assert DEFAULT_TENANT_ID  # default tenant has the module; delta does not
    assert connector_client.post("/mcp/delta", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 404
    for path in (
        "/.well-known/oauth-protected-resource/mcp/delta",
        "/.well-known/oauth-authorization-server/mcp/delta",
        "/mcp/delta/.well-known/oauth-authorization-server",
    ):
        assert connector_client.get(path).status_code == 404, path
