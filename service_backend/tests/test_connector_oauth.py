"""Connector OAuth authorization server (plan sprint-4/19, AC-19-20..30).

Product side is emulated in-test with python-jose using the product->SS secret.
No network, no real data.
"""

import time
from urllib.parse import parse_qs, urlparse

import pytest
from jose import jwt

from app.models import DEFAULT_TENANT_ID
from tests.connector_support import (
    CONNECTION_ID,
    CONSENT_URL,
    LONG_AGO,
    PRODUCT_TO_SS,
    PUBLIC_BASE,
    REDIRECT,
    SECRETS,
    SS_TO_PRODUCT,
    admin_headers,
    any_row_has,
    assertion,
    authorize,
    bearer,
    connect,
    consent_claims,
    consent_return,
    get_code,
    list_grants,
    pkce_pair,
    redirect_params,
    refresh,
    register,
    registered_client,
    rows,
    rpc,
    sql,
    token_exchange,
    values_of,
)

MCP = f"{PUBLIC_BASE}/mcp/acme"


def _assert_error_page(res):
    assert 400 <= res.status_code < 500, (res.status_code, res.text)
    assert "location" not in res.headers


def _no_grants_or_codes(c):
    assert rows(c._factory, "grants") == []
    assert rows(c._factory, "auth_codes") == []


# --- AC-19-20 discovery ---------------------------------------------------------


