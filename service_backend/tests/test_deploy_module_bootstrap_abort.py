"""Prod incident 26 Sep 2026 (issue #89) - RED tests, red-first (TDD).

The 14:50 MYT deploy ran the ideation module migrations while a previous
bootstrap's own install/seed hook still held an open write on the shared
`db` session; the module migration then lock-timed-out fighting its OWN
uncommitted transaction, `module_loader.bootstrap_modules` swallowed the
failure into `ERRORED_MODULES` and returned normally, `start.sh` printed
"bootstrap complete: migrated + seeded + modules", the container went
healthy, and production served ideation code 3 migrations ahead of its
schema (`column ideas.title does not exist`).

Covers:
  W0 - bootstrap must never call a module's per-module Alembic migration
       while that module's own install/seed hook still holds an
       uncommitted write on the shared `db` session (the self-block root
       cause).
  W1 - a module migration OR seed failure must propagate out of
       `bootstrap_modules` / `_bootstrap_one_module` so `bootstrap_db`
       (`scripts/bootstrap_db.py:main`) exits non-zero; no
       "bootstrap complete" line may print after any module failure; the
       per-module error log line (module name + the SQL) must still fire.

None of these tests touch real Postgres - `_bootstrap_one_module` and
`bootstrap_modules` are exercised with fakes/monkeypatches only.
"""
import logging

import pytest
import sqlalchemy as sa

from app import module_loader


# ── W0: bootstrap must never hold a lock against its own module migration ──


def test_bootstrap_one_module_runs_migrations_with_no_pending_install_write(monkeypatch):
    """W0 (issue #89 root cause): `_bootstrap_one_module` calls
    `hooks.install(engine, db)` (ideation's `install()` seeds
    `ideation_artifact_templates` through the shared `db` Session, whose
    transaction then stays open) BEFORE `run_module_migrations`, which opens
    a SEPARATE alembic connection needing a lock the still-open `db`
    transaction blocks - lock timeout, every time, even with no other
    session alive.

    RED today: this records "was there a pending (uncommitted) write on
    `db` at the moment `run_module_migrations` was invoked" and asserts
    there was NOT - i.e. the install hook's write must be committed (or the
    call order flipped to migrate-then-seed) before the migration step
    runs. Today's `_bootstrap_one_module` does neither, so this fails.
    """

    class _FakeDB:
        def __init__(self):
            self.pending_writes = 0

        def mark_write(self):
            self.pending_writes += 1

        def commit(self):
            self.pending_writes = 0

        def rollback(self):
            self.pending_writes = 0

    class _FakeHooks:
        def install(self, engine, db):
            db.mark_write()  # e.g. seed_br_template's INSERT, never committed here

    db = _FakeDB()
    pending_at_migration_time = []

    def _fake_run_module_migrations(engine, name):
        pending_at_migration_time.append(db.pending_writes)

    monkeypatch.setattr(
        "app.services.app_store_service.module_hooks", lambda name: _FakeHooks()
    )
    monkeypatch.setattr(
        "app.module_platform.migrations.run_module_migrations",
        _fake_run_module_migrations,
    )

    module_loader._bootstrap_one_module(engine=object(), db=db, name="fakemod-w0")

    assert pending_at_migration_time == [0], (
        "run_module_migrations ran while the module's own install/seed hook "
        f"still held an uncommitted write (pending_writes={pending_at_migration_time}) "
        "- bootstrap must never block its own module migration behind its "
        "own open transaction (issue #89)"
    )


# ── W1: a module failure is fatal, not swallowed ────────────────────────────


def test_bootstrap_modules_propagates_a_single_module_failure_instead_of_swallowing(
    monkeypatch, session_factory
):
    """W1 core: `bootstrap_modules`'s per-module loop currently does
    ``try: _bootstrap_one_module(...) except Exception: db.rollback();
    ERRORED_MODULES[name] = ...; logger.error(...)`` and then CONTINUES to
    `_backfill_tenant_modules` + `db.commit()` - exactly the swallow that
    let ideation's migration failure through in the incident. It must
    re-raise (after logging) so the caller (`bootstrap_db`) sees the
    failure and exits non-zero."""
    db = session_factory()
    engine = db.get_bind()

    def _boom(engine_, db_, name):
        raise sa.exc.OperationalError(
            "CREATE INDEX IF NOT EXISTS ix_ideation_artifact_tmpl_tenant ...",
            {},
            Exception("canceling statement due to lock timeout"),
        )

    monkeypatch.setattr(module_loader, "_bootstrap_one_module", _boom)
    monkeypatch.setattr(
        module_loader,
        "discover_manifests",
        lambda *a, **k: [{"module_name": "fakemod-w1", "version": "1.0.0"}],
    )
    monkeypatch.setattr(
        "app.module_platform.dependencies.resolve_install_order",
        lambda manifests: ["fakemod-w1"],
    )

    with pytest.raises(sa.exc.OperationalError):
        module_loader.bootstrap_modules(engine=engine, db=db)
    db.close()


# ── W1: scripts.bootstrap_db.main() entry point ─────────────────────────────


