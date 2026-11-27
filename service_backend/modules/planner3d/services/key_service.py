"""Planner 3D gateway keys (contract 2.1) - ``fx3_live_`` + secret, returned ONCE.

Only a sha256 hash and an 8-char lookup prefix are stored; matching uses
``hmac.compare_digest``. Repeats ``modules/lead_capture/services/key_service.py``
(cross-module imports are forbidden, so the code is repeated - BL-SS-210).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import P3ApiKey

KEY_SCHEME = "fx3_live_"
PREFIX_LEN = 8


class KeyNotFound(Exception):
    pass


def _hash(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def _prefix(full_key: str) -> str:
    return full_key[len(KEY_SCHEME): len(KEY_SCHEME) + PREFIX_LEN]


def masked(row: P3ApiKey) -> str:
    """``fx3_live_****`` + the last 4 characters only."""
    return f"{KEY_SCHEME}****{row.key_last4}"


def issue(db: Session, tenant_id: str, *, name: str, created_by: Optional[str]) -> Tuple[P3ApiKey, str]:
    full_key = KEY_SCHEME + secrets.token_urlsafe(32)
    row = P3ApiKey(
        tenant_id=tenant_id,
        name=(name or "").strip()[:200] or "3D Planner key",
        key_prefix=_prefix(full_key),
        key_hash=_hash(full_key),
        key_last4=full_key[-4:],
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, full_key


def resolve(db: Session, presented: Optional[str]) -> Optional[P3ApiKey]:
    """Uniform None for missing/malformed/unknown/revoked. The hash is computed
    whatever the input's shape (no timing difference between the cases)."""
    presented_hash = _hash(presented or "")
    if not (presented and presented.startswith(KEY_SCHEME) and len(presented) > len(KEY_SCHEME) + PREFIX_LEN):
        return None
    for row in db.query(P3ApiKey).filter(P3ApiKey.key_prefix == _prefix(presented)).all():
        if hmac.compare_digest(row.key_hash, presented_hash) and row.revoked_at is None:
            return row
    return None


def mark_used(db: Session, row: P3ApiKey) -> None:
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()


def revoke(db: Session, tenant_id: str, key_id: str) -> P3ApiKey:
    """Revoke one of the tenant's keys (idempotent). Another tenant's id = KeyNotFound."""
    row = db.query(P3ApiKey).filter(P3ApiKey.id == key_id, P3ApiKey.tenant_id == tenant_id).first()
    if row is None:
        raise KeyNotFound()
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    return row


def list_keys(db: Session, tenant_id: str) -> List[P3ApiKey]:
    return (
        db.query(P3ApiKey)
        .filter(P3ApiKey.tenant_id == tenant_id)
        .order_by(P3ApiKey.created_at.desc(), P3ApiKey.id.asc())
        .all()
    )
