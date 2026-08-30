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

``sanitize_error`` is the ONE place a driver message is turned into an
operator message - strip SQLAlchemy's ``[SQL: ...]`` echo, redact every
``scheme://...`` fragment and every known secret, cap the length.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, URL

from .errors import SqlConnectError, SqlGuardError, SqlQueryError, SqlSourceError

__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "DIALECTS",
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
DIALECTS: Dict[str, Tuple[str, int, str]] = {
    "mssql": ("mssql+pymssql", 1433, "Microsoft SQL Server"),
    "postgresql": ("postgresql+psycopg2", 5432, "PostgreSQL"),
    "mysql": ("mysql+pymysql", 3306, "MySQL"),
}

PREVIEW_ROW_LIMIT = 100
CONNECT_TIMEOUT_SECONDS = 10
QUERY_TIMEOUT_SECONDS = 30
# Operator-facing messages are capped - a driver can dump a page of text.
_MESSAGE_CAP = 300

_DSN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://\S+")
_SQL_ECHO_RE = re.compile(r"\[SQL:.*", re.S)
_BACKGROUND_RE = re.compile(r"\(Background on this error at:.*?\)", re.S)
_WS_RE = re.compile(r"\s+")


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


def sanitize_error(exc: BaseException, *, secrets: Sequence[str] = ()) -> str:
    """Driver/SQLAlchemy exception → an operator-safe message.

    Uses the DBAPI's own message (``exc.orig``) so SQLAlchemy's ``[SQL: ...]``
    echo of the statement (tenant data) and its docs pointer never ride along;
    redacts any ``scheme://`` fragment (a DSN carries the password) and every
    known secret; collapses whitespace; caps the length.
    """
    orig = getattr(exc, "orig", None)
    raw = str(orig) if orig is not None else str(exc)
    raw = _SQL_ECHO_RE.sub("", raw)
    raw = _BACKGROUND_RE.sub("", raw)
    raw = _DSN_RE.sub("[connection]", raw)
    for secret in secrets:
        if secret:
            raw = raw.replace(secret, "[redacted]")
    raw = _WS_RE.sub(" ", raw).strip()
    if len(raw) > _MESSAGE_CAP:
        raw = raw[: _MESSAGE_CAP - 1].rstrip() + "..."
    return raw or "The database returned an error."


def _fingerprint(url: URL, config: Dict[str, Any]) -> str:
    material = url.render_as_string(hide_password=False) + json.dumps(
        {k: v for k, v in sorted(config.items()) if not str(k).startswith("_")},
        sort_keys=True,
        default=str,
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
    """
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
    """Engine cache keyed by connection id (plan 22 §2.2).

    One small pooled engine per source connection, rebuilt when the config or
    credentials change (fingerprint) and disposable on demand. ``put_engine``
    is the injection seam tests and the provider's own probe use - the
    routes/services never build a URL themselves.
    """

    def __init__(self) -> None:
        self._engines: Dict[str, Tuple[str, Engine]] = {}
        self._lock = threading.Lock()

    def engine_for(
        self, connection_id: str, config: Dict[str, Any], credentials: Dict[str, Any]
    ) -> Engine:
        with self._lock:
            held = self._engines.get(connection_id)
            if held is not None and held[0] == "__injected__":
                return held[1]
            url = build_url(config, credentials)
            fingerprint = _fingerprint(url, config)
            if held is not None and held[0] == fingerprint:
                return held[1]
            if held is not None:
                held[1].dispose()
            engine = sa.create_engine(
                url,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=3,
                pool_timeout=CONNECT_TIMEOUT_SECONDS,
                pool_recycle=1800,
                connect_args=connect_args_for(str(config.get("dbType", ""))),
            )
            self._engines[connection_id] = (fingerprint, engine)
            return engine

    def put_engine(self, connection_id: str, engine: Engine) -> None:
        """Bind a ready engine to a connection id (tests, probes)."""
        with self._lock:
            held = self._engines.pop(connection_id, None)
            if held is not None and held[1] is not engine:
                held[1].dispose()
            self._engines[connection_id] = ("__injected__", engine)

    def evict(self, connection_id: str) -> None:
        with self._lock:
            held = self._engines.pop(connection_id, None)
        if held is not None:
            held[1].dispose()

    def dispose_all(self) -> None:
        with self._lock:
            held = list(self._engines.values())
            self._engines.clear()
        for _fp, engine in held:
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
        engine = self.engine_for(connection_id, config, credentials)
        with open_readonly(
            engine, timeout_s=timeout_s, secrets=secrets_of(config, credentials)
        ) as conn:
            yield conn


# Process-wide cache - one engine per source connection per process.
RUNTIME = SqlSourceRuntime()
