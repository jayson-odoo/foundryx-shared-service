"""Company-onboarding probes for a ``sql_database`` connection (plan
sprint-5/01 §2.3, AC-01-02/03).

A DB company's identity is the connection's ``config.database`` - but a login
can land somewhere else than the name it was given (a default database on the
login, a typo, a copied connection). ``probe_current_database`` asks the
server which database the session is actually in, so create can refuse a
mismatch BEFORE a company is minted under the wrong identity.

``read_profile_name`` is the best-effort ``CompanyName`` read off AutoCount's
``dbo.Profile`` (MSSQL only - AutoCount is an MSSQL product; the map exists so
a dialect without a profile statement answers "" instead of raising).

Both are READ-ONLY, ride the same runtime/engine cache the task path uses
(``RUNTIME.readonly_connection`` - injected engines and the connect-timeout
budget included), and never surface a credential or a DSN: every failure
passes ``sanitize_error`` on its way to ``SqlProbeFailed``.
"""
from __future__ import annotations

from typing import Any, Dict

from .errors import SqlProbeFailed, SqlSourceError
from .runtime import CONNECT_TIMEOUT_SECONDS, RUNTIME, sanitize_error, secrets_of

__all__ = [
    "CURRENT_DATABASE_SQL",
    "PROFILE_NAME_SQL",
    "SqlProbeFailed",
    "probe_current_database",
    "read_profile_name",
]

# dbType → the statement naming the session's CURRENT database (AC-01-02).
CURRENT_DATABASE_SQL: Dict[str, str] = {
    "mssql": "SELECT DB_NAME()",
    "postgresql": "SELECT current_database()",
    "mysql": "SELECT DATABASE()",
}

# dbType → the statement reading AutoCount's company name (AC-01-03). MSSQL
# only: AutoCount ships on SQL Server; other dialects have no profile table.
PROFILE_NAME_SQL: Dict[str, str] = {
    "mssql": "SELECT TOP 1 CompanyName FROM dbo.Profile",
}


def _scalar(
    connection_id: str, config: Dict[str, Any], credentials: Dict[str, Any], sql: str
) -> Any:
    """ONE scalar off a read-only, connect-time-boxed session. Every failure
    is a ``SqlProbeFailed`` carrying an operator-safe message."""
    secrets = secrets_of(config, credentials)
    try:
        with RUNTIME.readonly_connection(
            connection_id, config, credentials, timeout_s=CONNECT_TIMEOUT_SECONDS
        ) as conn:
            return conn.exec_driver_sql(sql).scalar()
    except SqlSourceError as exc:
        # ``build_url``/``open_readonly`` already speak operator language.
        raise SqlProbeFailed(exc.message) from exc
    except Exception as exc:  # noqa: BLE001 - every driver has its own class
        raise SqlProbeFailed(
            "The database probe failed: " + sanitize_error(exc, secrets=secrets)
        ) from exc


def probe_current_database(
    connection_id: str, config: Dict[str, Any], credentials: Dict[str, Any]
) -> str:
    """The database the connection's login ACTUALLY lands on, trimmed.

    Raises ``SqlProbeFailed`` when the dialect has no probe, the connection
    cannot be opened, or the statement fails - the caller renders it on
    ``connectionId`` (AC-01-02); nothing is created on that path.
    """
    db_type = str(config.get("dbType", "")).strip().lower()
    sql = CURRENT_DATABASE_SQL.get(db_type)
    if sql is None:
        raise SqlProbeFailed(
            "This database type cannot be probed for its current database."
        )
    value = _scalar(connection_id, config, credentials, sql)
    return str(value or "").strip()


def read_profile_name(
    connection_id: str, config: Dict[str, Any], credentials: Dict[str, Any]
) -> str:
    """AutoCount's ``CompanyName`` - best-effort (AC-01-03/Q19): a dialect
    without a profile statement, an absent/unreadable table, or an empty
    row all answer ``""``. Never raises."""
    db_type = str(config.get("dbType", "")).strip().lower()
    sql = PROFILE_NAME_SQL.get(db_type)
    if sql is None:
        return ""
    try:
        value = _scalar(connection_id, config, credentials, sql)
    except SqlProbeFailed:
        return ""
    return str(value or "").strip()
