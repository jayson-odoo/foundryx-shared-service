"""Numbering repository (sprint-4/07) — pure SQLAlchemy, tenant-scoped.

The counter access is the load-bearing piece: ``get_counter_for_update`` locks
the (tenant, doc_type, period_key) row ``FOR UPDATE`` on Postgres so concurrent
``next_number`` callers serialise; on SQLite (tests) the lock is a no-op but the
single-connection StaticPool makes the read-modify-write atomic anyway.
"""
from typing import Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.numbering import NumberCounter, NumberFormat


class NumberingRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── format overrides ──────────────────────────────────────────────────
    def list_formats(self, tenant_id: str) -> Dict[str, NumberFormat]:
        rows = (
            self.db.query(NumberFormat)
            .filter(NumberFormat.tenant_id == tenant_id)
            .all()
        )
        return {row.doc_type: row for row in rows}

    def get_format(self, tenant_id: str, doc_type: str) -> Optional[NumberFormat]:
        return (
            self.db.query(NumberFormat)
            .filter(
                NumberFormat.tenant_id == tenant_id,
                NumberFormat.doc_type == doc_type,
            )
            .first()
        )

    def upsert_format(
        self,
        tenant_id: str,
        doc_type: str,
        prefix: str,
        format_pattern: str,
        reset_period: str,
        updated_by: Optional[str],
    ) -> NumberFormat:
        row = self.get_format(tenant_id, doc_type)
        if row is None:
            row = NumberFormat(tenant_id=tenant_id, doc_type=doc_type)
            self.db.add(row)
        row.prefix = prefix
        row.format_pattern = format_pattern
        row.reset_period = reset_period
        row.updated_by = updated_by
        self.db.flush()
        return row

    def delete_format(self, tenant_id: str, doc_type: str) -> bool:
        row = self.get_format(tenant_id, doc_type)
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True

    # ── counters ──────────────────────────────────────────────────────────
    def get_counter(
        self, tenant_id: str, doc_type: str, period_key: str
    ) -> Optional[NumberCounter]:
        return (
            self.db.query(NumberCounter)
            .filter(
                NumberCounter.tenant_id == tenant_id,
                NumberCounter.doc_type == doc_type,
                NumberCounter.period_key == period_key,
            )
            .first()
        )

    def get_counter_for_update(
        self, tenant_id: str, doc_type: str, period_key: str
    ) -> Optional[NumberCounter]:
        """Lock the counter row ``FOR UPDATE`` (Postgres) — concurrency safety
        (AC-07-04). No-op lock on SQLite, but reads are serialised there anyway."""
        q = self.db.query(NumberCounter).filter(
            NumberCounter.tenant_id == tenant_id,
            NumberCounter.doc_type == doc_type,
            NumberCounter.period_key == period_key,
        )
        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            q = q.with_for_update()
        return q.first()

    def create_counter(
        self, tenant_id: str, doc_type: str, period_key: str, start: int = 1
    ) -> NumberCounter:
        row = NumberCounter(
            tenant_id=tenant_id,
            doc_type=doc_type,
            period_key=period_key,
            next_val=start,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_or_create_counter_for_update(
        self, tenant_id: str, doc_type: str, period_key: str, start: int = 1
    ) -> NumberCounter:
        """Race-safe lock-or-create of the (tenant, doc_type, period_key) counter.

        ``FOR UPDATE`` locks nothing when no row exists yet (DEFECT-1), so two
        concurrent first-of-period callers would both create → the loser's INSERT
        trips ``uq_number_counter_tenant_doctype_period`` and 500s. We INSERT
        inside a SAVEPOINT (``begin_nested``); on the unique-violation we roll the
        SAVEPOINT back and re-fetch under lock (the winner's row now exists and is
        locked, so the loser serialises behind it). Portable across Postgres
        (real row lock) and SQLite tests (StaticPool serialises anyway).
        """
        counter = self.get_counter_for_update(tenant_id, doc_type, period_key)
        if counter is not None:
            return counter
        try:
            with self.db.begin_nested():
                row = NumberCounter(
                    tenant_id=tenant_id,
                    doc_type=doc_type,
                    period_key=period_key,
                    next_val=start,
                )
                self.db.add(row)
                self.db.flush()
            return row
        except IntegrityError:
            # A concurrent caller won the create — re-fetch its row under lock.
            counter = self.get_counter_for_update(tenant_id, doc_type, period_key)
            if counter is None:  # pragma: no cover - constraint guarantees a row
                raise
            return counter