def test_mcp_without_token_401_with_resource_metadata_header(connector_client):
    res = connector_client.post("/mcp/acme", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == (
        f'Bearer resource_metadata="{PUBLIC_BASE}/.well-known/oauth-protected-resource/mcp/acme"'
    )


def test_bad_bearer_is_401_too(connector_client):
    res = rpc(connector_client, "not-a-real-token", "ping")
    assert res.status_code == 401
    assert "resource_metadata" in res.headers["www-authenticate"]


def test_protected_resource_metadata(connector_client):
    res = connector_client.get("/.well-known/oauth-protected-resource/mcp/acme")
    assert res.status_code == 200
    doc = res.json()
    assert doc["resource"] == MCP
    assert doc["authorization_servers"] == [MCP]


def test_authorization_server_metadata(connector_client):
    res = connector_client.get("/.well-known/oauth-authorization-server/mcp/acme")
    assert res.status_code == 200
    doc = res.json()
    assert doc["issuer"] == MCP
    assert doc["authorization_endpoint"] == f"{MCP}/oauth/authorize"
    assert doc["token_endpoint"] == f"{MCP}/oauth/token"
    assert doc["registration_endpoint"] == f"{MCP}/oauth/register"
    assert doc["revocation_endpoint"] == f"{MCP}/oauth/revoke"
    assert doc["code_challenge_methods_supported"] == ["S256"]
    assert "code" in doc["response_types_supported"]
    assert {"authorization_code", "refresh_token"} <= set(doc["grant_types_supported"])
    assert doc["token_endpoint_auth_methods_supported"] == ["none"]


# --- AC-19-21 DCR ---------------------------------------------------------------


def test_dcr_returns_public_client_and_stores_tenant(connector_client):
    res = register(connector_client)
    assert res.status_code in (200, 201)
    body = res.json()
    assert body["client_id"]
    assert "client_secret" not in body
    assert body["redirect_uris"] == [REDIRECT]
    stored = rows(connector_client._factory, "oauth_clients")
    assert len(stored) == 1
    assert stored[0]["tenant_id"] == DEFAULT_TENANT_ID  # from the product, never client input


@pytest.mark.parametrize("uri", [
    "https://evil.test/cb", REDIRECT + "/", REDIRECT + "?x=1", "http://claude.ai/api/mcp/auth_callback",
])
def test_dcr_rejects_non_allowlisted_redirect(connector_client, uri):
    res = register(connector_client, redirect=uri)
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_redirect_uri"
    assert rows(connector_client._factory, "oauth_clients") == []


def test_dcr_rejects_when_any_redirect_not_allowed(connector_client):
    res = connector_client.post("/mcp/acme/oauth/register", json={
        "client_name": "Claude", "redirect_uris": [REDIRECT, "https://evil.test/cb"]})
    assert res.status_code == 400 and res.json()["error"] == "invalid_redirect_uri"


def test_dcr_is_throttled_per_ip(connector_client):
    statuses = []
    for _ in range(250):
        r = register(connector_client)
        statuses.append(r.status_code)
        if r.status_code == 429:
            assert "retry-after" in r.headers
            break
    assert 429 in statuses


# --- AC-19-22 authorize ---------------------------------------------------------


def test_authorize_unknown_client_error_page(connector_client):
    _v, ch = pkce_pair()
    _assert_error_page(authorize(connector_client, "no-such-client", ch))


def test_authorize_unregistered_redirect_error_page(connector_client):
    cid = registered_client(connector_client)
    _v, ch = pkce_pair()
    _assert_error_page(authorize(connector_client, cid, ch, redirect="https://evil.test/cb"))


def test_authorize_redirect_variant_error_page(connector_client):
    # allow-listed globally but the client registered a different one -> still refused
    cid = registered_client(connector_client)
    _v, ch = pkce_pair()
    res = authorize(connector_client, cid, ch, redirect=REDIRECT + "/")
    _assert_error_page(res)


@pytest.mark.parametrize("kw", [
    {"challenge": None}, {"method": "plain"}, {"method": None}, {"method": "s256"},
])
def test_authorize_requires_s256_pkce(connector_client, kw):
    cid = registered_client(connector_client)
    _v, ch = pkce_pair()
    challenge = kw.get("challenge", ch)
    method = kw["method"] if "method" in kw else "S256"
    res = authorize(connector_client, cid, challenge, method=method)
    _assert_error_page(res)


def test_authorize_valid_creates_pending_request_cookie_and_consent_redirect(connector_client):
    cid = registered_client(connector_client)
    _v, ch = pkce_pair()
    res = authorize(connector_client, cid, ch, state="abc")
    claims = consent_claims(res)
    assert claims["typ"] == "connector_consent_request"
    assert claims["iss"] == "foundryx-ss"
    assert claims["aud"] == "acme-connector-consent"
    assert claims["connection_id"] == CONNECTION_ID
    assert claims["client_name"] == "Claude"
    assert claims["redirect_host"] == "claude.ai"
    assert claims["return_url"] == f"{MCP}/oauth/consent-return"
    assert claims["exp"] - claims["iat"] <= 600
    assert claims["jti"]
    pending = rows(connector_client._factory, "pending_requests")
    assert len(pending) == 1
    assert pending[0]["id"] == claims["request_id"]
    assert pending[0]["tenant_id"] == DEFAULT_TENANT_ID
    assert pending[0]["used_at"] is None


def test_binding_cookie_attributes(connector_client):
    cid = registered_client(connector_client)
    _v, ch = pkce_pair()
    res = authorize(connector_client, cid, ch)
    cookies = [h for h in res.headers.get_list("set-cookie") if h.startswith("fx_connector_bind=")]
    assert len(cookies) == 1
    low = cookies[0].lower()
    assert "httponly" in low and "secure" in low and "samesite=none" in low
    assert "path=/mcp/acme/oauth" in low
    assert "max-age" in low or "expires" in low


def test_consent_request_signed_with_ss_to_product_secret_only(connector_client):
    cid = registered_client(connector_client)
    _v, ch = pkce_pair()
    res = authorize(connector_client, cid, ch)
    req = parse_qs(urlparse(res.headers["location"]).query)["req"][0]
    with pytest.raises(Exception):
        jwt.decode(req, PRODUCT_TO_SS, algorithms=["HS256"], audience="acme-connector-consent")
    assert jwt.decode(req, SS_TO_PRODUCT, algorithms=["HS256"], audience="acme-connector-consent")


# --- AC-19-23 consent-return happy path -------------------------------------------


def test_consent_return_creates_grant_code_and_redirects(connector_client):
    c = connector_client
    iat = int(time.time()) - 5
    g = get_code(c, sub="42", name="Test User", state="orig-state", iat=iat)
    assert g["state"] == "orig-state"
    grants = rows(c._factory, "grants")
    assert len(grants) == 1
    gr = grants[0]
    assert gr["tenant_id"] == DEFAULT_TENANT_ID
    assert gr["product_user_id"] == "42"
    assert gr["status"] == "active"
    assert "Test User" in values_of(gr) and "t@example.com" in values_of(gr)
    assert any(str(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(iat))) in v for v in values_of(gr))
    codes = rows(c._factory, "auth_codes")
    assert len(codes) == 1 and codes[0]["tenant_id"] == DEFAULT_TENANT_ID
    assert g["code"] not in values_of(codes[0])  # hashed
    # the grant shows up for the tenant admin
    h = admin_headers(c)
    assert [x["productUserId"] for x in list_grants(c, h)["data"]] == ["42"]


