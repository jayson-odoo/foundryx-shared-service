"""Connector crypto primitives (plan sprint-4/19, AC-19-01..06).

Pure functions. The reference implementation of sorento's ``request_hash``
(access.py:92-101) is re-implemented INLINE below - never imported - so the golden
vectors pin wire compatibility with the product, not with our own code.
"""

import base64
import hashlib
import time
from urllib.parse import parse_qsl, quote

import pytest
from jose import jwt

from modules.connector import crypto


# --- inline reference (sorento access.py:92-101) -----------------------------


def ref_canonical_query(query: str) -> str:
    pairs = parse_qsl(query, keep_blank_values=True)
    return "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in pairs)


def ref_request_hash(method: str, raw_path: str, query: str, body: bytes) -> str:
    material = (
        f"{method.upper()}\n{raw_path}\n{ref_canonical_query(query)}\n"
        f"{hashlib.sha256(body).hexdigest()}"
    )
    return base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest()).rstrip(b"=").decode()


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# --- AC-19-01 PKCE ------------------------------------------------------------


def test_pkce_s256_accepts_matching_pair():
    v = "a" * 43
    assert crypto.pkce_verify(v, _challenge(v), "S256") is True


def test_pkce_rejects_wrong_verifier():
    assert crypto.pkce_verify("b" * 43, _challenge("a" * 43), "S256") is False


@pytest.mark.parametrize("method", ["plain", "s256", "", "S512"])
def test_pkce_only_s256_method(method):
    v = "a" * 43
    assert crypto.pkce_verify(v, _challenge(v), method) is False
    assert crypto.pkce_verify(v, v, method) is False


@pytest.mark.parametrize("verifier", ["a" * 42, "a" * 129, "a" * 42 + "!", "a" * 42 + " ", "é" * 50])
def test_pkce_rejects_verifier_outside_rfc7636(verifier):
    try:
        challenge = _challenge(verifier)
    except UnicodeEncodeError:
        challenge = "x" * 43
    assert crypto.pkce_verify(verifier, challenge, "S256") is False


def test_pkce_accepts_boundary_lengths_and_unreserved_chars():
    for v in ("a" * 43, "A1-._~" * 21 + "a", "z" * 128):
        assert crypto.pkce_verify(v, _challenge(v), "S256") is True


# --- AC-19-02 redirect allow-list ---------------------------------------------

ALLOWED = ["https://claude.ai/api/mcp/auth_callback"]


def test_redirect_exact_match_only():
    assert crypto.redirect_allowed("https://claude.ai/api/mcp/auth_callback", ALLOWED) is True


@pytest.mark.parametrize(
    "uri",
    [
        "https://claude.ai/api/mcp/auth_callback/",
        "https://claude.ai/api/mcp/auth_callback?x=1",
        "https://claude.ai/api/mcp/auth_callback#f",
        "https://CLAUDE.ai/api/mcp/auth_callback",
        "https://claude.ai/API/mcp/auth_callback",
        "http://claude.ai/api/mcp/auth_callback",
        "https://claude.ai.evil.com/api/mcp/auth_callback",
        "https://claude.ai/api/mcp/auth_callback/../x",
        " https://claude.ai/api/mcp/auth_callback",
        "",
    ],
)
def test_redirect_variants_refused(uri):
    assert crypto.redirect_allowed(uri, ALLOWED) is False


def test_redirect_empty_allowlist_refuses_everything():
    assert crypto.redirect_allowed("https://claude.ai/api/mcp/auth_callback", []) is False


# --- tokens ---------------------------------------------------------------------


def test_new_token_random_and_hash_stable_sha256_hex():
    a, b = crypto.new_token(), crypto.new_token()
    assert a != b and len(a) >= 43
    assert crypto.hash_token(a) == hashlib.sha256(a.encode()).hexdigest()
    assert crypto.hash_token(a) != a


# --- AC-19-03 request_hash golden vectors -------------------------------------

# Computed once from sorento access.py:92-101 and pinned here as literals.
GOLDEN = [
    ("GET", "/api/v1/connector/manifest", "", b"", "7HhXXsPMVOILYeQ7SQA9oSNDOP36SvU8myPL8qZGT6Y"),
    ("GET", "/api/v1/x/", "b=2&a=1&b=1", b"", "n5ACOG3jHMiK8oVv0Cs1Oudrg3Kk2_N5LwpmoDOAB-U"),
    ("GET", "/api/v1/x", "q=a b&n=café", b"", "6mR2XHVjc5vQ9R7OHRt-gvnLrB_gCAPenAIlLzVRQHo"),
    ("POST", "/api/v1/connector/query", "", b'{"a":1}', "i7hdOsi3ntPvl1j9afGhCuC6zlNsXJa97m7JynxbdOU"),
    ("GET", "/api/v1/master-data/brands/", "limit=5", b"", "xWaLs0Z1UeXT9wiHGUgkDsAco45_sS_jlO2VgdPi5ZY"),
]


