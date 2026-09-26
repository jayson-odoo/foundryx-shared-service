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
    monkeypatch.setattr("app.module_platform.drift_guard.STARTUP_GUARD_ENABLED", True)
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
    monkeypatch.setattr("app.module_platform.drift_guard.STARTUP_GUARD_ENABLED", True)
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
    monkeypatch.setattr("app.module_platform.drift_guard.STARTUP_GUARD_ENABLED", True)
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
    monkeypatch.setattr("app.module_platform.drift_guard.STARTUP_GUARD_ENABLED", True)
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


def test_the_startup_guard_is_not_switchable_from_the_environment():
    """Review N4: no env var or setting can switch the guard off in
    production - the only switch is a module attribute the test suite flips.
    Pin that drift_guard.py never reads the environment or settings."""
    import inspect as _inspect

    from app.module_platform import drift_guard

    src = _inspect.getsource(drift_guard)
    for needle in ("os.environ", "getenv", "environ[", "settings", "import os"):
        assert needle not in src, needle



# ── review round 1 ─────────────────────────────────────────────────────────


def test_the_session_is_committed_before_migrating_even_with_a_previous_modules_write(
    monkeypatch,
):
    """Review N5: a pending write left by a PREVIOUS module (or the catalog
    sync) must be committed before this module's migration on the versioned
    path too - not only the module's own seed."""
    calls = []
    db = _RecordingDB(calls)
    db.pending = 1  # the previous module's uncommitted seed

    def _migrate(engine, name):
        calls.append(f"migrate(pending={db.pending})")

    monkeypatch.setattr("app.services.app_store_service.module_hooks", lambda name: None)
    monkeypatch.setattr("app.module_platform.migrations.run_module_migrations", _migrate)
    monkeypatch.setattr(
        "app.module_platform.migrations.module_migration_state", lambda e, n: "versioned"
    )
    module_loader._bootstrap_one_module(engine=object(), db=db, name="fakemod-prev")
    assert "migrate(pending=0)" in calls


@pytest.mark.parametrize(
    "code_head, db_version, known, verdict",
    [
        ("a,b", "a", {"a", "b", "base"}, "behind"),  # a code head the DB lacks
        ("a,b", "a,b", {"a", "b"}, "current"),
        ("a,b", "b,a", {"a", "b"}, "current"),
        ("a,b", "a,c", {"a", "b"}, "ahead"),  # c unknown to this code
        ("b", "a", {"a", "b"}, "behind"),
    ],
)
def test_classify_handles_multiple_heads(code_head, db_version, known, verdict):
    from app.module_platform.drift_guard import _classify

    assert _classify(code_head, db_version, known)[0] == verdict


class _TrackingEngine:
    def __init__(self):
        self.disposed = 0

    def dispose(self):
        self.disposed += 1


@pytest.mark.parametrize("outcome", ["ok", "drift", "error"])
def test_the_celery_guard_disposes_the_engine_pool_before_prefork(monkeypatch, outcome):
    """Review B1: worker_init/beat_init run in the PARENT before the prefork
    pool forks; a pooled connection left behind would be shared by every
    child. The pool is disposed whatever the guard's outcome."""
    import celery.signals

    import app.workflow_engine.worker  # noqa: F401 - installs the guard
    from app.module_platform.drift_guard import ModuleSchemaDrift

    engine = _TrackingEngine()
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.module_platform.drift_guard.STARTUP_GUARD_ENABLED", True)

    def _check(e):
        if outcome == "drift":
            raise ModuleSchemaDrift("ideation", "0010_x", "0007_y")
        if outcome == "error":
            raise sa.exc.OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr("app.module_platform.drift_guard.check_module_schema_drift", _check)
    if outcome == "ok":
        celery.signals.worker_init.send(sender=None)
    else:
        with pytest.raises(SystemExit):
            celery.signals.worker_init.send(sender=None)
    assert engine.disposed == 1


def test_the_celery_guard_leaves_no_pooled_connection_on_a_real_engine(monkeypatch, tmp_path):
    """Review B1, on a real QueuePool: the check opens a pooled connection;
    after the guard nothing is left checked in for a forked child to inherit."""
    import celery.signals

    import app.workflow_engine.worker  # noqa: F401 - installs the guard

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'guard.db'}", poolclass=sa.pool.QueuePool)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.module_platform.drift_guard.STARTUP_GUARD_ENABLED", True)

    def _check(e):
        with e.connect() as conn:
            conn.execute(sa.text("SELECT 1"))

    monkeypatch.setattr("app.module_platform.drift_guard.check_module_schema_drift", _check)
    celery.signals.worker_init.send(sender=None)
    assert engine.pool.checkedin() == 0


