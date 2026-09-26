"""Prod incident 26 Sep 2026 (issue #89), W2 - RED tests, red-first (TDD).

Before giving up on a LockNotAvailable-flavoured error, the module migration
path must report WHO holds the blocking lock: pid, state, transaction age and
query text for every current holder (joining `pg_locks` to `pg_stat_activity`,
scoped to the module's own schema - the relation the migration was waiting on
lives there). This is what the manual re-run in the incident could not see
("no other session" in `pg_stat_activity` from a plain `SELECT * FROM
pg_stat_activity` - the operator had to guess).

Contract this file pins for the coder (both currently missing - natural
ImportError/AttributeError until implemented, not an absence-pin):

  ``app.module_platform.migrations.report_lock_holders(engine, schema) -> list[dict]``
      Queries `pg_locks` joined to `pg_stat_activity`, scoped to relations in
      ``schema`` (via `pg_class`/`pg_namespace` - the migration's own module
      schema, since a generic OperationalError does not reliably carry the
      exact blocked relation name). Logs one ERROR line per holder (pid,
      state, transaction age, query text) via the module's `logger`, and
      returns the holder rows for the caller.

  ``run_module_migrations`` calls ``report_lock_holders(engine, schema)``
      when the alembic `upgrade`/`stamp` call raises an
      ``sqlalchemy.exc.OperationalError`` wrapping a
      ``psycopg2.errors.LockNotAvailable`` (or the raw
      ``psycopg2.errors.LockNotAvailable`` directly), THEN re-raises (W1:
      the failure must still propagate).

No real Postgres anywhere in this file: fake engine/connection objects that
record the executed SQL text and return canned holder rows.
"""
import logging

import psycopg2.errors
import pytest
import sqlalchemy as sa


# ── the holder-report helper itself ─────────────────────────────────────────


def test_report_lock_holders_logs_pid_state_xact_age_and_query_for_each_holder(caplog):
    """W2 core: `report_lock_holders(engine, schema)` queries pg_locks
    joined to pg_stat_activity (scoped to the module's schema) and logs
    pid, state, transaction age and query text for every holder row
    returned. RED today: `report_lock_holders` does not exist."""
    from app.module_platform.migrations import report_lock_holders

    executed = []
    canned_rows = [
        {
            "pid": 4242,
            "state": "idle in transaction",
            "xact_age": "0:05:12",
            "query": "INSERT INTO app_ideation.ideation_artifact_templates (id) VALUES (1)",
        },
        {
            "pid": 5150,
            "state": "active",
            "xact_age": "0:00:03",
            "query": "SELECT * FROM app_ideation.ideas WHERE tenant_id = 't1'",
        },
    ]

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

    class _FakeConnection:
        def execute(self, statement, params=None):
            executed.append((str(statement), params))
            return _FakeResult(canned_rows)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    class _FakeEngine:
        def connect(self):
            return _FakeConnection()

    with caplog.at_level(logging.ERROR):
        holders = report_lock_holders(_FakeEngine(), "app_ideation")

    assert executed, "report_lock_holders never executed a pg_locks/pg_stat_activity query"
    sql_text, params = executed[0]
    assert "pg_locks" in sql_text
    assert "pg_stat_activity" in sql_text
    # Scoped to the module's own schema, not every lock in the cluster.
    assert (params and "app_ideation" in str(params)) or "app_ideation" in sql_text

    assert holders == canned_rows

    log_text = caplog.text
    for row in canned_rows:
        assert str(row["pid"]) in log_text
        assert row["state"] in log_text
        assert row["xact_age"] in log_text
        assert row["query"] in log_text


def test_report_lock_holders_logs_nothing_alarming_when_no_holder_is_found(caplog):
    """Control: an empty holder set (lock cleared between the failure and
    the report, or a non-lock cause) must not fabricate a holder row - the
    helper still runs cleanly and returns an empty list."""
    from app.module_platform.migrations import report_lock_holders

    class _FakeResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class _FakeConnection:
        def execute(self, statement, params=None):
            return _FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    class _FakeEngine:
        def connect(self):
            return _FakeConnection()

    holders = report_lock_holders(_FakeEngine(), "app_ideation")
    assert holders == []


