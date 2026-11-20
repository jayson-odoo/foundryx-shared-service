"""Shared helpers for the connector tests (plan sprint-4/19, build design section 9).

Everything here talks to the connector ONLY through its public wire (HTTP) or the
section-9 seams (``registry.set_env_for_tests``, ``product_client.TRANSPORT``).
The product side (sorento) is emulated by ``FakeProduct``; its verifier is an
independent inline reference, never imported from sorento.
"""

import base64
import hashlib
import json
import time
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, parse_qsl, quote, urlparse

import httpx
from jose import jwt
from sqlalchemy import text

PUBLIC_BASE = "https://ss.test"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
API_BASE = "https://acme.test"
CONSENT_URL = "https://acme.test/connect/claude"
SS_TO_PRODUCT = "acme-ss-to-product-secret"
PRODUCT_TO_SS = "acme-product-to-ss-secret"
CONNECTION_ID = "conn-acme"
CONSENT_AUD = "acme-connector-consent"
CALL_AUD = "acme-connector-api"
ASSERT_ISS = "acme"

# Per-product config used by the OAuth helpers (acme/beta from make_env; gamma is
# added by the admin tests' other-tenant fixture).
PRODUCT_CFG = {
    "acme": {"consent_url": CONSENT_URL, "ss": SS_TO_PRODUCT, "p2s": PRODUCT_TO_SS,
             "conn": CONNECTION_ID},
    "beta": {"consent_url": "https://beta.test/connect/claude", "ss": "beta-ss-to-product-secret",
             "p2s": "beta-product-to-ss-secret", "conn": "conn-beta"},
    "gamma": {"consent_url": "https://gamma.test/connect/claude", "ss": "gamma-ss",
              "p2s": "gamma-p2s", "conn": "conn-gamma"},
}


def _cfg(product: str) -> dict:
    return PRODUCT_CFG[product]


SECRETS = [SS_TO_PRODUCT, PRODUCT_TO_SS, "beta-ss-to-product-secret", "beta-product-to-ss-secret"]


def make_env(extra: Optional[dict] = None, tenant_slug: str = "default") -> dict:
    env = {
        "CONNECTOR_PRODUCTS": "acme,beta",
        "CONNECTOR_REDIRECT_ALLOWLIST": REDIRECT,
        "CONNECTOR_ACME_TENANT_SLUG": tenant_slug,
        "CONNECTOR_ACME_CONNECTION_ID": CONNECTION_ID,
        "CONNECTOR_ACME_CONSENT_URL": CONSENT_URL,
        "CONNECTOR_ACME_API_BASE_URL": API_BASE,
        "CONNECTOR_ACME_SS_TO_PRODUCT_SECRET": SS_TO_PRODUCT,
        "CONNECTOR_ACME_PRODUCT_TO_SS_SECRET": PRODUCT_TO_SS,
        "CONNECTOR_BETA_TENANT_SLUG": "default",
        "CONNECTOR_BETA_CONNECTION_ID": "conn-beta",
        "CONNECTOR_BETA_CONSENT_URL": "https://beta.test/connect/claude",
        "CONNECTOR_BETA_API_BASE_URL": "https://beta.test",
        "CONNECTOR_BETA_SS_TO_PRODUCT_SECRET": "beta-ss-to-product-secret",
        "CONNECTOR_BETA_PRODUCT_TO_SS_SECRET": "beta-product-to-ss-secret",
    }
    env.update(extra or {})
    return env


# --- request_hash reference (sorento access.py:92-101, inline) -------------------


def ref_request_hash(method: str, raw_path: str, query: str, body: bytes) -> str:
    pairs = parse_qsl(query, keep_blank_values=True)
    cq = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in pairs)
    material = f"{method.upper()}\n{raw_path}\n{cq}\n{hashlib.sha256(body).hexdigest()}"
    return base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest()).rstrip(b"=").decode()


# --- PKCE ---------------------------------------------------------------------------


def pkce_pair(seed: str = "v") -> tuple[str, str]:
    verifier = (seed * 50)[:50]
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# --- raw table access (the schema is attached as ``connector`` on SQLite) ----------