def test_same_pending_request_cannot_complete_twice(connector_client):
    c = connector_client
    cid = registered_client(c)
    _v, ch = pkce_pair()
    claims = consent_claims(authorize(c, cid, ch))
    rid = claims["request_id"]
    first = consent_return(c, rid, assertion(rid, jti="j-a"))
    assert first.status_code == 302 and "code=" in first.headers["location"]
    second = consent_return(c, rid, assertion(rid, jti="j-b"))
    _assert_error_page(second)
    assert len(rows(c._factory, "auth_codes")) == 1
    assert len(rows(c._factory, "grants")) == 1


# --- AC-19-24 refusals ------------------------------------------------------------


def _pending(c, seed="v"):
    cid = registered_client(c)
    verifier, ch = pkce_pair(seed)
    claims = consent_claims(authorize(c, cid, ch))
    return claims["request_id"], cid, verifier


def test_refuse_missing_binding_cookie(connector_client):
    c = connector_client
    rid, *_ = _pending(c)
    c.cookies.clear()
    _assert_error_page(consent_return(c, rid, assertion(rid)))
    _no_grants_or_codes(c)


def test_refuse_binding_cookie_from_another_request(connector_client):
    c = connector_client
    rid1, cid, _ = _pending(c)
    _v, ch = pkce_pair("w")
    consent_claims(authorize(c, cid, ch))  # jar now holds request 2's cookie
    _assert_error_page(consent_return(c, rid1, assertion(rid1)))
    _no_grants_or_codes(c)


def test_refuse_garbage_binding_cookie(connector_client):
    c = connector_client
    rid, *_ = _pending(c)
    c.cookies.clear()
    c.cookies.set("fx_connector_bind", "forged", domain="testserver", path="/mcp/acme/oauth")
    _assert_error_page(consent_return(c, rid, assertion(rid)))
    _no_grants_or_codes(c)


def test_refuse_expired_pending_request(connector_client):
    c = connector_client
    rid, *_ = _pending(c)
    sql(c._factory, "UPDATE connector.pending_requests SET expires_at = :t", t=LONG_AGO)
    _assert_error_page(consent_return(c, rid, assertion(rid)))
    _no_grants_or_codes(c)


def test_refuse_unknown_request_id(connector_client):
    c = connector_client
    _pending(c)
    _assert_error_page(consent_return(c, "no-such-request", assertion("no-such-request")))
    _no_grants_or_codes(c)


@pytest.mark.parametrize("name,over", [
    ("bad_signature", {"secret": "not-the-secret"}),
    ("ss_to_product_secret", {"secret": SS_TO_PRODUCT}),
    ("wrong_aud", {"aud": "someone-else"}),
    ("wrong_iss", {"iss": "other"}),
    ("wrong_typ", {"typ": "connector_call"}),
    ("wrong_connection", {"connection_id": "conn-other"}),
    ("expired", {"iat": int(time.time()) - 600, "exp": int(time.time()) - 480}),
    ("too_long_lived", {"exp": int(time.time()) + 3600}),
    ("empty_sub", {"sub": ""}),
])
def test_refuse_bad_assertion(connector_client, name, over):
    c = connector_client
    rid, *_ = _pending(c)
    token = assertion(rid, **over)
    _assert_error_page(consent_return(c, rid, token))
    _no_grants_or_codes(c)


def test_refuse_assertion_for_a_different_request_id(connector_client):
    c = connector_client
    rid, *_ = _pending(c)
    _assert_error_page(consent_return(c, rid, assertion("another-request-id")))
    _no_grants_or_codes(c)


