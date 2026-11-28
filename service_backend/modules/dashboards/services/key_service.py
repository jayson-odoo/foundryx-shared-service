"""Dashboards gateway keys (contract 1) - ``fxd_live_`` + secret, returned ONCE, bound to a tenant AND a product.

Only a sha256 hash and an 8-char lookup prefix are stored; matching uses ``hmac.compare_digest``.
Repeats ``modules/planner3d/services/key_service.py`` (cross-module imports are forbidden, BL-SS-210).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import DashApiKey
from ..repositories.key_repository import KeyRepository

KEY_SCHEME = "fxd_live_"
PREFIX_LEN = 8
PRODUCTS = ("sorento_crm", "ecohub")


class KeyNotFound(Exception):
    pass


def _hash(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def _prefix(full_key: str) -> str:
    return full_key[len(KEY_SCHEME): len(KEY_SCHEME) + PREFIX_LEN]


def masked(row: DashApiKey) -> str:
    """``fxd_live_****`` + the last 4 characters only."""
    return f"{KEY_SCHEME}****{row.key_last4}"


def issue(db: Session, tenant_id: str, *, product: str, name: str, created_by: Optional[str]) -> Tuple[DashApiKey, str]:
    full_key = KEY_SCHEME + secrets.token_urlsafe(32)
    row = KeyRepository(db).add(DashApiKey(
        tenant_id=tenant_id,
        product=product,
        name=(name or "").strip()[:200] or "Dashboards key",
        key_prefix=_prefix(full_key),
        key_hash=_hash(full_key),
        key_last4=full_key[-4:],
        created_by=created_by,
    ))
    db.commit()
    db.refresh(row)
    return row, full_key


def resolve(db: Session, presented: Optional[str]) -> Optional[DashApiKey]:
    """Uniform None for missing/malformed/unknown/revoked. The hash is computed whatever
    the input's shape (no timing difference between the cases)."""
    presented_hash = _hash(presented or "")
    if not (presented and presented.startswith(KEY_SCHEME) and len(presented) > len(KEY_SCHEME) + PREFIX_LEN):
        return None
    for row in KeyRepository(db).by_prefix(_prefix(presented)):
        if hmac.compare_digest(row.key_hash, presented_hash) and row.revoked_at is None:
            return row
    return None


def mark_used(db: Session, row: DashApiKey) -> None:
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()


def revoke(db: Session, tenant_id: str, key_id: str) -> DashApiKey:
    """Revoke one of the tenant's keys (idempotent). Another tenant's id = KeyNotFound."""
    row = KeyRepository(db).get(tenant_id, key_id)
    if row is None:
        raise KeyNotFound()
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    return row


def list_keys(db: Session, tenant_id: str) -> List[DashApiKey]:
    return KeyRepository(db).list(tenant_id)
