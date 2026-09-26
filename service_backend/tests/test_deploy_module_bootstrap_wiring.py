"""Issue #89 (prod 26 Sep 2026) - wiring guards added in the GREEN phase.

The red suite (test_deploy_module_bootstrap_abort / _lock_holder_report /
_drift_guard) pins the contracts; this file pins where they are wired:

- W0 ordering per module state: an already-migrated module migrates BEFORE
  its install/seed hook; a module brand-new to the database keeps
  install -> commit -> stamp (the chains were never written to replay from
  zero on top of their create_all baselines).
- W3: a module migration run by bootstrap_db sees the bootstrap lock_timeout
  (PGOPTIONS is set before any module migration opens its connection).
- W2: a failing lock-holder report never masks the original lock error.
- W4: the drift guard gates bootstrap_db's success line, the API lifespan and
  the Celery worker/beat start (as SystemExit, which Celery's signal dispatch
  does not swallow).

No real Postgres: fakes and monkeypatches only.
"""
import os

import psycopg2.errors
import pytest
import sqlalchemy as sa

from app import module_loader


class _RecordingDB:
    def __init__(self, calls):
        self.calls = calls
        self.pending = 0

    def commit(self):
        self.calls.append("commit")
        self.pending = 0

    def rollback(self):
        self.pending = 0


def _order_for_state(monkeypatch, state):
    calls = []
    db = _RecordingDB(calls)

    class _Hooks:
        def install(self, engine, db_):
            db_.pending += 1
            calls.append("install")

    def _migrate(engine, name):
        calls.append(f"migrate(pending={db.pending})")

    monkeypatch.setattr("app.services.app_store_service.module_hooks", lambda name: _Hooks())
    monkeypatch.setattr("app.module_platform.migrations.run_module_migrations", _migrate)
    monkeypatch.setattr(
        "app.module_platform.migrations.module_migration_state", lambda engine, name: state
    )
    module_loader._bootstrap_one_module(engine=object(), db=db, name="fakemod-order")
    return calls


def test_an_already_migrated_module_migrates_before_its_install_seed_hook(monkeypatch):
    calls = _order_for_state(monkeypatch, "versioned")
    assert calls.index("migrate(pending=0)") < calls.index("install")
    assert calls[-1] == "commit"  # the seed is committed, not left open


def test_a_legacy_unstamped_module_also_migrates_first(monkeypatch):
    calls = _order_for_state(monkeypatch, "legacy")
    assert calls.index("migrate(pending=0)") < calls.index("install")


def test_a_module_fresh_to_this_database_installs_commits_then_stamps(monkeypatch):
    calls = _order_for_state(monkeypatch, "fresh")
    assert calls.index("install") < calls.index("migrate(pending=0)")
    # the install's writes were committed before the migration step
    between = calls[calls.index("install"): calls.index("migrate(pending=0)")]
    assert "commit" in between


def test_module_migration_state_is_unmanaged_on_a_non_postgres_engine():
    from app.module_platform.migrations import module_migration_state

    engine = sa.create_engine("sqlite://")
    assert module_migration_state(engine, "ideation") == "unmanaged"
    assert module_migration_state(object(), "ideation") == "unmanaged"


def test_bootstrap_db_applies_lock_timeout_before_any_module_migration(monkeypatch):
    """W3: module migrations run under the same lock_timeout as core. It is
    delivered by PGOPTIONS (libpq reads it per connection), so it must be in
    the environment by the time a module migration opens Alembic's engine."""
    from tests.test_deploy_module_bootstrap_abort import (
        _stub_bootstrap_pipeline_except_modules,
    )

    fake_manifest = {"module_name": "fakemod-w3", "_dir": "fakemod-w3", "version": "1.0.0"}
    bootstrap_db_module = _stub_bootstrap_pipeline_except_modules(monkeypatch, fake_manifest)
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", "postgresql://x:x@localhost:5432/x")
    monkeypatch.setenv("PGOPTIONS", "")
    monkeypatch.setenv("BOOTSTRAP_LOCK_TIMEOUT", "17s")
    monkeypatch.setattr("app.services.app_store_service.module_hooks", lambda name: None)
    seen = []
    monkeypatch.setattr(
        "app.module_platform.migrations.run_module_migrations",
        lambda engine, name: seen.append(os.environ.get("PGOPTIONS", "")),
    )
    monkeypatch.setattr(
        "app.module_platform.drift_guard.check_module_schema_drift", lambda engine: None
    )

    bootstrap_db_module.main()

    assert seen == ["-c lock_timeout=17s"]


