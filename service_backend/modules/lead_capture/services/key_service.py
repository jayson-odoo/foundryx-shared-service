"""Gateway keys (plan 64 D8, AC-64-72) - ``fxl_live_`` + secret, returned ONCE.

Only a sha256 hash and an 8-char lookup prefix are stored; matching uses
``hmac.compare_digest``. Mirrors autocount's ``PullKeyService`` (cross-module
table reads are forbidden, so the code is repeated - BL-SS-210).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import LcApiKey

KEY_SCHEME = "fxl_live_"
PREFIX_LEN = 8


class KeyNotFound(Exception):
    pass


class KeyInUse(Exception):
    """The gateway caller tried to revoke the key it is calling with."""


def _hash(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def _prefix(full_key: str) -> str:
    return full_key[len(KEY_SCHEME): len(KEY_SCHEME) + PREFIX_LEN]


def masked(row: LcApiKey) -> str:
    """AC-64-71: ``****`` + the last 4 characters only."""
    return f"{KEY_SCHEME}****{row.key_last4}"


def issue(db: Session, tenant_id: str, *, name: str, created_by: Optional[str]) -> Tuple[LcApiKey, str]:
    full_key = KEY_SCHEME + secrets.token_urlsafe(32)
    row = LcApiKey(
        tenant_id=tenant_id,
        name=(name or "").strip()[:200] or "Lead Capture key",
        key_prefix=_prefix(full_key),
        key_hash=_hash(full_key),
        key_last4=full_key[-4:],
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, full_key


def resolve(db: Session, presented: Optional[str]) -> Optional[LcApiKey]:
    """Uniform None for missing/malformed/unknown/revoked. The hash is computed
    whatever the input's shape (no timing difference between the cases)."""
    presented_hash = _hash(presented or "")
    if not (presented and presented.startswith(KEY_SCHEME) and len(presented) > len(KEY_SCHEME) + PREFIX_LEN):
        return None
    for row in db.query(LcApiKey).filter(LcApiKey.key_prefix == _prefix(presented)).all():
        if hmac.compare_digest(row.key_hash, presented_hash) and row.revoked_at is None:
            return row
    return None


def mark_used(db: Session, row: LcApiKey) -> None:
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()


def revoke(db: Session, tenant_id: str, key_id: str, *, calling_key_id: Optional[str] = None) -> LcApiKey:
    """Revoke one of the tenant's keys. ``calling_key_id`` (gateway door) is
    the key the request came in with: revoking it would lock the caller out
    mid-request, so it is refused (create the new key, then revoke the old one
    with the new key)."""
    row = db.query(LcApiKey).filter(LcApiKey.id == key_id, LcApiKey.tenant_id == tenant_id).first()
    if row is None:
        raise KeyNotFound()
    if calling_key_id is not None and row.id == calling_key_id:
        raise KeyInUse()
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    return row


def list_keys(db: Session, tenant_id: str) -> List[LcApiKey]:
    return (
        db.query(LcApiKey)
        .filter(LcApiKey.tenant_id == tenant_id)
        .order_by(LcApiKey.created_at.desc(), LcApiKey.id.asc())
        .all()
    )
