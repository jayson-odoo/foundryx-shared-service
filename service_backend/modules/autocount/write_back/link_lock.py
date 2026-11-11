"""Serialise the over-link guard and its write per SO row (plan 62 review).

The guard reads ``ac_po_so_link`` and the PUT follows; two callers linking the same SO row could both
pass the guard. Postgres only: a SESSION advisory lock per (company, SO row), released in ``finally``. A
transaction-level lock would not do, because the operation commits several times between the guard and the
PUT; a session lock on the Session's own pooled connection could leak onto a different checkout. The lock
connection comes from a small dedicated engine (built once per database URL from the session's bind: a few
connections, no overflow, a short pool timeout, AUTOCOMMIT so it never idles inside a transaction), never from
the application pool, so waiting lock holders cannot starve ordinary requests. Keys are taken in sorted order
(no deadlock). A lock not won within the wait budget, a failed connect or an exhausted lock pool is
``SoRowBusy`` (a ``DOC_BUSY`` refusal, nothing sent, the key stays usable). SQLite (tests) takes no lock.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

logger = logging.getLogger("foundryx.autocount")

WAIT_SECONDS = 30.0
POLL_SECONDS = 0.1
LOCK_POOL_SIZE = 5
LOCK_POOL_TIMEOUT = 5

_engines: Dict[str, Any] = {}
_engines_guard = threading.Lock()


class SoRowBusy(Exception):
    """Another caller holds a lock on the same SO row for longer than the wait budget, or no lock
    connection is available."""


def _lock_engine(bind: Any) -> Any:
    """The dedicated lock engine for the database of ``bind`` (built once per URL); ``bind`` itself when it
    carries no URL (a test double)."""
    url = getattr(bind, "url", None)
    if url is None:
        return bind
    key = url.render_as_string(hide_password=False)
    with _engines_guard:
        engine = _engines.get(key)
        if engine is None:
            engine = create_engine(
                url, pool_size=LOCK_POOL_SIZE, max_overflow=0, pool_timeout=LOCK_POOL_TIMEOUT,
                pool_pre_ping=True, isolation_level="AUTOCOMMIT",
            )
            _engines[key] = engine
    return engine


@contextmanager
def so_row_locks(db: Session, company_id: str, so_dtl_keys: Iterable[int]) -> Iterator[None]:
    bind = db.get_bind()
    keys = sorted({int(k) for k in so_dtl_keys if k})
    if not keys or bind.dialect.name != "postgresql":
        yield
        return
    try:
        conn = _lock_engine(getattr(bind, "engine", bind)).connect()
    except Exception:  # noqa: BLE001 - no lock connection (down, pool exhausted): busy, never a crash
        logger.warning("autocount SO row lock connection unavailable")
        raise SoRowBusy() from None
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
            conn.close()
        except Exception:  # noqa: BLE001 - a lock that cannot be released must not return to the pool
            logger.exception("autocount SO row lock release failed")
            try:
                conn.invalidate()
            except Exception:  # noqa: BLE001
                pass
