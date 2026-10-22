"""Database configuration and session management."""
import logging
import os
import re
import sys
import threading
import weakref
from contextvars import ContextVar
from typing import Dict, Generator, List, Optional, Tuple

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

_READ_TXN_KEY = "foundryx_read_txn"
# Connections whose current transaction ran anything but a plain SELECT.
_wrote: "weakref.WeakSet[Connection]" = weakref.WeakSet()
_LOCKING = re.compile(
    r"\bFOR\s+(?:NO\s+KEY\s+UPDATE|UPDATE|KEY\s+SHARE|SHARE)\b"
    r"|ADVISORY_XACT_LOCK|\bSET_CONFIG\s*\(",
    re.IGNORECASE,
)


class _ReadTxn:
    """Bookkeeping for one autobegun session transaction, kept in
    ``session.info`` while the transaction lives. Its identity is the token
    a registry entry must match, so an entry left in a context that outlived
    its transaction can never act on the session's NEXT transaction."""

    __slots__ = ("transaction", "connections")

    def __init__(self, transaction: SessionTransaction, connection: Connection) -> None:
        self.transaction = transaction
        self.connections: List["weakref.ref[Connection]"] = [weakref.ref(connection)]


# Interpreters whose new threads start with a COPY of the caller's context
# (free-threaded 3.13+ by default) would hand a pool thread its caller's scope
# while the caller still uses the session; there, an entry stays pinned to the
# thread that registered it. Prod (python:3.12) never inherits: a pool thread
# starts with an empty context, so it can never see its caller's scope.
_THREADS_INHERIT_CONTEXT = bool(getattr(sys.flags, "thread_inherit_context", False))


class _Scope:
    """One unit of work's registry of autobegun session transactions.

    Mutable on purpose: FastAPI runs a request's sync auth dependency (where
    the request's transaction begins, reading the user), its endpoint and
    get_db's close as separate threadpool hops, each in a COPY of the request
    context and often on different pool threads. Every copy holds this same
    object, so a seam in the endpoint hop sees what the dependency hop began.
    Another request gets its own scope (``ReadTransactionScopeMiddleware``).
    """

    __slots__ = ("entries",)

    def __init__(self) -> None:
        self.entries: List[Tuple["weakref.ref[Session]", int, _ReadTxn]] = []


_scope: ContextVar[Optional[_Scope]] = ContextVar("foundryx_read_txn_scope", default=None)


def new_read_transaction_scope() -> None:
    """Start a fresh scope in the current context. One per API request
    (``ReadTransactionScopeMiddleware``); without one, the first transaction
    a context begins creates its own (a Celery worker's main thread, a pool
    thread)."""
    _scope.set(_Scope())


def _current_scope() -> _Scope:
    scope = _scope.get()
    if scope is None:
        scope = _Scope()
        _scope.set(scope)
    return scope


class ReadTransactionScopeMiddleware:
    """Pure ASGI: give every HTTP request its own read-transaction scope, so
    a seam in one request can reach the transaction an earlier hop of the
    SAME request began, and never another request's (pool threads are shared
    by every request)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _scope.set(_Scope())
        try:
            await self.app(scope, receive, send)
        finally:
            _scope.reset(token)


def _statement_is_plain_read(statement: str) -> bool:
    """True only for a SELECT that takes no row lock, no transaction-scoped
    advisory lock and sets no transaction-local setting - the only statements
    whose transaction can be ended under the caller without changing what it
    holds. Anything else (DML, DDL, SAVEPOINT, SET LOCAL, ...) is a write."""
    if statement.lstrip()[:6].upper() != "SELECT":
        return False
    return _LOCKING.search(statement) is None


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
    state = session.info.get(_READ_TXN_KEY)
    if state is not None and state.transaction is transaction:
        state.connections.append(weakref.ref(connection))  # a second bind
        return
    state = _ReadTxn(transaction, connection)
    session.info[_READ_TXN_KEY] = state
    scope = _current_scope()
    scope.entries = [
        entry for entry in scope.entries
        if entry[0]() is not None and entry[0]() is not session
    ] + [(weakref.ref(session), threading.get_ident(), state)]


@event.listens_for(Session, "after_transaction_end")
def _forget_transaction(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is not None:
        return
    state = session.info.pop(_READ_TXN_KEY, None)
    scope = _scope.get()
    if state is not None and scope is not None:
        # An entry left in ANOTHER scope (the transaction ended in a different
        # request) is inert: its token no longer matches ``session.info``.
        scope.entries = [entry for entry in scope.entries if entry[2] is not state]


def release_read_transactions() -> int:
    """End every read-only transaction this thread holds open; return how many.

    Call it right before slow network I/O (a vendor page, a Sorento POST, a
    customer-DB query, a long sleep). A transaction is ended only when it
    autobegan (never inside an explicit ``begin()`` / ``begin_nested()``),
    ran nothing but plain SELECTs and has no pending ORM changes - so no
    write is ever committed early and no unit of work is split. The commit
    does not expire loaded objects: the caller keeps using what it read,
    exactly as before, and its next query simply autobegins a fresh
    transaction. Only sessions of the current scope (this API request, or
    this worker thread) are touched - never another request's, never a
    caller's from a pool thread - so a caller about to fan I/O out to a
    thread pool must call it on its own thread first.
    """
    released = 0
    scope = _scope.get()
    if scope is None:
        return 0
    thread = threading.get_ident()
    for ref, owner, state in list(scope.entries):
        session = ref()
        if session is None or session.info.get(_READ_TXN_KEY) is not state:
            continue
        if _THREADS_INHERIT_CONTEXT and owner != thread:
            continue
        transaction = session.get_transaction()
        if (
            transaction is not state.transaction
            or not transaction.is_active
            or session.in_nested_transaction()
            or session.new
            or session.dirty
            or session.deleted
        ):
            continue
        connections = [conn_ref() for conn_ref in state.connections]
        if any(
            connection is None
            or connection.closed
            or connection.invalidated
            or connection in _wrote
            for connection in connections
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
