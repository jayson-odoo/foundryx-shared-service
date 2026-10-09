"""Connector protocol/crypto primitives (plan sprint-4/19).

Pure functions, no DB: PKCE S256, exact redirect allow-list, opaque token
minting + hashing, the SS -> product call signature and the product -> SS
consent assertion. Everything security-relevant compares in constant time and
fails closed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from typing import Mapping, Optional

from jose import JWTError, jwt

# RFC 7636 4.1: 43-128 chars of the unreserved set.
_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")

ASSERTION_TYP = "connector-assertion"
ASSERTION_MAX_LIFETIME_SECONDS = 120
CLOCK_SKEW_SECONDS = 60
CALL_MAX_SKEW_SECONDS = 300

H_TIMESTAMP = "X-FX-Connector-Timestamp"
H_NONCE = "X-FX-Connector-Nonce"
H_USER = "X-FX-Connector-User"
H_GRANT = "X-FX-Connector-Grant"
H_SIGNATURE = "X-FX-Connector-Signature"


class AssertionInvalid(Exception):
    """The product's consent assertion failed verification (never says why to the caller)."""


# --- PKCE --------------------------------------------------------------------

def pkce_verify(verifier: str, challenge: str, method: str) -> bool:
    if method != "S256" or not verifier or not challenge:
        return False
    if not _VERIFIER_RE.match(verifier):
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(expected, challenge)


# --- Redirect URIs -----------------------------------------------------------

def redirect_allowed(uri: str, allowed: list[str]) -> bool:
    """Exact string match only - no prefixes, wildcards or normalisation."""
    if not uri:
        return False
    return any(hmac.compare_digest(uri, a) for a in allowed)


# --- Opaque tokens -----------------------------------------------------------

def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- SS -> product call signature -------------------------------------------

def _call_mac(key: str, ts: str, nonce: str, method: str, path: str, body: bytes,
              user: str, grant: str) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    msg = "\n".join([ts, nonce, method.upper(), path, body_hash, user, grant])
    return hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_call(key: str, method: str, path: str, body: bytes, *, user: str, grant: str,
              now: Optional[int] = None) -> dict[str, str]:
    ts = str(int(now if now is not None else time.time()))
    nonce = secrets.token_urlsafe(16)
    sig = _call_mac(key, ts, nonce, method, path, body, user, grant)
    return {
        H_TIMESTAMP: ts,
        H_NONCE: nonce,
        H_USER: user,
        H_GRANT: grant,
        H_SIGNATURE: f"sha256={sig}",
    }


def verify_call(key: str, method: str, path: str, body: bytes, headers: Mapping[str, str],
                *, now: Optional[int] = None) -> bool:
    """Reference verifier for products (and our own tests).

    Products must ALSO keep a nonce ledger for the skew window to stop replays;
    this function only checks integrity + freshness.
    """
    try:
        ts = headers[H_TIMESTAMP]
        nonce = headers[H_NONCE]
        user = headers[H_USER]
        grant = headers[H_GRANT]
        sig = headers[H_SIGNATURE]
        ts_int = int(ts)
    except (KeyError, ValueError, TypeError):
        return False
    current = int(now if now is not None else time.time())
    if abs(current - ts_int) > CALL_MAX_SKEW_SECONDS:
        return False
    if not sig.startswith("sha256="):
        return False
    expected = _call_mac(key, ts, nonce, method, path, body, user, grant)
    return hmac.compare_digest(expected, sig[len("sha256="):])


# --- Product -> SS consent assertion ----------------------------------------

def verify_assertion(token: str, key: str, *, product: str, nonce: str,
                     now: Optional[int] = None) -> dict:
    """Verify a consent assertion. Returns its claims or raises AssertionInvalid.

    jti single-use is enforced by the caller against its ledger.
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise AssertionInvalid() from exc
    if header.get("alg") != "HS256":
        raise AssertionInvalid()
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            audience=f"ss-connector:{product}",
            issuer=product,
            options={"require_exp": True, "require_iat": True, "require_aud": True,
                     "require_iss": True, "require_sub": True, "require_jti": True},
        )
    except JWTError as exc:
        raise AssertionInvalid() from exc

    current = int(now if now is not None else time.time())
    iat, exp = claims.get("iat"), claims.get("exp")
    if not isinstance(iat, int) or not isinstance(exp, int):
        raise AssertionInvalid()
    if iat > current + CLOCK_SKEW_SECONDS:
        raise AssertionInvalid()
    if exp - iat > ASSERTION_MAX_LIFETIME_SECONDS:
        raise AssertionInvalid()
    if claims.get("typ") != ASSERTION_TYP:
        raise AssertionInvalid()
    if not claims.get("sub") or not claims.get("jti"):
        raise AssertionInvalid()
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise AssertionInvalid()
    return claims
