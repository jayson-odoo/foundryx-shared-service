"""``SqlDbSource`` against a real (throwaway) source database - plan 22 S2
(AC-22-08/15/16).

The source engine is an in-process SQLite bound through the runtime's
``put_engine`` seam, exactly as the S1 route suite does it: a REAL engine, real
SQL, real driver decoding, no socket. The MSSQL/MySQL statement branches are
unit-tested separately (`test_autocount_sql_source.py`) and smoked live per the
plan; the live-verify pass exercises Postgres end to end.

What this file pins is the behaviour that is expensive to get wrong:

* the initial load reads everything and the incremental reads only what moved;
* the mark advances to the max value SEEN and a re-run then fetches nothing;
* every fetched row leaves a hash behind, so S3's reconcile has a baseline;
* a run writes one activity row carrying dialect / rows / duration / SQL head.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import AcCompany, AcEntityConfig, AcRowHash
from modules.autocount.repositories import RowHashRepository
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sql_source.source import (
    CURSOR_COLUMN,
    CURSOR_MARK,
    SqlDbSource,
    SqlTaskNotConfigured,
)

PASSWORD = "S3cret!Pa55"
DB_NAME = "AED_2024"

ROWS = [
    ("300-A001", "Acme", "a@x.com", 1, "2026-08-01 09:00:00"),
    ("300-A002", "Bolt", "b@x.com", 1, "2026-08-02 09:00:00"),
    ("300-A003", "Cog", "c@x.com", 0, "2026-08-03 09:00:00"),
]


def _source_engine() -> sa.engine.Engine:
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE debtor (acc_no TEXT PRIMARY KEY, company_name TEXT, "
            "email TEXT, is_active INTEGER, last_modified TEXT)"
        )
        for row in ROWS:
            conn.exec_driver_sql("INSERT INTO debtor VALUES (?, ?, ?, ?, ?)", row)
    return engine


def _sql_connection(db, engine) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID,
        provider="sql_database",
        type="erp",
        name="Source DB",
        config_json={
            "dbType": "postgresql",
            "host": "db.example.com",
            "port": "5432",
            "database": DB_NAME,
            "username": "readonly",
        },
        credentials_json=encrypt_secret({"password": PASSWORD}),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    RUNTIME.put_engine(conn.id, engine)
    return conn


def _company(db) -> AcCompany:
    api = Connection(
        tenant_id=DEFAULT_TENANT_ID,
        provider="autocount",
        type="erp",
        name="AutoCount API",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID,
        connection_id=api.id,
        database_name=DB_NAME,
        company_name="AED Sdn Bhd",
        name="AED",
        is_active=True,
    )
    db.add(company)
    db.flush()
    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()
    db.refresh(company)
    return company


QUERY = "SELECT acc_no, company_name, email, is_active, last_modified FROM debtor"


def _configure(
    db,
    company,
    *,
    query: str = QUERY,
    key_columns=("acc_no",),
    watermark="last_modified",
    compared=(),
    connection_id: str,
    result_columns=("acc_no", "company_name", "email", "is_active", "last_modified"),
) -> AcEntityConfig:
    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company.id,
            AcEntityConfig.entity_type == ENTITY_CUSTOMER,
        )
        .one()
    )
    config.source_impl = "sql_db"
    config.source_config = {
        "connectionId": connection_id,
        "query": query,
        "keyColumns": list(key_columns),
        "watermarkColumn": watermark,
        "comparedColumns": list(compared),
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
    }
    config.result_columns = list(result_columns)
    db.commit()
    return config


def _ctx(db, company, config) -> SourceContext:
    return SourceContext(
        db=db,
        tenant_id=DEFAULT_TENANT_ID,
        company=company,
        entity_config=config,
        company_service=CompanyService(db),
    )


@pytest.fixture
def rig(session_factory):
    db = session_factory()
    engine = _source_engine()
    conn = _sql_connection(db, engine)
    company = _company(db)
    config = _configure(db, company, connection_id=conn.id)
    yield db, company, config, engine
    db.close()
    RUNTIME.dispose_all()


def _hashes(db, company):
    return {
        row.source_ref: row.row_hash
        for row in db.query(AcRowHash).filter(
            AcRowHash.tenant_id == DEFAULT_TENANT_ID,
            AcRowHash.company_id == company.id,
            AcRowHash.entity_type == ENTITY_CUSTOMER,
        )
    }


# ── initial load ─────────────────────────────────────────────────────────────


def test_the_initial_load_reads_every_row_and_reports_them_as_adds(rig):
    db, company, config, _engine = rig
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)
    result = source.fetch_changes(Watermark())

    assert len(result.records) == 3
    assert result.rows_scanned == 3
    assert result.added_count == 3
    assert result.updated_count == 0
    # Flat rows - the source path IS the result column name (AC-22-09).
    assert result.records[0].raw["acc_no"] == "300-A001"
    assert "Data" not in result.records[0].raw


def test_the_initial_load_writes_a_hash_for_every_row(rig):
    """S3's reconcile diffs against these, so an S2 run that wrote none would
    make the first reconcile see the whole table as brand new (AC-22-16)."""
    db, company, config, _engine = rig
    SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER).fetch_changes(
        Watermark()
    )
    stored = _hashes(db, company)
    assert set(stored) == {
        f"{DB_NAME}:300-A001", f"{DB_NAME}:300-A002", f"{DB_NAME}:300-A003"
    }
    assert all(len(h) == 64 for h in stored.values())


def test_a_preview_run_writes_NO_hashes(rig):
    """The activation dry run must leave no trace - otherwise the FIRST real
    run reports zero adds and the operator sees nothing happen."""
    db, company, config, _engine = rig
    source = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_CUSTOMER, persist_hashes=False
    )
    source.fetch_changes(Watermark())
    assert _hashes(db, company) == {}


# ── incremental (AC-22-15) ───────────────────────────────────────────────────


def _mark_after_initial(rig):
    db, company, config, _engine = rig
    result = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_CUSTOMER
    ).fetch_changes(Watermark())
    assert result.cursor is not None
    return result.cursor


def test_the_mark_advances_to_the_MAX_value_seen_never_the_clock(rig):
    cursor = _mark_after_initial(rig)
    assert cursor[CURSOR_COLUMN] == "last_modified"
    # The newest row's stamp, not "now" - a clock-based mark silently skips
    # anything written while the run was in flight.
    assert cursor[CURSOR_MARK] == "2026-08-03 09:00:00"


def test_re_running_immediately_fetches_NOTHING(rig):
    """Idempotence (AC-22-15): the whole point of a watermark."""
    db, company, config, _engine = rig
    cursor = _mark_after_initial(rig)
    again = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_CUSTOMER
    ).fetch_changes(Watermark(cursor=cursor))
    assert again.records == []
    assert again.rows_scanned == 0
    assert again.added_count == 0 and again.updated_count == 0
    # Nothing moved, so the mark HOLDS at the same value.
    assert again.cursor[CURSOR_MARK] == cursor[CURSOR_MARK]


def test_only_rows_past_the_mark_are_fetched_and_a_change_reads_as_an_update(rig):
    db, company, config, engine = rig
    cursor = _mark_after_initial(rig)

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE debtor SET company_name = 'Acme Holdings', "
            "last_modified = '2026-08-10 09:00:00' WHERE acc_no = '300-A001'"
        )
        conn.exec_driver_sql(
            "INSERT INTO debtor VALUES "
            "('300-A009', 'New Co', 'n@x.com', 1, '2026-08-11 09:00:00')"
        )

    result = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_CUSTOMER
    ).fetch_changes(Watermark(cursor=cursor))

    assert [r.raw["acc_no"] for r in result.records] == ["300-A001", "300-A009"]
    assert result.rows_scanned == 2
    # The edited row was already known and its compared columns moved; the new
    # one had never been seen.
    assert result.updated_count == 1
    assert result.added_count == 1
    assert result.cursor[CURSOR_MARK] == "2026-08-11 09:00:00"


def test_a_row_that_moves_ONLY_an_uncompared_column_is_not_an_update(rig):
    """"On change of which field" semantics (AC-22-16) - the reason compared
    columns exist at all."""
    db, company, config, engine = rig
    config.source_config = {**config.source_config, "comparedColumns": ["company_name"]}
    db.commit()
    cursor = _mark_after_initial(rig)

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE debtor SET email = 'changed@x.com', "
            "last_modified = '2026-08-12 09:00:00' WHERE acc_no = '300-A002'"
        )

    result = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_CUSTOMER
    ).fetch_changes(Watermark(cursor=cursor))
    # It is still FETCHED (the watermark moved, so it is a candidate) but the
    # hash of the compared set is identical, so it counts as neither.
    assert len(result.records) == 1
    assert result.added_count == 0 and result.updated_count == 0


def test_a_mark_left_by_a_DIFFERENT_watermark_column_is_ignored(rig):
    """Re-pointing the watermark makes the old mark meaningless; reusing it
    would compare apples to oranges and silently skip rows."""
    db, company, config, _engine = rig
    stale = {CURSOR_COLUMN: "some_other_column", CURSOR_MARK: "2026-08-03 09:00:00"}
    result = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_CUSTOMER
    ).fetch_changes(Watermark(cursor=stale))
    assert len(result.records) == 3  # a full initial load, not a filtered one


def test_a_NULLS_LAST_watermark_row_does_not_lose_the_mark(rig, monkeypatch):
    """S2 review SHOULD-FIX 3: ``new_mark`` was reassigned from EVERY row's
    watermark value, so a NULL on the LAST row (Postgres sorts NULLS LAST by
    default on ``ORDER BY t.<wm> ASC``) overwrote a real mark with ``None`` -
    the cursor came back empty and the NEXT run initial-loaded forever. The
    ``ORDER BY``'s own row order is what a real Postgres source would hand
    back; ``_read`` is stubbed here because SQLite (this suite's throwaway
    source) sorts NULLS FIRST, the opposite convention, so it cannot
    reproduce the failing row order on its own."""
    db, company, config, _engine = rig
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)
    raw_rows = [
        {"acc_no": "300-A001", "company_name": "Acme", "email": "a@x.com",
         "is_active": 1, "last_modified": "2026-08-01 09:00:00"},
        {"acc_no": "300-A002", "company_name": "Bolt", "email": "b@x.com",
         "is_active": 1, "last_modified": None},
    ]
    monkeypatch.setattr(source, "_read", lambda mark: raw_rows)
    result = source.fetch_changes(Watermark())
    assert result.cursor is not None
    assert result.cursor[CURSOR_MARK] == "2026-08-01 09:00:00"


def test_a_task_without_a_watermark_column_always_reads_everything(rig):
    db, company, config, _engine = rig
    config.source_config = {**config.source_config, "watermarkColumn": None}
    db.commit()
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)
    first = source.fetch_changes(Watermark())
    assert len(first.records) == 3
    assert first.cursor is None  # nothing to resume from
    second = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_CUSTOMER
    ).fetch_changes(Watermark(cursor=first.cursor))
    assert len(second.records) == 3
    # Second pass: every ref is known and unchanged.
    assert second.added_count == 0 and second.updated_count == 0


# ── safety + configuration ───────────────────────────────────────────────────


def test_a_non_select_stored_query_is_refused_at_EXECUTION_time(rig):
    """The save-time guard proved what was SAVED. A row edited straight into
    the JSON column (or a restored backup) must not sail through (AC-22-03)."""
    db, company, config, _engine = rig
    config.source_config = {**config.source_config, "query": "DELETE FROM debtor"}
    db.commit()
    with pytest.raises(Exception) as exc:
        SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)
    assert "SELECT" in str(exc.value)


def test_a_connection_from_ANOTHER_tenant_is_never_resolved(rig):
    """A stored connection id is a polymorphic reference (AC-22-29)."""
    db, company, config, _engine = rig
    config.source_config = {**config.source_config, "connectionId": "not-mine"}
    db.commit()
    with pytest.raises(SqlTaskNotConfigured):
        SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)


def test_a_task_with_no_key_columns_refuses_to_run(rig):
    db, company, config, _engine = rig
    config.source_config = {**config.source_config, "keyColumns": []}
    db.commit()
    with pytest.raises(SqlTaskNotConfigured):
        SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)


def test_a_watermark_column_the_query_no_longer_returns_fails_loudly(rig):
    db, company, config, _engine = rig
    config.source_config = {**config.source_config, "watermarkColumn": "gone"}
    db.commit()
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)
    with pytest.raises(SqlTaskNotConfigured):
        source.fetch_changes(Watermark(cursor={CURSOR_COLUMN: "gone", CURSOR_MARK: "x"}))


def test_a_row_with_a_blank_key_is_skipped_for_hashing_not_fatal(rig):
    """A blank key is a per-RECORD fault - the mapping engine stages it FAILED
    with a named error. It must not take the whole run down."""
    db, company, config, engine = rig
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO debtor VALUES ('', 'Blank', 'z@x.com', 1, '2026-08-20 09:00:00')"
        )
    result = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_CUSTOMER
    ).fetch_changes(Watermark())
    assert len(result.records) == 4  # it IS emitted, for the mapper to reject
    assert len(_hashes(db, company)) == 3  # but it has no ref to key a hash on


def test_a_row_limit_breach_stops_the_run_instead_of_exhausting_memory(rig):
    db, company, config, _engine = rig
    source = SqlDbSource(
        _ctx(db, company, config), entity_type=ENTITY_CUSTOMER, row_limit=1
    )
    with pytest.raises(Exception) as exc:
        source.fetch_changes(Watermark())
    assert "rows" in str(exc.value).lower()


# ── observability (plan 22 §2.1) ─────────────────────────────────────────────


def test_one_activity_record_per_executed_query(rig):
    db, company, config, _engine = rig
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)
    source.fetch_changes(Watermark())
    calls = source.drain_activity()
    assert len(calls) == 1
    call = calls[0]
    assert call.ok is True
    assert call.path == "sql:postgresql"
    assert call.request["dialect"] == "postgresql"
    assert call.request["mode"] == "initial"
    assert call.request["sql"].startswith("SELECT acc_no")
    assert call.response == {"rows": 3}
    assert isinstance(call.latency_ms, int)
    # Draining CLEARS the buffer, so a second read can never duplicate a row.
    assert source.drain_activity() == []


def test_the_activity_record_never_carries_the_password(rig):
    db, company, config, _engine = rig
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)
    source.fetch_changes(Watermark())
    assert PASSWORD not in repr(source.drain_activity())


# ── row-hash repository ──────────────────────────────────────────────────────


def test_row_hashes_are_scoped_to_tenant_company_and_entity(rig):
    db, company, config, _engine = rig
    repo = RowHashRepository(db)
    now = datetime.now(timezone.utc)
    repo.upsert_many(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER, {"r1": "a"}, seen_at=now)
    repo.upsert_many("other-tenant", company.id, ENTITY_CUSTOMER, {"r1": "b"}, seen_at=now)
    db.commit()
    assert repo.hashes_for(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER, ["r1"]) == {
        "r1": "a"
    }
    assert repo.hashes_for(DEFAULT_TENANT_ID, company.id, "supplier", ["r1"]) == {}


def test_upserting_an_existing_ref_replaces_its_hash(rig):
    db, company, config, _engine = rig
    repo = RowHashRepository(db)
    now = datetime.now(timezone.utc)
    repo.upsert_many(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER, {"r1": "a"}, seen_at=now)
    repo.upsert_many(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER, {"r1": "z"}, seen_at=now)
    db.commit()
    assert repo.hashes_for(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER, ["r1"]) == {
        "r1": "z"
    }
    assert repo.count(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER) == 1
