"""Plan 73: the SQL line-notes source (``SqlDocDb``), its tenant-scoped resolve from the company's
``line_notes_connection_id`` and the ``CompanyService.set_line_notes_connection`` setter. No network: the engine is an
in-memory SQLite injected through a private ``SqlSourceRuntime``."""

from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.sql_source.runtime import SqlSourceRuntime
from modules.autocount.write_back.frame import WriteFrame
from modules.autocount.write_back.line_notes import DB_HEADER_COLUMNS, DB_ROW_KEYS, SqlDocDb
from modules.autocount.services.company_service import AutocountServiceError, CompanyService
from tests.test_autocount_write_back_service import OTHER_TENANT, db, h  # noqa: F401

REAL_SOURCE = WriteFrame._line_notes_source  # the conftest default patches the class per test
FD_A = r"{\rtf1\ansi Special\par{\pict\pngblip 89504e47}\par}"
SECRET = "s3cr3t-pass-word"


def _engine(rows, header=None):
    """``rows``: (DtlKey, DocKey, FurtherDescription); the PO table holds one header per DocKey. Every whitelisted
    column exists (the explicit SELECT names them all); two are created in another case (REMARK4, deliverydate) to
    exercise the case-insensitive mapping."""
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    header_cols = ["REMARK4" if c == "Remark4" else c for c in DB_HEADER_COLUMNS if c not in ("DocKey", "DocNo")]
    row_cols = ["deliverydate" if c == "DeliveryDate" else c for c in DB_ROW_KEYS]
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE PODTL (DtlKey INTEGER, DocKey INTEGER, UDF_Y TEXT, "
                             + ", ".join(f"[{c}]" for c in row_cols) + ")"))
        conn.execute(sa.text("CREATE TABLE PO (DocKey INTEGER, DocNo TEXT, UDF_Extra TEXT, "
                             + ", ".join(f"[{c}]" for c in header_cols) + ")"))
        for dock in {r[1] for r in rows}:
            conn.execute(sa.text("INSERT INTO PO (DocKey, DocNo, UDF_Extra, REMARK4, CurrencyRate, DocDate, Phone1) "
                                 "VALUES (:a, :b, 'x', 'L', 1.5, :d, '')"),
                         {"a": dock, "b": f"PO-{dock}", "d": datetime(2026, 11, 4)})
        for dtl, dock, fd in rows:
            conn.execute(sa.text("INSERT INTO PODTL (DtlKey, DocKey, FurtherDescription, UDF_Y, Qty, deliverydate) "
                                 "VALUES (:a, :b, :c, 'y', 2.5, :d)"),
                         {"a": dtl, "b": dock, "c": fd, "d": datetime(2026, 12, 1, 9, 30)})
    return engine


def _source(rows=(), engine=None, conn_id="c1"):
    runtime = SqlSourceRuntime()
    runtime.put_engine(conn_id, engine or _engine(rows))
    conn = SimpleNamespace(id=conn_id, config_json={"dbType": "mssql"}, credentials_json=encrypt_secret({"password": SECRET}))
    return SqlDocDb(conn, runtime=runtime)


def _doc(*keys, dock=7001):
    return {"DocKey": dock, "DocNo": f"PO-{dock}", "Details": [{"DtlKey": k} for k in keys]}


def test_sql_db_reads_header_and_rows_of_the_document_only_in_the_wire_shape():
    src = _source([(1, 7001, FD_A), (2, 7001, None), (3, 9999, "other doc")])
    out = src.read("PO", _doc(1, 2))
    assert out["header"] == {"Remark4": "L", "CurrencyRate": 1.5,
                             "DocDate": "2026-11-04 00:00:00", "Phone1": ""}  # None omitted, str as is, "" kept
    assert out["rows"][1] == {"FurtherDescription": FD_A, "Qty": 2.5, "DeliveryDate": "2026-12-01 09:30:00"}
    assert out["rows"][2]["FurtherDescription"] == ""  # a NULL note is an empty one
    assert "DocKey" not in out["header"] and "DocNo" not in out["header"]  # the PUT keeps the requested identity
    assert "Desc2" not in out["rows"][1] and "UDF_Y" not in out["rows"][1] and "UDF_X" not in out["header"]


def test_wire_shape_of_driver_values():
    from datetime import date
    from decimal import Decimal

    from modules.autocount.write_back.line_notes import _wire

    assert _wire(Decimal("1.50")) == 1.5 and isinstance(_wire(Decimal("2")), float)
    assert _wire(datetime(2026, 11, 4, 9, 5, 7)) == "2026-11-04T09:05:07"
    assert _wire(date(2026, 11, 4)) == "2026-11-04T00:00:00"
    assert _wire(None) is None and _wire(True) is None and _wire(b"x") is None
    assert _wire(FD_A) == FD_A and _wire("") == ""


def test_sql_db_other_kinds_are_unknown():
    assert _source([(1, 7001, "x")]).read("SO", _doc(1)) is None


def test_sql_db_a_row_the_database_does_not_know_is_unknown():
    assert _source([(1, 7001, "x")]).read("PO", _doc(1, 2)) is None


def test_sql_db_an_extra_row_in_the_database_is_unknown():
    assert _source([(1, 7001, "x"), (2, 7001, "y")]).read("PO", _doc(1)) is None


def test_sql_db_a_docno_that_is_not_the_documents_is_unknown():
    doc = _doc(1)
    doc["DocNo"] = "PO-OTHER"
    assert _source([(1, 7001, "x")]).read("PO", doc) is None


def test_sql_db_an_error_is_unknown_and_logs_no_value_or_credential(caplog):
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})  # no tables
    with caplog.at_level(logging.DEBUG):
        assert _source(engine=engine).read("PO", _doc(1)) is None
    assert SECRET not in caplog.text


def test_sql_db_an_undecryptable_credential_is_unknown():
    runtime = SqlSourceRuntime()
    runtime.put_engine("c1", _engine([(1, 7001, "x")]))
    conn = SimpleNamespace(id="c1", config_json={}, credentials_json="not-a-fernet-token")
    assert SqlDocDb(conn, runtime=runtime).read("PO", _doc(1)) is None


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
    assert isinstance(_frame_source(h, monkeypatch, h.company), SqlDocDb)


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
    return CompanyService(h.db).set_line_notes_connection(company.tenant_id, company.id, conn_id)


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
    with pytest.raises(AutocountServiceError):
        _set(h, conn_id)
    h.db.expire_all()
    assert h.company.line_notes_connection_id is None


def test_setter_refuses_another_tenants_company(h):
    conn = _sql_conn(h, DEFAULT_TENANT_ID)
    with pytest.raises(AutocountServiceError):
        CompanyService(h.db).set_line_notes_connection(OTHER_TENANT, h.company.id, conn.id)



def test_the_header_read_names_its_columns_never_star_and_a_stray_column_is_never_read():
    from modules.autocount.write_back import line_notes as ln

    text = str(ln._HEADER_SELECT)
    assert "*" not in text
    selected = {c.strip(" []") for c in text.split("SELECT")[1].split("FROM")[0].split(",")}
    assert selected == set(DB_HEADER_COLUMNS)
    out = _source([(1, 7001, "x")]).read("PO", _doc(1))
    assert "UDF_Extra" not in out["header"] and "UDF_X" not in out["header"]
    assert "SalesAgent" not in out["header"] and "YourPONo" not in out["header"]  # not PO columns: never overlaid