# ── wiring: run_module_migrations must call it, then still propagate ───────


def test_run_module_migrations_reports_lock_holders_before_propagating_lock_not_available(
    monkeypatch, tmp_path
):
    """W2 wiring (+ W1): on a LockNotAvailable-flavoured OperationalError
    from the alembic upgrade/stamp call, `run_module_migrations` must call
    `report_lock_holders(engine, schema)` BEFORE the error propagates. Fully
    faked engine/inspector/alembic call - no Postgres.

    RED today: `report_lock_holders` is never called (it does not exist
    yet); the exception itself already propagates unguarded (that part is
    already correct and must stay that way - W1)."""
    from app.module_platform import migrations as migrations_mod

    module_dir = tmp_path / "fakemod-w2"
    (module_dir / "alembic").mkdir(parents=True)
    manifest = {"module_name": "fakemod-w2", "_dir": "fakemod-w2"}  # no schema -> skip CREATE SCHEMA

    monkeypatch.setattr(migrations_mod, "MODULES_DIR", tmp_path)
    monkeypatch.setattr(migrations_mod, "discover_manifests", lambda *a, **k: [manifest])

    class _FakeInspector:
        def get_table_names(self, schema=None):
            return []

    monkeypatch.setattr(migrations_mod, "inspect", lambda engine: _FakeInspector())

    class _FakeDialect:
        name = "postgresql"

    class _FakeEngine:
        dialect = _FakeDialect()

    orig = psycopg2.errors.LockNotAvailable("canceling statement due to lock timeout")
    lock_exc = sa.exc.OperationalError("CREATE INDEX ix_fake ON fake_table (tenant_id)", {}, orig)

    def _boom_upgrade(cfg, revision):
        raise lock_exc

    monkeypatch.setattr("alembic.command.upgrade", _boom_upgrade)

    calls = []
    monkeypatch.setattr(
        migrations_mod,
        "report_lock_holders",
        lambda engine, schema: calls.append((engine, schema)),
        raising=False,
    )

    with pytest.raises(sa.exc.OperationalError):
        migrations_mod.run_module_migrations(_FakeEngine(), "fakemod-w2")

    assert calls, (
        "report_lock_holders was never called before the LockNotAvailable "
        "propagated out of run_module_migrations"
    )


def test_run_module_migrations_does_not_report_holders_for_an_unrelated_failure(
    monkeypatch, tmp_path
):
    """Control: a non-lock failure (e.g. a genuine syntax/constraint error)
    must NOT trigger the lock-holder report - only a LockNotAvailable does."""
    from app.module_platform import migrations as migrations_mod

    module_dir = tmp_path / "fakemod-w2-other"
    (module_dir / "alembic").mkdir(parents=True)
    manifest = {"module_name": "fakemod-w2-other", "_dir": "fakemod-w2-other"}

    monkeypatch.setattr(migrations_mod, "MODULES_DIR", tmp_path)
    monkeypatch.setattr(migrations_mod, "discover_manifests", lambda *a, **k: [manifest])

    class _FakeInspector:
        def get_table_names(self, schema=None):
            return []

    monkeypatch.setattr(migrations_mod, "inspect", lambda engine: _FakeInspector())

    class _FakeDialect:
        name = "postgresql"

    class _FakeEngine:
        dialect = _FakeDialect()

    orig = psycopg2.errors.UniqueViolation("duplicate key value violates unique constraint")
    other_exc = sa.exc.OperationalError("INSERT INTO fake_table ...", {}, orig)

    def _boom_upgrade(cfg, revision):
        raise other_exc

    monkeypatch.setattr("alembic.command.upgrade", _boom_upgrade)

    calls = []
    monkeypatch.setattr(
        migrations_mod,
        "report_lock_holders",
        lambda engine, schema: calls.append((engine, schema)),
        raising=False,
    )

    with pytest.raises(sa.exc.OperationalError):
        migrations_mod.run_module_migrations(_FakeEngine(), "fakemod-w2-other")

    assert not calls, "report_lock_holders fired for a non-lock failure"
