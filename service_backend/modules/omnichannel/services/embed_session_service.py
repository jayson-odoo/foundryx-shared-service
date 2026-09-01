"""Embed session exchange - plan 11H Slice 2 (AC-11H-04..08) + §2/§3 of the
cross-repo contract.

``POST /embed/session { assertion }`` verifies a consumer-minted HS256 assertion
against the connection's decrypted ``embedSecret`` (resolved by ``iss`` = the
connection id), enforces single-use ``jti`` + origin allow-list + workspace
membership, provisions/loads the external agent, and mints a ~15-min access
token embedding ``workspaceId/scope/caps/external_agent_id/connection_id`` with
``typ="embed"``. No cookie.

Fail closed on any check - the typed error codes are the contract's:
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
    """A typed verification failure - the router emits the uniform envelope."""

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

    def exchange(self, assertion: str, parent_origin: Optional[str]) -> Dict[str, Any]:
        """Verify + exchange, recording ONE ``embed_session`` activity row on both
        the success and each typed-``EmbedError`` path (AC-DLC-20). The recorder is
        fully failure-isolated (fresh session, swallow-and-log) so logging can
        never break this security path; a tenant is resolved from the connection
        the assertion maps to as soon as it's known (``ctx``), and a failure
        before that (no attributable tenant) is skipped."""
        # Tracks the tenant/workspace resolved DURING the exchange so a failure at
        # any step still attributes what it can (the recorder skips a None tenant).
        ctx: Dict[str, Any] = {"tenant_id": None, "workspace_id": None}
        try:
            result = self._exchange(assertion, parent_origin, ctx)
        except EmbedError as exc:
            self._record(
                ctx,
                status="error",
                status_code=exc.status_code,
                parent_origin=parent_origin,
                error_code=exc.code,
                error_message=exc.message,
            )
            raise
        self._record(
            ctx, status="success", status_code=200, parent_origin=parent_origin
        )
        return result

    def _record(
        self,
        ctx: Dict[str, Any],
        *,
        status: str,
        status_code: int,
        parent_origin: Optional[str],
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        # Import here to avoid a circular import at module load (activity imports
        # the adapter, which the module wires eagerly).
        from .activity import record_embed_session

        record_embed_session(
            self.db,
            tenant_id=ctx.get("tenant_id"),
            workspace_id=ctx.get("workspace_id"),
            status=status,
            status_code=status_code,
            parent_origin=parent_origin,
            error_code=error_code,
            error_message=error_message,
        )

    def _exchange(
        self, assertion: str, parent_origin: Optional[str], ctx: Dict[str, Any]
    ) -> Dict[str, Any]:
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
        # Tenant is now attributable - every subsequent failure lands on the
        # connection's tenant console (AC-DLC-20).
        ctx["tenant_id"] = conn.tenant_id

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

        # 4) iat skew - reject a token minted "in the future" (jose validates exp
        #    but not a future iat).
        iat = claims.get("iat")
        if isinstance(iat, (int, float)) and iat > int(_now().timestamp()) + IAT_SKEW_SECONDS:
            raise EmbedError(401, "invalid_assertion", "Assertion issued in the future.")

        jti = claims.get("jti")
        if not jti:
            raise EmbedError(401, "invalid_assertion", "Assertion id (jti) missing.")

        # 5) Parent-origin allow-list - validate the VALIDATED PARENT origin the
        #    widget captured from the accepted `init` (§5), NOT the widget's own
        #    request Origin header. The widget's fetch carries the shared-service
        #    origin as its browser Origin, never the parent's, so checking that
        #    would be meaningless against the connection's PARENT allowedOrigins
        #    (and would force the operator to whitelist the shared-service origin).
        #    A widget COULD spoof parentOrigin, but a party without the connection's
        #    embedSecret can't mint a valid assertion (step 3), and the browser-
        #    enforced `frame-ancestors` CSP is the real clickjacking control - this
        #    check keeps allowedOrigins purely parent origins, consistent with the
        #    assertion's own `allowedOrigins` claim + frame-ancestors.
        allowed_origins = self._allowed_origins(conn)
        if not parent_origin or parent_origin not in allowed_origins:
            raise EmbedError(403, "origin_not_allowed", "This origin is not permitted to embed.")

        # 6) Connection active for tenant + workspace belongs to it.
        workspace_id = claims.get("workspaceId")
        ctx["workspace_id"] = workspace_id
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

        # 7) Single-use jti (AC-11H-05) - retained ≥ the assertion TTL. Prune
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
            # Concurrent replay race - the other request won the insert.
            self.db.rollback()
            raise EmbedError(401, "replayed", "This assertion has already been used.")