@pytest.mark.parametrize("method,path,query,body,expected", GOLDEN)
def test_request_hash_golden_vectors(method, path, query, body, expected):
    assert ref_request_hash(method, path, query, body) == expected  # reference sanity
    assert crypto.request_hash(method, path, query, body) == expected


def test_request_hash_lowercase_method_normalised_and_no_padding():
    h = crypto.request_hash("get", "/p", "", b"")
    assert h == ref_request_hash("GET", "/p", "", b"")
    assert "=" not in h


def test_canonical_query_keeps_sent_order_and_quotes():
    assert crypto.canonical_query("b=2&a=1&b=1") == "b=2&a=1&b=1"
    assert crypto.canonical_query("q=a b&n=café") == "q=a%20b&n=caf%C3%A9"
    assert crypto.canonical_query("") == ""
    assert crypto.canonical_query("k=&z=1") == ref_canonical_query("k=&z=1")


def test_request_hash_binds_path_and_trailing_slash():
    assert crypto.request_hash("GET", "/p/", "", b"") != crypto.request_hash("GET", "/p", "", b"")


# --- AC-19-04 sign_call ---------------------------------------------------------

SS_KEY = "ss-to-product-secret-for-tests"
NOW = 1_800_000_000


def _call(**over):
    kw = dict(
        connection_id="conn-1",
        audience="acme-connector-api",
        sub="42",
        grant_id="g-1",
        consented_at=NOW - 100,
        tool="list_things",
        method="GET",
        raw_path="/api/v1/things/",
        query="limit=5&a=b c",
        body=b"",
        now=NOW,
    )
    kw.update(over)
    return crypto.sign_call(SS_KEY, **kw)


def _decode_call(token, **kw):
    return jwt.decode(
        token, SS_KEY, algorithms=["HS256"], audience="acme-connector-api", issuer="foundryx-ss",
        options={"verify_exp": False, "verify_iat": False, **kw},
    )


def test_sign_call_claims_exact():
    tok = _call()
    assert jwt.get_unverified_header(tok)["alg"] == "HS256"
    c = _decode_call(tok)
    assert set(c) == {
        "typ", "iss", "aud", "connection_id", "sub", "grant_id", "consented_at",
        "tool", "req_hash", "iat", "exp", "jti",
    }
    assert c["typ"] == "connector_call" and c["iss"] == "foundryx-ss"
    assert c["aud"] == "acme-connector-api" and c["connection_id"] == "conn-1"
    assert c["sub"] == "42" and c["grant_id"] == "g-1" and c["tool"] == "list_things"
    assert c["consented_at"] == NOW - 100 and isinstance(c["consented_at"], int)
    assert isinstance(c["iat"], int) and c["iat"] == NOW
    assert c["exp"] == c["iat"] + 60
    assert c["jti"]


def test_sign_call_jti_unique():
    assert _decode_call(_call())["jti"] != _decode_call(_call())["jti"]


def test_sign_call_default_now_is_current_time():
    tok = crypto.sign_call(
        SS_KEY, connection_id="c", audience="acme-connector-api", sub="1", grant_id="g",
        consented_at=1, tool="t", method="GET", raw_path="/p", query="", body=b"",
    )
    iat = _decode_call(tok)["iat"]
    assert abs(iat - int(time.time())) <= 3


def _reference_verify(token, method, path, query, body):
    """What a product does: signature + recompute req_hash from the received request."""
    claims = _decode_call(token)
    return claims["req_hash"] == ref_request_hash(method, path, query, body)


def test_reference_verifier_accepts_and_rejects_changes():
    body = b'{"x":1}'
    tok = _call(method="POST", raw_path="/api/v1/connector/query", query="", body=body)
    assert _reference_verify(tok, "POST", "/api/v1/connector/query", "", body) is True
    assert not _reference_verify(tok, "POST", "/api/v1/connector/query", "", b'{"x":2}')
    assert not _reference_verify(tok, "POST", "/api/v1/other", "", body)
    assert not _reference_verify(tok, "POST", "/api/v1/connector/query", "a=1", body)
    assert not _reference_verify(tok, "GET", "/api/v1/connector/query", "", body)


def test_sign_call_req_hash_matches_request_hash():
    tok = _call()
    assert _decode_call(tok)["req_hash"] == crypto.request_hash("GET", "/api/v1/things/", "limit=5&a=b c", b"")


def test_sign_call_other_secret_does_not_verify():
    tok = _call()
    with pytest.raises(Exception):
        jwt.decode(tok, "other", algorithms=["HS256"], audience="acme-connector-api",
                   options={"verify_exp": False})


