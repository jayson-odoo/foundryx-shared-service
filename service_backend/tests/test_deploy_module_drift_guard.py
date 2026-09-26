"""Prod incident 26 Sep 2026 (issue #89), W4 - RED tests, red-first (TDD).

Even with W1 (a module migration failure is now fatal), a path that skips
bootstrap entirely (a hand-rolled container start, a stuck retry loop an
operator kills, `SKIP_MIGRATIONS=1` misused) must never let the API serve
traffic against a database that is behind the code's module migrations -
"code ahead of schema" is exactly how `column ideas.title does not exist`
happened in production. This is the LAST line of defence, checked at API
start, independent of whatever ran (or didn't) before it.

Contract this file pins for the coder (new module - natural ImportError
until it exists, not an absence-pin):

  ``app.module_platform.drift_guard.ModuleSchemaDrift(RuntimeError)``
      Named error, raised when an installed module's database schema is
      behind its code's alembic head. Carries ``.module_name``,
      ``.code_head``, ``.db_version`` for the boot log.

  ``app.module_platform.drift_guard.module_code_head(manifest) -> str | None``
      The module's alembic head revision read from its on-disk
      ``alembic/versions`` dir (via `alembic.script.ScriptDirectory`), or
      ``None`` when the module has no ``alembic/`` dir (legacy create_all
      module - ignored by the guard, same convention as
      `run_module_migrations`).

  ``app.module_platform.drift_guard.module_db_version(engine, manifest) -> str | None``
      The module's stamped alembic version read from its
      ``alembic_version_<name>`` table (schema-qualified), or ``None`` when
      the table does not exist yet (module never installed in this
      database - ignored by the guard, NOT a drift).

  ``app.module_platform.drift_guard.check_module_schema_drift(engine) -> None``
      For every module `discover_manifests()` returns: skip when
      `module_code_head` is None (no alembic dir) or `module_db_version` is
      None (never installed here); otherwise raise `ModuleSchemaDrift` when
      the two differ. No-ops entirely on a non-Postgres engine (matches
      `run_module_migrations`'s own dialect guard - the sqlite test suite
      must never hit it for real). Called once at API start, AFTER
      bootstrap, on the real app engine.

No real Postgres anywhere in this file - `discover_manifests`,
`module_code_head` and `module_db_version` are monkeypatched; the "engine"
is a bare fake carrying only `.dialect.name`.
"""
import pytest


class _FakePostgresEngine:
    class _Dialect:
        name = "postgresql"

    dialect = _Dialect()


class _FakeSqliteEngine:
    class _Dialect:
        name = "sqlite"

    dialect = _Dialect()


def test_check_module_schema_drift_raises_named_error_when_db_is_behind(monkeypatch):
    """W4 core: the DB's stamped version differs from the module's code
    head -> refuse to start with the named `ModuleSchemaDrift`, carrying
    both revisions for the boot log. RED today: the module does not exist."""
    from app.module_platform.drift_guard import ModuleSchemaDrift, check_module_schema_drift

    manifest = {"module_name": "ideation", "_dir": "ideation", "schema": "app_ideation"}
    monkeypatch.setattr(
        "app.module_platform.drift_guard.discover_manifests", lambda *a, **k: [manifest]
    )
    monkeypatch.setattr(
        "app.module_platform.drift_guard.module_code_head", lambda m: "0010_business_reqs"
    )
    monkeypatch.setattr(
        "app.module_platform.drift_guard.module_db_version", lambda engine, m: "0007_something"
    )

    with pytest.raises(ModuleSchemaDrift) as exc_info:
        check_module_schema_drift(_FakePostgresEngine())

    err = exc_info.value
    assert err.module_name == "ideation"
    assert err.code_head == "0010_business_reqs"
    assert err.db_version == "0007_something"
    assert "ideation" in str(err)


def test_check_module_schema_drift_starts_clean_when_db_matches_code_head(monkeypatch):
    """W4 control: DB version == code head -> no raise, API starts."""
    from app.module_platform.drift_guard import check_module_schema_drift

    manifest = {"module_name": "ideation", "_dir": "ideation", "schema": "app_ideation"}
    monkeypatch.setattr(
        "app.module_platform.drift_guard.discover_manifests", lambda *a, **k: [manifest]
    )
    monkeypatch.setattr(
        "app.module_platform.drift_guard.module_code_head", lambda m: "0010_business_reqs"
    )
    monkeypatch.setattr(
        "app.module_platform.drift_guard.module_db_version", lambda engine, m: "0010_business_reqs"
    )

    check_module_schema_drift(_FakePostgresEngine())  # must not raise


