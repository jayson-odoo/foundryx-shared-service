"""Connector OAuth discovery under a path-prefixed public base URL (lane SS-CONNECTOR-PREFIX).

Prod serves the backend under ``https://<host>/be`` (Caddy ``handle_path /be/*``
strips the prefix, scripts/blue_green_deploy.sh), so the connector's public base
URL is ``https://<host>/be`` and the MCP resource is ``https://<host>/be/mcp/<p>``.

An MCP OAuth client (the MCP TypeScript SDK ``client/auth.js``, MCP spec
2025-06-18 / 2025-11-25) then requests:

1. ``POST <mcp url>`` with no token -> 401 ``WWW-Authenticate: Bearer resource_metadata="..."``
2. protected-resource metadata: the header URL; without one, the RFC 9728
   path-inserted URL ``https://<host>/.well-known/oauth-protected-resource/be/mcp/<p>``
3. authorization-server metadata for issuer ``https://<host>/be/mcp/<p>``, RFC 8414
   path insertion first: ``https://<host>/.well-known/oauth-authorization-server/be/mcp/<p>``
4. the endpoints that metadata names.

Steps 2 (no-header form) and 3 hit ``/.well-known/...`` at the host ROOT, outside
``/be/*``. Caddy must forward them to the backend unstripped, and the backend must
serve the prefixed form. ``_through_caddy`` below mirrors the fragment the deploy
script writes; ``test_deploy_script_routes_prefixed_well_known_to_backend`` pins
that the script really writes that route.
"""

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import pytest

from modules.connector import registry
from tests.connector_support import (
    admin_headers,
    authorize,
    consent_claims,
    make_env,
    pkce_pair,
    registered_client,
)

HOST = "https://ss.test"
PREFIX = "/be"
BASE = HOST + PREFIX
MCP = f"{BASE}/mcp/acme"
DEPLOY_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "blue_green_deploy.sh"


def _env(base: str = BASE) -> None:
    registry.set_env_for_tests(make_env({"CONNECTOR_PUBLIC_BASE_URL": base}))


def _through_caddy(url: str, prefix: str = PREFIX) -> Optional[str]:
    """The backend path Caddy hands over for a public URL, or None (frontend = 404).

    Mirrors the deploy fragment: the prefixed well-known passthrough (unstripped),
    then ``handle_path <prefix>/*`` (stripped), then the frontend catch-all."""
    u = urlparse(url)
    assert u.scheme + "://" + u.netloc == HOST, url
    path = u.path
    for kind in ("oauth-authorization-server", "oauth-protected-resource"):
        if path.startswith(f"/.well-known/{kind}{prefix}/"):
            return path
    if path.startswith(prefix + "/"):
        return path[len(prefix):]
    return None


def _get(c, url: str):
    path = _through_caddy(url)
    assert path is not None, f"{url} would hit the frontend (404) in prod"
    return c.get(path)


@pytest.fixture
def prefixed(connector_client):
    _env()
    return connector_client


# --- the discovery walk an MCP client does --------------------------------------------


