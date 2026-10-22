"""Database configuration and session management."""
import logging
import os
import sys
import threading
import weakref
from typing import Dict, Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import (
    Session,
    SessionTransaction,
    SessionTransactionOrigin,
    declarative_base,
    sessionmaker,
)

from app.config import settings

logger = logging.getLogger(__name__)


def worker_connect_args() -> Dict[str, str]:
    """Settings-driven Postgres session bounds (sprint-5/11 S1, AC-11-85).

    Every worker process (this same ``create_engine`` call, imported by both
    the API and every Celery worker) reads the SAME three settings; the
    settings themselves are 0/unset by default, so the API's behaviour is
    unchanged - only the compose worker services set the envs that make this
    return anything. Returns ``{}`` when all three are 0 (no ``connect_args``
    at all, today's behaviour exactly); otherwise a single Postgres
    ``options`` GUC string carrying only the non-zero timeouts, converted
    from settings-seconds to Postgres-milliseconds.

    Postgres-only (review round 1, S5): the ``options`` GUC string is a
    libpq/Postgres connect arg. A non-Postgres ``DATABASE_URL`` (the pytest
    suite's in-memory sqlite) must never receive it - sqlite's DBAPI raises
    on an unrecognised ``connect_args`` key.
    """
    if not settings.database_url.startswith("postgresql"):
        return {}
    parts = []
    if settings.worker_db_statement_timeout_seconds:
        parts.append(
            f"-c statement_timeout={settings.worker_db_statement_timeout_seconds * 1000}"
        )
    if settings.worker_db_lock_timeout_seconds:
        parts.append(
            f"-c lock_timeout={settings.worker_db_lock_timeout_seconds * 1000}"
        )
    if settings.worker_db_idle_in_transaction_session_timeout_seconds:
        parts.append(
            "-c idle_in_transaction_session_timeout="
            f"{settings.worker_db_idle_in_transaction_session_timeout_seconds * 1000}"
        )
    if not parts:
        return {}
    return {"options": " ".join(parts)}


# Postgres truncates application_name to NAMEDATALEN - 1 bytes.
_APPLICATION_NAME_MAX = 63


def process_application_name() -> str:
    """The Postgres ``application_name`` this process's app-DB connections
    carry (plan 34), so ``pg_stat_activity`` - and the DEPLOY.md lock-holder
    report - names the owner of a held lock instead of an empty string.

    ``settings.db_application_name`` (env ``DB_APPLICATION_NAME``) wins;
    otherwise it is derived from argv: the API (gunicorn/uvicorn) is
    ``foundryx-api``, a Celery worker ``foundryx-worker-<queues>``, beat
    ``foundryx-beat``, any other entry point ``foundryx-<script>``.
    """
    if settings.db_application_name:
        return settings.db_application_name[:_APPLICATION_NAME_MAX]
    argv = list(sys.argv)
    entry = argv[0] if argv else ""
    program = os.path.splitext(os.path.basename(entry))[0]
    if program == "__main__":  # `python -m gunicorn` (start.sh), `python -m celery`
        program = os.path.basename(os.path.dirname(entry))
    if program in ("gunicorn", "uvicorn"):
        name = "foundryx-api"
    elif program == "celery" and "beat" in argv:
        name = "foundryx-beat"
    elif program == "celery" and "worker" in argv:
        queues = ""
        if "-Q" in argv and argv.index("-Q") + 1 < len(argv):
            queues = argv[argv.index("-Q") + 1].replace(",", "+")
        name = f"foundryx-worker-{queues}" if queues else "foundryx-worker"
    else:
        name = f"foundryx-{program}" if program else "foundryx"
    return name[:_APPLICATION_NAME_MAX]


def app_connect_args() -> Dict[str, str]:
    """``connect_args`` for the app engine: ``worker_connect_args()`` plus
    this process's ``application_name``. Postgres-only, for the same reason
    as ``worker_connect_args`` (sqlite's DBAPI rejects unknown keys)."""
    if not settings.database_url.startswith("postgresql"):
        return {}
    return {"application_name": process_application_name(), **worker_connect_args()}


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=settings.debug,
    connect_args=app_connect_args(),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Yield a DB session and ensure it is closed."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Read transactions never outlive a network call (plan 34) ──────────────
