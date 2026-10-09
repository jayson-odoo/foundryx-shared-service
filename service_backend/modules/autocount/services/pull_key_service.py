"""Sprint-5/10 S4 - pull API key issuance + resolution (AC-10-27/28/47).

Mirrors the omnichannel precedent (``modules.omnichannel.models.
WorkspaceApiKey`` + ``services.api_key_service.ApiKeyService``) in SPIRIT -
scheme-prefixed plaintext returned ONCE, only a sha256 hash + an 8-char
indexed lookup prefix stored, ``hmac.compare_digest`` for the match,
``last_used_at`` stamped once a call is genuinely served - but is REIMPLEMENTED
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
from ..repositories import CompanyRepository, PullKeyRepository
from .company_service import AutocountServiceError

KEY_SCHEME = "fxa_live_"
PREFIX_LEN = 8  # chars after the scheme used for the O(1) lookup

# The ONE uniform message for every reason a company id could be rejected at
# issue time (unknown entirely, or real but in another tenant) - the two
# cases are deliberately indistinguishable on the wire (security round 1
# HIGH 2's own "does not reveal whether the id exists in another tenant").
_UNKNOWN_COMPANY_MESSAGE = "companyIds must name companies that exist in this tenant."


class PullKeyNotFound(AutocountServiceError):
    """Unknown key id, or one belonging to another tenant. ``revoke`` is
    ALWAYS tenant-scoped (AC-10-47's polymorphic-id rule) - unlike
    ``resolve``, which genuinely does not know the tenant until AFTER it
    resolves the key."""


class PullKeyValidationError(AutocountServiceError):
    """Sprint-5/10 S4 security round 1, HIGH 2 - ``issue()`` rejected
    ``company_ids`` at SAVE TIME (the polymorphic-stored-id rule: a stored
    id needs save-time validation AND tenant-scoped resolution at use time -
    this class was previously missing the first half). ``field_errors``
    mirrors ``EtlValidationError``'s own per-field 422 shape so the router
    can render it the same way."""

    def __init__(self, field_errors: dict):
        super().__init__("The key could not be issued. Fix the highlighted fields.")
        self.field_errors = field_errors


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
        persisted, never re-derivable, never logged.

        Security round 1 HIGH 2 - ``company_ids`` is validated here, not
        merely at use time: empty, a repeated id, or ANY id that does not
        resolve to a company in THIS tenant (unknown entirely, or real but
        belonging to another tenant - deliberately indistinguishable, see
        ``_UNKNOWN_COMPANY_MESSAGE``) all raise ``PullKeyValidationError``
        before a single row is written.
        """
        ids = list(company_ids or [])
        if not ids:
            raise PullKeyValidationError(
                {"companyIds": "Choose at least one company."}
            )
        if len(ids) != len(set(ids)):
            raise PullKeyValidationError(
                {"companyIds": "companyIds must not repeat a company."}
            )
        company_repo = CompanyRepository(self.db)
        for company_id in ids:
            if company_repo.get(tenant_id, company_id) is None:
                raise PullKeyValidationError({"companyIds": _UNKNOWN_COMPANY_MESSAGE})

        full_key = KEY_SCHEME + secrets.token_urlsafe(32)
        row = AcPullApiKey(
            tenant_id=tenant_id,
            name=(name or "").strip() or "Pull API key",
            key_prefix=_prefix_of(full_key),
            key_hash=_hash_key(full_key),
            company_ids=ids,
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
        never giving a timing oracle between the two.

        AC-10-58 L5 - resolution does NOT stamp ``last_used_at``: a key whose
        tenant is suspended, or whose module is deactivated, is refused one
        step later (``pull_auth._service_enabled``) and must not record usage
        for a call that was never served. The caller stamps with
        ``mark_used`` once that gate passes."""
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
        return match

    def mark_used(self, key_row: AcPullApiKey) -> AcPullApiKey:
        """Stamp ``last_used_at`` - called by ``pull_auth.resolve_pull_key``
        only AFTER the service gate passes (AC-10-58 L5), so the column means
        "this key last had a call served", never "somebody presented it"."""
        key_row.last_used_at = datetime.now(timezone.utc)
        self.db.commit()
        return key_row

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
