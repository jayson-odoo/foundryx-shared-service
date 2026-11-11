"""Serialise the over-link guard and its write per SO row (plan 62 review).

The guard reads ``ac_po_so_link`` and the PUT follows; two callers linking the same SO row could both
pass the guard. Postgres only: one dedicated connection holds a SESSION advisory lock per (company, SO row),
released in ``finally``. A transaction-level lock would not do, because the operation commits several times
between the guard and the PUT; a session lock taken on the Session's own pooled connection could leak onto a
different checkout. Keys are taken in sorted order (no deadlock); a lock not won within the wait budget is a
``DOC_BUSY`` refusal (nothing sent). SQLite (tests) takes no lock.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterable, Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("foundryx.autocount")

WAIT_SECONDS = 30.0
POLL_SECONDS = 0.1


class SoRowBusy(Exception):
    """Another caller holds a lock on the same SO row for longer than the wait budget."""


@contextmanager
def so_row_locks(db: Session, company_id: str, so_dtl_keys: Iterable[int]) -> Iterator[None]:
    bind = db.get_bind()
    keys = sorted({int(k) for k in so_dtl_keys if k})
    if not keys or bind.dialect.name != "postgresql":
        yield
        return
    engine = getattr(bind, "engine", bind)
    conn = engine.connect()
    try:
        deadline = time.monotonic() + WAIT_SECONDS
        for key in keys:
            token = f"po-so-link:{company_id}:{key}"
            while True:
                got = conn.execute(text("SELECT pg_try_advisory_lock(hashtextextended(:t, 0))"), {"t": token}).scalar()
                if got:
                    break
                if time.monotonic() > deadline:
                    raise SoRowBusy()
                time.sleep(POLL_SECONDS)
        yield
    finally:
        try:
            conn.execute(text("SELECT pg_advisory_unlock_all()"))
            conn.commit()
            conn.close()
        except Exception:  # noqa: BLE001 - a lock that cannot be released must not return to the pool
            logger.exception("autocount SO row lock release failed")
            try:
                conn.invalidate()
            except Exception:  # noqa: BLE001
                pass
