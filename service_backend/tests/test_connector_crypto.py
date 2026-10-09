"""Connector module - pure protocol/crypto helpers (plan sprint-4/19).

Red-first: these pin the security-critical building blocks that do not
depend on any open owner question (PKCE S256, exact redirect allow-list,
opaque token hashing, the SS -> product call signature and the product ->
SS consent assertion).
"""

import base64
import hashlib
import time

import pytest
from jose import jwt

from modules.connector import crypto


# --- PKCE (RFC 7636, S256 only) -------------------------------------------

def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def test_pkce_s256_accepts_matching_verifier():
    verifier = "a" * 43
    assert crypto.pkce_verify(verifier, _challenge(verifier), "S256") is True


def test_pkce_rejects_wrong_verifier():
    assert crypto.pkce_verify("b" * 43, _challenge("a" * 43), "S256") is False


def test_pkce_rejects_plain_method():
    # OAuth 2.1: plain is not allowed, even when verifier == challenge.
    assert crypto.pkce_verify("a" * 43, "a" * 43, "plain") is False


@pytest.mark.parametrize("verifier", ["a" * 42, "a" * 129, "a" * 42 + "!"])
def test_pkce_rejects_malformed_verifier(verifier):
    assert crypto.pkce_verify(verifier, _challenge(verifier), "S256") is False


# --- Redirect URI allow-list (exact match, no prefix/wildcard) ------------

ALLOWED = ["https://claude.ai/api/mcp/auth_callback"]


def test_redirect_exact_match_allowed():
    assert crypto.redirect_allowed("https://claude.ai/api/mcp/auth_callback", ALLOWED)


@pytest.mark.parametrize(
    "uri",
    [
        "https://claude.ai/api/mcp/auth_callback/../evil",
        "https://claude.ai/api/mcp/auth_callback?x=1",
        "https://claude.ai.evil.com/api/mcp/auth_callback",
        "http://claude.ai/api/mcp/auth_callback",
        "https://claude.ai/api/mcp/auth_callback#frag",
        "",
    ],
)
def test_redirect_anything_else_refused(uri):
    assert not crypto.redirect_allowed(uri, ALLOWED)


# --- Opaque tokens ---------------------------------------------------------

def test_new_token_is_random_and_hash_is_stable():
    a, b = crypto.new_token(), crypto.new_token()
    assert a != b and len(a) >= 43
    assert crypto.hash_token(a) == crypto.hash_token(a)
    assert crypto.hash_token(a) != a


# --- SS -> product call signature -----------------------------------------

KEY = "call-key-for-tests"


def test_signed_call_verifies():
    h = crypto.sign_call(KEY, "POST", "/connector/tools/list_x", b'{"a":1}', user="u1", grant="g1")
    assert crypto.verify_call(KEY, "POST", "/connector/tools/list_x", b'{"a":1}', h) is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda h: {**h, "X-FX-Connector-User": "u2"},
        lambda h: {**h, "X-FX-Connector-Grant": "g2"},
        lambda h: {**h, "X-FX-Connector-Nonce": "other"},
        lambda h: {**h, "X-FX-Connector-Signature": "sha256=" + "0" * 64},
    ],
)
def test_signature_binds_every_header(mutate):
    h = crypto.sign_call(KEY, "POST", "/p", b"{}", user="u1", grant="g1")
    assert crypto.verify_call(KEY, "POST", "/p", b"{}", mutate(h)) is False


def test_signature_binds_path_body_and_method():
    h = crypto.sign_call(KEY, "POST", "/p", b"{}", user="u1", grant="g1")
    assert not crypto.verify_call(KEY, "POST", "/q", b"{}", h)
    assert not crypto.verify_call(KEY, "POST", "/p", b'{"x":1}', h)
    assert not crypto.verify_call(KEY, "GET", "/p", b"{}", h)
    assert not crypto.verify_call("other-key", "POST", "/p", b"{}", h)


def test_signature_rejects_stale_timestamp():
    old = int(time.time()) - 301
    h = crypto.sign_call(KEY, "POST", "/p", b"{}", user="u1", grant="g1", now=old)
    assert crypto.verify_call(KEY, "POST", "/p", b"{}", h) is False


# --- Product -> SS consent assertion --------------------------------------

AKEY = "assertion-key-for-tests"


def _assertion(**over):
    now = int(time.time())
    claims = {
        "iss": "sorento",
        "aud": "ss-connector:sorento",
        "typ": "connector-assertion",
        "sub": "42",
        "name": "Test User",
        "nonce": "req-1",
        "iat": now,
        "exp": now + 60,
        "jti": "j-1",
    }
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, AKEY, algorithm="HS256")


def test_assertion_valid():
    c = crypto.verify_assertion(_assertion(), AKEY, product="sorento", nonce="req-1")
    assert c["sub"] == "42" and c["jti"] == "j-1"


@pytest.mark.parametrize(
    "over",
    [
        {"iss": "other"},
        {"aud": "ss-connector:other"},
        {"typ": "assertion"},
        {"nonce": "req-2"},
        {"exp": int(time.time()) - 5},
        {"iat": int(time.time()) + 600},
        {"exp": int(time.time()) + 3600},  # lifetime longer than the cap
        {"jti": None},
        {"sub": None},
        {"sub": ""},
    ],
)
def test_assertion_rejected(over):
    with pytest.raises(crypto.AssertionInvalid):
        crypto.verify_assertion(_assertion(**over), AKEY, product="sorento", nonce="req-1")


def test_assertion_wrong_key_rejected():
    with pytest.raises(crypto.AssertionInvalid):
        crypto.verify_assertion(_assertion(), "wrong", product="sorento", nonce="req-1")


def test_assertion_alg_none_rejected():
    unsigned = jwt.encode({"sub": "1"}, AKEY, algorithm="HS256").rsplit(".", 1)[0]
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    forged = header + "." + unsigned.split(".")[1] + "."
    with pytest.raises(crypto.AssertionInvalid):
        crypto.verify_assertion(forged, AKEY, product="sorento", nonce="req-1")