def rows(factory, table: str) -> list[dict]:
    db = factory()
    try:
        res = db.execute(text(f"SELECT * FROM connector.{table}"))
        return [dict(r._mapping) for r in res]
    finally:
        db.close()


def values_of(row: dict) -> list[str]:
    return [str(v) for v in row.values() if v is not None]


def any_row_has(factory, table: str, needle: str) -> bool:
    return any(needle in values_of(r) for r in rows(factory, table))


def sql(factory, statement: str, **params) -> None:
    db = factory()
    try:
        db.execute(text(statement), params)
        db.commit()
    finally:
        db.close()


LONG_AGO = "2000-01-01 00:00:00.000000"


# --- OAuth flow helpers -----------------------------------------------------------


def register(c, product="acme", redirect=REDIRECT, name="Claude"):
    return c.post(
        f"/mcp/{product}/oauth/register",
        json={
            "client_name": name,
            "redirect_uris": [redirect],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )


def registered_client(c, product="acme", **kw) -> str:
    res = register(c, product, **kw)
    assert res.status_code in (200, 201), res.text
    return res.json()["client_id"]


def authorize(c, client_id, challenge, product="acme", state="st-1", redirect=REDIRECT,
              method="S256", **extra):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "code_challenge": challenge,
        "code_challenge_method": method,
        "state": state,
    }
    params.update(extra)
    params = {k: v for k, v in params.items() if v is not None}
    return c.get(f"/mcp/{product}/oauth/authorize", params=params, follow_redirects=False)


def consent_claims(res, secret=None, audience=None, product="acme") -> dict:
    assert res.status_code == 302, res.text
    loc = res.headers["location"]
    cfg = _cfg(product)
    assert loc.startswith(cfg["consent_url"] + "?req="), loc
    req = parse_qs(urlparse(loc).query)["req"][0]
    return jwt.decode(req, secret or cfg["ss"], algorithms=["HS256"],
                      audience=audience or f"{product}-connector-consent")


def assertion(request_id, *, sub="42", name="Test User", email="t@example.com", jti=None,
              iat=None, exp=None, secret=None, connection_id=None,
              iss=None, aud="foundryx-connector", typ="connector_assertion",
              algorithm="HS256", product="acme") -> str:
    cfg = _cfg(product)
    secret = cfg["p2s"] if secret is None else secret
    connection_id = cfg["conn"] if connection_id is None else connection_id
    iss = product if iss is None else iss
    now = int(time.time())
    iat = now if iat is None else iat
    claims = {
        "typ": typ, "iss": iss, "aud": aud, "connection_id": connection_id,
        "request_id": request_id, "sub": sub, "name": name, "email": email,
        "iat": iat, "exp": iat + 120 if exp is None else exp,
        "jti": jti or f"jti-{request_id}-{sub}",
    }
    return jwt.encode(claims, secret, algorithm=algorithm)


def consent_return(c, request_id, assertion_token=None, error=None, product="acme"):
    data = {"request_id": request_id}
    if assertion_token is not None:
        data["assertion"] = assertion_token
    if error is not None:
        data["error"] = error
    return c.post(f"/mcp/{product}/oauth/consent-return", data=data, follow_redirects=False)


def redirect_params(res) -> dict:
    assert res.status_code == 302, res.text
    loc = res.headers["location"]
    assert loc.startswith(REDIRECT + "?"), loc
    return {k: v[0] for k, v in parse_qs(urlparse(loc).query).items()}


def token_exchange(c, code, verifier, client_id, product="acme", redirect=REDIRECT):
    return c.post(
        f"/mcp/{product}/oauth/token",
        data={
            "grant_type": "authorization_code", "code": code, "code_verifier": verifier,
            "client_id": client_id, "redirect_uri": redirect,
        },
    )


def refresh(c, refresh_token, client_id, product="acme"):
    return c.post(
        f"/mcp/{product}/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id},
    )


