"""Sprint-5/10 S4 - pull API key issuance + resolution (AC-10-27/28/47).

Mirrors the omnichannel precedent (``modules.omnichannel.models.
WorkspaceApiKey`` + ``services.api_key_service.ApiKeyService``) in SPIRIT -
scheme-prefixed plaintext returned ONCE, only a sha256 hash + an 8-char
indexed lookup prefix stored, ``hmac.compare_digest`` for the match,
``last_used_at`` stamped on every successful resolve - but is REIMPLEMENTED
module-locally (D9): a cross-module table read is exactly what the module-
governance rule forbids. The duplication is acknowledged (BL-SS-210).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from ..models import AcPullApiKey
from ..repositories import PullKeyRepository
from .company_service import AutocountServiceError

KEY_SCHEME = "fxa_live_"
PREFIX_LEN = 8  # chars after the scheme used for the O(1) lookup


class PullKeyNotFound(AutocountServiceError):
    """Unknown key id, or one belonging to another tenant. ``revoke`` is
    ALWAYS tenant-scoped (AC-10-47's polymorphic-id rule) - unlike
    ``resolve``, which genuinely does not know the tenant until AFTER it
    resolves the key."""


def _hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def _prefix_of(full_key: str) -> str:
    """The ``PREFIX_LEN`` lookup chars immediately after the scheme."""
    return full_key[len(KEY_SCHEME) : len(KEY_SCHEME) + PREFIX_LEN]


class PullKeyService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PullKeyRepository(db)

    # ── issuance (AC-10-28) ──────────────────────────────────────────────

    def issue(
        self,
        tenant_id: str,
        *,
        name: str,
        company_ids: Sequence[str],
        created_by: Optional[str] = None,
    ) -> Tuple[AcPullApiKey, str]:
        """Create a key, returning ``(row, full_plaintext_key)``. The
        plaintext is the ONLY time the caller ever sees the full key - never
        persisted, never re-derivable, never logged."""
        full_key = KEY_SCHEME + secrets.token_urlsafe(32)
        row = AcPullApiKey(
            tenant_id=tenant_id,
            name=(name or "").strip() or "Pull API key",
            key_prefix=_prefix_of(full_key),
            key_hash=_hash_key(full_key),
            company_ids=list(dict.fromkeys(company_ids or [])),
            created_by=created_by,
        )
        self.repo.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row, full_key

    # ── resolution (public-gateway auth, AC-10-28/30) ───────────────────

    def resolve(self, presented_key: Optional[str]) -> Optional[AcPullApiKey]:
        """Uniform ``None`` for missing/malformed/wrong-scheme/unknown/
        revoked - the caller maps every one of those to the SAME 401, no
        enumeration. The hash is computed REGARDLESS of the presented
        string's shape (dummy work on the invalid-shape path) precisely so a
        wrong-scheme key and a right-scheme-wrong-secret key cost the same,
        never giving a timing oracle between the two."""
        presented_hash = _hash_key(presented_key or "")
        valid_shape = (
            bool(presented_key)
            and presented_key.startswith(KEY_SCHEME)
            and len(presented_key) >= len(KEY_SCHEME) + PREFIX_LEN
        )
        candidates = self.repo.by_prefix(_prefix_of(presented_key)) if valid_shape else []
        match: Optional[AcPullApiKey] = None
        for row in candidates:
            if hmac.compare_digest(row.key_hash, presented_hash):
                match = row
                break
        if match is None:
            return None
        match.last_used_at = datetime.now(timezone.utc)
        self.db.commit()
        return match

    # ── revoke / list (AC-10-27/47) ─────────────────────────────────────

    def revoke(self, tenant_id: str, key_id: str) -> AcPullApiKey:
        row = self.repo.get(tenant_id, key_id)
        if row is None:
            raise PullKeyNotFound("This pull API key was not found.")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(row)
        return row

    def list_for_tenant(self, tenant_id: str) -> List[AcPullApiKey]:
        return self.repo.list_for_tenant(tenant_id)