def test_check_module_schema_drift_ignores_a_module_never_installed_in_this_database(
    monkeypatch,
):
    """W4: a module on disk (new code) whose version table does not exist
    yet in THIS database (never globally installed here) is ignored by the
    guard - that is bootstrap's job, not a drift."""
    from app.module_platform.drift_guard import check_module_schema_drift

    manifest = {"module_name": "brand-new-module", "_dir": "brand-new-module", "schema": "app_brandnew"}
    monkeypatch.setattr(
        "app.module_platform.drift_guard.discover_manifests", lambda *a, **k: [manifest]
    )
    monkeypatch.setattr(
        "app.module_platform.drift_guard.module_code_head", lambda m: "0001_initial"
    )
    monkeypatch.setattr(
        "app.module_platform.drift_guard.module_db_version", lambda engine, m: None
    )

    check_module_schema_drift(_FakePostgresEngine())  # must not raise


def test_check_module_schema_drift_ignores_a_module_with_no_alembic_dir(monkeypatch):
    """W4: a legacy create_all module (no `alembic/` dir - `module_code_head`
    returns None) is ignored, same convention as `run_module_migrations`."""
    from app.module_platform.drift_guard import check_module_schema_drift

    manifest = {"module_name": "legacy-module", "_dir": "legacy-module", "schema": "app_legacy"}
    monkeypatch.setattr(
        "app.module_platform.drift_guard.discover_manifests", lambda *a, **k: [manifest]
    )
    monkeypatch.setattr("app.module_platform.drift_guard.module_code_head", lambda m: None)

    def _boom_if_called(engine, m):
        raise AssertionError("module_db_version must not be queried when there is no code head")

    monkeypatch.setattr("app.module_platform.drift_guard.module_db_version", _boom_if_called)

    check_module_schema_drift(_FakePostgresEngine())  # must not raise, must not query the DB


def test_check_module_schema_drift_noops_on_a_non_postgres_engine(monkeypatch):
    """Control: the sqlite test-suite engine must never trip the guard - it
    should not even call `discover_manifests`."""
    from app.module_platform.drift_guard import check_module_schema_drift

    def _boom_if_called(*a, **k):
        raise AssertionError("discover_manifests must not run on a non-Postgres engine")

    monkeypatch.setattr("app.module_platform.drift_guard.discover_manifests", _boom_if_called)

    check_module_schema_drift(_FakeSqliteEngine())  # must not raise, must not touch manifests


def test_check_module_schema_drift_raises_on_the_first_behind_module_and_reports_its_name(
    monkeypatch,
):
    """W4: with several modules installed, the guard must name the actual
    offending module (not a generic message) - the incident's log line
    ("column ideas.title does not exist") gave no hint it was ideation
    specifically without reading application code."""
    from app.module_platform.drift_guard import ModuleSchemaDrift, check_module_schema_drift

    manifests = [
        {"module_name": "omnichannel", "_dir": "omnichannel", "schema": "app_omnichannel"},
        {"module_name": "ideation", "_dir": "ideation", "schema": "app_ideation"},
    ]
    monkeypatch.setattr(
        "app.module_platform.drift_guard.discover_manifests", lambda *a, **k: manifests
    )

    heads = {"omnichannel": "0012_x", "ideation": "0010_business_reqs"}
    db_versions = {"omnichannel": "0012_x", "ideation": "0007_something"}
    monkeypatch.setattr(
        "app.module_platform.drift_guard.module_code_head", lambda m: heads[m["module_name"]]
    )
    monkeypatch.setattr(
        "app.module_platform.drift_guard.module_db_version",
        lambda engine, m: db_versions[m["module_name"]],
    )

    with pytest.raises(ModuleSchemaDrift) as exc_info:
        check_module_schema_drift(_FakePostgresEngine())

    assert exc_info.value.module_name == "ideation"