def get_code(c, *, client_id=None, product="acme", sub="42", name="Test User", seed="v",
             state="st-1", iat=None, jti=None, exp=None):
    """DCR (unless client_id given) -> authorize -> consent-return. Returns dict."""
    client_id = client_id or registered_client(c, product)
    verifier, challenge = pkce_pair(seed)
    claims = consent_claims(authorize(c, client_id, challenge, product, state=state), product=product)
    token = assertion(claims["request_id"], sub=sub, name=name, iat=iat, exp=exp, jti=jti,
                      product=product)
    res = consent_return(c, claims["request_id"], token, product=product)
    params = redirect_params(res)
    return {"client_id": client_id, "verifier": verifier, "code": params["code"],
            "state": params.get("state"), "request_id": claims["request_id"]}


def connect(c, *, product="acme", sub="42", name="Test User", client_id=None, seed="v",
            iat=None, exp=None) -> dict:
    """Full OAuth dance; returns {access, refresh, client_id, ...}."""
    g = get_code(c, client_id=client_id, product=product, sub=sub, name=name, seed=seed, iat=iat,
                 exp=exp, jti=f"jti-{sub}-{time.time_ns()}")
    res = token_exchange(c, g["code"], g["verifier"], g["client_id"], product)
    assert res.status_code == 200, res.text
    body = res.json()
    return {**g, "access": body["access_token"], "refresh": body["refresh_token"], "body": body}


def bearer(token) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- MCP helpers -------------------------------------------------------------------


def rpc(c, token, method, params=None, *, product="acme", id=1, notification=False):
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if not notification:
        msg["id"] = id
    if params is not None:
        msg["params"] = params
    return c.post(f"/mcp/{product}", json=msg, headers=bearer(token) if token else {})


def call_tool(c, token, name, arguments=None, *, product="acme"):
    return rpc(c, token, "tools/call", {"name": name, "arguments": arguments or {}}, product=product)


def tool_text(res) -> str:
    body = res.json()
    return body["result"]["content"][0]["text"]


def is_tool_error(res) -> bool:
    return res.status_code == 200 and bool(res.json().get("result", {}).get("isError"))


# --- admin helpers -----------------------------------------------------------------


def admin_headers(c, email="demo@example.com", password="demo1234", tenant_slug=None) -> dict:
    payload = {"email": email, "password": password}
    if tenant_slug:
        payload["tenantSlug"] = tenant_slug
    res = c.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def list_grants(c, h, **params):
    res = c.get("/connector/grants", params=params, headers=h)
    assert res.status_code == 200, res.text
    return res.json()


def grant_ids(c, h, **params) -> list[str]:
    return [g["id"] for g in list_grants(c, h, **params)["data"]]


# --- the emulated product ----------------------------------------------------------


def default_manifest() -> dict:
    ro = {"readOnlyHint": True, "destructiveHint": False}
    return {
        "version": "v1",
        "tools": [
            {
                "name": "stock_list", "title": "Stock list", "description": "List stock.",
                "input_schema": {
                    "type": "object",
                    "properties": {"limit": {"type": "string"}, "search": {"type": "string"}},
                    "additionalProperties": False,
                },
                "annotations": ro,
                "http": {"method": "GET", "path_template": "/api/v1/stock/",
                         "query_params": ["limit", "search"], "path_params": []},
            },
            {
                "name": "item_get", "title": "Item", "description": "One item.",
                "input_schema": {
                    "type": "object",
                    "properties": {"item_code": {"type": "string"}, "expand": {"type": "string"}},
                    "required": ["item_code"],
                    "additionalProperties": False,
                },
                "annotations": ro,
                "http": {"method": "GET", "path_template": "/api/v1/items/{item_code}/detail",
                         "query_params": ["expand"], "path_params": ["item_code"]},
            },
            {
                "name": "chat_query", "title": "Chat query", "description": "Aggregate chats.",
                "input_schema": {
                    "type": "object",
                    "properties": {"set_key": {"type": "string"}, "group_by": {"type": "string"}},
                    "required": ["set_key"],
                    "additionalProperties": False,
                },
                "annotations": ro,
                "http": {"method": "POST", "path_template": "/api/v1/connector/query",
                         "query_params": [], "path_params": []},
            },
            {
                "name": "write_thing", "title": "Write", "description": "Mutates.",
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
                "annotations": {"readOnlyHint": False, "destructiveHint": False},
                "http": {"method": "POST", "path_template": "/api/v1/things/", "query_params": [],
                         "path_params": []},
            },
            {
                "name": "risky_read", "title": "Risky", "description": "Destructive flag.",
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
                "annotations": {"readOnlyHint": True, "destructiveHint": True},
                "http": {"method": "GET", "path_template": "/api/v1/risky/", "query_params": [],
                         "path_params": []},
            },
        ],
    }


