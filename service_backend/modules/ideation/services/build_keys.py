"""Build write-back keys (plan ideation-br-send-to-build D8, AC-STB-15).

Scheme-prefixed plaintext (``fxb_live_`` + 32 url-safe chars) returned ONCE; only
a sha256 hash + an 8-char indexed lookup prefix are stored. A deliberate,
module-local mirror of autocount's ``PullKeyService`` (cross-module table reads
are forbidden). ``resolve`` does not know the tenant until AFTER it matches the
key; ``revoke`` and ``list`` are always tenant-scoped.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import BrBuildKey

KEY_SCHEME = "fxb_live_"
PREFIX_LEN = 8
SECRET_LEN = 32


def _hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def _prefix_of(full_key: str) -> str:
    return full_key[len(KEY_SCHEME) : len(KEY_SCHEME) + PREFIX_LEN]


class BuildKeyService:
    def __init__(self, db: Session):
        self.db = db

    def mint(
        self, tenant_id: str, name: str, created_by: Optional[str] = None
    ) -> Tuple[BrBuildKey, str]:
        """Create a key; returns ``(row, plaintext)`` - the only time the caller
        ever sees the plaintext."""
        full_key = KEY_SCHEME + secrets.token_urlsafe(SECRET_LEN)[:SECRET_LEN]
        row = BrBuildKey(
            tenant_id=tenant_id,
            name=(name or "").strip() or "Build key",
            key_prefix=_prefix_of(full_key),
            key_hash=_hash_key(full_key),
            created_by=created_by,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row, full_key

    def resolve(self, presented: Optional[str]) -> Optional[BrBuildKey]:
        """Uniform ``None`` for missing/malformed/wrong-scheme/unknown/revoked.
        The hash is computed regardless of shape (no timing oracle)."""
        presented_hash = _hash_key(presented or "")
        valid_shape = (
            bool(presented)
            and presented.startswith(KEY_SCHEME)
            and len(presented) >= len(KEY_SCHEME) + PREFIX_LEN
        )
        if not valid_shape:
            return None
        candidates = (
            self.db.query(BrBuildKey)
            .filter(
                BrBuildKey.key_prefix == _prefix_of(presented),
                BrBuildKey.revoked_at.is_(None),
            )
            .all()
        )
        for row in candidates:
            if hmac.compare_digest(row.key_hash, presented_hash):
                return row
        return None

    def mark_used(self, row: BrBuildKey) -> None:
        row.last_used_at = datetime.now(timezone.utc)
        self.db.commit()

    def list_for_tenant(self, tenant_id: str) -> List[BrBuildKey]:
        return (
            self.db.query(BrBuildKey)
            .filter(BrBuildKey.tenant_id == tenant_id, BrBuildKey.revoked_at.is_(None))
            .order_by(BrBuildKey.created_at.desc(), BrBuildKey.id.desc())
            .all()
        )

    def revoke(self, key_id: str, tenant_id: str) -> None:
        row = (
            self.db.query(BrBuildKey)
            .filter(BrBuildKey.id == key_id, BrBuildKey.tenant_id == tenant_id)
            .first()
        )
        if row is None:
            raise HTTPException(404, "Key not found.")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            self.db.commit()