def test_the_celery_guard_fails_closed_on_any_error(monkeypatch, caplog):
    """Review S5: a guard that cannot run (DB unreachable, bad manifest) stops
    the Celery process with a logged reason - not only a detected drift."""
    import logging

    import celery.signals

    import app.workflow_engine.worker  # noqa: F401 - installs the guard

    monkeypatch.setattr("app.database.engine", _TrackingEngine())
    monkeypatch.setattr("app.module_platform.drift_guard.STARTUP_GUARD_ENABLED", True)

    def _check(e):
        raise RuntimeError("could not read alembic_version_ideation")

    monkeypatch.setattr("app.module_platform.drift_guard.check_module_schema_drift", _check)
    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(SystemExit) as exc_info:
            celery.signals.beat_init.send(sender=None)
    assert exc_info.value.code == 1
    assert "could not read alembic_version_ideation" in caplog.text
    assert "fail closed" in caplog.text


# ── S2 / N1: lock-holder report redaction + outside-schema fallback ───────


class _SeqEngine:
    """Returns the n-th canned row list for the n-th execute; records SQL."""

    def __init__(self, *results):
        self.results = list(results)
        self.sql = []

    def connect(self):
        engine = self

        class _Conn:
            def execute(self, statement, params=None):
                engine.sql.append(str(statement))
                rows = engine.results.pop(0) if engine.results else []

                class _R:
                    def mappings(self):
                        return self

                    def all(self):
                        return rows

                return _R()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Conn()


def test_lock_holder_report_redacts_literals_and_truncates_query_text(caplog):
    import logging

    from app.module_platform.migrations import report_lock_holders

    secret_query = (
        "UPDATE users SET password_hash = '$2b$12$abcdefSECRETHASH', "
        "email = 'ceo@example.com' WHERE api_token = 'tok_live_123' " + "x" * 400
    )
    engine = _SeqEngine([{"pid": 7, "state": "idle in transaction", "xact_age": "0:01", "query": secret_query}])
    with caplog.at_level(logging.ERROR):
        holders = report_lock_holders(engine, "app_ideation")

    for secret in ("SECRETHASH", "ceo@example.com", "tok_live_123"):
        assert secret not in caplog.text
        assert secret not in holders[0]["query"]
    assert "'?'" in holders[0]["query"]
    assert len(holders[0]["query"]) <= 200
    # and the SQL itself redacts + truncates before the text leaves Postgres
    assert "left(regexp_replace(a.query" in engine.sql[0]
    assert ", 200)" in engine.sql[0]


def test_lock_holder_report_lists_idle_in_transaction_sessions_when_the_schema_has_no_holder(
    caplog,
):
    """Review N1: nothing holds a lock inside the module schema -> say the
    holder may be outside it and list database-wide idle-in-transaction
    sessions older than 10s (redacted)."""
    import logging

    from app.module_platform.migrations import report_lock_holders

    engine = _SeqEngine(
        [],
        [{"pid": 99, "state": "idle in transaction", "xact_age": "0:04:00",
          "query": "INSERT INTO public.tenants (slug) VALUES ('acme-secret')",
          "application_name": "celery", "backend_type": "client backend", "client_addr": "10.0.0.5"}],
    )
    with caplog.at_level(logging.ERROR):
        holders = report_lock_holders(engine, "app_ideation")

    assert holders == []  # the schema-scoped contract is unchanged
    assert "OUTSIDE the schema" in caplog.text
    assert "pid=99" in caplog.text
    assert "acme-secret" not in caplog.text
    assert "idle in transaction" in engine.sql[1]
    assert "interval '10 seconds'" in engine.sql[1]
    assert "regexp_replace" in engine.sql[1]


# ── S1: a DB ahead of this code (rollback) never runs `upgrade head` ──────


class _BeginEngine:
    class dialect:
        name = "postgresql"

    def begin(self):
        class _C:
            def execute(self, *a, **k):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _C()


def _versioned_ideation(monkeypatch, db_version):
    from app.module_platform import migrations as migrations_mod

    monkeypatch.setattr(migrations_mod, "_migration_state", lambda *a, **k: "versioned")
    monkeypatch.setattr(
        "app.module_platform.drift_guard.module_db_version", lambda engine, m: db_version
    )
    upgrades = []
    monkeypatch.setattr("alembic.command.upgrade", lambda cfg, rev: upgrades.append(rev))
    return migrations_mod, upgrades


def test_a_rollback_image_skips_module_migrations_when_the_db_is_ahead(monkeypatch, caplog):
    import logging

    migrations_mod, upgrades = _versioned_ideation(monkeypatch, "0011_from_a_newer_image")
    with caplog.at_level(logging.WARNING):
        migrations_mod.run_module_migrations(_BeginEngine(), "ideation")  # must not raise
    assert upgrades == []
    assert "0011_from_a_newer_image" in caplog.text


def test_a_db_behind_the_code_still_upgrades(monkeypatch):
    migrations_mod, upgrades = _versioned_ideation(monkeypatch, "0007_ideation_idea_attachments")
    migrations_mod.run_module_migrations(_BeginEngine(), "ideation")
    assert upgrades == ["head"]
