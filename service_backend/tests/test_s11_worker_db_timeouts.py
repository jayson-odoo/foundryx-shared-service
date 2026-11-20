"""Sprint-5/11 S1 - RED tests for settings-driven worker Postgres session
timeouts (AC-11-85).

S0 baseline (``11-evidence/s0-baseline/README.md`` (d)) confirmed
``app/database.py`` passes NO ``connect_args`` at all today - worker sessions
have no ``statement_timeout`` / ``lock_timeout`` /
``idle_in_transaction_session_timeout`` bound, matching the plan's "the
vendor client... carry their own timeouts... the hang is something that has
none" claim (a Postgres lock wait or a raw driver socket - claim 3 of the
incident narrative).

CONTRACT this file pins (the brief's own named fallback, since the plan text
describes the BEHAVIOUR - "settings-driven connect_args options string" -
without naming the helper): ``app/database.py`` gains

    def worker_connect_args() -> dict:
        ...

reading three new ``app/config.py`` settings (seconds, default 0 = unset):
``worker_db_statement_timeout_seconds``, ``worker_db_lock_timeout_seconds``,
``worker_db_idle_in_transaction_session_timeout_seconds``. Returns ``{}``
when all three are 0/unset (the API's default profile - unchanged today's
behaviour, per AC-11-85: "unset (the API default) leaves today's behaviour
exactly as is"), else ``{"options": "-c statement_timeout=<ms> -c
lock_timeout=<ms> -c idle_in_transaction_session_timeout=<ms>"}`` (only the
non-zero ones included; Postgres' ``options`` GUC list wants MILLISECONDS,
the settings are SECONDS). ``create_engine(...)`` in the same module must be
wired through this helper (pinned by a source-string check rather than a
risky module reload of a singleton every other test file's ``session_factory``
fixture builds its OWN engine around anyway - ``app.database.engine`` itself
is never touched by the test suite).

The "worker profile only, never the API" half of AC-11-85 is achieved by
this being SETTINGS-driven, not code-branched: ``docker-compose.yml``'s
``x-backend-env`` anchor (shared by ``backend_blue``/``backend_green``) must
NOT carry these three envs, while ``worker_workflow`` + the new
``worker_jobs`` DO - pinned separately in ``test_s11_compose_worker_jobs.py``.
"""
from __future__ import annotations

import inspect


def test_worker_connect_args_is_empty_when_settings_are_unset(monkeypatch):
    from app.config import settings

    for name in (
        "worker_db_statement_timeout_seconds",
        "worker_db_lock_timeout_seconds",
        "worker_db_idle_in_transaction_session_timeout_seconds",
    ):
        monkeypatch.setattr(settings, name, 0, raising=False)

    from app.database import worker_connect_args

    assert worker_connect_args() == {}, (
        "unset must leave today's behaviour exactly as is - no connect_args "
        "at all, matching the API's default profile"
    )


def test_worker_connect_args_renders_all_three_timeouts_in_milliseconds(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "worker_db_statement_timeout_seconds", 120, raising=False)
    monkeypatch.setattr(settings, "worker_db_lock_timeout_seconds", 30, raising=False)
    monkeypatch.setattr(
        settings, "worker_db_idle_in_transaction_session_timeout_seconds", 300, raising=False
    )

    from app.database import worker_connect_args

    result = worker_connect_args()
    assert "options" in result
    options = result["options"]
    # Seconds -> milliseconds: Postgres' statement_timeout/lock_timeout/
    # idle_in_transaction_session_timeout GUCs are integer milliseconds.
    assert "statement_timeout=120000" in options
    assert "lock_timeout=30000" in options
    assert "idle_in_transaction_session_timeout=300000" in options


def test_worker_connect_args_omits_a_timeout_that_stays_unset(monkeypatch):
    """Partial configuration (R10: 'confirmed against the measured slowest
    statement... before they are enabled') must not fabricate a value for a
    timeout nobody set."""
    from app.config import settings

    monkeypatch.setattr(settings, "worker_db_statement_timeout_seconds", 120, raising=False)
    monkeypatch.setattr(settings, "worker_db_lock_timeout_seconds", 0, raising=False)
    monkeypatch.setattr(
        settings, "worker_db_idle_in_transaction_session_timeout_seconds", 0, raising=False
    )

    from app.database import worker_connect_args

    options = worker_connect_args()["options"]
    assert "statement_timeout=120000" in options
    assert "lock_timeout" not in options
    assert "idle_in_transaction_session_timeout" not in options


def test_worker_connect_args_is_empty_for_a_non_postgres_database_url(monkeypatch):
    """Review round 1 (S5) - the `options` GUC string is a libpq/Postgres
    connect arg; a non-Postgres DATABASE_URL (the pytest suite's own
    in-memory sqlite) must never receive it - sqlite's DBAPI raises on an
    unrecognised connect_args key."""
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", "sqlite:///:memory:", raising=False)
    monkeypatch.setattr(settings, "worker_db_statement_timeout_seconds", 120, raising=False)
    monkeypatch.setattr(settings, "worker_db_lock_timeout_seconds", 30, raising=False)
    monkeypatch.setattr(
        settings, "worker_db_idle_in_transaction_session_timeout_seconds", 300, raising=False
    )

    from app.database import worker_connect_args

    assert worker_connect_args() == {}, (
        "a non-postgresql DATABASE_URL must return {} regardless of the "
        "worker timeout settings - those settings are Postgres-only options"
    )


def test_database_module_wires_create_engine_through_worker_connect_args():
    """Source-string pin, deliberately NOT an ``importlib.reload`` of
    ``app.database`` - that module's ``Base``/``engine`` singletons are
    imported by name all over the codebase at collection time (models
    register their tables against THIS ``Base`` instance) and the whole
    suite builds its own throwaway engine per test via ``session_factory``
    rather than touching ``app.database.engine`` at all, so a reload here
    would risk corrupting every other file's fixtures for a check that a
    plain source read answers just as precisely."""
    from app import database as database_module

    source = inspect.getsource(database_module)
    assert "worker_connect_args" in source, (
        "create_engine(...) must be wired through worker_connect_args() so "
        "the settings-driven timeouts (AC-11-85) actually reach the engine, "
        "not just exist as an unused helper"
    )