def test_bootstrap_db_never_prints_complete_over_a_module_schema_drift(monkeypatch, capsys):
    from app.module_platform.drift_guard import ModuleSchemaDrift
    from tests.test_deploy_module_bootstrap_abort import (
        _stub_bootstrap_pipeline_except_modules,
    )

    fake_manifest = {"module_name": "fakemod-w4", "_dir": "fakemod-w4", "version": "1.0.0"}
    bootstrap_db_module = _stub_bootstrap_pipeline_except_modules(monkeypatch, fake_manifest)
    monkeypatch.setattr("app.services.app_store_service.module_hooks", lambda name: None)
    monkeypatch.setattr(
        "app.module_platform.migrations.run_module_migrations", lambda engine, name: None
    )

    def _drift(engine):
        raise ModuleSchemaDrift("ideation", "0010_x", "0007_y")

    monkeypatch.setattr("app.module_platform.drift_guard.check_module_schema_drift", _drift)

    with pytest.raises(ModuleSchemaDrift):
        bootstrap_db_module.main()
    assert "bootstrap complete" not in capsys.readouterr().out


def test_the_api_refuses_to_start_on_module_schema_drift(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.module_platform.drift_guard import ModuleSchemaDrift

    def _drift(engine):
        raise ModuleSchemaDrift("ideation", "0010_x", "0007_y")

    monkeypatch.setattr("app.module_platform.drift_guard.check_module_schema_drift", _drift)

    with pytest.raises(ModuleSchemaDrift):
        with TestClient(app):
            pass


def test_the_api_lifespan_runs_the_guard_against_the_app_engine(monkeypatch):
    from fastapi.testclient import TestClient

    from app.database import engine as app_engine
    from app.main import app

    seen = []
    monkeypatch.setattr(
        "app.module_platform.drift_guard.check_module_schema_drift",
        lambda engine: seen.append(engine),
    )
    with TestClient(app):
        pass
    assert seen == [app_engine]


@pytest.mark.parametrize("signal_name", ["worker_init", "beat_init"])
def test_a_celery_worker_or_beat_exits_on_module_schema_drift(monkeypatch, signal_name):
    """Celery's Signal.send swallows Exception from a handler, so the guard
    must surface drift as SystemExit (not swallowed) to stop the process."""
    import celery.signals

    import app.workflow_engine.worker  # noqa: F401 - installs the guard
    from app.module_platform.drift_guard import ModuleSchemaDrift

    def _drift(engine):
        raise ModuleSchemaDrift("ideation", "0010_x", "0007_y")

    monkeypatch.setattr("app.module_platform.drift_guard.check_module_schema_drift", _drift)

    with pytest.raises(SystemExit) as exc_info:
        getattr(celery.signals, signal_name).send(sender=None)
    assert exc_info.value.code == 1


def test_a_celery_worker_starts_when_there_is_no_drift(monkeypatch):
    import celery.signals

    import app.workflow_engine.worker  # noqa: F401 - installs the guard

    monkeypatch.setattr(
        "app.module_platform.drift_guard.check_module_schema_drift", lambda engine: None
    )
    celery.signals.worker_init.send(sender=None)  # must not raise


def test_a_failing_lock_holder_report_never_masks_the_lock_error(monkeypatch, tmp_path):
    from app.module_platform import migrations as migrations_mod

    (tmp_path / "fakemod-w2r" / "alembic").mkdir(parents=True)
    manifest = {"module_name": "fakemod-w2r", "_dir": "fakemod-w2r"}
    monkeypatch.setattr(migrations_mod, "MODULES_DIR", tmp_path)
    monkeypatch.setattr(migrations_mod, "discover_manifests", lambda *a, **k: [manifest])

    class _Insp:
        def get_table_names(self, schema=None):
            return []

    monkeypatch.setattr(migrations_mod, "inspect", lambda engine: _Insp())

    class _Engine:
        class dialect:
            name = "postgresql"

    lock_exc = sa.exc.OperationalError(
        "CREATE INDEX ix_fake ON fake (tenant_id)",
        {},
        psycopg2.errors.LockNotAvailable("canceling statement due to lock timeout"),
    )

    def _boom(cfg, rev):
        raise lock_exc

    monkeypatch.setattr("alembic.command.upgrade", _boom)

    def _report_fails(engine, schema):
        raise RuntimeError("pg_stat_activity unreadable")

    monkeypatch.setattr(migrations_mod, "report_lock_holders", _report_fails)

    with pytest.raises(sa.exc.OperationalError) as exc_info:
        migrations_mod.run_module_migrations(_Engine(), "fakemod-w2r")
    assert exc_info.value is lock_exc


def test_the_lock_holder_query_is_filtered_to_the_module_schema_in_sql():
    """The tester's report test accepts the schema appearing in the bound
    params alone; pin that the SQL actually FILTERS on it (a report of every
    lock in the cluster would bury the holder)."""
    from app.module_platform import migrations as migrations_mod

    sql = " ".join(migrations_mod._LOCK_HOLDERS_SQL.split())
    assert "n.nspname = :schema" in sql
    assert "l.granted" in sql
    assert "pg_backend_pid()" in sql