def test_header_resource_metadata_url_resolves_through_the_prefix(prefixed):
    res = prefixed.post(_through_caddy(MCP), json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert res.status_code == 401
    m = re.fullmatch(r'Bearer resource_metadata="([^"]+)"', res.headers["www-authenticate"])
    assert m, res.headers["www-authenticate"]
    assert m.group(1).startswith(BASE + "/")
    doc = _get(prefixed, m.group(1))
    assert doc.status_code == 200, doc.text
    assert doc.json()["resource"] == MCP
    assert doc.json()["authorization_servers"] == [MCP]


def test_rfc9728_path_inserted_protected_resource_metadata(prefixed):
    url = f"{HOST}/.well-known/oauth-protected-resource{PREFIX}/mcp/acme"
    res = _get(prefixed, url)
    assert res.status_code == 200, res.text
    assert res.json() == {"resource": MCP, "authorization_servers": [MCP],
                          "bearer_methods_supported": ["header"]}


def test_rfc8414_path_inserted_authorization_server_metadata(prefixed):
    issuer = _get(prefixed, f"{HOST}/.well-known/oauth-protected-resource{PREFIX}/mcp/acme"
                  ).json()["authorization_servers"][0]
    # RFC 8414 s3.1: insert the well-known segment between host and the issuer's path
    url = f"{HOST}/.well-known/oauth-authorization-server{urlparse(issuer).path}"
    assert url == f"{HOST}/.well-known/oauth-authorization-server/be/mcp/acme"
    res = _get(prefixed, url)
    assert res.status_code == 200, res.text
    doc = res.json()
    assert doc["issuer"] == issuer == MCP  # RFC 8414 s3.3 issuer must match
    for k, p in [("authorization_endpoint", "authorize"), ("token_endpoint", "token"),
                 ("registration_endpoint", "register"), ("revocation_endpoint", "revoke")]:
        assert doc[k] == f"{MCP}/oauth/{p}"
        assert _through_caddy(doc[k]) == f"/mcp/acme/oauth/{p}"


@pytest.mark.parametrize("kind", ["oauth-authorization-server", "oauth-protected-resource"])
def test_unprefixed_well_known_still_served(prefixed, kind):
    """The header form (<base>/.well-known/...) reaches the backend stripped."""
    res = prefixed.get(f"/.well-known/{kind}/mcp/acme")
    assert res.status_code == 200
    assert MCP in res.text


@pytest.mark.parametrize("kind", ["oauth-authorization-server", "oauth-protected-resource"])
def test_nested_prefix(connector_client, kind):
    _env(HOST + "/a/b")
    res = connector_client.get(f"/.well-known/{kind}/a/b/mcp/acme")
    assert res.status_code == 200, res.text
    assert f"{HOST}/a/b/mcp/acme" in res.text


# --- the prefix must be the configured one, nothing else -------------------------------


@pytest.mark.parametrize("kind", ["oauth-authorization-server", "oauth-protected-resource"])
@pytest.mark.parametrize("path", ["/other/mcp/acme", "/be/x/mcp/acme", "/b/mcp/acme",
                                  "/be/mcp/nope", "/be/mcp/acme/extra"])
def test_wrong_prefix_or_product_is_uniform_404(prefixed, kind, path):
    assert prefixed.get(f"/.well-known/{kind}{path}").status_code == 404


@pytest.mark.parametrize("kind", ["oauth-authorization-server", "oauth-protected-resource"])
def test_prefixed_form_404_when_base_has_no_prefix(connector_client, kind):
    _env(HOST)
    assert connector_client.get(f"/.well-known/{kind}/be/mcp/acme").status_code == 404
    assert connector_client.get(f"/.well-known/{kind}/mcp/acme").status_code == 200


@pytest.mark.parametrize("kind", ["oauth-authorization-server", "oauth-protected-resource"])
def test_prefixed_form_non_get_is_405(prefixed, kind):
    res = prefixed.post(f"/.well-known/{kind}/be/mcp/acme")
    assert res.status_code == 405
    assert res.headers["allow"] == "GET"


# --- every other URL the connector emits carries the prefix ----------------------------


def test_consent_return_url_and_binding_cookie_path_carry_prefix(prefixed):
    cid = registered_client(prefixed)
    _, challenge = pkce_pair()
    res = authorize(prefixed, cid, challenge)
    claims = consent_claims(res)
    assert claims["return_url"] == f"{MCP}/oauth/consent-return"
    assert _through_caddy(claims["return_url"]) == "/mcp/acme/oauth/consent-return"
    cookie = res.headers["set-cookie"]
    # the browser sees /be/mcp/acme/oauth/consent-return, so the cookie path must too
    assert "Path=/be/mcp/acme/oauth" in cookie, cookie


def test_admin_mcp_url_carries_prefix(prefixed):
    h = admin_headers(prefixed)
    res = prefixed.get("/connector/products", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    items = body["data"] if isinstance(body, dict) else body
    assert {p["key"]: p["mcpUrl"] for p in items}["acme"] == MCP


# --- deploy: Caddy forwards the root-level prefixed well-known paths -------------------


def test_deploy_script_routes_prefixed_well_known_to_backend():
    script = DEPLOY_SCRIPT.read_text()
    m = re.search(r"@connector_wellknown path (.+)\n", script)
    assert m, "deploy fragment lacks the connector well-known matcher"
    assert set(m.group(1).split()) == {
        "/.well-known/oauth-authorization-server${BACKEND_PATH}/*",
        "/.well-known/oauth-protected-resource${BACKEND_PATH}/*",
    }
    block = re.search(r"handle @connector_wellknown \{\n\s*reverse_proxy 127\.0\.0\.1:\$\{NEW_BE_PORT\}",
                      script)
    assert block, "matcher must proxy to the backend (unstripped, plain handle)"
    assert block.start() < script.index("handle_path ${BACKEND_PATH}/*")
    assert block.start() < script.index("\thandle {\n")
