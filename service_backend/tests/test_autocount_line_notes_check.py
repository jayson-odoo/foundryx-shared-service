"""Plan 73 B2: the release guard ``python -m modules.autocount.write_back.admin check-line-notes``.

For every active company with a write connection (all tenants) the line notes source is resolved exactly as a write
resolves it (``WriteFrame._line_notes_source``) and one tiny read-only probe runs through it. One line per company:
its id and OK / NO_CONNECTION / READ_FAILED, never a host, database name, value or credential. Exit 0 when all OK or
no company can write; 1 otherwise. The deploy runs it in the NEW backend container before the swap.
"""
from __future__ import annotations

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.write_back import admin
from modules.autocount.write_back.frame import WriteFrame
from modules.autocount.write_back.line_notes import SqlDocDb
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

REAL_SOURCE = WriteFrame._line_notes_source  # the conftest default patches the class per test; keep the real one
SECRET_HOST = "db-secret-host.internal"


@pytest.fixture(autouse=True)
def _session_factory(h, monkeypatch):
    """The CLI opens its own session: hand it the test one."""
    monkeypatch.setattr(WriteFrame, "_line_notes_source", REAL_SOURCE)
    import app.database as database

    class _Session:
        def __enter__(self):
            return h.db

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(database, "SessionLocal", lambda: _Session())


def _sql_conn(h, name="Own source"):
    conn = Connection(tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="database", name=name,
                      config_json={"dbType": "mssql", "host": SECRET_HOST, "database": "AED_SECRET"},
                      credentials_json=encrypt_secret({"password": "pw-secret-1"}), is_active=True)
    h.db.add(conn)
    h.db.commit()
    return conn


def _company(h, *, write=True, notes_id=None, source_id=None):
    h.company.write_connection_id = h.conn.id if write else None
    h.company.line_notes_connection_id = notes_id
    if source_id is not None:
        h.company.connection_id = source_id
    h.db.commit()


def test_no_write_enabled_company_exits_0(h, capsys):
    _company(h, write=False)
    assert admin.main(["check-line-notes"]) == 0


def test_a_write_company_without_a_source_is_no_connection_but_exit_0(h, capsys):
    _company(h, notes_id=None)  # its own source connection is the hapi one: legacy mode, a warning only
    assert admin.main(["check-line-notes"]) == 0
    out = capsys.readouterr().out
    assert f"{h.company.id} NO_CONNECTION" in out


def test_a_probe_that_raises_is_read_failed_and_exit_1(h, monkeypatch, capsys):
    _company(h, notes_id=_sql_conn(h).id)

    def boom(self):
        raise RuntimeError(f"cannot reach {SECRET_HOST}")

    monkeypatch.setattr(SqlDocDb, "probe", boom)
    assert admin.main(["check-line-notes"]) == 1
    out = capsys.readouterr().out
    assert f"{h.company.id} READ_FAILED" in out
    assert SECRET_HOST not in out and "AED_SECRET" not in out and "pw-secret-1" not in out


def test_a_probe_that_answers_false_is_read_failed(h, monkeypatch, capsys):
    _company(h, notes_id=_sql_conn(h).id)
    monkeypatch.setattr(SqlDocDb, "probe", lambda self: False)
    assert admin.main(["check-line-notes"]) == 1


def test_an_ok_probe_is_exit_0_and_prints_ok_without_the_connection_config(h, monkeypatch, capsys):
    _company(h, notes_id=_sql_conn(h).id)
    monkeypatch.setattr(SqlDocDb, "probe", lambda self: True)
    assert admin.main(["check-line-notes"]) == 0
    out = capsys.readouterr().out
    assert f"{h.company.id} OK" in out
    assert SECRET_HOST not in out and "AED_SECRET" not in out and "pw-secret-1" not in out


def test_an_inactive_company_is_not_checked(h, capsys):
    _company(h)
    h.company.is_active = False
    h.db.commit()
    assert admin.main(["check-line-notes"]) == 0


def test_the_probe_statements_are_two_tiny_selects():
    from modules.autocount.write_back import line_notes as ln

    assert str(ln._PROBE_HEADER) == "SELECT TOP 1 DocKey FROM PO"
    assert str(ln._PROBE_ROWS) == "SELECT TOP 1 DtlKey FROM PODTL"
