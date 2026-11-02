"""Dialect runtime (plan 22 §2.2): URL builder, engine cache, read-only
sessions, per-query timeouts, sanitised errors.

Drivers are pip-only wheels - ``pymssql`` (bundles FreeTDS, no ODBC system
deps), ``psycopg2`` (already present), ``pymysql`` (pure Python). No
``pyodbc`` (would need unixODBC + msodbcsql provisioning on the host).

Read-only enforcement is LAYERED (AC-22-03): the static guard always runs
first; the session is opened read-only where the dialect has it (Postgres
``SET TRANSACTION READ ONLY``, MySQL ``SET SESSION TRANSACTION READ ONLY``;
MSSQL has none - guard + login); every transaction is rolled back; and a
per-query timeout applies on every dialect (Postgres ``statement_timeout``,
MySQL ``MAX_EXECUTION_TIME`` / MariaDB ``max_statement_time`` best-effort,
pymssql ``timeout``).

    !!  Nothing here ever logs or raises a credential or a DSN.  !!

``sanitize_error`` is the ONE place a driver error is turned into an
operator message: a fixed sentence for a known code, otherwise the error class
and code. The driver's text never reaches the message; it goes to the log.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Sequence, Tuple

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, URL

from app.database import release_read_transactions, scrub_error_params
from app.db_errors import db_error_text, error_code_of

from .errors import SqlConnectError, SqlGuardError, SqlQueryError, SqlSourceError

__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "DIALECTS",
    "EXTRACT_TIMEOUT_SECONDS",
    "PREVIEW_ROW_LIMIT",
    "QUERY_TIMEOUT_SECONDS",
    "RUNTIME",
    "SqlConnectError",
    "SqlGuardError",
    "SqlQueryError",
    "SqlSourceError",
    "SqlSourceRuntime",
    "build_url",
    "connect_args_for",
    "dialect_label",
    "open_readonly",
    "sanitize_error",
    "secrets_of",
]

# dbType → (SQLAlchemy driver name, default port, label)
logger = logging.getLogger(__name__)

DIALECTS: Dict[str, Tuple[str, int, str]] = {
    "mssql": ("mssql+pymssql", 1433, "Microsoft SQL Server"),
    "postgresql": ("postgresql+psycopg2", 5432, "PostgreSQL"),
    "mysql": ("mysql+pymysql", 3306, "MySQL"),
}

PREVIEW_ROW_LIMIT = 100
CONNECT_TIMEOUT_SECONDS = 10
QUERY_TIMEOUT_SECONDS = 30
# A real extract (the initial-load preview_task dry run, and every scheduled
# or manual RUN) reads far more than a capped preview and must not share its
# 30s budget (S2 review SHOULD-FIX 5) - a real table easily takes longer.
EXTRACT_TIMEOUT_SECONDS = 300

def dialect_label(db_type: str) -> str:
    entry = DIALECTS.get(str(db_type or "").strip().lower())
    return entry[2] if entry else str(db_type or "")


def build_url(config: Dict[str, Any], credentials: Dict[str, Any]) -> URL:
    """A SQLAlchemy ``URL`` from a ``sql_database`` connection's config +
    DECRYPTED credentials. Raises ``SqlSourceError`` (operator message) when a
    required field is missing or the dialect is not one we ship."""
    db_type = str(config.get("dbType", "")).strip().lower()
    entry = DIALECTS.get(db_type)
    if entry is None:
        raise SqlSourceError(
            "Choose a database type: Microsoft SQL Server, PostgreSQL or MySQL."
        )
    driver, default_port, _label = entry
    host = str(config.get("host", "")).strip()
    if not host:
        raise SqlSourceError("Enter the database host.")
    database = str(config.get("database", "")).strip()
    if not database:
        raise SqlSourceError("Enter the database name.")
    raw_port = str(config.get("port", "") or "").strip()
    port = default_port
    if raw_port:
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise SqlSourceError("The port must be a number.") from exc
        if not (1 <= port <= 65535):
            raise SqlSourceError("The port must be between 1 and 65535.")
    username = str(config.get("username", "") or "").strip() or None
    password = credentials.get("password")
    password = str(password) if password not in (None, "") else None
    return URL.create(
        driver,
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
    )


def connect_args_for(
    db_type: str,
    *,
    connect_timeout: int = CONNECT_TIMEOUT_SECONDS,
    query_timeout: int = QUERY_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Driver-level timeouts so no request can hang on a dead host (AC-22-02).
    MSSQL's per-query timeout lives HERE (pymssql has no session statement);
    Postgres/MySQL get theirs per transaction in ``open_readonly``."""
    db_type = str(db_type or "").strip().lower()
    if db_type == "mssql":
        return {"login_timeout": connect_timeout, "timeout": query_timeout}
    if db_type == "postgresql":
        return {"connect_timeout": connect_timeout}
    if db_type == "mysql":
        return {
            "connect_timeout": connect_timeout,
            "read_timeout": query_timeout,
            "write_timeout": query_timeout,
        }
    return {}


