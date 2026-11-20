"""RED tests: env-configurable public base URL + Claude IP allowlist (plan sprint-4/19 s7 Q5).

CONNECTOR_PUBLIC_BASE_URL overrides settings.public_base_url for everything the
connector emits; CONNECTOR_ALLOWED_CLIENT_CIDRS gates ONLY the Claude-facing
server-to-server endpoints (fail closed on an invalid entry).
"""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from modules.connector import registry
from tests.connector_support import (
    REDIRECT, bearer, consent_claims, authorize, make_env, pkce_pair, register, registered_client,
)

TUNNEL = "https://abc.trycloudflare.com"
CLAUDE_IP = "160.79.105.9"
OUTSIDE_IP = "203.0.113.5"
CIDR = "160.79.104.0/21"


def _env(**extra):
    registry.set_env_for_tests(make_env(extra))


def _client_from(connector_client, ip, headers=None):
    """A second client presenting `ip` as the socket peer (same DB override)."""
    return TestClient(app, base_url="https://testserver", client=(ip, 50000),
                      headers=headers or {})


# ---- 1. CONNECTOR_PUBLIC_BASE_URL -------------------------------------------------


@pytest.mark.parametrize("base", [TUNNEL, TUNNEL + "/"])
def test_metadata_uses_env_base_url(connector_client, base):
    _env(CONNECTOR_PUBLIC_BASE_URL=base)
    mcp = f"{TUNNEL}/mcp/acme"
    pr = connector_client.get("/.well-known/oauth-protected-resource/mcp/acme").json()
    assert pr["resource"] == mcp and pr["authorization_servers"] == [mcp]
    doc = connector_client.get("/.well-known/oauth-authorization-server/mcp/acme").json()
    assert doc["issuer"] == mcp
    for k, p in [("authorization_endpoint", "authorize"), ("token_endpoint", "token"),
                 ("registration_endpoint", "register"), ("revocation_endpoint", "revoke")]:
        assert doc[k] == f"{mcp}/oauth/{p}"


