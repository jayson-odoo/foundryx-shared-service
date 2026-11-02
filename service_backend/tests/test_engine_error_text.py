"""Plan 46: a database error's text names the statement, never bound values."""
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


def test_ac_46_03_a_constraint_error_names_the_statement_without_values():
    with database.engine.connect() as conn:
        conn.execute(sa.text("CREATE TEMP TABLE plan46_probe (name TEXT NOT NULL UNIQUE)"))
        conn.execute(sa.text("INSERT INTO plan46_probe (name) VALUES (:v)"), {"v": MARKER})
        try:
            conn.execute(
                sa.text("INSERT INTO plan46_probe (name) VALUES (:v)"), {"v": MARKER}
            )
        except IntegrityError as exc:
            text = str(exc)
        else:
            raise AssertionError("expected a constraint error")
        finally:
            conn.rollback()
    assert MARKER not in text
    assert "INSERT INTO plan46_probe" in text


def test_ac_46_03_control_a_valid_statement_still_runs_through_the_app_engine():
    with database.engine.connect() as conn:
        assert conn.execute(sa.text("SELECT :v"), {"v": 7}).scalar() == 7


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
