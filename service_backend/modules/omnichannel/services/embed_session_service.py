"""Embed session exchange — plan 11H Slice 2 (AC-11H-04..08) + §2/§3 of the
cross-repo contract.

``POST /embed/session { assertion }`` verifies a consumer-minted HS256 assertion
against the connection's decrypted ``embedSecret`` (resolved by ``iss`` = the
connection id), enforces single-use ``jti`` + origin allow-list + workspace
membership, provisions/loads the external agent, and mints a ~15-min access
token embedding ``workspaceId/scope/caps/external_agent_id/connection_id`` with
``typ="embed"``. No cookie.

Fail closed on any check — the typed error codes are the contract's:
``invalid_assertion`` / ``replayed`` / ``expired`` / ``origin_not_allowed`` /
``workspace_not_found``.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from cryptography.fernet import InvalidToken
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError, JWTError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.repositories.module_repository import ModuleRepository
from app.secrets import decrypt_secret
from app.security import create_access_token

from ..models import EmbedJti, Workspace
from .external_agent_service import ExternalAgentService

MODULE_NAME = "omnichannel"
EMBED_AUDIENCE = "omnichannel-embed"
EMBED_PROVIDER = "omnichannel_shared"
ACCESS_TOKEN_TTL_MINUTES = 15
ACCESS_TOKEN_TTL_SECONDS = ACCESS_TOKEN_TTL_MINUTES * 60
# An assertion is short-lived (contract: iat+900); reject any minted "in the
# future" beyond this clock-skew tolerance.
IAT_SKEW_SECONDS = 60
VALID_CAPS = {"reply", "assign", "close", "note", "send_template", "read_only"}


class EmbedError(Exception):
    """A typed verification failure — the router emits the uniform envelope."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EmbedSessionService:
    def __init__(self, db: Session):
        self.db = db

    def exchange(self, assertion: str, origin: Optional[str]) -> Dict[str, Any]:
        assertion = (assertion or "").strip()
        if not assertion:
            raise EmbedError(401, "invalid_assertion", "Missing assertion.")

        # 1) Header must declare HS256 (the only algorithm we verify against).
        try:
            header = jwt.get_unverified_header(assertion)
        except JWTError:
            raise EmbedError(401, "invalid_assertion", "Malformed assertion.")
        if header.get("alg") != "HS256":
            raise EmbedError(401, "invalid_assertion", "Unsupported assertion algorithm.")

        # 2) Resolve the connection by the UNVERIFIED iss (the connection id), then
        #    verify the signature with its decrypted embedSecret.
        try:
            unverified = jwt.get_unverified_claims(assertion)
        except JWTError:
            raise EmbedError(401, "invalid_assertion", "Malformed assertion.")
        iss = unverified.get("iss")
        if not iss:
            raise EmbedError(401, "invalid_assertion", "Assertion issuer missing.")
        conn = (
            self.db.query(Connection)
            .filter(Connection.id == iss, Connection.provider == EMBED_PROVIDER)
            .first()
        )
        if conn is None:
            raise EmbedError(401, "invalid_assertion", "Unknown assertion issuer.")

        embed_secret = self._embed_secret(conn)

        # 3) Verify signature + audience + expiry. A rotated embedSecret makes an
        #    outstanding assertion fail here (blast radius = one connection).
        try:
            claims = jwt.decode(
                assertion,
                embed_secret,
                algorithms=["HS256"],
                audience=EMBED_AUDIENCE,
            )
        except ExpiredSignatureError:
            raise EmbedError(401, "expired", "Assertion has expired.")
        except (JWTClaimsError, JWTError):
            raise EmbedError(401, "invalid_assertion", "Assertion verification failed.")

        # 4) iat skew — reject a token minted "in the future" (jose validates exp
        #    but not a future iat).
        iat = claims.get("iat")
        if isinstance(iat, (int, float)) and iat > int(_now().timestamp()) + IAT_SKEW_SECONDS:
            raise EmbedError(401, "invalid_assertion", "Assertion issued in the future.")

        jti = claims.get("jti")
        if not jti:
            raise EmbedError(401, "invalid_assertion", "Assertion id (jti) missing.")

        # 5) Origin allow-list — the request Origin must be one the connection
        #    permits (drives clickjacking + postMessage trust).
        allowed_origins = self._allowed_origins(conn)
        if not origin or origin not in allowed_origins:
            raise EmbedError(403, "origin_not_allowed", "This origin is not permitted to embed.")

        # 6) Connection active for tenant + workspace belongs to it.
        workspace_id = claims.get("workspaceId")
        if not workspace_id or not ModuleRepository(self.db).is_active(conn.tenant_id, MODULE_NAME):
            raise EmbedError(404, "workspace_not_found", "Workspace not found.")
        workspace = (
            self.db.query(Workspace)
            .filter(
                Workspace.id == workspace_id,
                Workspace.tenant_id == conn.tenant_id,
                Workspace.is_trashed.is_(False),
            )
            .first()
        )
        if workspace is None:
            raise EmbedError(404, "workspace_not_found", "Workspace not found.")

        # 7) Single-use jti (AC-11H-05) — retained ≥ the assertion TTL. Prune
        #    expired rows opportunistically. A duplicate → replayed.
        self._consume_jti(jti, claims.get("exp"))

        # 8) Provision/load the external agent keyed by (connection_id, sub).
        sub = claims.get("sub")
        if not sub:
            raise EmbedError(401, "invalid_assertion", "Assertion subject (sub) missing.")
        agent = ExternalAgentService(self.db).upsert(
            connection_id=conn.id,
            tenant_id=conn.tenant_id,
            sub=str(sub),
            name=str(claims.get("name") or sub),
            email=claims.get("email"),
            avatar_url=claims.get("avatarUrl"),
        )

        scope = claims.get("scope") or "inbox"
        caps = self._clean_caps(claims.get("caps"))

        # 9) Mint the access token (no cookie). It carries everything §4 needs to
        #    authorize without a DB round-trip on scope/caps.
        access_token = create_access_token(
            {
                "sub": agent.id,
                "typ": "embed",
                "tenant_id": conn.tenant_id,
                "connection_id": conn.id,
                "workspaceId": workspace.id,
                "external_agent_id": agent.id,
                "scope": scope,
                "caps": caps,
            },
            expires_minutes=ACCESS_TOKEN_TTL_MINUTES,
        )

        return {
            "accessToken": access_token,
            "expiresIn": ACCESS_TOKEN_TTL_SECONDS,
            "agent": {"id": agent.id, "name": agent.name, "avatarUrl": agent.avatar_url},
            "workspace": {"id": workspace.id, "name": workspace.name},
            "scope": scope,
            "caps": caps,
        }

    def allowed_origins_for(self, connection_id: Optional[str]) -> List[str]:
        """Public frame-policy lookup (AC-11H-15): the parent origins a connection
        permits, driving the embed page's ``frame-ancestors`` CSP. Unknown / absent
        connection → empty list (uniform, no enumeration)."""
        if not connection_id:
            return []
        conn = (
            self.db.query(Connection)
            .filter(Connection.id == connection_id, Connection.provider == EMBED_PROVIDER)
            .first()
        )
        if conn is None:
            return []
        return self._allowed_origins(conn)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _embed_secret(self, conn: Connection) -> str:
        try:
            creds = decrypt_secret(conn.credentials_json or "")
        except (InvalidToken, ValueError, TypeError):
            raise EmbedError(401, "invalid_assertion", "Assertion verification failed.")
        secret = (creds or {}).get("embedSecret")
        if not secret:
            raise EmbedError(401, "invalid_assertion", "Embed is not configured for this connection.")
        return secret

    @staticmethod
    def _allowed_origins(conn: Connection) -> List[str]:
        cfg = conn.config_json or {}
        origins = cfg.get("allowedOrigins") or []
        return [o for o in origins if isinstance(o, str)]

    @staticmethod
    def _clean_caps(caps: Any) -> List[str]:
        if not isinstance(caps, list):
            return []
        return [c for c in caps if isinstance(c, str) and c in VALID_CAPS]

    def _consume_jti(self, jti: str, exp: Any) -> None:
        # Opportunistic prune of expired rows (keeps the ledger bounded).
        now = _now()
        self.db.query(EmbedJti).filter(EmbedJti.expires_at < now).delete(
            synchronize_session=False
        )
        expires_at = now
        if isinstance(exp, (int, float)):
            expires_at = datetime.fromtimestamp(int(exp), tz=timezone.utc)
        if self.db.query(EmbedJti).filter(EmbedJti.jti == jti).first() is not None:
            raise EmbedError(401, "replayed", "This assertion has already been used.")
        self.db.add(EmbedJti(jti=jti, expires_at=expires_at))
        try:
            self.db.commit()
        except IntegrityError:
            # Concurrent replay race — the other request won the insert.
            self.db.rollback()
            raise EmbedError(401, "replayed", "This assertion has already been used.")
