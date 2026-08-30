"""AutoCount direct-DB ETL, slice S1 - the SQL source runtime (plan 22 §2.2).

Pins the read-only guard (accept/reject matrix, AC-22-03), the per-dialect URL
builder + connect timeouts, the preview wrapping per dialect (AC-22-06), real
introspection against a throwaway engine (AC-22-05, cached + refreshable),
credential/DSN sanitisation (AC-22-30) and the ``sql_database`` provider's
``test()`` (AC-22-01/02).

Nothing here needs a network. The introspection/preview tests run against an
in-process SQLite engine seeded with a throwaway table; the one Postgres test
introspects the LOCAL ``DATABASE_URL`` and skips cleanly when it is not
reachable (the plan's "local Postgres is the CI source DB").
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from modules.autocount.sql_source.guard import SqlGuardError, assert_select_only
from modules.autocount.sql_source.introspect import (
    SchemaCache,
    introspect_schema,
)
from modules.autocount.sql_source.preview import (
    describe_type,
    is_orderable_type,
    run_preview,
    wrap_preview,
)
from modules.autocount.sql_source.runtime import (
    PREVIEW_ROW_LIMIT,
    SqlConnectError,
    SqlQueryError,
    SqlSourceError,
    SqlSourceRuntime,
    build_url,
    connect_args_for,
    sanitize_error,
)
from modules.autocount.sql_provider import (
    SQL_DATABASE_PROVIDER_KEY,
    SqlDatabaseProvider,
)

PASSWORD = "S3cret!Pa55"


def _sqlite_engine() -> sa.engine.Engine:
    """A throwaway in-process source DB with a seeded table."""
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE debtor (acc_no TEXT PRIMARY KEY, company_name TEXT, "
            "balance NUMERIC, last_modified TIMESTAMP, is_active INTEGER)"
        )
        conn.exec_driver_sql("CREATE TABLE empty_table (id INTEGER PRIMARY KEY, note TEXT)")
        for i in range(150):
            conn.exec_driver_sql(
                "INSERT INTO debtor VALUES (?, ?, ?, ?, ?)",
                (
                    f"3000/A{i:03d}",
                    f"Company {i}",
                    12.5 * i,
                    f"2026-08-{1 + (i % 28):02d} 09:00:00",
                    1,
                ),
            )
    return engine


# ── SELECT-only guard (AC-22-03) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT AccNo, CompanyName FROM Debtor",
        "select * from dbo.Debtor",
        "  SELECT 1  ",
        "SELECT * FROM Debtor;",  # ONE trailing terminator is tolerated
        "WITH recent AS (SELECT * FROM Debtor) SELECT * FROM recent",
        "-- leading comment\nSELECT * FROM Debtor",
        "/* block */ SELECT * FROM Debtor",
        "SELECT * FROM Debtor WHERE CompanyName = 'O''Brien'",
        "SELECT [Update], \"delete\" FROM `Debtor`",  # quoted identifiers are data
        "SELECT * FROM Debtor WHERE Note = 'DROP TABLE x'",  # inside a literal
        "SELECT t.* FROM Debtor t LEFT JOIN Creditor c ON c.AccNo = t.AccNo",
        "SELECT * FROM Debtor ORDER BY LastModified DESC",
    ],
)
def test_guard_accepts_single_select_statements(sql):
    assert assert_select_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "-- only a comment",
        "INSERT INTO Debtor (AccNo) VALUES ('x')",
        "UPDATE Debtor SET CompanyName = 'x'",
        "DELETE FROM Debtor",
        "DROP TABLE Debtor",
        "CREATE TABLE t (id int)",
        "ALTER TABLE Debtor ADD x int",
        "TRUNCATE TABLE Debtor",
        "EXEC sp_who",
        "EXECUTE sp_executesql N'SELECT 1'",
        "MERGE INTO Debtor USING x ON 1=1",
        "GRANT SELECT ON Debtor TO public",
        "CALL some_proc()",
        "SELECT 1; DROP TABLE Debtor",
        "SELECT 1;; SELECT 2",
        "SELECT * INTO NewTable FROM Debtor",
        "SELECT * FROM Debtor FOR UPDATE",
        "WITH x AS (SELECT 1) DELETE FROM Debtor",
        "WITH x AS (SELECT 1) INSERT INTO Debtor SELECT * FROM x",
        "SELECT * FROM Debtor; -- trailing comment after a second statement\nDELETE FROM Debtor",
        "SELECT * FROM OPENROWSET('x','y','z')",
        "SELECT * FROM Debtor WHERE 1 = 1 UNION SELECT * FROM Debtor; DROP TABLE x",
        "select xp_cmdshell 'dir'",
        "COPY Debtor TO '/tmp/x'",
        "LOAD DATA INFILE '/tmp/x' INTO TABLE Debtor",
        "SET search_path TO public; SELECT 1",
        "SELECT pg_sleep(10) INTO TEMP t",
        "BEGIN; SELECT 1; COMMIT",
    ],
)
def test_guard_rejects_everything_that_is_not_one_select(sql):
    with pytest.raises(SqlGuardError):
        assert_select_only(sql)


def test_guard_error_is_a_source_error_with_an_operator_message():
    with pytest.raises(SqlSourceError) as excinfo:
        assert_select_only("DELETE FROM Debtor")
    assert "SELECT" in excinfo.value.message
    assert isinstance(excinfo.value, SqlGuardError)


def test_guard_returns_the_statement_without_its_trailing_terminator():
    assert assert_select_only("SELECT 1;") == "SELECT 1"
    assert assert_select_only("  SELECT 1  \n") == "SELECT 1"


# ── URL builder + timeouts per dialect (AC-22-02) ────────────────────────────


@pytest.mark.parametrize(
    "db_type,driver,default_port",
    [
        ("mssql", "mssql+pymssql", 1433),
        ("postgresql", "postgresql+psycopg2", 5432),
        ("mysql", "mysql+pymysql", 3306),
    ],
)
def test_build_url_per_dialect(db_type, driver, default_port):
    url = build_url(
        {"dbType": db_type, "host": "db.example.com", "database": "AED", "username": "ro"},
        {"password": PASSWORD},
    )
    assert url.drivername == driver
    assert url.host == "db.example.com"
    assert url.port == default_port  # blank port → dialect default
    assert url.database == "AED"
    assert url.username == "ro"
    assert url.password == PASSWORD
    # SQLAlchemy's default rendering masks the password - the thing a log or
    # error would ever see.
    assert PASSWORD not in str(url)


def test_build_url_honours_an_explicit_port_and_rejects_bad_input():
    url = build_url(
        {"dbType": "mssql", "host": "h", "port": "14330", "database": "d", "username": "u"},
        {"password": "p"},
    )
    assert url.port == 14330
    with pytest.raises(SqlSourceError):
        build_url({"dbType": "oracle", "host": "h", "database": "d"}, {})
    with pytest.raises(SqlSourceError):
        build_url({"dbType": "mssql", "database": "d"}, {})  # no host
    with pytest.raises(SqlSourceError):
        build_url({"dbType": "mssql", "host": "h"}, {})  # no database
    with pytest.raises(SqlSourceError):
        build_url({"dbType": "mssql", "host": "h", "database": "d", "port": "abc"}, {})


@pytest.mark.parametrize(
    "db_type,expected",
    [
        ("mssql", {"login_timeout": 10, "timeout": 30}),
        ("postgresql", {"connect_timeout": 10}),
        ("mysql", {"connect_timeout": 10, "read_timeout": 30}),
    ],
)
def test_connect_args_carry_a_bounded_timeout_per_dialect(db_type, expected):
    args = connect_args_for(db_type, connect_timeout=10, query_timeout=30)
    for key, value in expected.items():
        assert args[key] == value


# ── sanitised errors (AC-22-30) ──────────────────────────────────────────────


def test_sanitize_error_never_echoes_credentials_or_a_dsn():
    raw = OperationalError(
        "SELECT 1",
        {},
        Exception(
            f"FATAL: password authentication failed for user \"ro\" "
            f"(password={PASSWORD}) at postgresql+psycopg2://ro:{PASSWORD}@10.0.0.9:5432/AED"
        ),
    )
    message = sanitize_error(raw, secrets=[PASSWORD])
    assert PASSWORD not in message
    assert "://" not in message
    assert "[SQL:" not in message
    assert "Background on this error" not in message
    assert "authentication failed" in message


def test_sanitize_error_strips_sqlalchemy_wrapping_and_caps_length():
    raw = OperationalError("SELECT " + "x" * 5000, {}, Exception("boom " * 500))
    message = sanitize_error(raw, secrets=[])
    assert len(message) <= 400
    assert "[SQL:" not in message


# ── preview wrapping per dialect (AC-22-06) ──────────────────────────────────


def test_wrap_preview_uses_top_on_mssql_and_limit_elsewhere():
    assert (
        wrap_preview("SELECT * FROM Debtor", "mssql", 100)
        == "SELECT TOP (101) * FROM (SELECT * FROM Debtor) AS _preview"
    )
    assert (
        wrap_preview("SELECT * FROM debtor;", "postgresql", 100)
        == "SELECT * FROM (SELECT * FROM debtor) AS _preview LIMIT 101"
    )
    assert wrap_preview("SELECT * FROM debtor", "mysql", 100).endswith("LIMIT 101")
    assert wrap_preview("SELECT * FROM debtor", "sqlite", 100).endswith("LIMIT 101")


def test_wrap_preview_refuses_a_non_select_before_any_wrapping():
    with pytest.raises(SqlGuardError):
        wrap_preview("DELETE FROM Debtor", "postgresql", 100)


def test_run_preview_caps_rows_reports_truncation_and_types():
    engine = _sqlite_engine()
    result = run_preview(engine, "SELECT * FROM debtor ORDER BY acc_no", timeout_s=5)
    assert result.row_count == PREVIEW_ROW_LIMIT == 100
    assert result.truncated is True
    assert len(result.rows) == 100
    assert [c.name for c in result.columns] == [
        "acc_no",
        "company_name",
        "balance",
        "last_modified",
        "is_active",
    ]
    types = {c.name: c.type for c in result.columns}
    assert types["acc_no"] == "string"
    assert types["balance"] in ("float", "decimal")
    assert types["is_active"] == "integer"
    assert result.duration_ms >= 0
    # Every cell is JSON-safe (a datetime/Decimal never reaches the wire raw).
    assert all(isinstance(v, (str, int, float, bool, type(None))) for v in result.rows[0].values())


def test_run_preview_reports_zero_rows_without_truncation():
    engine = _sqlite_engine()
    result = run_preview(engine, "SELECT id, note FROM empty_table", timeout_s=5)
    assert result.rows == []
    assert result.row_count == 0
    assert result.truncated is False
    assert [c.name for c in result.columns] == ["id", "note"]


def test_run_preview_rejects_non_select_before_touching_the_source(monkeypatch):
    engine = _sqlite_engine()
    touched = {"connect": 0}
    real_connect = engine.connect

    def counting_connect(*a, **kw):
        touched["connect"] += 1
        return real_connect(*a, **kw)

    monkeypatch.setattr(engine, "connect", counting_connect)
    with pytest.raises(SqlGuardError):
        run_preview(engine, "DROP TABLE debtor", timeout_s=5)
    assert touched["connect"] == 0


def test_run_preview_surfaces_a_query_error_sanitised():
    engine = _sqlite_engine()
    with pytest.raises(SqlQueryError) as excinfo:
        run_preview(engine, "SELECT nope FROM debtor", timeout_s=5)
    assert "nope" in excinfo.value.message
    assert "[SQL:" not in excinfo.value.message
    assert "sqlite://" not in excinfo.value.message


def test_run_preview_never_commits_a_write_even_if_the_guard_were_bypassed():
    """Defence in depth: the preview runs inside a transaction that is ALWAYS
    rolled back. Drive the executor directly past the guard with a write and
    prove nothing persisted."""
    from modules.autocount.sql_source.preview import _execute_preview_unguarded

    engine = _sqlite_engine()
    try:
        _execute_preview_unguarded(engine, "DELETE FROM debtor", timeout_s=5)
    except SqlSourceError:
        pass
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM debtor").scalar() == 150


@pytest.mark.parametrize(
    "value,expected",
    [
        (1, "integer"),
        (True, "boolean"),
        (1.5, "float"),
        (Decimal("1.5"), "decimal"),
        ("x", "string"),
        (datetime(2026, 1, 1), "datetime"),
        (date(2026, 1, 1), "date"),
        (b"\x00", "binary"),
        (None, "unknown"),
    ],
)
def test_describe_type_from_python_values(value, expected):
    assert describe_type(value) == expected


@pytest.mark.parametrize(
    "type_name,orderable",
    [
        ("integer", True),
        ("decimal", True),
        ("float", True),
        ("datetime", True),
        ("date", True),
        ("time", True),
        ("string", False),
        ("boolean", False),
        ("binary", False),
        ("unknown", False),
    ],
)
def test_orderable_types_for_a_watermark(type_name, orderable):
    assert is_orderable_type(type_name) is orderable


# ── introspection (AC-22-05) ─────────────────────────────────────────────────


def test_introspect_returns_schemas_tables_and_columns():
    engine = _sqlite_engine()
    tree = introspect_schema(engine, database="main")
    assert [s.name for s in tree.schemas] == ["main"]
    tables = {t.name: t for t in tree.schemas[0].tables}
    assert set(tables) == {"debtor", "empty_table"}
    columns = {c.name: c.type for c in tables["debtor"].columns}
    assert set(columns) == {"acc_no", "company_name", "balance", "last_modified", "is_active"}
    assert columns["acc_no"].upper().startswith("TEXT")
    assert tree.introspected_at.tzinfo is not None


def test_introspect_against_local_postgres_when_reachable():
    from app.config import settings

    if not settings.database_url.startswith("postgresql"):
        pytest.skip("local DATABASE_URL is not Postgres")
    engine = sa.create_engine(settings.database_url, connect_args={"connect_timeout": 2})
    try:
        with engine.connect():
            pass
    except Exception:  # noqa: BLE001 - environment, not code
        pytest.skip("local Postgres not reachable")
    try:
        tree = introspect_schema(engine, database=engine.url.database or "")
    finally:
        engine.dispose()
    names = {s.name for s in tree.schemas}
    assert "public" in names
    assert not names & {"pg_catalog", "information_schema", "pg_toast"}
    public = next(s for s in tree.schemas if s.name == "public")
    users = next(t for t in public.tables if t.name == "users")
    assert "email" in {c.name for c in users.columns}


def test_schema_cache_serves_within_ttl_and_refreshes_on_demand():
    clock = {"now": 1000.0}
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return f"tree-{calls['n']}"

    cache = SchemaCache(ttl_seconds=600, clock=lambda: clock["now"])
    assert cache.get("c1", loader) == "tree-1"
    assert cache.get("c1", loader) == "tree-1"  # cached
    assert calls["n"] == 1
    assert cache.get("c1", loader, refresh=True) == "tree-2"  # explicit bust
    assert calls["n"] == 2
    clock["now"] += 601
    assert cache.get("c1", loader) == "tree-3"  # TTL expired
    assert cache.get("c2", loader) == "tree-4"  # per connection
    cache.invalidate("c1")
    assert cache.get("c1", loader) == "tree-5"


# ── engine cache ─────────────────────────────────────────────────────────────


def test_runtime_caches_engines_per_connection_and_rebuilds_on_config_change():
    runtime = SqlSourceRuntime()
    cfg = {"dbType": "postgresql", "host": "h", "database": "d", "username": "u"}
    first = runtime.engine_for("c1", cfg, {"password": "p1"})
    assert runtime.engine_for("c1", cfg, {"password": "p1"}) is first
    # A rotated password / edited host = a different engine, never a stale one.
    second = runtime.engine_for("c1", cfg, {"password": "p2"})
    assert second is not first
    runtime.evict("c1")
    assert runtime.engine_for("c1", cfg, {"password": "p2"}) is not second
    runtime.dispose_all()


def test_runtime_put_engine_seam_serves_a_registered_engine():
    runtime = SqlSourceRuntime()
    engine = _sqlite_engine()
    runtime.put_engine("c9", engine)
    assert runtime.engine_for("c9", {"dbType": "mssql"}, {}) is engine


def test_runtime_connect_failure_is_a_sanitised_connect_error():
    runtime = SqlSourceRuntime()
    # Port 1 is closed - refused immediately, no network needed.
    cfg = {
        "dbType": "postgresql",
        "host": "127.0.0.1",
        "port": "1",
        "database": "nope",
        "username": "ro",
    }
    with pytest.raises(SqlConnectError) as excinfo:
        with runtime.readonly_connection("c2", cfg, {"password": PASSWORD}, timeout_s=2):
            pass
    assert PASSWORD not in excinfo.value.message
    assert "://" not in excinfo.value.message
    assert excinfo.value.message.startswith("Could not connect to the database")
    runtime.dispose_all()


# ── the sql_database provider (AC-22-01/02/04) ───────────────────────────────


def test_provider_is_registered_as_an_erp_provider(client):
    from app.integrations import get_provider

    provider = get_provider(SQL_DATABASE_PROVIDER_KEY)
    assert provider is not None
    assert provider.provider == "sql_database"
    assert provider.type == "erp"
    assert provider.test_target is None


def test_provider_fields_match_the_frontend_descriptor_exactly():
    """The frontend's ``SQL_DATABASE_PROVIDER`` (integration-service.mock.ts) is
    the phase-1 spec; ``fields()`` must emit that shape byte-for-byte."""
    provider = SqlDatabaseProvider()
    assert provider.title == "SQL Database"
    assert provider.icon == "database"
    assert provider.test_label == "Test connection"
    assert provider.fields() == [
        {
            "key": "dbType",
            "label": "Database type",
            "type": "select",
            "required": True,
            "defaultValue": "mssql",
            "options": [
                {"value": "mssql", "label": "Microsoft SQL Server"},
                {"value": "postgresql", "label": "PostgreSQL"},
                {"value": "mysql", "label": "MySQL"},
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
            "defaultValue": "1433",
            "defaultsFrom": {
                "field": "dbType",
                "values": {"mssql": "1433", "postgresql": "5432", "mysql": "3306"},
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


def test_provider_test_succeeds_with_a_select_one_probe():
    engine = _sqlite_engine()
    result = SqlDatabaseProvider().test(
        {"dbType": "postgresql", "host": "h", "database": "d", "username": "u"},
        {"password": "p"},
        engine_factory=lambda cfg, creds: engine,
    )
    assert result.ok is True
    assert "Connected" in result.message
    assert "p" not in result.message.split()  # never the password


def test_provider_test_reports_a_connect_failure_sanitised():
    def failing(cfg, creds):
        raise OperationalError(
            "SELECT 1", {}, Exception(f"connection refused (password={PASSWORD})")
        )

    result = SqlDatabaseProvider().test(
        {"dbType": "mssql", "host": "10.0.0.9", "database": "d", "username": "u"},
        {"password": PASSWORD},
        engine_factory=failing,
    )
    assert result.ok is False
    assert PASSWORD not in result.message
    assert "refused" in result.message


def test_provider_test_names_missing_fields_before_connecting():
    provider = SqlDatabaseProvider()
    assert provider.test({"dbType": "mssql"}, {"password": "p"}).ok is False
    assert (
        provider.test({"dbType": "mssql", "host": "h", "database": "d", "username": "u"}, {}).ok
        is False
    )
    assert (
        provider.test({"dbType": "oracle", "host": "h", "database": "d", "username": "u"}, {"password": "p"}).ok
        is False
    )


def test_provider_test_against_local_postgres_when_reachable():
    from app.config import settings

    if not settings.database_url.startswith("postgresql"):
        pytest.skip("local DATABASE_URL is not Postgres")
    url = sa.engine.make_url(settings.database_url)
    result = SqlDatabaseProvider().test(
        {
            "dbType": "postgresql",
            "host": url.host or "localhost",
            "port": str(url.port or 5432),
            "database": url.database or "",
            "username": url.username or "",
        },
        {"password": url.password or ""},
    )
    if not result.ok and "Could not connect" in result.message:
        pytest.skip("local Postgres not reachable")
    assert result.ok is True
    # The success line names database + host + dialect, never the password
    # (the local dev password happens to equal the role/db prefix, so assert
    # on the shape rather than a substring).
    assert result.message == (
        f"Connected to {url.database} on {url.host or 'localhost'} (PostgreSQL)."
    )