def test_sign_call_manifest_shape_empty_tool_and_sub():
    c = _decode_call(_call(tool="", sub=""))
    assert c["tool"] == "" and c["sub"] == ""


# --- AC-19-05 sign_consent_request ---------------------------------------------


def _consent(**over):
    kw = dict(
        connection_id="conn-1", audience="acme-connector-consent", request_id="req-1",
        client_name="Claude", redirect_host="claude.ai",
        return_url="https://ss.test/mcp/acme/oauth/consent-return", now=NOW,
    )
    kw.update(over)
    return crypto.sign_consent_request(SS_KEY, **kw)


def _decode_consent(tok):
    return jwt.decode(tok, SS_KEY, algorithms=["HS256"], audience="acme-connector-consent",
                      options={"verify_exp": False, "verify_iat": False})


def test_sign_consent_request_claims_exact():
    c = _decode_consent(_consent())
    assert set(c) == {
        "typ", "iss", "aud", "connection_id", "request_id", "client_name", "redirect_host",
        "return_url", "iat", "exp", "jti",
    }
    assert c["typ"] == "connector_consent_request" and c["iss"] == "foundryx-ss"
    assert c["connection_id"] == "conn-1" and c["request_id"] == "req-1"
    assert c["client_name"] == "Claude" and c["redirect_host"] == "claude.ai"
    assert c["return_url"] == "https://ss.test/mcp/acme/oauth/consent-return"
    assert c["iat"] == NOW and c["exp"] == NOW + 600 and c["jti"]
    assert _decode_consent(_consent())["jti"] != c["jti"]


def test_sign_consent_request_ttl_default_and_custom():
    assert _decode_consent(_consent(ttl=60))["exp"] == NOW + 60
    assert _decode_consent(_consent())["exp"] - NOW <= 600


# --- AC-19-06 verify_assertion --------------------------------------------------

P2S = "product-to-ss-secret-for-tests"


def _assertion(secret=P2S, headers=None, **over):
    claims = {
        "typ": "connector_assertion", "iss": "acme", "aud": "foundryx-connector",
        "connection_id": "conn-1", "request_id": "req-1", "sub": "42", "name": "Test User",
        "email": "t@example.com", "iat": NOW, "exp": NOW + 120, "jti": "j-1",
    }
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, secret, algorithm="HS256", headers=headers)


def _verify(token, now=NOW):
    return crypto.verify_assertion(
        token, P2S, issuer="acme", connection_id="conn-1", request_id="req-1", now=now,
    )


def test_assertion_valid_returns_claims():
    c = _verify(_assertion())
    assert c["sub"] == "42" and c["jti"] == "j-1" and c["iat"] == NOW


def test_assertion_valid_at_boundaries():
    _verify(_assertion(), now=NOW + 119)
    _verify(_assertion(iat=NOW + 5, exp=NOW + 125), now=NOW)  # 5 s future skew tolerated


@pytest.mark.parametrize(
    "over",
    [
        {"typ": "connector_call"},
        {"iss": "other"},
        {"aud": "something-else"},
        {"connection_id": "conn-2"},
        {"request_id": "req-2"},
        {"exp": NOW + 121},  # lifetime over 120
        {"iat": NOW + 6, "exp": NOW + 100},  # iat beyond 5 s skew
        {"exp": NOW - 1, "iat": NOW - 100},  # expired
        {"jti": None},
        {"jti": ""},
        {"sub": None},
        {"sub": ""},
        {"typ": None},
    ],
)
def test_assertion_refused(over):
    with pytest.raises(crypto.AssertionInvalid):
        _verify(_assertion(**over))


def test_assertion_wrong_secret_and_ss_to_product_secret_refused():
    with pytest.raises(crypto.AssertionInvalid):
        _verify(_assertion(secret="wrong"))
    with pytest.raises(crypto.AssertionInvalid):
        _verify(_assertion(secret=SS_KEY))  # the other direction's secret


def test_assertion_alg_none_refused():
    body = jwt.encode({"sub": "1"}, P2S, algorithm="HS256").split(".")[1]
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    with pytest.raises(crypto.AssertionInvalid):
        _verify(header + "." + body + ".")


def test_assertion_other_algorithm_refused():
    tok = jwt.encode({"sub": "1", "iss": "acme", "aud": "foundryx-connector"}, P2S, algorithm="HS512")
    with pytest.raises(crypto.AssertionInvalid):
        _verify(tok)


def test_assertion_over_4096_chars_refused():
    with pytest.raises(crypto.AssertionInvalid):
        _verify(_assertion(name="x" * 5000))


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c", None])
def test_assertion_garbage_refused_with_opaque_error(garbage):
    with pytest.raises(crypto.AssertionInvalid):
        _verify(garbage)
