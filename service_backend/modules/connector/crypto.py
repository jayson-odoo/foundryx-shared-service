"""Connector protocol/crypto primitives (plan sprint-4/19, section 9).

Pure functions, no DB: PKCE S256, exact redirect allow-list, opaque token
minting + hashing, ``request_hash`` (byte-identical to the product verifier),
the SS -> product call JWT, the consent-request JWT and the product -> SS
consent assertion verifier. Comparisons are constant time; every verification
failure is one opaque error (fail closed).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
import uuid
from typing import Optional
from urllib.parse import parse_qsl, quote

from jose import JWTError, jwt

# RFC 7636 4.1: 43-128 chars of the unreserved set.
_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")

ISSUER = "foundryx-ss"
CALL_TYP = "connector_call"
CONSENT_TYP = "connector_consent_request"
ASSERTION_TYP = "connector_assertion"
ASSERTION_AUDIENCE = "foundryx-connector"
ASSERTION_MAX_LIFETIME_SECONDS = 120
ASSERTION_MAX_CHARS = 4096
IAT_SKEW_SECONDS = 5
CALL_LIFETIME_SECONDS = 60


class AssertionInvalid(Exception):
    """The product's consent assertion failed verification (never says why)."""


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
    return any(hmac.compare_digest(uri.encode("utf-8"), a.encode("utf-8")) for a in allowed)


# --- Opaque tokens -----------------------------------------------------------

def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- request hash (parity with the product's verifier) -------------------------

def canonical_query(query: str) -> str:
    pairs = parse_qsl(query, keep_blank_values=True)
    return "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in pairs)


def request_hash(method: str, raw_path: str, query: str, body: bytes) -> str:
    material = (
        f"{method.upper()}\n{raw_path}\n{canonical_query(query)}\n"
        f"{hashlib.sha256(body).hexdigest()}"
    )
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# --- SS -> product JWTs ---------------------------------------------------------

def sign_call(secret: str, *, connection_id: str, audience: str, sub: str, grant_id: str,
              consented_at: int, tool: str, method: str, raw_path: str, query: str,
              body: bytes, now: Optional[int] = None) -> str:
    iat = int(now if now is not None else time.time())
    claims = {
        "typ": CALL_TYP,
        "iss": ISSUER,
        "aud": audience,
        "connection_id": connection_id,
        "sub": sub,
        "grant_id": grant_id,
        "consented_at": int(consented_at),
        "tool": tool,
        "req_hash": request_hash(method, raw_path, query, body),
        "iat": iat,
        "exp": iat + CALL_LIFETIME_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def sign_consent_request(secret: str, *, connection_id: str, audience: str, request_id: str,
                         client_name: str, redirect_host: str, return_url: str,
                         now: Optional[int] = None, ttl: int = 600) -> str:
    iat = int(now if now is not None else time.time())
    claims = {
        "typ": CONSENT_TYP,
        "iss": ISSUER,
        "aud": audience,
        "connection_id": connection_id,
        "request_id": request_id,
        "client_name": client_name,
        "redirect_host": redirect_host,
        "return_url": return_url,
        "iat": iat,
        "exp": iat + min(ttl, 600),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


# --- Product -> SS consent assertion ----------------------------------------------

def _eq(a: object, b: str) -> bool:
    return isinstance(a, str) and hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def verify_assertion(token: str, secret: str, *, issuer: str, connection_id: str,
                     request_id: str, now: Optional[int] = None) -> dict:
    """Verify a consent assertion; returns its claims or raises AssertionInvalid.

    jti single-use is enforced by the caller against the ``assertion_jti`` ledger.
    """
    try:
        if not isinstance(token, str) or not token or len(token) > ASSERTION_MAX_CHARS:
            raise AssertionInvalid()
        if jwt.get_unverified_header(token).get("alg") != "HS256":
            raise AssertionInvalid()
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_exp": False, "verify_iat": False, "verify_nbf": False,
                     "verify_aud": False, "verify_iss": False, "verify_sub": False,
                     "verify_jti": False, "verify_at_hash": False},
        )
    except AssertionInvalid:
        raise
    except (JWTError, ValueError, TypeError) as exc:
        raise AssertionInvalid() from exc

    current = int(now if now is not None else time.time())
    iat, exp = claims.get("iat"), claims.get("exp")
    if isinstance(iat, bool) or isinstance(exp, bool) or not isinstance(iat, int) or not isinstance(exp, int):
        raise AssertionInvalid()
    if iat > current + IAT_SKEW_SECONDS or exp <= current:
        raise AssertionInvalid()
    if exp - iat > ASSERTION_MAX_LIFETIME_SECONDS:
        raise AssertionInvalid()
    if not (
        _eq(claims.get("typ"), ASSERTION_TYP)
        and _eq(claims.get("iss"), issuer)
        and _eq(claims.get("aud"), ASSERTION_AUDIENCE)
        and _eq(claims.get("connection_id"), connection_id)
        and _eq(claims.get("request_id"), request_id)
    ):
        raise AssertionInvalid()
    sub, jti = claims.get("sub"), claims.get("jti")
    if not isinstance(sub, str) or not sub or not isinstance(jti, str) or not jti:
        raise AssertionInvalid()
    return claims
