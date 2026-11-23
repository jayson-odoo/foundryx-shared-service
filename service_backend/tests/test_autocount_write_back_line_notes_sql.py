"""Plan 73: the SQL line-notes source (``SqlLineNotes``), its tenant-scoped resolve from the company's
``line_notes_connection_id`` and the ``set_line_notes_connection`` setter. No network: the engine is an
in-memory SQLite injected through a private ``SqlSourceRuntime``."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.sql_source.runtime import SqlSourceRuntime
from modules.autocount.write_back.frame import WriteFrame
from modules.autocount.write_back.line_notes import SqlLineNotes
from modules.autocount.write_back.service import WriteConnectionError, set_line_notes_connection
from tests.test_autocount_write_back_service import OTHER_TENANT, db, h  # noqa: F401

REAL_SOURCE = WriteFrame._line_notes_source  # the conftest default patches the class per test
FD_A = r"{\rtf1\ansi Special\par{\pict\pngblip 89504e47}\par}"
SECRET = "s3cr3t-pass-word"


def _engine(rows):
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE PODTL (DtlKey INTEGER, DocKey INTEGER, FurtherDescription TEXT)"))
        conn.execute(sa.text("CREATE TABLE PO (DocKey INTEGER, DocNo TEXT)"))
        for dock in {r[1] for r in rows}:
            conn.execute(sa.text("INSERT INTO PO VALUES (:a, :b)"), {"a": dock, "b": f"PO-{dock}"})
        for dtl, dock, fd in rows:
            conn.execute(sa.text("INSERT INTO PODTL VALUES (:a, :b, :c)"), {"a": dtl, "b": dock, "c": fd})
    return engine


def _source(rows=(), engine=None, conn_id="c1"):
    runtime = SqlSourceRuntime()
    runtime.put_engine(conn_id, engine or _engine(rows))
    conn = SimpleNamespace(id=conn_id, config_json={"dbType": "mssql"}, credentials_json=encrypt_secret({"password": SECRET}))
    return SqlLineNotes(conn, runtime=runtime)


def _doc(*keys, dock=7001):
    return {"DocKey": dock, "DocNo": f"PO-{dock}", "Details": [{"DtlKey": k} for k in keys]}


def test_sql_notes_reads_every_row_of_the_document_only():
    src = _source([(1, 7001, FD_A), (2, 7001, None), (3, 9999, "other doc")])
    assert src.notes("PO", _doc(1, 2)) == {1: FD_A, 2: ""}


def test_sql_notes_other_kinds_are_unknown():
    assert _source([(1, 7001, "x")]).notes("SO", _doc(1)) is None


def test_sql_notes_a_row_the_database_does_not_know_is_unknown():
    assert _source([(1, 7001, "x")]).notes("PO", _doc(1, 2)) is None


def test_sql_notes_an_error_is_unknown_and_logs_no_note_or_credential(caplog):
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})  # no PODTL
    with caplog.at_level(logging.DEBUG):
        assert _source(engine=engine).notes("PO", _doc(1)) is None
    assert SECRET not in caplog.text


def test_sql_notes_an_undecryptable_credential_is_unknown():
    runtime = SqlSourceRuntime()
    runtime.put_engine("c1", _engine([(1, 7001, "x")]))
    conn = SimpleNamespace(id="c1", config_json={}, credentials_json="not-a-fernet-token")
    assert SqlLineNotes(conn, runtime=runtime).notes("PO", _doc(1)) is None


# ---- the company resolve (tenant-scoped) --------------------------------------------------------

def _sql_conn(h, tenant_id, active=True, provider="sql_database"):
    conn = Connection(tenant_id=tenant_id, provider=provider, type="database", name="Notes DB",
                      config_json={"dbType": "mssql", "host": "x", "database": "d"},
                      credentials_json=encrypt_secret({"password": SECRET}), is_active=active)
    h.db.add(conn)
    h.db.commit()
    return conn


def _frame_source(h, monkeypatch, company):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", REAL_SOURCE)
    return h.service()._line_notes_source(company)


def test_company_without_a_line_notes_connection_has_no_sql_source(h, monkeypatch):
    h.company.line_notes_connection_id = None
    assert _frame_source(h, monkeypatch, h.company) is None


def test_company_resolves_its_same_tenant_sql_connection(h, monkeypatch):
    conn = _sql_conn(h, DEFAULT_TENANT_ID)
    h.company.line_notes_connection_id = conn.id
    assert isinstance(_frame_source(h, monkeypatch, h.company), SqlLineNotes)


@pytest.mark.parametrize("variant", ["other_tenant", "inactive", "wrong_provider"])
def test_company_never_resolves_a_foreign_inactive_or_non_sql_connection(h, monkeypatch, variant):
    conn = {
        "other_tenant": lambda: _sql_conn(h, OTHER_TENANT),
        "inactive": lambda: _sql_conn(h, DEFAULT_TENANT_ID, active=False),
        "wrong_provider": lambda: _sql_conn(h, DEFAULT_TENANT_ID, provider="smtp"),
    }[variant]()
    h.company.line_notes_connection_id = conn.id
    assert _frame_source(h, monkeypatch, h.company) is None


# ---- set_line_notes_connection -------------------------------------------------------------------

def _set(h, conn_id, company=None):
    company = company or h.company
    return set_line_notes_connection(h.db, tenant_id=company.tenant_id, company_id=company.id, connection_id=conn_id)


def test_setter_sets_a_same_tenant_sql_connection_and_clears_it(h):
    conn = _sql_conn(h, DEFAULT_TENANT_ID)
    _set(h, conn.id)
    h.db.expire_all()
    assert h.company.line_notes_connection_id == conn.id
    _set(h, None)
    h.db.expire_all()
    assert h.company.line_notes_connection_id is None


@pytest.mark.parametrize("variant", ["other_tenant", "wrong_provider", "unknown"])
def test_setter_refuses_and_leaves_the_company_unchanged(h, variant):
    h.company.line_notes_connection_id = None
    h.db.commit()
    conn_id = {
        "other_tenant": lambda: _sql_conn(h, OTHER_TENANT).id,
        "wrong_provider": lambda: _sql_conn(h, DEFAULT_TENANT_ID, provider="autocount").id,
        "unknown": lambda: "no-such-connection",
    }[variant]()
    with pytest.raises(WriteConnectionError) as exc:
        _set(h, conn_id)
    assert exc.value.code == "CONNECTION_NOT_FOUND"
    h.db.expire_all()
    assert h.company.line_notes_connection_id is None


def test_setter_refuses_another_tenants_company(h):
    conn = _sql_conn(h, DEFAULT_TENANT_ID)
    with pytest.raises(WriteConnectionError) as exc:
        set_line_notes_connection(h.db, tenant_id=OTHER_TENANT, company_id=h.company.id, connection_id=conn.id)
    assert exc.value.code == "CONNECTION_NOT_FOUND"


# ---- fix round 1 F3: the rows are tied to the document read ---------------------------------------

def test_sql_notes_a_docno_that_is_not_the_documents_is_unknown():
    src = _source([(1, 7001, "x")])
    doc = _doc(1)
    doc["DocNo"] = "PO-OTHER"
    assert src.notes("PO", doc) is None


def test_sql_notes_an_extra_row_in_the_database_is_unknown():
    assert _source([(1, 7001, "x"), (2, 7001, "y")]).notes("PO", _doc(1)) is None