def test_refuse_alg_none_assertion(connector_client):
    import base64

    c = connector_client
    rid, *_ = _pending(c)
    good = assertion(rid)
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    forged = header + "." + good.split(".")[1] + "."
    _assert_error_page(consent_return(c, rid, forged))
    _no_grants_or_codes(c)


def test_refuse_replayed_assertion_jti(connector_client):
    c = connector_client
    cid = registered_client(c)
    _v, ch = pkce_pair()
    rid1 = consent_claims(authorize(c, cid, ch))["request_id"]
    assert consent_return(c, rid1, assertion(rid1, jti="same-jti")).status_code == 302
    rid2 = consent_claims(authorize(c, cid, ch))["request_id"]
    _assert_error_page(consent_return(c, rid2, assertion(rid2, jti="same-jti")))
    assert len(rows(c._factory, "auth_codes")) == 1


def test_refusal_does_not_burn_the_request_for_a_valid_retry(connector_client):
    c = connector_client
    rid, *_ = _pending(c)
    _assert_error_page(consent_return(c, rid, assertion(rid, secret="wrong")))
    assert consent_return(c, rid, assertion(rid, jti="good-jti")).status_code == 302


def test_consent_return_without_assertion_or_error_refused(connector_client):
    c = connector_client
    rid, *_ = _pending(c)
    _assert_error_page(consent_return(c, rid))
    _no_grants_or_codes(c)


# --- AC-19-25 deny ------------------------------------------------------------------


def test_deny_redirects_with_access_denied_and_logs_event(connector_client):
    c = connector_client
    cid = registered_client(c)
    _v, ch = pkce_pair()
    rid = consent_claims(authorize(c, cid, ch, state="deny-state"))["request_id"]
    res = consent_return(c, rid, error="access_denied")
    params = redirect_params(res)
    assert params["error"] == "access_denied" and params["state"] == "deny-state"
    assert "code" not in params
    _no_grants_or_codes(c)
    assert any_row_has(c._factory, "grant_events", "denied")


def test_deny_requires_binding_cookie(connector_client):
    c = connector_client
    rid, *_ = _pending(c)
    c.cookies.clear()
    _assert_error_page(consent_return(c, rid, error="access_denied"))
    assert not any_row_has(c._factory, "grant_events", "denied")


def test_deny_cannot_reuse_a_completed_request(connector_client):
    c = connector_client
    g = get_code(c)
    res = consent_return(c, g["request_id"], error="access_denied")
    _assert_error_page(res)


# --- AC-19-26 token: authorization_code ----------------------------------------------


def test_token_exchange_issues_access_and_refresh(connector_client):
    c = connector_client
    g = get_code(c)
    res = token_exchange(c, g["code"], g["verifier"], g["client_id"])
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"].lower() == "bearer"
    assert body["expires_in"] == 3600
    assert body["access_token"] and body["refresh_token"]
    assert body["access_token"] != body["refresh_token"]
    assert res.headers.get("cache-control") == "no-store"
    ok = rpc(c, body["access_token"], "ping")
    assert ok.status_code == 200


@pytest.mark.parametrize("mutate", [
    lambda g: {"code_verifier": "x" * 50},
    lambda g: {"client_id": "someone-else"},
    lambda g: {"redirect_uri": REDIRECT + "/"},
    lambda g: {"code": "not-the-code"},
    lambda g: {"code_verifier": None},
])
def test_token_exchange_refusals_are_invalid_grant(connector_client, mutate):
    c = connector_client
    g = get_code(c)
    data = {"grant_type": "authorization_code", "code": g["code"], "code_verifier": g["verifier"],
            "client_id": g["client_id"], "redirect_uri": REDIRECT}
    data.update(mutate(g))
    data = {k: v for k, v in data.items() if v is not None}
    res = c.post("/mcp/acme/oauth/token", data=data)
    assert res.status_code == 400
    assert res.json()["error"] in ("invalid_grant", "invalid_request", "invalid_client")


