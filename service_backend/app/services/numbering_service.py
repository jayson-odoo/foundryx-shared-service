"""Numbering service (sprint-4/07, Cluster F) - gapless, concurrency-safe
document numbering. Service-Repository, tenant-scoped.

``next_number(db, tenant_id, doc_type, at_date)`` is the engine entry point
(AC-07-04/05/06): resolve the effective format → compute the period bucket →
lock-or-create the counter row → format the running value → increment
``next_val`` → **flush, NOT commit** so the caller owns the transaction (a
caller rollback un-advances the counter = no gap; a Postgres SEQUENCE would
skip on rollback = illegal gap).

The number is assigned at a STATE-CHANGE seam by the CALLER (e.g. a Draft → Issued
transition), not at create - the engine just hands out the next gapless string.
"""
import re
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.module_platform.active import active_modules, is_visible
from app.numbering.registry import (
    RESET_MONTHLY,
    RESET_NEVER,
    RESET_YEARLY,
    NumberSequenceDef,
    is_registered,
    list_sequences,
)
from app.repositories.numbering_repository import NumberingRepository
from app.schemas.numbering import NumberCatalogItem

# Format tokens (AC-07-05). {NNNN…} = the zero-padded running number (pad width =
# the count of N). Date tokens read from ``at_date``. Everything else is literal.
_DATE_TOKENS = {
    "YYYY": "%Y",
    "YY": "%y",
    "MM": "%m",
    "DD": "%d",
}
_RUNNING_RE = re.compile(r"\{(N+)\}")
_TOKEN_RE = re.compile(r"\{(prefix|YYYY|YY|MM|DD|N+)\}")


def period_key_for(reset_period: str, at_date: date) -> str:
    """The bucket key the counter is scoped to (AC-07-05). ``never`` = "" (one
    bucket forever); ``yearly`` = "2026"; ``monthly`` = "2026-06"."""
    if reset_period == RESET_YEARLY:
        return f"{at_date.year:04d}"
    if reset_period == RESET_MONTHLY:
        return f"{at_date.year:04d}-{at_date.month:02d}"
    return ""  # never


def format_number(
    pattern: str, prefix: str, seq: int, at_date: date
) -> str:
    """Substitute the format tokens (AC-07-05). Pure - unit-tested directly.

    ``{prefix}`` → the prefix; date tokens → ``at_date``; ``{NNNN}`` → ``seq``
    zero-padded to the N count; literals pass through untouched.
    """

    def _sub(m: "re.Match[str]") -> str:
        tok = m.group(1)
        if tok == "prefix":
            return prefix
        if tok in _DATE_TOKENS:
            return at_date.strftime(_DATE_TOKENS[tok])
        # running counter - pad width = number of N's
        return str(seq).zfill(len(tok))

    return _TOKEN_RE.sub(_sub, pattern)


class NumberingService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = NumberingRepository(db)

    # ── effective format resolution (override ⊕ registry default) ──────────
    def _effective(self, tenant_id: str, doc_type: str):
        """Return (prefix, format_pattern, reset_period) - the tenant override
        row else the registered default."""
        seq = self._require_registered(doc_type)
        ov = self.repo.get_format(tenant_id, doc_type)
        if ov is not None:
            return ov.prefix, ov.format_pattern, ov.reset_period
        return seq.default_prefix, seq.default_format, seq.default_reset

    def _require_registered(self, doc_type: str) -> NumberSequenceDef:
        from app.numbering.registry import get_sequence

        seq = get_sequence(doc_type)
        if seq is None or not is_registered(doc_type):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown numbering doc type: {doc_type}",
            )
        return seq

    # ── the engine entry point (AC-07-04/05/06) ────────────────────────────
    def next_number(
        self, tenant_id: str, doc_type: str, at_date: Optional[date] = None
    ) -> str:
        """Hand out the next gapless number for ``doc_type``. Increments the
        counter inside the CALLER's transaction (flush, NOT commit) - the caller
        commits/rolls back; a rollback leaves the counter UN-advanced (no gap)."""
        if at_date is None:
            at_date = datetime.now(timezone.utc).date()
        prefix, pattern, reset = self._effective(tenant_id, doc_type)
        pkey = period_key_for(reset, at_date)

        # Race-safe lock-or-create: FOR UPDATE locks nothing when the row is
        # absent, so two concurrent first-of-period callers must not both create
        # (DEFECT-1) - the repo INSERTs in a SAVEPOINT and re-fetches under lock
        # on the unique-violation.
        counter = self.repo.get_or_create_counter_for_update(
            tenant_id, doc_type, pkey, start=1
        )

        seq = counter.next_val
        number = format_number(pattern, prefix, seq, at_date)
        counter.next_val = seq + 1
        self.db.flush()  # NOT commit - caller owns the transaction (AC-07-04)
        return number

    # ── settings surface (AC-07-07) ────────────────────────────────────────
    def _visible_sequences(self, tenant_id: str) -> List[NumberSequenceDef]:
        active = active_modules(self.db, tenant_id)
        return [s for s in list_sequences() if is_visible(s.module, active)]

    def catalog(self, tenant_id: str) -> List[NumberCatalogItem]:
        overrides = self.repo.list_formats(tenant_id)
        today = datetime.now(timezone.utc).date()
        items: List[NumberCatalogItem] = []
        for seq in self._visible_sequences(tenant_id):
            ov = overrides.get(seq.key)
            prefix = ov.prefix if ov else seq.default_prefix
            pattern = ov.format_pattern if ov else seq.default_format
            reset = ov.reset_period if ov else seq.default_reset
            pkey = period_key_for(reset, today)
            counter = self.repo.get_counter(tenant_id, seq.key, pkey)
            next_val = counter.next_val if counter else 1
            items.append(
                NumberCatalogItem(
                    docType=seq.key,
                    label=seq.label,
                    module=seq.module,
                    defaultPrefix=seq.default_prefix,
                    defaultFormat=seq.default_format,
                    defaultReset=seq.default_reset,
                    overridePrefix=ov.prefix if ov else None,
                    overrideFormat=ov.format_pattern if ov else None,
                    overrideReset=ov.reset_period if ov else None,
                    prefix=prefix,
                    formatPattern=pattern,
                    reset=reset,
                    nextVal=next_val,
                    sample=format_number(pattern, prefix, next_val, today),
                )
            )
        return items

    def set_format(
        self,
        tenant_id: str,
        doc_type: str,
        prefix: str,
        format_pattern: str,
        reset_period: str,
        actor_id: Optional[str],
    ) -> None:
        self._require_registered(doc_type)
        self.repo.upsert_format(
            tenant_id, doc_type, prefix, format_pattern, reset_period, actor_id
        )
        self.db.commit()

    def set_next_val(self, tenant_id: str, doc_type: str, next_val: int) -> None:
        """Set the next running value for the CURRENT period (AC-07-07)."""
        prefix, pattern, reset = self._effective(tenant_id, doc_type)
        today = datetime.now(timezone.utc).date()
        pkey = period_key_for(reset, today)
        counter = self.repo.get_counter(tenant_id, doc_type, pkey)
        if counter is None:
            counter = self.repo.create_counter(tenant_id, doc_type, pkey, start=next_val)
        else:
            counter.next_val = next_val
        self.db.commit()

    def reset(self, tenant_id: str, doc_type: str) -> None:
        """Drop the tenant override (revert to the registered default)."""
        self._require_registered(doc_type)
        self.repo.delete_format(tenant_id, doc_type)
        self.db.commit()
