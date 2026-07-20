"""Ideation iframe-embed SSO — verify + mint (PLAN-ideation-embed-sso §8, AC-E-5..9).

The shared-service side of the SSO handshake. The host (sorento) mints a
short-lived **assertion** signed with the connection's shared signing secret and
POSTs ``{connection_id, assertion, idea_id?}`` to ``/embed/session``. This
service:

  1. resolves the ``EmbedConnection`` by the body ``connection_id`` (active only);
  2. verifies the assertion signature against the connection's DECRYPTED secret,
     plus ``aud="ideation-embed"`` + ``iss="sorento"`` + ``typ="assertion"`` +
     expiry — a rotated secret invalidates every outstanding assertion (blast
     radius = one connection, AC-E-6);
  3. on success mints a short-lived **embed token** (``typ="embed"``, ≤ a few
     minutes, carrying the connection's ``tenant_id`` + optional ``idea_id``,
     AC-E-7) signed with the shared-service app JWT secret — NOT the app session
     token, NOT the shared signing secret.

Fail closed on every check with a typed :class:`IdeationEmbedError` (401/403) —
the router maps it to the uniform ``{"error":{code,message}}`` envelope. Secrets
(the shared signing secret, the assertion, the minted token) are NEVER logged.

``resolve_embed_token`` is the reverse: it verifies an embed token (for
``POST /embed/validate`` + the embed data reads) and returns the tenant scope,
re-checking the connection is still active (a disabled connection kills its live
embed tokens on the next request).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from cryptography.fernet import InvalidToken
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError, JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.secrets import decrypt_secret, encrypt_secret
from app.security import create_access_token, decode_access_token

from ..models import EmbedConnection

ASSERTION_AUDIENCE = "ideation-embed"
ASSERTION_ISSUER = "sorento"
ASSERTION_TYP = "assertion"
EMBED_TOKEN_TYP = "embed"
EMBED_TOKEN_TTL_MINUTES = 5
# Reject an assertion minted "in the future" beyond this clock-skew tolerance
# (jose validates ``exp`` but not a future ``iat``).
IAT_SKEW_SECONDS = 60


class IdeationEmbedError(Exception):
    """A typed verification failure — the router emits the uniform envelope."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class EmbedTokenPrincipal:
    """Resolved from a valid embed token — the tenant scope the data reads use."""

    tenant_id: str
    connection_id: str
    idea_id: Optional[str] = None
    sub: Optional[str] = None
    scope: str = "ideation"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── admin / seed ──────────────────────────────────────────────────────────────
def upsert_connection(
    db: Session,
    *,
    connection_id: str,
    tenant_id: str,
    signing_secret: str,
    allowed_origins: Optional[List[str]] = None,
    product_id: Optional[str] = None,
    is_active: bool = True,
) -> EmbedConnection:
    """Create or update an embed connection (admin/seed path, AC-E-5). The signing
    secret is Fernet-encrypted at rest and never returned in plaintext. Idempotent
    by ``connection_id`` so a seed script / admin re-save is safe."""
    if not connection_id or not tenant_id or not signing_secret:
        raise ValueError("connection_id, tenant_id and signing_secret are required")
    origins = [o for o in (allowed_origins or []) if isinstance(o, str) and o]
    row = (
        db.query(EmbedConnection)
        .filter(EmbedConnection.connection_id == connection_id)
        .first()
    )
    ciphertext = encrypt_secret({"signingSecret": signing_secret})
    if row is None:
        row = EmbedConnection(
            connection_id=connection_id,
            tenant_id=tenant_id,
            signing_secret_ciphertext=ciphertext,
            allowed_origins=origins,
            product_id=product_id,
            is_active=is_active,
        )
        db.add(row)
    else:
        row.tenant_id = tenant_id
        row.signing_secret_ciphertext = ciphertext
        row.allowed_origins = origins
        row.product_id = product_id
        row.is_active = is_active
    db.commit()
    db.refresh(row)
    return row