def test_token_exchange_wrong_verifier_exact_error(connector_client):
    c = connector_client
    g = get_code(c)
    res = token_exchange(c, g["code"], "z" * 50, g["client_id"])
    assert res.status_code == 400 and res.json()["error"] == "invalid_grant"


def test_auth_code_expires_after_60s(connector_client):
    c = connector_client
    g = get_code(c)
    sql(c._factory, "UPDATE connector.auth_codes SET expires_at = :t", t=LONG_AGO)
    res = token_exchange(c, g["code"], g["verifier"], g["client_id"])
    assert res.status_code == 400 and res.json()["error"] == "invalid_grant"


def test_auth_code_single_use_and_reuse_revokes_first_tokens(connector_client):
    c = connector_client
    g = get_code(c)
    first = token_exchange(c, g["code"], g["verifier"], g["client_id"])
    assert first.status_code == 200
    access = first.json()["access_token"]
    assert rpc(c, access, "ping").status_code == 200
    second = token_exchange(c, g["code"], g["verifier"], g["client_id"])
    assert second.status_code == 400 and second.json()["error"] == "invalid_grant"
    assert rpc(c, access, "ping").status_code == 401  # first use's tokens revoked
    assert rpc(c, first.json()["refresh_token"], "ping").status_code == 401


def test_token_endpoint_unsupported_grant_type(connector_client):
    res = connector_client.post("/mcp/acme/oauth/token", data={"grant_type": "password"})
    assert res.status_code == 400
    assert res.json()["error"] in ("unsupported_grant_type", "invalid_request")


# --- AC-19-27 refresh rotation ------------------------------------------------------


def test_refresh_rotates_pair(connector_client):
    c = connector_client
    t = connect(c)
    res = refresh(c, t["refresh"], t["client_id"])
    assert res.status_code == 200
    new = res.json()
    assert new["access_token"] != t["access"] and new["refresh_token"] != t["refresh"]
    assert rpc(c, new["access_token"], "ping").status_code == 200
    again = refresh(c, new["refresh_token"], t["client_id"])
    assert again.status_code == 200


def test_refresh_replay_revokes_whole_grant(connector_client):
    c = connector_client
    t = connect(c)
    rotated = refresh(c, t["refresh"], t["client_id"]).json()
    replay = refresh(c, t["refresh"], t["client_id"])
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    assert rpc(c, rotated["access_token"], "ping").status_code == 401
    assert refresh(c, rotated["refresh_token"], t["client_id"]).status_code == 400
    h = admin_headers(c)
    assert [g["status"] for g in list_grants(c, h)["data"]] == ["revoked"]
    assert any_row_has(c._factory, "grant_events", "refresh_reuse")


def test_refresh_requires_same_client(connector_client):
    c = connector_client
    t = connect(c)
    other = registered_client(c)
    res = refresh(c, t["refresh"], other)
    assert res.status_code == 400


def test_access_token_cannot_be_used_as_refresh(connector_client):
    c = connector_client
    t = connect(c)
    assert refresh(c, t["access"], t["client_id"]).status_code == 400


def test_expired_refresh_token_refused(connector_client):
    c = connector_client
    t = connect(c)
    sql(c._factory, "UPDATE connector.tokens SET expires_at = :t", t=LONG_AGO)
    assert refresh(c, t["refresh"], t["client_id"]).status_code == 400


def test_expired_access_token_is_401(connector_client):
    c = connector_client
    t = connect(c)
    sql(c._factory, "UPDATE connector.tokens SET expires_at = :t WHERE kind = 'access'", t=LONG_AGO)
    assert rpc(c, t["access"], "ping").status_code == 401


# --- AC-19-28 revoke ------------------------------------------------------------------


@pytest.mark.parametrize("which", ["access", "refresh"])
def test_revoke_kills_grant_tokens_and_returns_200(connector_client, which):
    c = connector_client
    t = connect(c)
    res = c.post("/mcp/acme/oauth/revoke", data={"token": t[which], "client_id": t["client_id"]})
    assert res.status_code == 200
    assert rpc(c, t["access"], "ping").status_code == 401
    assert refresh(c, t["refresh"], t["client_id"]).status_code == 400