#
# Every ORM read autobegins a transaction, and Postgres keeps its
# AccessShareLocks until the transaction ends. A unit of work that reads
# ``ac_company`` / ``ac_entity_config`` and then walks a vendor API or POSTs
# to Sorento for minutes sits "idle in transaction" the whole time, and any
# ``ALTER TABLE`` (a deploy's migration) waits on it until ``lock_timeout``.
# ``release_read_transactions()`` is called by every network seam right
# before its I/O and ends such transactions; it never ends one that wrote.

_CONNECTION_KEY = "foundryx_read_txn_connection"
_thread_state = threading.local()
# Connections whose current transaction ran anything but a plain SELECT.
_wrote: "weakref.WeakSet[Connection]" = weakref.WeakSet()
_LOCKING_CLAUSES = (
    " FOR UPDATE",
    " FOR NO KEY UPDATE",
    " FOR SHARE",
    " FOR KEY SHARE",
    "ADVISORY_XACT_LOCK",
)


def _thread_sessions() -> "weakref.WeakSet[Session]":
    sessions = getattr(_thread_state, "sessions", None)
    if sessions is None:
        sessions = _thread_state.sessions = weakref.WeakSet()
    return sessions


def _statement_is_plain_read(statement: str) -> bool:
    """True only for a SELECT that takes no row lock and no transaction-scoped
    advisory lock - the only statements whose transaction can be ended under
    the caller without changing what it holds. Anything else (DML, DDL,
    SAVEPOINT, SET LOCAL, ...) counts as a write."""
    head = statement.lstrip()[:6].upper()
    if head != "SELECT":
        return False
    upper = statement.upper()
    return not any(clause in upper for clause in _LOCKING_CLAUSES)


@event.listens_for(Engine, "before_cursor_execute")
def _mark_write(conn, cursor, statement, parameters, context, executemany) -> None:
    if executemany or not _statement_is_plain_read(statement):
        _wrote.add(conn)


@event.listens_for(Session, "after_begin")
def _track_autobegun_transaction(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    if transaction.origin is not SessionTransactionOrigin.AUTOBEGIN:
        return
    _wrote.discard(connection)
    session.info[_CONNECTION_KEY] = weakref.ref(connection)
    _thread_sessions().add(session)


@event.listens_for(Session, "after_transaction_end")
def _forget_transaction(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is None:
        session.info.pop(_CONNECTION_KEY, None)
        _thread_sessions().discard(session)


def release_read_transactions() -> int:
    """End every read-only transaction this thread holds open; return how many.

    Call it right before slow network I/O (a vendor page, a Sorento POST, a
    customer-DB query, a long sleep). A transaction is ended only when it
    autobegan (never inside an explicit ``begin()`` / ``begin_nested()``),
    ran nothing but plain SELECTs and has no pending ORM changes - so no
    write is ever committed early and no unit of work is split. The commit
    does not expire loaded objects: the caller keeps using what it read,
    exactly as before, and its next query simply autobegins a fresh
    transaction. Only the calling thread's sessions are touched (a Session
    is not thread-safe).
    """
    released = 0
    for session in list(_thread_sessions()):
        transaction = session.get_transaction()
        if (
            transaction is None
            or not transaction.is_active
            or transaction.origin is not SessionTransactionOrigin.AUTOBEGIN
            or session.in_nested_transaction()
            or session.new
            or session.dirty
            or session.deleted
        ):
            continue
        ref = session.info.get(_CONNECTION_KEY)
        connection = ref() if ref is not None else None
        if (
            connection is None
            or connection.closed
            or connection.invalidated
            or connection in _wrote
        ):
            continue
        expire_on_commit = session.expire_on_commit
        session.expire_on_commit = False
        try:
            session.commit()
        except Exception:  # noqa: BLE001 - never break the caller's network call
            # A session that cannot end its own read transaction is its
            # owner's to roll back; its next statement raises there as before.
            logger.warning("could not end a read transaction before network I/O", exc_info=True)
            continue
        finally:
            session.expire_on_commit = expire_on_commit
        released += 1
    return released