def secrets_of(config: Dict[str, Any], credentials: Dict[str, Any]) -> List[str]:
    """Every value that must never appear in an operator message.

    Only credential VALUES (password etc.) are redacted - the username and
    host live in the plain ``config`` and are deliberately NOT redacted, since
    the operator needs them to make sense of "could not connect to <host>".
    """
    out: List[str] = []
    for value in credentials.values():
        if isinstance(value, str) and len(value) >= 3:
            out.append(value)
    return out


# Failures an operator can act on: driver code (or libpq phrase) ->
# fixed sentence. Anything else is reduced to the error class and code by
# ``db_error_text``. No sentence names a host, user or identifier.
_LOGIN_REFUSED = "The database refused the login. Check the username and password."
_DATABASE_MISSING = "The database name was not found on the server."
_HOST_UNREACHABLE = "The database server could not be reached. Check the host and port."
_TIMED_OUT = "The database did not answer in time."
_TLS_FAILED = "The secure (TLS) connection to the database could not be set up."
_TABLE_MISSING = "A table in the query was not found."
_COLUMN_MISSING = "A column in the query was not found."
_KNOWN_CODES = {
    "18456": _LOGIN_REFUSED, "28P01": _LOGIN_REFUSED, "28000": _LOGIN_REFUSED,
    "1045": _LOGIN_REFUSED,
    "4060": _DATABASE_MISSING, "3D000": _DATABASE_MISSING, "1049": _DATABASE_MISSING,
    "20002": _HOST_UNREACHABLE, "20009": _HOST_UNREACHABLE, "08001": _HOST_UNREACHABLE,
    "2002": _HOST_UNREACHABLE, "2003": _HOST_UNREACHABLE, "2005": _HOST_UNREACHABLE,
    "20003": _TIMED_OUT, "57014": _TIMED_OUT, "2013": _TIMED_OUT,
    "3024": _TIMED_OUT, "1969": _TIMED_OUT,
    "2026": _TLS_FAILED, "20017": _TLS_FAILED,
    "208": _TABLE_MISSING, "42P01": _TABLE_MISSING, "1146": _TABLE_MISSING,
    "207": _COLUMN_MISSING, "42703": _COLUMN_MISSING, "1054": _COLUMN_MISSING,
}

# A psycopg2 connect failure carries no pgcode. Only then, and only on libpq's
# own phrases (never a bare word, which a table or host name could hold), the
# message picks the fixed sentence. First match wins; the text is never returned.
_LIBPQ_PHRASES = (
    (re.compile(r"could not translate host name"), _HOST_UNREACHABLE),
    (re.compile(r"timeout expired"), _TIMED_OUT),
    (re.compile(r"server does not support ssl|\bssl error\b|\bssl connection has been closed"), _TLS_FAILED),
    (re.compile(r"password authentication failed|no pg_hba\.conf entry"), _LOGIN_REFUSED),
    (re.compile(r'\bfatal:\s+role "[^"]*" does not exist'), _LOGIN_REFUSED),
    (re.compile(r'\bfatal:\s+database "[^"]*" does not exist'), _DATABASE_MISSING),
    (re.compile(r"connection refused|name or service not known|no route to host|network is unreachable|could not connect to server"), _HOST_UNREACHABLE),
)


def _libpq_sentence(exc: BaseException) -> str:
    """A fixed sentence for a code-less psycopg2 connect failure, else ``""``.
    An error that carries a pgcode never comes here: it goes through
    ``db_error_text``."""
    orig = getattr(exc, "orig", None)
    if orig is None or type(orig).__module__.split(".")[0] != "psycopg2":
        return ""
    if getattr(orig, "pgcode", None):
        return ""
    try:
        message = str(orig).lower()
    except Exception:  # noqa: BLE001
        return ""
    for pattern, sentence in _LIBPQ_PHRASES:
        if pattern.search(message):
            return sentence
    return ""


