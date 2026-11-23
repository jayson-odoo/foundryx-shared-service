"""Partner API keys (``fxp_live_...``): issuance, resolution, revoke, return origins.

A partner key resolves to exactly ONE tenant and authenticates only the partner
routes (``/api/v1/omnichannel/partner/*``). Same storage and verification rules
as the workspace key (``api_key_service``): the plaintext is returned once and
never stored, a SHA-256 hash is compared in constant time behind an indexed
8-char prefix lookup, and the tenant comes FROM the key, never from the request.
The scheme differs (``fxp_live_`` vs ``fxw_live_``), so neither resolver can
ever match the other's keys.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.tenant import Tenant

from ..models import PartnerApiKey
from ..origins import _validate_origins

KEY_SCHEME = "fxp_live_"
PREFIX_LEN = 8


def _hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def _prefix_of(full_key: str) -> str:
    return full_key[len(KEY_SCHEME) : len(KEY_SCHEME) + PREFIX_LEN]


def normalize_origins(origins: Optional[List[str]]) -> Optional[List[str]]:
    """Validated, normalized, deduplicated origins, or None for "none allowed".
    Raises ``origins.InvalidOrigin`` on a bad entry."""
    if origins is None:
        return None
    cleaned = _validate_origins(origins)
    return cleaned or None


class PartnerKeyNotFound(Exception):
    pass


class PartnerKeyService:
    def __init__(self, db: Session):
        self.db = db

    def mint(
        self,
        tenant_id: str,
        name: str,
        created_by: Optional[str],
        allowed_return_origins: Optional[List[str]] = None,
        client_app_id: Optional[str] = None,
    ) -> Tuple[PartnerApiKey, str]:
        """Create a key, returning (row, full plaintext key). The plaintext is
        the only time anyone sees the full key."""
        from .client_app_service import ClientAppService

        origins = normalize_origins(allowed_return_origins)
        full_key = KEY_SCHEME + secrets.token_urlsafe(32)
        # The key acts for the given client app of this tenant (else
        # `ClientAppNotFound`), or the tenant's default when none is given.
        apps = ClientAppService(self.db)
        if client_app_id:
            client_app = apps.require(client_app_id, tenant_id)
        else:
            client_app = apps.default_for_tenant(tenant_id)
        row = PartnerApiKey(
            tenant_id=tenant_id,
            client_app_id=client_app.id,
            name=(name or "").strip() or "Partner key",
            key_prefix=_prefix_of(full_key),
            key_hash=_hash_key(full_key),
            allowed_return_origins=origins,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row, full_key

    def list_for_tenant(self, tenant_id: str) -> List[PartnerApiKey]:
        from .client_app_service import ClientAppService

        # Read fallback: a key (or workspace) an older version wrote without a
        # parent is resolved and persisted first.
        ClientAppService(self.db).heal_tenant(tenant_id)
        self.db.commit()
        return (
            self.db.query(PartnerApiKey)
            .filter(PartnerApiKey.tenant_id == tenant_id)
            .order_by(PartnerApiKey.created_at.desc(), PartnerApiKey.id.asc())
            .all()
        )

    def client_app_names(self, tenant_id: str) -> dict:
        from ..repositories.client_app_repository import ClientAppRepository

        return {a.id: a.name for a in ClientAppRepository(self.db).list_for_tenant(tenant_id)}

    def _get(self, key_id: str, tenant_id: str) -> PartnerApiKey:
        row = (
            self.db.query(PartnerApiKey)
            .filter(PartnerApiKey.id == key_id, PartnerApiKey.tenant_id == tenant_id)
            .first()
        )
        if row is None:
            raise PartnerKeyNotFound()
        return row

    def get(self, key_id: str, tenant_id: str) -> PartnerApiKey:
        return self._get(key_id, tenant_id)

    def revoke(self, key_id: str, tenant_id: str) -> PartnerApiKey:
        """Revoke a key. Repeating it changes nothing."""
        row = self._get(key_id, tenant_id)
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(row)
        return row

    def set_return_origins(
        self, key_id: str, tenant_id: str, origins: Optional[List[str]]
    ) -> PartnerApiKey:
        """Replace the return-origin allow-list (None or [] clears it)."""
        cleaned = normalize_origins(origins)
        row = self._get(key_id, tenant_id)
        row.allowed_return_origins = list(cleaned) if cleaned else None
        self.db.commit()
        self.db.refresh(row)
        return row

    def resolve(self, presented_key: Optional[str]) -> Optional[PartnerApiKey]:
        """An active key by prefix + constant-time hash compare, or None for any
        miss (unknown, revoked, malformed, other scheme)."""
        if not presented_key or not presented_key.startswith(KEY_SCHEME):
            return None
        prefix = _prefix_of(presented_key)
        if len(prefix) < PREFIX_LEN:
            return None
        presented_hash = _hash_key(presented_key)
        candidates = (
            self.db.query(PartnerApiKey)
            .filter(PartnerApiKey.key_prefix == prefix, PartnerApiKey.revoked_at.is_(None))
            .all()
        )
        for row in candidates:
            if hmac.compare_digest(row.key_hash, presented_hash):
                return row
        return None

    def tenant_name(self, tenant_id: str) -> str:
        tenant = self.db.get(Tenant, tenant_id)
        return tenant.name if tenant is not None else ""

    def touch(self, row: PartnerApiKey) -> None:
        """Stamp ``last_used_at`` for an admitted request only."""
        row.last_used_at = datetime.now(timezone.utc)
        self.db.commit()
