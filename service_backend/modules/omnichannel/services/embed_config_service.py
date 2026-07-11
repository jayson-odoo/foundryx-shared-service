"""Embed-access configuration — plan 11H (tenant-level embed connection admin).

A shared-service tenant admin provisions + manages the ONE embed connection for
their tenant (core ``connections`` row, provider ``omnichannel_shared``,
``UNIQUE(tenant_id, provider)``). The connection carries:

- ``embedSecret`` — the HMAC secret the consumer signs assertions with. Stored
  Fernet-encrypted in ``credentials_json``; **write-only** — never echoed over
  the API, revealed exactly once at rotate.
- ``allowedOrigins`` — the parent origins permitted to embed (plain
  ``config_json``; drives ``frame-ancestors`` + the ``/embed/session`` origin
  check).

Both are tenant-wide; the assertion's ``workspaceId`` picks the workspace at
mint time — so this is ONE tenant-level screen, not per-workspace.

Layering: this service owns the business logic; the router is HTTP-only. All DB
access goes through the CORE ``ConnectionRepository`` (never raw SQL) and the
module's workspace query — every read/write is tenant-scoped from the JWT.
"""
import secrets as pysecrets
from typing import Dict, List
from urllib.parse import urlsplit

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.models.connection import CONNECTION_STATUS_ACTIVE, Connection
from app.repositories.connection_repository import ConnectionRepository
from app.secrets import decrypt_secret, encrypt_secret

from ..models import Workspace

EMBED_PROVIDER = "omnichannel_shared"
EMBED_TYPE = "omnichannel"
EMBED_CONNECTION_NAME = "Embed access"
# 32 bytes of entropy → ~43-char url-safe secret. Ample for HS256.
SECRET_ENTROPY_BYTES = 32


class EmbedNotEnabled(Exception):
    """The embed connection does not exist yet — enable it first (router → 409)."""


class InvalidOrigin(Exception):
    """A submitted origin failed validation (router → 422)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _validate_origin(raw: str) -> str:
    """Return the normalized origin, or raise ``InvalidOrigin``.

    A valid origin is a bare ``scheme://host[:port]`` — NO path, trailing slash,
    query, fragment, or credentials. ``https://`` is required for real hosts;
    ``http://`` is allowed ONLY for ``localhost`` / ``127.0.0.1`` (dev)."""
    value = (raw or "").strip()
    if not value:
        raise InvalidOrigin("An origin cannot be blank.")

    parts = urlsplit(value)
    if parts.scheme not in ("https", "http"):
        raise InvalidOrigin(
            f"'{value}' must start with https:// (or http:// for localhost)."
        )
    if parts.username or parts.password:
        raise InvalidOrigin(f"'{value}' must not include credentials.")
    if parts.query or parts.fragment:
        raise InvalidOrigin(f"'{value}' must not include a query or fragment.")
    # A trailing slash / any path both surface as a non-empty path.
    if parts.path not in ("", "/") or value.endswith("/"):
        raise InvalidOrigin(
            f"'{value}' must be a bare origin with no path or trailing slash "
            "(e.g. https://crm.acme.com)."
        )

    host = (parts.hostname or "").lower()
    if not host:
        raise InvalidOrigin(f"'{value}' is missing a host.")
    try:
        port = parts.port
    except ValueError:
        raise InvalidOrigin(f"'{value}' has an invalid port.")

    is_local = host in ("localhost", "127.0.0.1")
    if parts.scheme == "http" and not is_local:
        raise InvalidOrigin(
            f"'{value}' must use https:// (http:// is only allowed for localhost)."
        )

    netloc = host if port is None else f"{host}:{port}"
    return f"{parts.scheme}://{netloc}"


def _validate_origins(origins: List[str]) -> List[str]:
    """Validate + normalize + dedupe (preserving first-seen order)."""
    seen: Dict[str, None] = {}
    for raw in origins:
        normalized = _validate_origin(raw)
        seen.setdefault(normalized, None)
    return list(seen.keys())


class EmbedConfigService:
    def __init__(self, db: Session):
        self.db = db
        self.connections = ConnectionRepository(db)

    # ── reads ────────────────────────────────────────────────────────────────
    def get_config(self, tenant_id: str) -> Dict:
        conn = self.connections.get_by_provider(tenant_id, EMBED_PROVIDER)
        return self._config_payload(tenant_id, conn)

    def _config_payload(self, tenant_id: str, conn) -> Dict:
        return {
            "connectionId": conn.id if conn else None,
            "allowedOrigins": self._allowed_origins(conn) if conn else [],
            "hasSecret": self._has_secret(conn) if conn else False,
            "host": settings.public_base_url,
            "workspaces": self._workspaces(tenant_id),
        }

    def _workspaces(self, tenant_id: str) -> List[Dict]:
        rows = (
            self.db.query(Workspace)
            .filter(Workspace.tenant_id == tenant_id, Workspace.is_trashed.is_(False))
            .order_by(Workspace.created_at.asc(), Workspace.id.asc())
            .all()
        )
        return [{"id": ws.id, "name": ws.name} for ws in rows]

    @staticmethod
    def _allowed_origins(conn: Connection) -> List[str]:
        cfg = conn.config_json or {}
        origins = cfg.get("allowedOrigins") or []
        return [o for o in origins if isinstance(o, str)]

    @staticmethod
    def _has_secret(conn: Connection) -> bool:
        token = conn.credentials_json or ""
        if not token:
            return False
        try:
            creds = decrypt_secret(token)
        except (InvalidToken, ValueError, TypeError):
            return False
        return bool((creds or {}).get("embedSecret"))

    # ── writes ───────────────────────────────────────────────────────────────
    def enable(self, tenant_id: str) -> Dict:
        """Create the embed connection if absent (idempotent). No secret yet —
        the admin rotates one in as a separate, explicit step."""
        conn = self.connections.get_by_provider(tenant_id, EMBED_PROVIDER)
        if conn is None:
            conn = Connection(
                tenant_id=tenant_id,
                provider=EMBED_PROVIDER,
                type=EMBED_TYPE,
                name=EMBED_CONNECTION_NAME,
                config_json={"allowedOrigins": []},
                credentials_json="",
                status=CONNECTION_STATUS_ACTIVE,
            )
            self.connections.create(conn)
            self.db.commit()
        return self._config_payload(tenant_id, conn)

    def rotate_secret(self, tenant_id: str) -> Dict:
        """Generate a strong secret, store it Fernet-encrypted, and return the
        PLAINTEXT exactly once. Rotation invalidates every outstanding assertion
        (they fail signature against the new secret) — automatic, no ledger."""
        conn = self.connections.get_by_provider(tenant_id, EMBED_PROVIDER)
        if conn is None:
            raise EmbedNotEnabled()
        secret = pysecrets.token_urlsafe(SECRET_ENTROPY_BYTES)
        conn.credentials_json = encrypt_secret({"embedSecret": secret})
        self.db.commit()
        return {"embedSecret": secret}

    def set_origins(self, tenant_id: str, origins: List[str]) -> Dict:
        """Validate + dedupe + persist the allowed parent origins. Merge-safe —
        other ``config_json`` keys are preserved."""
        conn = self.connections.get_by_provider(tenant_id, EMBED_PROVIDER)
        if conn is None:
            raise EmbedNotEnabled()
        clean = _validate_origins(origins)
        # Reassign a NEW dict so SQLAlchemy tracks the JSON change.
        conn.config_json = {**(conn.config_json or {}), "allowedOrigins": clean}
        self.db.commit()
        return self._config_payload(tenant_id, conn)
