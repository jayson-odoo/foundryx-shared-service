"""Issue #118 / BL-SS-303: X-Forwarded-For is trusted only from configured proxies.

`client_ip` used to return the FIRST X-Forwarded-For hop whenever
`trust_proxy_headers` was on, so any caller could forge
`X-Forwarded-For: 160.79.105.9` and pass the Claude connector allowlist, or
rotate the header to mint fresh rate-limit buckets. The resolver now walks the
chain right-to-left from the socket peer and returns the first hop that is NOT
a trusted proxy (`trusted_proxies`, empty = trust nobody).
"""

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import settings
from app.main import app
from app.services.throttle import client_ip
from modules.connector import registry
from tests.connector_support import make_env

CLAUDE_IP = "160.79.105.9"
OUTSIDE_IP = "203.0.113.5"
CIDR = "160.79.104.0/21"
PROXY = "172.18.0.1"


def _req(peer, xff=None):
    headers = [] if xff is None else [(b"x-forwarded-for", xff.encode())]
    return Request({"type": "http", "client": (peer, 5000) if peer else None,
                    "headers": headers, "method": "GET", "path": "/"})


@pytest.fixture
def trusting(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxies", "127.0.0.1, 172.16.0.0/12")


# ---- unit: the resolver --------------------------------------------------------


def test_default_trusts_no_proxy_even_with_flag_on(monkeypatch):
    """The flag alone is not enough: an empty trusted set = socket peer."""
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxies", "")
    assert client_ip(_req("127.0.0.1", CLAUDE_IP)) == "127.0.0.1"


def test_flag_off_ignores_forwarded_for(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    monkeypatch.setattr(settings, "trusted_proxies", "127.0.0.1")
    assert client_ip(_req("127.0.0.1", CLAUDE_IP)) == "127.0.0.1"


def test_untrusted_peer_header_ignored(trusting):
    assert client_ip(_req(OUTSIDE_IP, CLAUDE_IP)) == OUTSIDE_IP


def test_forged_leftmost_hop_is_skipped(trusting):
    """A proxy that APPENDS (cloudflared, Caddy with trusted_proxies, nginx
    $proxy_add_x_forwarded_for) leaves the client's forged value on the left."""
    assert client_ip(_req("127.0.0.1", f"{CLAUDE_IP}, {OUTSIDE_IP}")) == OUTSIDE_IP


def test_real_client_behind_proxy_chain(trusting):
    assert client_ip(_req(PROXY, f"{OUTSIDE_IP}, 127.0.0.1")) == OUTSIDE_IP
    assert client_ip(_req(PROXY, OUTSIDE_IP)) == OUTSIDE_IP


def test_all_hops_trusted_returns_leftmost(trusting):
    assert client_ip(_req("127.0.0.1", "172.20.0.5, 172.18.0.1")) == "172.20.0.5"


def test_garbage_hop_never_becomes_the_key(trusting):
    """An unparsable hop can only come from the client side of the chain - stop
    at the last address a trusted proxy vouched for, never return the junk."""
    assert client_ip(_req("127.0.0.1", "not-an-ip")) == "127.0.0.1"
    assert client_ip(_req(PROXY, "zzz, 127.0.0.1")) == "127.0.0.1"


def test_empty_header_and_missing_peer(trusting):
    assert client_ip(_req("127.0.0.1", " , ")) == "127.0.0.1"
    assert client_ip(_req(None, CLAUDE_IP)) == "unknown"


def test_invalid_trusted_entry_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxies", "127.0.0.1, garbage")
    assert client_ip(_req("127.0.0.1", CLAUDE_IP)) == "127.0.0.1"


def test_ipv6_peer_and_hops(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxies", "::1")
    assert client_ip(_req("::1", f"{CLAUDE_IP}, 2001:db8::7")) == "2001:db8::7"


# ---- endpoint: the connector allowlist ----------------------------------------


def _from(ip):
    return TestClient(app, base_url="https://testserver", client=(ip, 50000))


def test_forged_xff_does_not_pass_connector_allowlist(connector_client, trusting):
    registry.set_env_for_tests(make_env({"CONNECTOR_ALLOWED_CLIENT_CIDRS": CIDR}))
    # Direct (untrusted) caller forging the header.
    with _from(OUTSIDE_IP) as c:
        assert c.post("/mcp/acme", json={}, headers={"X-Forwarded-For": CLAUDE_IP}).status_code == 403
    # Through an appending proxy: the forged value sits left of the real hop.
    with _from("127.0.0.1") as c:
        res = c.post("/mcp/acme", json={},
                     headers={"X-Forwarded-For": f"{CLAUDE_IP}, {OUTSIDE_IP}"})
    assert res.status_code == 403


def test_real_proxied_claude_ip_passes_allowlist(connector_client, trusting):
    registry.set_env_for_tests(make_env({"CONNECTOR_ALLOWED_CLIENT_CIDRS": CIDR}))
    with _from(PROXY) as c:
        res = c.post("/mcp/acme", json={}, headers={"X-Forwarded-For": f"{OUTSIDE_IP}, {CLAUDE_IP}"})
    assert res.status_code != 403


# ---- endpoint: the login rate limit -------------------------------------------


def test_rotating_forged_xff_does_not_reset_login_throttle(session_factory, monkeypatch, trusting):
    from app.database import get_db

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "throttle_ip_max_fails", 2)
    try:
        with _from("127.0.0.1") as c:
            for i in range(3):
                res = c.post("/auth/login",
                             json={"email": f"u{i}@example.com", "password": "definitely-wrong"},
                             headers={"X-Forwarded-For": f"10.9.9.{i}, {OUTSIDE_IP}"})
            assert res.status_code == 429
    finally:
        app.dependency_overrides.pop(get_db, None)