def test_www_authenticate_uses_env_base_url(connector_client):
    _env(CONNECTOR_PUBLIC_BASE_URL=TUNNEL)
    res = connector_client.post("/mcp/acme", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == (
        f'Bearer resource_metadata="{TUNNEL}/.well-known/oauth-protected-resource/mcp/acme"')


def test_consent_return_url_uses_env_base_url(connector_client):
    _env(CONNECTOR_PUBLIC_BASE_URL=TUNNEL)
    cid = registered_client(connector_client)
    _, challenge = pkce_pair()
    claims = consent_claims(authorize(connector_client, cid, challenge))
    assert claims["return_url"] == f"{TUNNEL}/mcp/acme/oauth/consent-return"


def test_products_mcp_url_uses_env_base_url(connector_client):
    from tests.connector_support import admin_headers
    _env(CONNECTOR_PUBLIC_BASE_URL=TUNNEL)
    h = admin_headers(connector_client)
    body = connector_client.get("/connector/products", headers=h).json()
    items = body["data"] if isinstance(body, dict) else body
    acme = next(i for i in items if i["key"] == "acme")
    assert acme["mcpUrl"] == f"{TUNNEL}/mcp/acme"


def test_unset_env_base_falls_back_to_settings(connector_client):
    # existing behaviour; expected to already pass
    assert settings.public_base_url == "https://ss.test"
    doc = connector_client.get("/.well-known/oauth-authorization-server/mcp/acme").json()
    assert doc["issuer"] == "https://ss.test/mcp/acme"


# ---- 2. CONNECTOR_ALLOWED_CLIENT_CIDRS --------------------------------------------

CLAUDE_FACING = [
    ("POST", "/mcp/acme", {"json": {"jsonrpc": "2.0", "id": 1, "method": "ping"}}),
    ("POST", "/mcp/acme/oauth/register", {"json": {"client_name": "c", "redirect_uris": [REDIRECT]}}),
    ("POST", "/mcp/acme/oauth/token", {"data": {"grant_type": "refresh_token",
                                               "refresh_token": "x", "client_id": "y"}}),
    ("POST", "/mcp/acme/oauth/revoke", {"data": {"token": "x"}}),
]


@pytest.mark.parametrize("method,path,kw", CLAUDE_FACING)
def test_cidr_refuses_outside_ip_on_claude_facing(connector_client, monkeypatch, method, path, kw):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    _env(CONNECTOR_ALLOWED_CLIENT_CIDRS=CIDR)
    with _client_from(connector_client, OUTSIDE_IP) as c:
        res = c.request(method, path, **kw)
    assert res.status_code == 403
    assert "detail" not in res.json()


@pytest.mark.parametrize("method,path,kw", CLAUDE_FACING)
def test_cidr_allows_inside_ip_on_claude_facing(connector_client, monkeypatch, method, path, kw):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    _env(CONNECTOR_ALLOWED_CLIENT_CIDRS=CIDR)
    with _client_from(connector_client, CLAUDE_IP) as c:
        res = c.request(method, path, **kw)
    assert res.status_code != 403


def test_cidr_unset_or_empty_means_no_check(connector_client):
    for v in (None, "", "  "):
        _env(**({} if v is None else {"CONNECTOR_ALLOWED_CLIENT_CIDRS": v}))
        with _client_from(connector_client, OUTSIDE_IP) as c:
            assert c.post("/mcp/acme", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401


def test_cidr_list_accepts_any_listed_range(connector_client, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    _env(CONNECTOR_ALLOWED_CLIENT_CIDRS=f"10.0.0.0/8, {CIDR}")
    with _client_from(connector_client, CLAUDE_IP) as c:
        assert c.post("/mcp/acme", json={}).status_code != 403
    with _client_from(connector_client, "10.1.2.3") as c:
        assert c.post("/mcp/acme", json={}).status_code != 403


def test_cidr_browser_endpoints_exempt(connector_client, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    _env(CONNECTOR_ALLOWED_CLIENT_CIDRS=CIDR)
    cid = registered_client(_client_from(connector_client, CLAUDE_IP))
    _, challenge = pkce_pair()
    with _client_from(connector_client, OUTSIDE_IP) as c:
        assert c.get("/.well-known/oauth-protected-resource/mcp/acme").status_code == 200
        assert c.get("/.well-known/oauth-authorization-server/mcp/acme").status_code == 200
        assert authorize(c, cid, challenge).status_code == 302
        res = c.post("/mcp/acme/oauth/consent-return", data={"request_id": "nope"},
                     follow_redirects=False)
        assert res.status_code != 403


def test_cidr_trust_on_uses_forwarded_for(connector_client, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxies", "127.0.0.1")
    _env(CONNECTOR_ALLOWED_CLIENT_CIDRS=CIDR)
    with _client_from(connector_client, "127.0.0.1") as c:
        ok = c.post("/mcp/acme", json={}, headers={"X-Forwarded-For": CLAUDE_IP})
        bad = c.post("/mcp/acme", json={}, headers={"X-Forwarded-For": OUTSIDE_IP})
    assert ok.status_code != 403
    assert bad.status_code == 403


def test_cidr_trust_off_ignores_forwarded_for(connector_client, monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    _env(CONNECTOR_ALLOWED_CLIENT_CIDRS=CIDR)
    with _client_from(connector_client, OUTSIDE_IP) as c:
        spoof = c.post("/mcp/acme", json={}, headers={"X-Forwarded-For": CLAUDE_IP})
    assert spoof.status_code == 403
    with _client_from(connector_client, CLAUDE_IP) as c:
        real = c.post("/mcp/acme", json={}, headers={"X-Forwarded-For": OUTSIDE_IP})
    assert real.status_code != 403


@pytest.mark.parametrize("bad", ["not-a-cidr", f"{CIDR},garbage", "160.79.104.0/99"])
def test_invalid_cidr_fails_closed_only_on_claude_facing(connector_client, monkeypatch, bad):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    _env(CONNECTOR_ALLOWED_CLIENT_CIDRS=bad)
    with _client_from(connector_client, CLAUDE_IP) as c:
        for method, path, kw in CLAUDE_FACING:
            assert c.request(method, path, **kw).status_code == 403, path
        # nothing else breaks
        assert c.get("/.well-known/oauth-authorization-server/mcp/acme").status_code == 200
        assert c.get("/health").status_code in (200, 404)


# ---- 3. redirect allow-list (env, already working) --------------------------------

SECOND = "https://claude.com/api/mcp/auth_callback"


def test_dcr_second_listed_redirect_accepted(connector_client):
    _env(CONNECTOR_REDIRECT_ALLOWLIST=f"{REDIRECT},{SECOND}")
    res = register(connector_client, redirect=SECOND)
    assert res.status_code in (200, 201), res.text


def test_dcr_unlisted_redirect_refused(connector_client):
    res = register(connector_client, redirect=SECOND)
    assert res.status_code == 400 and res.json()["error"] == "invalid_redirect_uri"