def test_revoke_unknown_token_still_200(connector_client):
    res = connector_client.post("/mcp/acme/oauth/revoke", data={"token": "nope"})
    assert res.status_code == 200


def test_revoke_with_other_products_token_changes_nothing(connector_client):
    c = connector_client
    t = connect(c)
    assert c.post("/mcp/beta/oauth/revoke", data={"token": t["access"]}).status_code == 200
    assert rpc(c, t["access"], "ping").status_code == 200


# --- AC-19-29 hashed storage / no secrets in logs -----------------------------------------


def test_tokens_stored_only_hashed_and_nothing_secret_logged(connector_client, caplog):
    import logging

    from modules.connector import crypto

    caplog.set_level(logging.DEBUG)
    c = connector_client
    rid_holder = {}
    cid = registered_client(c)
    verifier, ch = pkce_pair()
    claims = consent_claims(authorize(c, cid, ch))
    rid = rid_holder["rid"] = claims["request_id"]
    token = assertion(rid, jti="log-jti")
    res = consent_return(c, rid, token)
    code = redirect_params(res)["code"]
    body = token_exchange(c, code, verifier, cid).json()
    rpc(c, body["access_token"], "ping")
    secrets_seen = [body["access_token"], body["refresh_token"], code, token, verifier] + SECRETS
    for table in ("tokens", "auth_codes", "pending_requests", "assertion_jti", "call_log", "grants",
                  "grant_events", "oauth_clients"):
        for row in rows(c._factory, table):
            blob = " ".join(values_of(row))
            for s in secrets_seen:
                assert s not in blob, (table, s[:8])
    assert any_row_has(c._factory, "tokens", crypto.hash_token(body["access_token"]))
    assert any_row_has(c._factory, "tokens", crypto.hash_token(body["refresh_token"]))
    assert any_row_has(c._factory, "auth_codes", crypto.hash_token(code))
    for s in secrets_seen:
        assert s not in caplog.text
    for row in rows(c._factory, "tokens") + rows(c._factory, "auth_codes") + rows(c._factory, "grants"):
        assert row["tenant_id"] == DEFAULT_TENANT_ID


# --- AC-19-30 grant reuse -----------------------------------------------------------------


def test_same_user_and_client_reuses_active_grant(connector_client):
    c = connector_client
    first = connect(c, sub="42")
    second = connect(c, sub="42", client_id=first["client_id"], seed="w")
    assert second["access"] != first["access"]
    assert len(rows(c._factory, "grants")) == 1
    assert rpc(c, second["access"], "ping").status_code == 200


def test_different_user_or_client_gets_new_grant(connector_client):
    c = connector_client
    first = connect(c, sub="42")
    connect(c, sub="43", client_id=first["client_id"], seed="w")
    connect(c, sub="42", seed="x")  # new client registration
    assert len(rows(c._factory, "grants")) == 3


def test_revoked_grant_never_reactivated(connector_client):
    c = connector_client
    first = connect(c, sub="42")
    c.post("/mcp/acme/oauth/revoke", data={"token": first["access"]})
    second = connect(c, sub="42", client_id=first["client_id"], seed="w")
    grants = rows(c._factory, "grants")
    assert len(grants) == 2
    assert sorted(g["status"] for g in grants) == ["active", "revoked"]
    assert rpc(c, first["access"], "ping").status_code == 401
    assert rpc(c, second["access"], "ping").status_code == 200


# --- review round: throttles on the remaining public endpoints ----------------------------


def _until_429(fire, n=300):
    for _ in range(n):
        r = fire()
        if r.status_code == 429:
            assert "retry-after" in r.headers
            return True
    return False


def test_authorize_is_throttled_per_ip(connector_client):
    cid = registered_client(connector_client)
    _, ch = pkce_pair()
    assert _until_429(lambda: authorize(connector_client, cid, ch))


def test_consent_return_is_throttled_per_ip(connector_client):
    assert _until_429(lambda: consent_return(connector_client, "no-such-request", "junk"))


def test_revoke_is_throttled_per_ip(connector_client):
    assert _until_429(lambda: connector_client.post(
        "/mcp/acme/oauth/revoke", data={"token": "nope", "client_id": "nope"}))
