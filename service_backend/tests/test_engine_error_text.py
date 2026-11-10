"""Plan 46: a database error's text names the statement, never bound values."""
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import database
from modules.autocount import sql_provider
from modules.autocount.sql_source.runtime import SqlSourceRuntime

MARKER = "zz-placeholder-marker-9137"

CONFIG = {
    "dbType": "postgresql",
    "host": "db.invalid",
    "database": "sample",
    "username": "reader",
}
CREDENTIALS = {"password": "placeholder-pw"}


def _spy_create_engine(monkeypatch):
    real = sa.create_engine
    calls = []

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(sa, "create_engine", spy)
    return calls


def test_ac_46_01_the_app_engine_hides_bound_parameters():
    assert database.engine.hide_parameters is True


def _builder_engine():
    return database.build_engine("sqlite://")


def test_ac_46_01_the_shared_builder_hides_bound_parameters():
    engine = _builder_engine()
    try:
        assert engine.hide_parameters is True
    finally:
        engine.dispose()


def test_ac_46_01_the_app_engine_is_made_by_the_shared_builder():
    """Import the module with the engine factory observed, no connection made."""
    import subprocess
    import sys
    import textwrap

    code = textwrap.dedent(
        """
        import sqlalchemy
        calls = []
        real = sqlalchemy.create_engine
        def spy(*a, **k):
            calls.append(k)
            return real(*a, **k)
        sqlalchemy.create_engine = spy
        import app.database as d
        assert hasattr(d, "build_engine"), "no shared builder"
        assert len(calls) == 1, calls
        assert calls[0].get("hide_parameters") is True, calls
        assert d.engine.hide_parameters is True
        print("ok")
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr[-600:]
    assert "ok" in done.stdout


def test_ac_46_03_a_constraint_error_names_the_statement_without_values():
    engine = _builder_engine()
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE TABLE plan46_probe (name TEXT NOT NULL UNIQUE)"))
            conn.execute(sa.text("INSERT INTO plan46_probe (name) VALUES (:v)"), {"v": MARKER})
            with pytest.raises(IntegrityError) as caught:
                conn.execute(
                    sa.text("INSERT INTO plan46_probe (name) VALUES (:v)"), {"v": MARKER}
                )
        exc = caught.value
        assert MARKER not in str(exc)
        assert MARKER not in repr(exc.params)
        assert "INSERT INTO plan46_probe" in str(exc)
    finally:
        engine.dispose()


def test_ac_46_03_control_a_valid_statement_still_runs_through_the_builder():
    engine = _builder_engine()
    try:
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT :v"), {"v": 7}).scalar() == 7
    finally:
        engine.dispose()


def test_ac_46_02_the_probe_engine_hides_bound_parameters(monkeypatch):
    calls = _spy_create_engine(monkeypatch)
    engine = sql_provider._probe_engine(CONFIG, CREDENTIALS)
    assert len(calls) == 1
    assert engine.hide_parameters is True


def test_ac_46_02_the_runtime_engine_hides_bound_parameters(monkeypatch):
    calls = _spy_create_engine(monkeypatch)
    engine = SqlSourceRuntime().engine_for("plan46-conn", CONFIG, CREDENTIALS)
    assert len(calls) == 1
    assert engine.hide_parameters is True