def sanitize_error(exc: BaseException, *, secrets: Sequence[str] = ()) -> str:
    """Driver/SQLAlchemy exception -> an operator-safe message.

    Never carries the driver's own text (it can hold table names, row values,
    a host, a user or a DSN). A known code, or a known libpq fragment for a
    code-less Postgres connect failure, maps to a fixed sentence; any other
    error becomes its class and code through ``db_error_text``. The detail
    goes to the server log only. ``secrets`` is kept so callers do not
    change; no output holds driver text, so there is nothing to redact.
    """
    logger.warning("SQL source database error", exc_info=exc)
    code = error_code_of(exc)
    text = (
        _KNOWN_CODES.get(code or "")
        or _libpq_sentence(exc)
        or db_error_text(exc, "The database returned an error", with_constraint=False)
    )
    return text


def _fingerprint(url: URL, config: Dict[str, Any], query_timeout: int) -> str:
    material = (
        url.render_as_string(hide_password=False)
        + json.dumps(
            {k: v for k, v in sorted(config.items()) if not str(k).startswith("_")},
            sort_keys=True,
            default=str,
        )
        + f":qt={int(query_timeout)}"
    )
    return hashlib.sha256(material.encode()).hexdigest()


@contextmanager
def open_readonly(
    engine: Engine, *, timeout_s: int = QUERY_TIMEOUT_SECONDS, secrets: Sequence[str] = ()
) -> Iterator[Connection]:
    """A connection whose transaction is read-only where the dialect supports
    it, time-boxed per query, and ALWAYS rolled back on exit.

    Connect/setup failures raise ``SqlConnectError``; the caller's own
    statements raise whatever they raise (the preview maps those to
    ``SqlQueryError``).

    Plan 34: the pool wait, the connect and the customer-DB queries can each
    take tens of seconds, so the caller's app-DB read transaction is ended
    first - never held (with its ac_* locks) across a customer database.
    """
    release_read_transactions()
    try:
        conn = engine.connect()
    except Exception as exc:  # noqa: BLE001 - every driver has its own class
        raise SqlConnectError(
            "Could not connect to the database: " + sanitize_error(exc, secrets=secrets)
        ) from exc
    try:
        try:
            _begin_readonly(conn, engine.dialect.name, timeout_s)
        except Exception as exc:  # noqa: BLE001
            raise SqlConnectError(
                "Could not open a read-only session: " + sanitize_error(exc, secrets=secrets)
            ) from exc
        yield conn
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def _begin_readonly(conn: Connection, dialect: str, timeout_s: int) -> None:
    millis = max(1, int(timeout_s)) * 1000
    if dialect == "postgresql":
        # Both are transaction-scoped: SQLAlchemy autobegins on the first
        # execute, so these open the transaction the query then runs in.
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {millis}")
    elif dialect == "mysql":
        # Session-scoped: they govern the NEXT transaction, so end the implicit
        # one they ran in - the query below autobegins a fresh read-only txn.
        # READ ONLY is mandatory (a failure propagates → SqlConnectError); the
        # timeout pragma is best-effort - see ``_set_mysql_timeout``.
        conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
        _set_mysql_timeout(conn, timeout_s)
        conn.rollback()
    # mssql: no session-level read-only; the guard + the login + pymssql's
    # per-query ``timeout`` (connect_args) are the layers. sqlite (tests): none.


def _set_mysql_timeout(conn: Connection, timeout_s: int) -> None:
    """Best-effort per-query timeout for the MySQL family (S1 review).

    MySQL 5.7+ has ``MAX_EXECUTION_TIME`` (milliseconds); MariaDB does not and
    errors on it - it has ``max_statement_time`` (seconds) instead. Try each
    in turn; when neither is accepted the session runs WITHOUT a server-side
    timeout rather than failing the whole preview - pymysql's
    ``read_timeout`` (connect_args) still bounds the wait client-side, and
    the read-only transaction is never skipped (it is set before this runs).
    """
    seconds = max(1, int(timeout_s))
    for pragma in (
        f"SET SESSION MAX_EXECUTION_TIME = {seconds * 1000}",
        f"SET SESSION max_statement_time = {seconds}",
    ):
        try:
            conn.exec_driver_sql(pragma)
            return
        except Exception:  # noqa: BLE001 - unknown variable on this server flavour
            continue