# Sentinel for "field not supplied" in a partial update (so ``product_id=None``
# meaning "clear the scope" is distinguishable from "leave it unchanged").
_UNSET: Any = object()


def get_connection(
    db: Session, *, connection_id: str, tenant_id: str
) -> Optional[EmbedConnection]:
    """Fetch one embed connection scoped to the caller's tenant (admin CRUD). A
    connection registered for another tenant is invisible (returns ``None``)."""
    return (
        db.query(EmbedConnection)
        .filter(
            EmbedConnection.connection_id == connection_id,
            EmbedConnection.tenant_id == tenant_id,
        )
        .first()
    )


def rotate_secret(
    db: Session, *, connection_id: str, tenant_id: str, signing_secret: str
) -> Optional[EmbedConnection]:
    """Replace the connection's signing secret (rotation, AC-E-6). The new secret
    is Fernet-encrypted at rest; it is NEVER returned here — the caller (which
    supplied the plaintext) is the only side that reveals it. Rotating
    invalidates every outstanding assertion signed with the old secret. Returns
    ``None`` when the connection is not in the caller's tenant."""
    if not signing_secret:
        raise ValueError("signing_secret is required")
    row = get_connection(db, connection_id=connection_id, tenant_id=tenant_id)
    if row is None:
        return None
    row.signing_secret_ciphertext = encrypt_secret({"signingSecret": signing_secret})
    db.commit()
    db.refresh(row)
    return row


def update_connection_fields(
    db: Session,
    *,
    connection_id: str,
    tenant_id: str,
    allowed_origins: Any = _UNSET,
    product_id: Any = _UNSET,
    is_active: Any = _UNSET,
) -> Optional[EmbedConnection]:
    """Partial update of the non-secret fields (enable/disable, re-scope, edit the
    origin allow-list) WITHOUT touching the signing secret. Only the fields
    explicitly supplied are written. Returns ``None`` when the connection is not
    in the caller's tenant."""
    row = get_connection(db, connection_id=connection_id, tenant_id=tenant_id)
    if row is None:
        return None
    if allowed_origins is not _UNSET:
        row.allowed_origins = [
            o for o in (allowed_origins or []) if isinstance(o, str) and o
        ]
    if product_id is not _UNSET:
        row.product_id = product_id or None
    if is_active is not _UNSET:
        row.is_active = bool(is_active)
    db.commit()
    db.refresh(row)
    return row


