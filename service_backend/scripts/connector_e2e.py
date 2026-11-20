#!/usr/bin/env python3
"""Automated end-to-end client for the Claude connector (plan sprint-4/19).

Does exactly what claude.ai does against a shared-service (SS) copy and a product
(sorento) copy: 401 discovery, DCR, PKCE authorize, consent bounce through the
product, token exchange, MCP initialize/tools/list/tools/call, refresh rotation,
RFC 7009 revoke, plus the lifecycle fault-injection steps. Prints one
PASS/FAIL/DEFERRED line per step; exits non-zero on any FAIL.

stdlib + httpx only. psql (CLI) is used for the optional DB assertions.
Runbook: documentation/plans/sprint-4/19-claude-connector-e2e-runbook.md

Environment
  SS_BASE                 SS backend origin            (default http://localhost:8031)
  SS_PRODUCT              product key in SS            (default sorento)
  SORENTO_API             product backend origin       (default http://localhost:8032)
  SORENTO_WEB             product frontend origin      (default http://localhost:3032)
  SORENTO_LOGIN_EMAIL / SORENTO_LOGIN_PASSWORD   an ACTIVE user holding analytics.connector.use
  CONSENT_MODE            browser | api                (default browser)
  SS_DB_URL               SS Postgres URL, SUPERUSER (steps 12, 15, 16, row evidence)
  SS_APP_ROLE             SS application DB role       (default foundryx)
  SORENTO_DB_URL          product Postgres URL         (step 9 evidence, 14, 16)
  EXPECT_TOOLS            expected tool count          (default 39)
  RBAC_WAIT               seconds to wait out the product RBAC cache (default 35)
Never point this at production: steps 12/14/15 change the given databases.
Remote hosts are refused (exit 2) unless E2E_ALLOW_REMOTE=1.
Nothing secret is printed: tokens, codes, the email and the password never reach stdout.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.parse as up
from typing import Any, Callable, Optional

import httpx

SS = os.environ.get("SS_BASE", "http://localhost:8031").rstrip("/")
PRODUCT = os.environ.get("SS_PRODUCT", "sorento")
SO_API = os.environ.get("SORENTO_API", "http://localhost:8032").rstrip("/")
SO_WEB = os.environ.get("SORENTO_WEB", "http://localhost:3032").rstrip("/")
EMAIL = os.environ.get("SORENTO_LOGIN_EMAIL", "")
PASSWORD = os.environ.get("SORENTO_LOGIN_PASSWORD", "")
MODE = os.environ.get("CONSENT_MODE", "browser").lower()
SS_DB = os.environ.get("SS_DB_URL", "")
SO_DB = os.environ.get("SORENTO_DB_URL", "")
APP_ROLE = os.environ.get("SS_APP_ROLE", "foundryx")
EXPECT_TOOLS = int(os.environ.get("EXPECT_TOOLS", "39"))
RBAC_WAIT = int(os.environ.get("RBAC_WAIT", "35"))
CLAUDE_CB = "https://claude.ai/api/mcp/auth_callback"
BROWSER_SESSION = f"connector-e2e-{int(time.time())}"
CHAT_TOOLS = ["chat_list_datasets", "chat_describe_dataset", "chat_query", "chat_search_messages"]
RUN_STARTED = time.time()

http = httpx.Client(timeout=90, follow_redirects=False)
results: list[tuple[str, str]] = []
ctx: dict[str, Any] = {}


class Deferred(Exception):
    pass


def step(sid: str, name: str, fn: Callable[[], str]) -> bool:
    try:
        detail = fn()
        results.append((sid, "PASS"))
        print(f"PASS {sid} {name}: {detail}", flush=True)
        return True
    except Deferred as e:
        results.append((sid, "DEFERRED"))
        print(f"DEFERRED {sid} {name}: {e}", flush=True)
    except AssertionError as e:
        results.append((sid, "FAIL"))
        print(f"FAIL {sid} {name}: {e}", flush=True)
    except Exception as e:  # noqa: BLE001
        results.append((sid, "FAIL"))
        print(f"FAIL {sid} {name}: {type(e).__name__}: {str(e)[:300]}", flush=True)
    return False


# ---------------------------------------------------------------- helpers
def psql(url: str, sql: str) -> str:
    out = subprocess.run(["psql", url, "-v", "ON_ERROR_STOP=1", "-At", "-F", "|", "-c", sql],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"psql failed: {out.stderr.strip()[:200]}")
    return out.stdout.strip()


def b64u_sha256(s: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(s.encode()).digest()).rstrip(b"=").decode()


def rpc(method: str, params: Optional[dict] = None, *, token: Optional[str] = None,
        rid: int = 1) -> httpx.Response:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return http.post(ctx["mcp_url"], json=body,
                     headers={"Authorization": "Bearer " + (token or ctx["access"])})


def call(name: str, args: Optional[dict] = None, *, token: Optional[str] = None) -> tuple[int, dict, str]:
    """-> (http status, result dict, text). Empty text on transport/protocol error."""
    r = rpc("tools/call", {"name": name, "arguments": args or {}}, token=token, rid=7)
    if r.status_code != 200:
        return r.status_code, {}, ""
    j = r.json()
    res = j.get("result") or {}
    txt = (res.get("content") or [{}])[0].get("text", "") if res else json.dumps(j.get("error", {}))
    return r.status_code, res, txt


def product_login() -> dict:
    r = http.post(f"{SO_API}/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"product login {r.status_code}"
    j = r.json()
    tok = j.get("token") or j.get("access_token")
    assert tok, "product login returned no token"
    return {"token": tok, "id": j.get("id"), "role_ids": j.get("role_ids") or []}


def new_pkce() -> tuple[str, str]:
    ver = secrets.token_urlsafe(48)
    return ver, b64u_sha256(ver)


def authorize_params(chal: str, state: str) -> dict:
    return {"response_type": "code", "client_id": ctx["client_id"], "redirect_uri": CLAUDE_CB,
            "code_challenge": chal, "code_challenge_method": "S256", "state": state,
            "resource": ctx["resource"]}


def grant_row() -> str:
    if not SS_DB:
        return ""
    return psql(SS_DB, "select status||'|'||coalesce(revoked_reason,'') from app_connector.grants "
                       f"where id='{ctx['grant_id']}'") if ctx.get("grant_id") else ""


def find_grant_id() -> Optional[str]:
    if not SS_DB or not ctx.get("user_id"):
        return None
    gid = psql(SS_DB, "select id from app_connector.grants where product_user_id="
                      f"'{ctx['user_id']}' and client_id='{ctx['client_id']}' order by created_at desc limit 1")
    return gid or None


# ------------------------------------------------------- consent: api mode
def consent_api(state: str, chal: str) -> str:
    """Python stand-in for the browser: authorize, product approve, form POST. -> code"""
    r = http.get(ctx["authorization_endpoint"], params=authorize_params(chal, state))
    assert r.status_code == 302, f"authorize {r.status_code}"
    loc = r.headers["location"]
    assert loc.startswith(f"{SO_WEB}/connect/claude"), "consent redirect target"
    req = dict(up.parse_qsl(up.urlparse(loc).query))["req"]
    bind = ""
    for h in r.headers.get_list("set-cookie"):
        if h.startswith("fx_connector_bind="):
            bind = h.split("=", 1)[1].split(";")[0]
    assert bind, "binding cookie not set"
    pl = product_login()
    H = {"Authorization": "Bearer " + pl["token"]}
    ins = http.post(f"{SO_API}/api/v1/connector/consent/inspect", json={"req": req}, headers=H)
    assert ins.status_code == 200 and ins.json().get("allowed") is True, "consent inspect not allowed"
    ap = http.post(f"{SO_API}/api/v1/connector/consent/approve", json={"req": req}, headers=H)
    assert ap.status_code == 200, f"approve {ap.status_code}"
    aj = ap.json()
    back = http.post(aj["return_url"], data={"request_id": aj["request_id"], "assertion": aj["assertion"]},
                     cookies={"fx_connector_bind": bind})
    assert back.status_code == 302 and back.headers["location"].startswith(CLAUDE_CB), \
        f"consent-return {back.status_code}"
    q = dict(up.parse_qsl(up.urlparse(back.headers["location"]).query))
    assert q.get("state") == state and q.get("code"), "callback missing code/state echo"
    return q["code"]


# ----------------------------------------------------- consent: browser mode
def ab(*args: str, check: bool = True) -> str:
    p = subprocess.run(["agent-browser", "--session", BROWSER_SESSION, *args],
                       capture_output=True, text=True, timeout=90)
    if check and p.returncode != 0:
        raise RuntimeError(f"agent-browser {args[0]} failed: {(p.stdout + p.stderr).strip()[:200]}")
    return p.stdout


def ref_for(snapshot: str, role: str, name: str) -> Optional[str]:
    m = re.search(rf'{role} "{re.escape(name)}"[^\n]*?ref=(e\d+)', snapshot)
    return m.group(1) if m else None


def consent_browser(state: str, chal: str) -> str:
    """Drive the REAL product consent page. The browser starts at the SS authorize URL so
    the SS binding cookie is set in its jar exactly as for claude.ai. -> code"""
    url = ctx["authorization_endpoint"] + "?" + up.urlencode(authorize_params(chal, state))
    ab("open", url)
    deadline = time.time() + 60
    signed_in_form = False
    allow_clicked = False
    while time.time() < deadline:
        cur = ab("get", "url").strip()
        if "/signin" in cur and not signed_in_form:
            snap = ab("snapshot", "-i")
            e, p, b = (ref_for(snap, "textbox", "Email"), ref_for(snap, "textbox", "Your password"),
                       ref_for(snap, "button", "Continue"))
            if e and p and b:
                ab("fill", "@" + e, EMAIL)
                ab("fill", "@" + p, PASSWORD)
                ab("click", "@" + b)
                signed_in_form = True
            time.sleep(1)
            continue
        if "/connect/claude" in cur and not allow_clicked:
            snap = ab("snapshot", "-i")
            if ref_for(snap, "button", "Allow"):
                body = ab("get", "text", "body").lower()
                assert "claude" in body, "consent page does not name the client"
                ab("network", "route", "https://claude.ai/**", "--abort", check=False)
                ab("find", "role", "button", "click", "--name", "Allow")
                allow_clicked = True
        if allow_clicked:
            reqs = ab("network", "requests", "--filter", "auth_callback", check=False)
            m = re.search(r"auth_callback\?([^\s]+)", reqs)
            if m:
                q = dict(up.parse_qsl(m.group(1)))
                assert q.get("state") == state and q.get("code"), "callback missing code/state echo"
                return q["code"]
        time.sleep(1)
    raise AssertionError("browser consent did not reach the claude.ai callback in 60s")


def do_consent(mode: str) -> tuple[str, str]:
    ver, chal = new_pkce()
    state = "st" + secrets.token_hex(6)
    code = consent_browser(state, chal) if mode == "browser" else consent_api(state, chal)
    return code, ver


def exchange(code: str, ver: str) -> dict:
    r = http.post(ctx["token_endpoint"], data={"grant_type": "authorization_code", "code": code,
                  "code_verifier": ver, "client_id": ctx["client_id"], "redirect_uri": CLAUDE_CB})
    assert r.status_code == 200, f"token exchange {r.status_code}"
    return r.json()


def reconnect(label: str) -> None:
    """Fresh grant through the api consent path (documented; browser proof is step 4)."""
    code, ver = do_consent("api")
    t = exchange(code, ver)
    ctx["access"], ctx["refresh"] = t["access_token"], t["refresh_token"]
    ctx["grant_id"] = find_grant_id() or ctx.get("grant_id")


# ------------------------------------------------------------------ steps
def s1() -> str:
    mcp = f"{SS}/mcp/{PRODUCT}"
    r = http.post(mcp, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401, f"got {r.status_code}"
    wa = r.headers.get("www-authenticate", "")
    m = re.search(r'resource_metadata="([^"]+)"', wa)
    assert m, "WWW-Authenticate lacks resource_metadata"
    pr = http.get(m.group(1))
    assert pr.status_code == 200, f"protected-resource metadata {pr.status_code}"
    prj = pr.json()
    ctx["resource"] = prj["resource"]
    ctx["mcp_url"] = prj["resource"]
    issuer = prj["authorization_servers"][0]
    u = up.urlparse(issuer)
    az_url = f"{u.scheme}://{u.netloc}/.well-known/oauth-authorization-server{u.path}"
    az = http.get(az_url)
    assert az.status_code == 200, f"authorization-server metadata {az.status_code}"
    meta = az.json()
    for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"):
        assert meta.get(k), f"AS metadata lacks {k}"
        ctx[k] = meta[k]
    assert "S256" in meta.get("code_challenge_methods_supported", []), "S256 not advertised"
    return "401 + resource_metadata; discovered protected-resource and AS metadata; endpoints taken from metadata only"


def s2() -> str:
    r = http.post(ctx["registration_endpoint"], json={
        "client_name": "connector-e2e", "redirect_uris": [CLAUDE_CB],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]})
    assert r.status_code in (200, 201), f"DCR {r.status_code}"
    ctx["client_id"] = r.json()["client_id"]
    return f"{r.status_code} client_id issued"


def s3() -> str:
    ver, chal = new_pkce()
    r = http.get(ctx["authorization_endpoint"], params=authorize_params(chal, "s3" + secrets.token_hex(4)))
    assert r.status_code == 302, f"authorize {r.status_code}"
    loc = r.headers["location"]
    assert loc.startswith(f"{SO_WEB}/connect/claude?req="), "redirect is not the product consent page"
    return "302 to product /connect/claude?req= (PKCE S256 + state + resource accepted)"


def s4() -> str:
    pl = product_login()
    ctx["user_id"], ctx["role_ids"] = pl["id"], pl["role_ids"]
    mode = MODE
    if mode == "browser":
        try:
            subprocess.run(["agent-browser", "--version"], capture_output=True, check=True, timeout=20)
        except Exception:  # noqa: BLE001
            raise AssertionError("agent-browser not available for CONSENT_MODE=browser")
    try:
        code, ver = do_consent(mode)
    finally:
        if mode == "browser":
            ab("close", check=False)
    ctx["code"], ctx["ver"] = code, ver
    return f"{mode} mode: consent completed, claude.ai callback URL carried code and echoed state"


def s5() -> str:
    t = exchange(ctx["code"], ctx["ver"])
    assert t.get("token_type", "").lower() == "bearer", "token_type"
    assert t.get("access_token") and t.get("refresh_token"), "missing tokens"
    ctx["access"], ctx["refresh"] = t["access_token"], t["refresh_token"]
    ctx["grant_id"] = find_grant_id()
    return f"200, bearer, expires_in={t.get('expires_in')}, access+refresh issued"


def s6() -> str:
    r = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "connector-e2e", "version": "1"}})
    assert r.status_code == 200 and "result" in r.json(), f"initialize {r.status_code}"
    http.post(ctx["mcp_url"], json={"jsonrpc": "2.0", "method": "notifications/initialized"},
              headers={"Authorization": "Bearer " + ctx["access"]})
    r = rpc("tools/list", {})
    tools = r.json()["result"]["tools"]
    names = [t["name"] for t in tools]
    assert len(tools) == EXPECT_TOOLS, f"{len(tools)} tools, expected {EXPECT_TOOLS}"
    bad = [t["name"] for t in tools if (t.get("annotations") or {}).get("readOnlyHint") is not True
           or (t.get("annotations") or {}).get("destructiveHint") not in (False, None)]
    assert not bad, f"not read-only: {bad[:3]}"
    assert all(c in names for c in CHAT_TOOLS), "chat tools missing"
    ctx["tools"] = {t["name"]: t for t in tools}
    return f"{len(tools)} tools, all readOnlyHint=true, chat tools present"


OUTPUTS: list[tuple[str, str]] = []  # (tool, text) for the step-9 scan


def s7() -> str:
    done = []

    def ok(name: str, args: dict) -> str:
        st, res, txt = call(name, args)
        assert st == 200 and not res.get("isError") and txt, f"{name}: http {st} isError={res.get('isError')}"
        OUTPUTS.append((name, txt))
        done.append(name)
        return txt

    for n, a in (("crm_master_brands_list", {"limit": "5"}), ("crm_master_customers_list", {"limit": "5"}),
                 ("crm_inventory_warehouses_list", {})):
        ok(n, a)
    t = json.loads(ok("chat_list_datasets", {}))
    assert t["datasets"], "no datasets"
    d = json.loads(ok("chat_describe_dataset", {"key": "messages"}))
    assert d.get("columns"), "describe returned no columns"
    q = json.loads(ok("chat_query", {"dataset": "messages", "limit": 50}))
    assert q.get("rows"), "chat_query returned no rows"
    s = json.loads(ok("chat_search_messages", {"text": "verification code", "limit": 100}))
    ctx["search_rows"] = s.get("rows", [])
    return f"{len(done)} calls ok: {', '.join(done)}"


def s8() -> str:
    st, res, txt = call("crm_master_products_list", {"limit": "1000"})
    assert st == 200 and not res.get("isError"), "call failed"
    doc = json.loads(txt)
    assert doc.get("truncated") is True and doc.get("originalChars", 0) > 120_000, \
        "no truncation marker on an oversize result"
    assert len(txt) <= 124_500, f"truncated output still {len(txt)} chars"
    OUTPUTS.append(("crm_master_products_list", txt))
    note = ""
    # row cap: needs a tool returning >1000 rows. The product caps its own rows at 1000, so
    # only a list route with >1000 rows could prove it; probe the biggest candidates.
    row_cap = None
    for n, a in (("chat_query", {"dataset": "messages", "limit": 1000}),):
        st2, res2, txt2 = call(n, a)
        if st2 == 200 and txt2.startswith("{"):
            j = json.loads(txt2)
            if j.get("truncated") and j.get("originalRows", 0) > 1000:
                row_cap = j
    note = ("row cap exercised" if row_cap else
            "row cap (>1000 rows) not reachable on this data: product caps at 1000, covered by unit tests")
    ctx["row_cap_note"] = note
    return (f"char cap: originalChars={doc['originalChars']} cut to {len(txt)} chars with "
            f'"truncated":true marker; {note}')


PHONE_KEY = re.compile(r'"(phone|phone_number|contact_number|mobile|mobile_number|msisdn|whatsapp_number|'
                       r'telephone|tel)"\s*:', re.I)
PHONE_VAL = re.compile(r"(?<![\d.])(?:\+\s?60|\+\s?\d{2,3}[\s-]?\d{2}|\b0\s?1\d)[\s-]?\d{3,4}[\s-]?\d{4}(?!\d)")
OTP_RAW = re.compile(r"(?:sign-in|verification) code is\s+\d{4,8}", re.I)
OTP_MASKED = re.compile(r"(?:sign-in|verification) code is\s+\*{6}", re.I)


def s9() -> str:
    # more chat output to scan: contacts-bearing datasets
    for ds in ("contacts", "bot_turns", "episodes"):
        st, res, txt = call("chat_query", {"dataset": ds, "limit": 200})
        if st == 200 and not res.get("isError"):
            OUTPUTS.append((f"chat_query:{ds}", txt))
    st, res, txt = call("chat_get_conversation", {"contact": (ctx.get("search_rows") or [[None, None, None, "x"]])[0][3] or "x", "limit": 50})
    if st == 200 and not res.get("isError"):
        OUTPUTS.append(("chat_get_conversation", txt))
    key_hits = [t for t, x in OUTPUTS if PHONE_KEY.search(x)]
    assert not key_hits, f"phone-named keys in output of: {sorted(set(key_hits))}"
    # a phone-shaped value is only tolerated inside free message text, never in a structured field
    structured = []
    for tool, x in OUTPUTS:
        if tool.startswith("chat_query:") or tool in ("chat_search_messages", "chat_get_conversation"):
            continue
        if PHONE_VAL.search(x):
            structured.append(tool)
    assert not structured, f"phone-like values in structured output of: {sorted(set(structured))}"
    raw = [t for t, x in OUTPUTS if OTP_RAW.search(x)]
    assert not raw, f"unmasked OTP code in output of: {sorted(set(raw))}"
    masked = sum(len(OTP_MASKED.findall(x)) for _, x in OUTPUTS)
    free_phone = sum(len(PHONE_VAL.findall(x)) for t, x in OUTPUTS
                     if t.startswith("chat_query:") or t in ("chat_search_messages", "chat_get_conversation"))
    raw_in_db = ""
    if SO_DB:
        try:
            n = psql(SO_DB, "select count(*) from analytics_connector.messages where "
                            "text ~* '(sign-in|verification) code is\\s+\\*{6}'")
            raw_in_db = f"; view rows with masked OTP text: {n}"
            assert int(n) == 0 or masked >= 1, "OTP rows exist in the data but none came back masked"
        except Exception:  # noqa: BLE001
            pass
    return (f"{len(OUTPUTS)} outputs scanned: no phone keys, no phone values in structured fields, "
            f"no unmasked OTP; {masked} masked '******' codes seen{raw_in_db}; "
            f"phone-shaped strings inside free message text: {free_phone} in {sorted(set(t for t, x in OUTPUTS if PHONE_VAL.search(x) and (t.startswith('chat_query:') or t in ('chat_search_messages', 'chat_get_conversation'))))} (customer-typed, raw text allowed)")


def s10() -> str:
    r = http.post(ctx["token_endpoint"], data={"grant_type": "refresh_token",
                  "refresh_token": ctx["refresh"], "client_id": ctx["client_id"]})
    assert r.status_code == 200, f"refresh {r.status_code}"
    t2 = r.json()
    assert t2["refresh_token"] != ctx["refresh"] and t2["access_token"] != ctx["access"], "no rotation"
    st, res, _ = call("chat_list_datasets", token=t2["access_token"])
    assert st == 200 and not res.get("isError"), "rotated access token unusable"
    old = ctx["refresh"]
    r2 = http.post(ctx["token_endpoint"], data={"grant_type": "refresh_token",
                   "refresh_token": old, "client_id": ctx["client_id"]})
    assert r2.status_code == 400 and r2.json().get("error") == "invalid_grant", f"replay {r2.status_code}"
    st3, _, _ = call("chat_list_datasets", token=t2["access_token"])
    assert st3 == 401, f"family not revoked after replay (got {st3})"
    g = grant_row()
    if SS_DB:
        assert g.startswith("revoked|"), f"grant not revoked: {g}"
    reconnect("after refresh reuse")
    return f"rotation ok, old refresh -> 400 invalid_grant, rotated access then 401{', grant ' + g if g else ''}; reconnected"


def s11() -> str:
    st, _, _ = call("chat_list_datasets")
    assert st == 200, "precondition: token works"
    r = http.post(ctx["revocation_endpoint"], data={"token": ctx["access"], "token_type_hint": "access_token",
                  "client_id": ctx["client_id"]})
    assert r.status_code == 200, f"revoke {r.status_code}"
    st2, _, _ = call("chat_list_datasets")
    assert st2 == 401, f"after revoke got {st2}"
    reconnect("after revoke")
    return "/revoke 200, next call 401; reconnected"


def s12() -> str:
    if not SS_DB:
        raise Deferred("SS_DB_URL not set")
    n = psql(SS_DB, "update app_connector.tokens set expires_at = now() - interval '1 minute' "
                    f"where kind='access' and grant_id='{ctx['grant_id']}' and revoked_at is null "
                    "returning 1").count("1")
    assert n >= 1, "no access token aged"
    st, _, _ = call("chat_list_datasets")
    assert st == 401, f"expired access got {st}"
    r = http.post(ctx["token_endpoint"], data={"grant_type": "refresh_token",
                  "refresh_token": ctx["refresh"], "client_id": ctx["client_id"]})
    assert r.status_code == 200, f"refresh after expiry {r.status_code}"
    t = r.json()
    ctx["access"], ctx["refresh"] = t["access_token"], t["refresh_token"]
    st2, res, _ = call("chat_list_datasets")
    assert st2 == 200 and not res.get("isError"), "new access unusable"
    return "aged access -> 401; refresh -> 200; new access works"


def s13() -> str:
    time.sleep(2)  # consented_at must predate the sign-out-everywhere stamp
    pl = product_login()
    r = http.post(f"{SO_API}/api/v1/auth/sessions/revoke-others",
                  headers={"Authorization": "Bearer " + pl["token"]})
    assert r.status_code == 200, f"revoke-others {r.status_code}"
    st, res, txt = call("crm_master_brands_list", {"limit": "1"})
    assert st == 200 and res.get("isError") is True, f"expected tool error, got http {st} isError={res.get('isError')}"
    assert "data" not in txt[:10], "data returned with the error"
    g = grant_row()
    if SS_DB:
        assert g == "revoked|reconsent_required", f"grant {g}"
    st2, _, _ = call("crm_master_brands_list", {"limit": "1"})
    assert st2 == 401, f"after revoke got {st2}"
    reconnect("after reconsent_required")
    return f"revoke-others -> tool error, grant {g or 'unchecked (no SS_DB_URL)'} , next call 401; reconnected"


def s14() -> str:
    if not SO_DB:
        raise Deferred("SORENTO_DB_URL not set")
    roles = "','".join(r.replace("'", "") for r in ctx["role_ids"])
    perm = psql(SO_DB, "select id from user_permissions where slug='analytics.connector.use'")
    saved = psql(SO_DB, "select id||'|'||role_id||'|'||permission_id||'|'||assigned_at from "
                        f"user_role_permissions where permission_id='{perm}' and role_id in ('{roles}')")
    assert saved, "user's roles do not hold analytics.connector.use"
    rows = [x.split("|") for x in saved.splitlines()]
    try:
        psql(SO_DB, f"delete from user_role_permissions where permission_id='{perm}' and role_id in ('{roles}')")
        res_txt = ""
        deadline = time.time() + RBAC_WAIT
        while True:
            st, res, txt = call("crm_master_brands_list", {"limit": "1"})
            if res.get("isError") or st == 401 or time.time() > deadline:
                break
            time.sleep(3)
        assert res.get("isError") is True, f"expected tool error, got http {st}"
        res_txt = txt
        g = grant_row()
        if SS_DB:
            assert g == "revoked|connector_access_removed", f"grant {g}"
        st2, _, _ = call("crm_master_brands_list", {"limit": "1"})
        assert st2 == 401, f"after revoke got {st2}"
    finally:
        for rid, role, pid, at in rows:
            psql(SO_DB, "insert into user_role_permissions(id,role_id,permission_id,assigned_at) values "
                        f"('{rid}','{role}','{pid}','{at}') on conflict do nothing")
    reconnect("after connector_access_removed")
    st3, res3, _ = call("crm_master_brands_list", {"limit": "1"})
    assert st3 == 200 and not res3.get("isError"), "restored permission does not work after reconnect"
    return f"permission removed -> tool error, grant {g or 'unchecked'}, next call 401; restored, reconnect works"


def s15() -> str:
    if not SS_DB:
        raise Deferred("SS_DB_URL not set")
    st, res, _ = call("chat_list_datasets")
    assert st == 200 and not res.get("isError"), "control call before the revoke failed"
    psql(SS_DB, f'revoke insert on app_connector.call_log from "{APP_ROLE}"')
    try:
        st, res, txt = call("crm_master_brands_list", {"limit": "5"})
        assert st == 200 and res.get("isError") is True, f"expected tool error, got http {st}"
        assert "could not be recorded" in txt, "wrong error text"
        assert "brand_code" not in txt and "data" not in txt.lower().replace("no data was returned", ""), \
            "data leaked with the audit failure"
    finally:
        psql(SS_DB, f'grant insert on app_connector.call_log to "{APP_ROLE}"')
    st2, res2, txt2 = call("crm_master_brands_list", {"limit": "5"})
    assert st2 == 200 and not res2.get("isError") and "brand_code" in txt2, "no recovery after GRANT"
    return "INSERT revoked -> 'could not be recorded' tool error, no data; GRANT restored -> same call returns data"


def s16() -> str:
    parts = []
    if SS_DB:
        since = time.strftime("%Y-%m-%d %H:%M:%S+00", time.gmtime(RUN_STARTED))
        ss = psql(SS_DB, "select status||':'||count(*) from app_connector.call_log "
                         f"where created_at >= '{since}' group by status order by 1").replace("\n", ", ")
        assert ss and "ok:" in ss, "no SS call_log rows for this run"
        trunc = psql(SS_DB, f"select count(*) from app_connector.call_log where created_at >= '{since}' "
                            "and truncated")
        parts.append(f"SS call_log since start: {ss}; truncated rows {trunc}")
    else:
        raise Deferred("SS_DB_URL not set")
    if SO_DB:
        so = psql(SO_DB, "select count(*) from audit_logs where event='connector.tool_call' and "
                         f"action_timestamp >= to_timestamp({int(RUN_STARTED)}) at time zone 'UTC' "
                         f"and user_id='{ctx['user_id']}'")
        assert int(so) >= 5, f"only {so} sorento audit rows"
        det = psql(SO_DB, "select count(*) from audit_logs where event='connector.tool_call' and "
                          f"action_timestamp >= to_timestamp({int(RUN_STARTED)}) at time zone 'UTC' "
                          "and source='connector' and auth_method='connector' and new_values ? 'tool'")
        parts.append(f"sorento audit_logs connector.tool_call rows: {so} ({det} with source/auth_method/tool)")
    return "; ".join(parts)


def _refuse_remote() -> Optional[str]:
    """Name of the first non-local target, or None. Empty DB host = local socket."""
    if os.environ.get("E2E_ALLOW_REMOTE") == "1":
        return None
    local = {"localhost", "127.0.0.1", "::1"}
    for name, value in (("SS_BASE", SS), ("SORENTO_API", SO_API), ("SORENTO_WEB", SO_WEB),
                        ("SS_DB_URL", SS_DB), ("SORENTO_DB_URL", SO_DB)):
        if not value:
            continue
        host = up.urlsplit(value).hostname or ""
        if host and host not in local:
            return f"{name} host '{host}'"
    return None


def main() -> int:
    remote = _refuse_remote()
    if remote:
        print(f"REFUSED: {remote} is not local. Never point this at production "
              "(steps 12/14/15 change the databases). Set E2E_ALLOW_REMOTE=1 to override.",
              file=sys.stderr)
        return 2
    if not EMAIL or not PASSWORD:
        print("FAIL 0 config: set SORENTO_LOGIN_EMAIL and SORENTO_LOGIN_PASSWORD")
        return 2
    ok = step("1", "401 + discovery", s1)
    if ok:
        ok = step("2", "dynamic client registration", s2)
    if ok:
        ok = step("3", "PKCE authorize -> product consent", s3)
    if ok:
        ok = step("4", f"consent bounce ({MODE})", s4)
    if ok:
        ok = step("5", "token exchange", s5)
    if ok:
        ok = step("6", "initialize + tools/list", s6)
    if ok:
        step("7", "tools/call (reused + chat)", s7)
        step("8", "output caps", s8)
        step("9", "no phones, OTP masked", s9)
        step("10", "refresh rotation + replay", s10)
        step("11", "RFC 7009 revoke", s11)
        step("12", "access token expiry", s12)
        step("13", "reconsent_required", s13)
        step("14", "connector_access_removed", s14)
        step("15", "fail-closed audit", s15)
        step("16", "audit rows both sides", s16)
    counts = {k: sum(1 for _, v in results if v == k) for k in ("PASS", "FAIL", "DEFERRED")}
    print(f"SUMMARY pass={counts['PASS']} fail={counts['FAIL']} deferred={counts['DEFERRED']}", flush=True)
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