VISIBLE_TOOLS = ["stock_list", "item_get", "chat_query"]
MANIFEST_PATH = "/api/v1/connector/manifest"


class FakeProduct:
    """Emulates the sorento connector API. Verifies every call JWT with an INLINE
    reference verifier and records what it saw."""

    def __init__(self, secret: str = SS_TO_PRODUCT, audience: str = CALL_AUD,
                 connection_id: str = CONNECTION_ID):
        self.secret, self.audience, self.connection_id = secret, audience, connection_id
        self.manifest = default_manifest()
        self.manifest_error: Optional[Callable[[httpx.Request], httpx.Response]] = None
        self.responder: Optional[Callable[[httpx.Request, dict], httpx.Response]] = None
        self.calls: list[dict] = []          # tool (non-manifest) requests
        self.manifest_calls: list[dict] = []
        self.invalid: list[str] = []         # reasons a request failed reference verification

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        raw = request.url.raw_path.decode()
        path, _, query = raw.partition("?")
        body = request.content or b""
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme != "Connector" or not token:
            self.invalid.append("no Connector authorization header")
            return httpx.Response(401, json={"error": {"code": "invalid_signature", "message": "no"}})
        try:
            claims = jwt.decode(token, self.secret, algorithms=["HS256"], audience=self.audience,
                                issuer="foundryx-ss", options={"leeway": 5})
        except Exception as exc:  # noqa: BLE001 - any failure is a verification failure
            self.invalid.append(f"jwt: {exc}")
            return httpx.Response(401, json={"error": {"code": "invalid_signature", "message": "bad"}})
        problems = []
        if claims.get("typ") != "connector_call":
            problems.append("typ")
        if claims.get("connection_id") != self.connection_id:
            problems.append("connection_id")
        if claims["exp"] - claims["iat"] > 60:
            problems.append("lifetime")
        if claims.get("req_hash") != ref_request_hash(request.method, path, query, body):
            problems.append("req_hash")
        for k in ("sub", "grant_id", "consented_at", "tool", "jti"):
            if k not in claims:
                problems.append(f"missing {k}")
        if not isinstance(claims.get("consented_at"), int):
            problems.append("consented_at type")
        if problems:
            self.invalid.append(",".join(problems))
            return httpx.Response(401, json={"error": {"code": "invalid_signature", "message": "bad"}})
        rec = {"method": request.method, "path": path, "query": query, "body": body,
               "claims": claims, "url": str(request.url), "headers": dict(request.headers)}
        if path == MANIFEST_PATH:
            self.manifest_calls.append(rec)
            if self.manifest_error:
                return self.manifest_error(request)
            return httpx.Response(200, json=self.manifest)
        self.calls.append(rec)
        if self.responder:
            return self.responder(request, claims)
        return httpx.Response(200, json={"rows": [{"id": 1}], "marker": "PRODUCT-DATA"})


def err_response(status: int, code: str, message: str = "Plain words.") -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


def seed_user_with_perms(factory, email: str, perm_keys: list[str], password="Passw0rd!x") -> None:
    from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
    from app.models.permission import Permission
    from app.security import hash_password

    db = factory()
    try:
        role = Role(tenant_id=DEFAULT_TENANT_ID, name=f"role-{email}", description="t")
        role.permissions = (
            db.query(Permission).filter(Permission.key.in_(perm_keys)).all() if perm_keys else []
        )
        db.add(role)
        db.flush()
        user = User(tenant_id=DEFAULT_TENANT_ID, email=email, password=hash_password(password),
                    name=email.split("@")[0], status=UserStatus.ACTIVE.value)
        user.roles = [role]
        db.add(user)
        db.commit()
    finally:
        db.close()


def json_args_text(res) -> Any:
    return json.loads(tool_text(res))