def delete_connection(db: Session, *, connection_id: str, tenant_id: str) -> bool:
    """Hard-delete an embed connection (off-boarding). Any live embed token for it
    stops resolving on its next request. Returns ``False`` when the connection is
    not in the caller's tenant."""
    row = get_connection(db, connection_id=connection_id, tenant_id=tenant_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def _decrypt_signing_secret(conn: EmbedConnection) -> str:
    try:
        creds = decrypt_secret(conn.signing_secret_ciphertext or "")
    except (InvalidToken, ValueError, TypeError):
        # A secret we cannot decrypt is unusable — fail closed (never 500).
        raise IdeationEmbedError(401, "invalid_assertion", "Assertion verification failed.")
    secret = (creds or {}).get("signingSecret")
    if not secret:
        raise IdeationEmbedError(
            401, "invalid_assertion", "Embed is not configured for this connection."
        )
    return secret


# ── the SSO exchange ──────────────────────────────────────────────────────────
def verify_and_mint(
    db: Session,
    *,
    connection_id: Optional[str],
    assertion: str,
    idea_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify the host assertion + mint an embed token. Returns
    ``{"token", "expires_at"}``. Raises :class:`IdeationEmbedError` on any failure
    — never mints on a failed check (AC-E-6)."""
    assertion = (assertion or "").strip()
    if not connection_id:
        raise IdeationEmbedError(401, "invalid_connection", "Connection id missing.")
    if not assertion:
        raise IdeationEmbedError(401, "invalid_assertion", "Missing assertion.")

    conn = (
        db.query(EmbedConnection)
        .filter(
            EmbedConnection.connection_id == connection_id,
            EmbedConnection.is_active.is_(True),
        )
        .first()
    )
    if conn is None:
        raise IdeationEmbedError(401, "invalid_connection", "Unknown embed connection.")

    # Header must declare the app algorithm (the only one we verify against) —
    # blocks an alg-confusion downgrade.
    try:
        header = jwt.get_unverified_header(assertion)
    except JWTError:
        raise IdeationEmbedError(401, "invalid_assertion", "Malformed assertion.")
    if header.get("alg") != settings.jwt_algorithm:
        raise IdeationEmbedError(401, "invalid_assertion", "Unsupported assertion algorithm.")

    secret = _decrypt_signing_secret(conn)

    # Signature + audience + expiry, verified against THIS connection's secret.
    try:
        claims = jwt.decode(
            assertion,
            secret,
            algorithms=[settings.jwt_algorithm],
            audience=ASSERTION_AUDIENCE,
        )
    except ExpiredSignatureError:
        raise IdeationEmbedError(401, "expired", "Assertion has expired.")
    except (JWTClaimsError, JWTError):
        raise IdeationEmbedError(401, "invalid_assertion", "Assertion verification failed.")

    if claims.get("iss") != ASSERTION_ISSUER:
        raise IdeationEmbedError(401, "invalid_assertion", "Unexpected assertion issuer.")
    if claims.get("typ") != ASSERTION_TYP:
        raise IdeationEmbedError(401, "invalid_assertion", "Unexpected assertion type.")

    iat = claims.get("iat")
    if isinstance(iat, (int, float)) and iat > int(_now().timestamp()) + IAT_SKEW_SECONDS:
        raise IdeationEmbedError(401, "invalid_assertion", "Assertion issued in the future.")

    expires_at = _now() + timedelta(minutes=EMBED_TOKEN_TTL_MINUTES)
    token = create_access_token(
        {
            # ``typ="embed"`` is the sole discriminator: ``_resolve_user`` refuses
            # it on every staff endpoint, and ``resolve_embed_token`` accepts only
            # it — so it is single-purpose (AC-E-7). No ``aud`` claim: the app
            # ``decode_access_token`` verifies signature+exp only (matching the
            # omnichannel embed token), so an ``aud`` here would need every caller
            # to pass it back.
            "sub": str(claims.get("sub") or ""),
            "typ": EMBED_TOKEN_TYP,
            "tenant_id": conn.tenant_id,
            "connection_id": conn.connection_id,
            "idea_id": idea_id,
            "email": claims.get("email"),
            "name": claims.get("name"),
            "scope": "ideation",
        },
        expires_minutes=EMBED_TOKEN_TTL_MINUTES,
    )
    return {"token": token, "expires_at": expires_at.isoformat()}


def resolve_embed_token(db: Session, token: str) -> EmbedTokenPrincipal:
    """Verify an embed token → the tenant scope. Raises :class:`IdeationEmbedError`
    (401) on any failure. Re-checks the connection is still active so a disabled
    connection invalidates its live embed tokens on the next request."""
    token = (token or "").strip()
    if not token:
        raise IdeationEmbedError(401, "invalid_token", "Missing embed token.")
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise IdeationEmbedError(401, "invalid_token", "Invalid or expired session.")
    if payload.get("typ") != EMBED_TOKEN_TYP:
        raise IdeationEmbedError(401, "invalid_token", "Not an embed token.")
    tenant_id = payload.get("tenant_id")
    connection_id = payload.get("connection_id")
    if not tenant_id or not connection_id:
        raise IdeationEmbedError(401, "invalid_token", "Embed token missing scope.")
    conn = (
        db.query(EmbedConnection)
        .filter(
            EmbedConnection.connection_id == connection_id,
            EmbedConnection.is_active.is_(True),
        )
        .first()
    )
    if conn is None or conn.tenant_id != tenant_id:
        raise IdeationEmbedError(401, "invalid_token", "Embed connection is no longer active.")
    return EmbedTokenPrincipal(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idea_id=payload.get("idea_id"),
        sub=payload.get("sub"),
        scope=payload.get("scope") or "ideation",
    )
