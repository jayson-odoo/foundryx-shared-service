"""Serialise the over-link guard and its write per PO document and per SO row (plan 62 review, POL lane).

The guard reads ``ac_po_so_link`` and the PUT follows; two callers linking the same SO row could both
pass the guard. Postgres only: a SESSION advisory lock per (company, SO row), released in ``finally``. A
transaction-level lock would not do, because the operation commits several times between the guard and the
PUT; a session lock on the Session's own pooled connection could leak onto a different checkout. The lock
connection comes from a small dedicated engine (built once per database URL from the session's bind: a few
connections, no overflow, a short pool timeout, AUTOCOMMIT so it never idles inside a transaction), never from
the application pool, so waiting lock holders cannot starve ordinary requests. Keys are taken in sorted order
(no deadlock). A lock not won within the wait budget, a failed connect or an exhausted lock pool is
``SoRowBusy`` (a ``DOC_BUSY`` refusal, nothing sent, the key stays usable). SQLite (tests) takes no lock.

The per-SO-row lock alone does not serialise the same PO row linked to two DIFFERENT SO rows; every
operation that writes a PO therefore also takes a per-PO-document lock, always BEFORE its SO row locks.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterable, Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

logger = logging.getLogger("foundryx.autocount")

WAIT_SECONDS = 30.0
POLL_SECONDS = 0.1
LOCK_POOL_SIZE = 5
LOCK_POOL_TIMEOUT = 5

_engines: Dict[str, Any] = {}
_engines_guard = threading.Lock()
_held: "ContextVar[Optional[Any]]" = ContextVar("autocount_write_lock_conn", default=None)


class SoRowBusy(Exception):
    """Another caller holds a lock on the same PO document or SO row for longer than the wait budget, or no
    lock connection is available."""


def _connect_args(url: Any) -> Dict[str, str]:
    """The app's ``application_name`` (so the lock connections show up in pg_stat_activity like every other
    connection of this process, ``-lock`` appended); nothing else of the app's connect args."""
    from app.database import app_connect_args

    name = app_connect_args(str(url)).get("application_name")
    return {"application_name": f"{name}-lock"} if name else {}


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
                connect_args=_connect_args(url),
            )
            _engines[key] = engine
    return engine


def _po_token(company_id: str, doc_key: int) -> str:
    return f"po-doc:{company_id}:{doc_key}"


def _so_token(company_id: str, so_dtl_key: int) -> str:
    return f"po-so-link:{company_id}:{so_dtl_key}"


@contextmanager
def link_locks(
    db: Session, company_id: str, *, po_doc_keys: Iterable[int] = (), so_dtl_keys: Iterable[int] = ()
) -> Iterator[None]:
    """The per-PO-document locks, then the per-SO-row locks (that order, each set sorted), on ONE lock
    connection. Nested inside a lock already held by this call chain (an operation running the plan 55 split
    link), the held connection is reused: an advisory lock is re-entrant per session, so a lock this chain
    already holds is taken again at once, and only the locks taken at this level are released at its end."""
    bind = db.get_bind()
    tokens = [_po_token(company_id, k) for k in sorted({int(k) for k in po_doc_keys if k})]
    tokens += [_so_token(company_id, k) for k in sorted({int(k) for k in so_dtl_keys if k})]
    if not tokens or bind.dialect.name != "postgresql":
        yield
        return
    outer = _held.get()
    if outer is None:
        try:
            conn = _lock_engine(getattr(bind, "engine", bind)).connect()
        except Exception:  # noqa: BLE001 - no lock connection (down, pool exhausted): busy, never a crash
            logger.warning("autocount write lock connection unavailable")
            raise SoRowBusy() from None
        reset = _held.set(conn)
    else:
        conn = outer
    taken: list = []
    try:
        deadline = time.monotonic() + WAIT_SECONDS
        for token in tokens:
            while True:
                try:
                    got = conn.execute(
                        text("SELECT pg_try_advisory_lock(hashtextextended(:t, 0))"), {"t": token}).scalar()
                except Exception:  # noqa: BLE001 - a lock connection that broke before the body ran: busy, nothing sent
                    logger.warning("autocount write lock take failed")
                    raise SoRowBusy() from None
                if got:
                    taken.append(token)
                    break
                if time.monotonic() > deadline:
                    raise SoRowBusy()
                time.sleep(POLL_SECONDS)
        yield
    finally:
        if outer is None:
            _held.reset(reset)
            _release_all(conn)
        else:
            _release(conn, taken)


@contextmanager
def so_row_locks(db: Session, company_id: str, so_dtl_keys: Iterable[int]) -> Iterator[None]:
    with link_locks(db, company_id, so_dtl_keys=so_dtl_keys):
        yield


def _release(conn: Any, tokens: list) -> None:
    """Release the locks one nested level took (the outer level releases everything at its end)."""
    try:
        for token in reversed(tokens):
            conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:t, 0))"), {"t": token})
    except Exception:  # noqa: BLE001 - the outer level still releases everything (or invalidates the connection)
        logger.exception("autocount nested write lock release failed")


def _release_all(conn: Any) -> None:
    try:
        conn.execute(text("SELECT pg_advisory_unlock_all()"))
        conn.close()
    except Exception:  # noqa: BLE001 - a lock that cannot be released must not return to the pool
        logger.exception("autocount write lock release failed")
        try:
            conn.invalidate()
        except Exception:  # noqa: BLE001
            pass