def _stub_bootstrap_pipeline_except_modules(monkeypatch, fake_manifest):
    """Stub every `scripts.bootstrap_db.main()` step EXCEPT the real
    `bootstrap_modules()` call, and point `SessionLocal`/`engine` at a fresh,
    schema-created (but otherwise empty) sqlite db so `bootstrap_modules`'s
    real `sync_module_catalog` / `_backfill_tenant_modules` queries work."""
    import scripts.bootstrap_db as bootstrap_db_module
    from app.database import Base
    from sqlalchemy.orm import sessionmaker

    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.database.SessionLocal", TestSessionLocal)
    monkeypatch.setattr(bootstrap_db_module, "SessionLocal", TestSessionLocal)

    monkeypatch.setattr(bootstrap_db_module, "run_migrations", lambda: None)
    monkeypatch.setattr(bootstrap_db_module, "ensure_role_and_db", lambda: None)
    monkeypatch.setattr(bootstrap_db_module, "seed_all", lambda db: None)
    monkeypatch.setattr("app.seed.sweep_tenant_admin_grants", lambda db: None)
    monkeypatch.setattr(
        "scripts.seed_ideation_grill_agent.seed_all_grill_agents", lambda db: 0
    )

    class _FakeAppStoreService:
        def __init__(self, db):
            pass

        def install(self, tenant_id, name):
            pass

    monkeypatch.setattr(
        "app.services.app_store_service.AppStoreService", _FakeAppStoreService
    )
    from app.config import settings

    monkeypatch.setattr(settings, "environment", "production")

    monkeypatch.setattr(
        module_loader, "discover_manifests", lambda *a, **k: [fake_manifest]
    )
    monkeypatch.setattr(
        "app.module_platform.dependencies.resolve_install_order",
        lambda manifests: [fake_manifest["module_name"]],
    )
    return bootstrap_db_module


def test_main_aborts_with_no_bootstrap_complete_line_on_a_module_migration_failure(
    monkeypatch, capsys, caplog
):
    """W1 (migration failure), entry point: `python -m scripts.bootstrap_db`
    must exit non-zero (an uncaught exception from `main()` does this) and
    the log must still carry the module name + the failing SQL. RED today:
    `main()` returns normally and prints "bootstrap complete ..."."""
    fake_manifest = {"module_name": "fakemod-w1-mig", "_dir": "fakemod-w1-mig", "version": "1.0.0"}
    bootstrap_db_module = _stub_bootstrap_pipeline_except_modules(monkeypatch, fake_manifest)

    monkeypatch.setattr(
        "app.services.app_store_service.module_hooks", lambda name: None
    )

    def _boom_migrate(engine, name):
        raise sa.exc.OperationalError(
            "CREATE INDEX IF NOT EXISTS ix_ideation_artifact_tmpl_tenant ...",
            {},
            Exception("canceling statement due to lock timeout"),
        )

    monkeypatch.setattr(
        "app.module_platform.migrations.run_module_migrations", _boom_migrate
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(sa.exc.OperationalError):
            bootstrap_db_module.main()

    out = capsys.readouterr().out
    assert "bootstrap complete" not in out, (
        "'bootstrap complete' printed after a module migration failure - "
        "the swap would have gone green on a broken deploy"
    )
    assert "fakemod-w1-mig" in caplog.text
    assert "canceling statement due to lock timeout" in caplog.text


def test_main_aborts_with_no_bootstrap_complete_line_on_a_module_seed_failure(
    monkeypatch, capsys, caplog
):
    """W1 (seed failure), entry point: same contract as the migration
    variant, but the failure originates in the module's `install()` seed
    step (e.g. `seed_br_template` hitting a duplicate key). RED today for
    the same reason: `bootstrap_modules` swallows it."""
    fake_manifest = {"module_name": "fakemod-w1-seed", "_dir": "fakemod-w1-seed", "version": "1.0.0"}
    bootstrap_db_module = _stub_bootstrap_pipeline_except_modules(monkeypatch, fake_manifest)

    class _Hooks:
        def install(self, engine, db):
            raise RuntimeError(
                "seed_br_template failed: duplicate key value violates unique constraint"
            )

    monkeypatch.setattr(
        "app.services.app_store_service.module_hooks", lambda name: _Hooks()
    )
    monkeypatch.setattr(
        "app.module_platform.migrations.run_module_migrations", lambda engine, name: None
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError):
            bootstrap_db_module.main()

    out = capsys.readouterr().out
    assert "bootstrap complete" not in out
    assert "fakemod-w1-seed" in caplog.text
    assert "seed_br_template" in caplog.text


def test_main_completes_and_prints_bootstrap_complete_when_every_module_bootstraps_cleanly(
    monkeypatch, capsys
):
    """W1 control: a clean bootstrap (no module failure) must still reach
    the end of `main()` and print the "bootstrap complete" line - the fix
    for W1 must not turn every bootstrap fatal, only a failing one. This
    passes both before and after the fix (it is the regression guard)."""
    fake_manifest = {"module_name": "fakemod-w1-clean", "_dir": "fakemod-w1-clean", "version": "1.0.0"}
    bootstrap_db_module = _stub_bootstrap_pipeline_except_modules(monkeypatch, fake_manifest)

    monkeypatch.setattr(
        "app.services.app_store_service.module_hooks", lambda name: None
    )
    monkeypatch.setattr(
        "app.module_platform.migrations.run_module_migrations", lambda engine, name: None
    )

    bootstrap_db_module.main()  # must not raise

    out = capsys.readouterr().out
    assert "bootstrap complete: migrated + seeded + modules" in out
