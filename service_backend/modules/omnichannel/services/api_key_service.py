"""Workspace API-key issuance + resolution (plan sprint-1/01 Slice 3).

Security invariants:
- The plaintext key is generated, returned ONCE, and never persisted — only a
  SHA-256 hash + an 8-char lookup prefix are stored.
- Verification is constant-time (`hmac.compare_digest`) over the hash, guarded
  by an indexed prefix lookup so it stays O(1).
- Resolution derives (tenant, workspace) FROM the key — never from client input.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import WorkspaceApiKey, Workspace

KEY_SCHEME = "fxw_live_"
PREFIX_LEN = 8  # chars after the scheme used for the O(1) lookup


def _hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def _prefix_of(full_key: str) -> str:
    """The 8 lookup chars immediately after the ``fxw_live_`` scheme."""
    return full_key[len(KEY_SCHEME) : len(KEY_SCHEME) + PREFIX_LEN]


class ApiKeyService:
    def __init__(self, db: Session):
        self.db = db

    # ── Issuance ─────────────────────────────────────────────────────────────
    def mint(
        self, tenant_id: str, workspace_id: str, name: str, created_by: Optional[str]
    ) -> Tuple[WorkspaceApiKey, str]:
        """Create a key, returning (row, full_plaintext_key). The plaintext is
        the ONLY time the caller ever sees the full key."""
        workspace = (
            self.db.query(Workspace)
            .filter(Workspace.tenant_id == tenant_id, Workspace.id == workspace_id)
            .first()
        )
        if workspace is None:
            raise ValueError("Workspace not found.")

        full_key = KEY_SCHEME + secrets.token_urlsafe(32)
        row = WorkspaceApiKey(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=(name or "").strip() or "API key",
            key_prefix=_prefix_of(full_key),
            key_hash=_hash_key(full_key),
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row, full_key

    def revoke(self, key_id: str, tenant_id: str, workspace_id: str) -> WorkspaceApiKey:
        row = (
            self.db.query(WorkspaceApiKey)
            .filter(
                WorkspaceApiKey.id == key_id,
                WorkspaceApiKey.tenant_id == tenant_id,
                WorkspaceApiKey.workspace_id == workspace_id,
            )
            .first()
        )
        if row is None:
            raise ValueError("API key not found.")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(row)
        return row

    def list_for_workspace(
        self, tenant_id: str, workspace_id: str
    ) -> List[WorkspaceApiKey]:
        return (
            self.db.query(WorkspaceApiKey)
            .filter(
                WorkspaceApiKey.tenant_id == tenant_id,
                WorkspaceApiKey.workspace_id == workspace_id,
            )
            .order_by(WorkspaceApiKey.created_at.desc())
            .all()
        )

    # ── Resolution (public-gateway auth) ─────────────────────────────────────
    def resolve(self, presented_key: str) -> Optional[WorkspaceApiKey]:
        """Look up an active key by prefix + constant-time hash compare, stamp
        ``last_used_at``. Returns None for any miss (unknown/revoked/malformed) —
        the caller maps a uniform 401 with no enumeration."""
        if not presented_key or not presented_key.startswith(KEY_SCHEME):
            return None
        prefix = _prefix_of(presented_key)
        if len(prefix) < PREFIX_LEN:
            return None
        presented_hash = _hash_key(presented_key)
        candidates = (
            self.db.query(WorkspaceApiKey)
            .filter(
                WorkspaceApiKey.key_prefix == prefix,
                WorkspaceApiKey.revoked_at.is_(None),
            )
            .all()
        )
        match: Optional[WorkspaceApiKey] = None
        for row in candidates:
            if hmac.compare_digest(row.key_hash, presented_hash):
                match = row
                break
        if match is None:
            return None
        match.last_used_at = datetime.now(timezone.utc)
        self.db.commit()
        return match