class SqlSourceRuntime:
    """Engine cache keyed by (connection id, query timeout) (plan 22 §2.2).

    One small pooled engine per (source connection, timeout budget), rebuilt
    when the config/credentials change (fingerprint) and disposable on
    demand. **The timeout is part of the cache key, not just an argument**
    (S2 review SHOULD-FIX 5): pymssql has no session-level statement
    timeout, so its per-query budget is baked into ``connect_args`` at ENGINE
    CREATION time - a preview-budget engine (30s) and an extract-budget
    engine (300s) for the SAME connection are genuinely DIFFERENT engines,
    never interchangeable just because they share a connection id.
    ``put_engine`` is the injection seam tests and the provider's own probe
    use - it serves for ANY requested timeout (a test binds ONE fake engine,
    regardless of which budget the code under test asks for) - the routes/
    services never build a URL themselves.
    """

    def __init__(self) -> None:
        self._engines: Dict[Tuple[str, int], Tuple[str, Engine]] = {}
        self._injected: Dict[str, Engine] = {}
        self._lock = threading.Lock()

    def engine_for(
        self,
        connection_id: str,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        query_timeout: int = QUERY_TIMEOUT_SECONDS,
    ) -> Engine:
        with self._lock:
            injected = self._injected.get(connection_id)
            if injected is not None:
                return injected
            key = (connection_id, int(query_timeout))
            held = self._engines.get(key)
            url = build_url(config, credentials)
            fingerprint = _fingerprint(url, config, query_timeout)
            if held is not None and held[0] == fingerprint:
                return held[1]
            if held is not None:
                held[1].dispose()
            #     !!  POOL SIZE FITS THE CONCURRENT LINE-FETCH WORKER COUNT
            #         (S5, plan sprint-5/03 performance round) - NEVER
            #         STARVES.  !!
            # A page's own header connection plus up to `autocount_line_
            # fetch_workers` line-fetch workers can all be open AT ONCE
            # (`SqlDbSource._attach_lines`) - the OLD fixed `pool_size=2`
            # (5 total with the default overflow) was sized for the
            # single-connection sequential world before S5. Read at engine-
            # CONSTRUCTION time, same as `query_timeout` above; a live
            # settings change takes effect the next time this connection's
            # engine is rebuilt (a credential/config fingerprint change,
            # or an explicit `evict`), not retroactively on an already-
            # pooled engine (pools are not resizable once created).
            from app.config import settings as _settings

            workers = int(getattr(_settings, "autocount_line_fetch_workers", 4) or 4)
            # Headroom for TWO concurrent paged tasks sharing one connection
            # on a real worker (a real deployment runs more than one entity
            # task at a time) - `max_overflow` scales with `workers` too,
            # not a flat 3, so a second task's own worker pool never starves
            # waiting for the first task's to give connections back.
            engine = scrub_error_params(sa.create_engine(
                url,
                pool_pre_ping=True,
                hide_parameters=True,
                pool_size=max(2, workers),
                max_overflow=workers + 3,
                pool_timeout=CONNECT_TIMEOUT_SECONDS,
                pool_recycle=1800,
                connect_args=connect_args_for(
                    str(config.get("dbType", "")), query_timeout=query_timeout
                ),
            ))
            self._engines[key] = (fingerprint, engine)
            return engine

    def put_engine(self, connection_id: str, engine: Engine) -> None:
        """Bind a ready engine to a connection id (tests, probes) - served
        for EVERY timeout variant ``engine_for`` is asked for."""
        with self._lock:
            for key in [k for k in self._engines if k[0] == connection_id]:
                _fp, held_engine = self._engines.pop(key)
                if held_engine is not engine:
                    held_engine.dispose()
            old = self._injected.pop(connection_id, None)
            if old is not None and old is not engine:
                old.dispose()
            self._injected[connection_id] = engine

    def evict(self, connection_id: str) -> None:
        with self._lock:
            removed: List[Engine] = []
            injected = self._injected.pop(connection_id, None)
            if injected is not None:
                removed.append(injected)
            for key in [k for k in self._engines if k[0] == connection_id]:
                _fp, engine = self._engines.pop(key)
                removed.append(engine)
        for engine in removed:
            engine.dispose()

    def dispose_all(self) -> None:
        with self._lock:
            held = [engine for _fp, engine in self._engines.values()]
            held.extend(self._injected.values())
            self._engines.clear()
            self._injected.clear()
        for engine in held:
            engine.dispose()

    @contextmanager
    def readonly_connection(
        self,
        connection_id: str,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        timeout_s: int = QUERY_TIMEOUT_SECONDS,
    ) -> Iterator[Connection]:
        engine = self.engine_for(connection_id, config, credentials, query_timeout=timeout_s)
        with open_readonly(
            engine, timeout_s=timeout_s, secrets=secrets_of(config, credentials)
        ) as conn:
            yield conn


# Process-wide cache - one engine per source connection per process.
RUNTIME = SqlSourceRuntime()
