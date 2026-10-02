"""Generic SQL-database connection provider (plan 22 §2.3, AC-22-01/02/04).

The READ-ONLY source counterpart to ``AutoCountProvider`` (HTTP wrapper) -
where that one signs in to the vendor API, this one opens a database session
against the customer's own AutoCount database (Microsoft SQL Server,
PostgreSQL or MySQL). ``type='erp'`` reuses core's erp multiplicity carve-out
(several active erp connections per tenant), so one tenant may point at
several company databases.

Fields are the registry-driven form (``dbType`` select, host, port with a
per-dialect ``defaultsFrom``, database, username; secret ``password`` -
Fernet, write-only, blank = keep). The shape is pinned byte-for-byte against
the phase-1 frontend descriptor (``integration-service.mock.ts``).

``test()`` = connect + ``SELECT 1`` on a read-only session under a 10s cap,
naming the failing step with a SANITISED message (never credentials, never a
DSN, never a driver stack - AC-22-02/30).

Extraction of this provider into a platform-core data-integration engine is a
registered backlog item (plan 22 §7); it lives in the module for now (Q3).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from app.integrations.base import TestResult

from .sql_source.errors import SqlSourceError
from .sql_source.runtime import (
    DIALECTS,
    build_url,
    connect_args_for,
    dialect_label,
    open_readonly,
    sanitize_error,
    secrets_of,
)

SQL_DATABASE_PROVIDER_KEY = "sql_database"
SQL_DATABASE_CONNECTION_TYPE = "erp"
_TEST_TIMEOUT_SECONDS = 10

EngineFactory = Callable[[Dict[str, Any], Dict[str, Any]], Engine]


def _probe_engine(config: Dict[str, Any], credentials: Dict[str, Any]) -> Engine:
    """A throwaway, unpooled engine for the Test button - never cached, so a
    Test never leaves a connection open and never poisons the runtime cache
    with credentials the operator is still editing."""
    return sa.create_engine(
        build_url(config, credentials),
        poolclass=NullPool,
        connect_args=connect_args_for(
            str(config.get("dbType", "")),
            connect_timeout=_TEST_TIMEOUT_SECONDS,
            query_timeout=_TEST_TIMEOUT_SECONDS,
        ),
    )


class SqlDatabaseProvider:
    provider = SQL_DATABASE_PROVIDER_KEY
    type = SQL_DATABASE_CONNECTION_TYPE
    title = "SQL Database"
    description = (
        "Read directly from an accounting database over a read-only login. "
        "Microsoft SQL Server, PostgreSQL or MySQL."
    )
    icon = "database"
    test_label = "Test connection"
    # Connection check only - there is no targeted test for a read source.
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "dbType",
                "label": "Database type",
                "type": "select",
                "required": True,
                "defaultValue": "mssql",
                "options": [
                    {"value": key, "label": DIALECTS[key][2]}
                    for key in ("mssql", "postgresql", "mysql")
                ],
            },
            {
                "key": "host",
                "label": "Host",
                "type": "text",
                "required": True,
                "placeholder": "db.yourcompany.com",
            },
            {
                "key": "port",
                "label": "Port",
                "type": "number",
                "required": True,
                "defaultValue": str(DIALECTS["mssql"][1]),
                # Registry-driven dependent default (AC-22-04): the form resets
                # the port when the dialect changes, unless the operator typed
                # a non-stock value.
                "defaultsFrom": {
                    "field": "dbType",
                    "values": {key: str(DIALECTS[key][1]) for key in ("mssql", "postgresql", "mysql")},
                },
            },
            {
                "key": "database",
                "label": "Database",
                "type": "text",
                "required": True,
                "placeholder": "AED_Company_2024",
            },
            {
                "key": "username",
                "label": "Username",
                "type": "text",
                "required": True,
                "placeholder": "readonly_user",
            },
            {
                "key": "password",
                "label": "Password",
                "type": "password",
                "required": True,
                "secret": True,
            },
        ]

    def test(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        target: Optional[str] = None,
        *,
        engine_factory: Optional[EngineFactory] = None,
    ) -> TestResult:
        """Connect + ``SELECT 1`` under a bounded timeout, sanitised failure.

        ``engine_factory`` is injectable for tests (the integrations service
        calls ``test(config, credentials, target)`` positionally, so the
        keyword-only default is transparent to it).
        """
        db_type = str(config.get("dbType", "")).strip().lower()
        if db_type not in DIALECTS:
            return TestResult(
                ok=False,
                message="Choose a database type: Microsoft SQL Server, PostgreSQL or MySQL.",
            )
        host = str(config.get("host", "")).strip()
        if not host:
            return TestResult(ok=False, message="Enter the database host.")
        database = str(config.get("database", "")).strip()
        if not database:
            return TestResult(ok=False, message="Enter the database name.")
        if not str(config.get("username", "") or "").strip():
            return TestResult(ok=False, message="Enter the database username.")
        if not str(credentials.get("password", "") or ""):
            return TestResult(ok=False, message="Enter the database password.")

        secrets = secrets_of(config, credentials)
        injected = engine_factory is not None
        factory = engine_factory or _probe_engine
        engine: Optional[Engine] = None
        try:
            engine = factory(config, credentials)
            with open_readonly(engine, timeout_s=_TEST_TIMEOUT_SECONDS, secrets=secrets) as conn:
                conn.exec_driver_sql("SELECT 1").scalar()
        except SqlSourceError as exc:
            return TestResult(ok=False, message=exc.message)
        except Exception as exc:  # noqa: BLE001 - never a raw driver stack
            return TestResult(
                ok=False,
                message="Could not connect to the database: " + sanitize_error(exc, secrets=secrets),
            )
        finally:
            if engine is not None and not injected:
                engine.dispose()
        return TestResult(
            ok=True,
            message=f"Connected to {database} on {host} ({dialect_label(db_type)}).",
        )
