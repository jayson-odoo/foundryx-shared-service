"""Plan 73 r7 (RED): the AutoCount DB source falls back to the company's own SQL connection.

Rule for ``WriteFrame._line_notes_source(company)``: ``line_notes_connection_id`` unset -> the company's own source
connection (``company.connection_id``) when it resolves WITH ``company.tenant_id`` as an ACTIVE ``sql_database``
connection; an explicit ``line_notes_connection_id`` still wins; anything else (hapi / autocount provider, inactive,
another tenant, missing) -> None (writes refuse AUTOCOUNT_DB_UNREAD). These tests bypass the conftest autouse default
source (they restore the real method).
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.write_back.frame import WriteFrame
from modules.autocount.write_back.line_notes import DB_HEADER_COLUMNS, DB_ROW_KEYS, SqlDocDb
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_service import OTHER_TENANT
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

REAL_SOURCE = WriteFrame._line_notes_source  # the conftest default patches the class per test; keep the real one
FD1 = r"{\rtf1\ansi\deff0\pard\f0\fs20 Kept note\par{\pict\pngblip\picw10\pich10 89504e470d0a1a0a}\par" + "\r\n}"


def _conn(h, tenant_id=DEFAULT_TENANT_ID, *, provider="sql_database", active=True, name="Own source") -> Connection:
    conn = Connection(tenant_id=tenant_id, provider=provider, type="database", name=name,
                      config_json={"dbType": "mssql", "host": "x", "database": "d"},
                      credentials_json=encrypt_secret({"password": "pw-1"}), is_active=active)
    h.db.add(conn)
    h.db.commit()
    return conn


def _resolve(h, monkeypatch, *, source_id, notes_id=None):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", REAL_SOURCE)  # not the conftest echo default
    h.company.connection_id = source_id
    h.company.line_notes_connection_id = notes_id
    h.db.commit()
    return h.service()._line_notes_source(h.company)


def test_unset_id_uses_the_companys_own_active_same_tenant_sql_source(h, monkeypatch):
    conn = _conn(h)
    src = _resolve(h, monkeypatch, source_id=conn.id)
    assert isinstance(src, SqlDocDb)
    assert src._connection.id == conn.id


def test_an_explicit_line_notes_connection_is_used_whatever_the_source_is(h, monkeypatch):
    # one sql_database connection per tenant: the explicit one; the company's own source is its hapi connection
    explicit = _conn(h, name="Notes DB")
    src = _resolve(h, monkeypatch, source_id=h.conn.id, notes_id=explicit.id)
    assert isinstance(src, SqlDocDb) and src._connection.id == explicit.id


def test_an_explicit_line_notes_connection_that_is_not_usable_is_not_replaced_by_the_source(h, monkeypatch):
    explicit = _conn(h, active=False, name="Notes DB")  # inactive explicit id: unknown, no silent fallback
    assert _resolve(h, monkeypatch, source_id=h.conn.id, notes_id=explicit.id) is None


def test_a_hapi_autocount_source_is_not_a_database_source(h, monkeypatch):
    hapi = _conn(h, provider="autocount")
    assert _resolve(h, monkeypatch, source_id=hapi.id) is None
    assert _resolve(h, monkeypatch, source_id=h.conn.id) is None  # the harness's own autocount connection


def test_an_inactive_sql_source_is_not_used(h, monkeypatch):
    assert _resolve(h, monkeypatch, source_id=_conn(h, active=False).id) is None


def test_a_source_id_of_another_tenant_is_not_used(h, monkeypatch):
    assert _resolve(h, monkeypatch, source_id=_conn(h, OTHER_TENANT).id) is None


def test_a_missing_source_connection_is_not_used(h, monkeypatch):
    assert _resolve(h, monkeypatch, source_id="no-such-connection") is None


# ---- end to end: link_row reads the database through the company's own SQL source ------------------

def _engine_for(h, doc_key=7001):
    """A fake AutoCount DB (in-memory SQLite) holding PO ``doc_key`` exactly as the fake vendor does: every row with
    the note FD1; ``resync`` re-copies it after each vendor edit so the DtlKey set always matches the document."""
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    header_cols = [c for c in DB_HEADER_COLUMNS if c not in ("DocKey", "DocNo")]
    row_cols = [c for c in DB_ROW_KEYS if c not in ("DtlKey", "Qty", "FurtherDescription")]
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE PODTL (DtlKey INTEGER, DocKey INTEGER, FurtherDescription TEXT, Qty REAL"
                             + "".join(f", [{c}] TEXT" for c in row_cols) + ")"))
        conn.execute(sa.text("CREATE TABLE PO (DocKey INTEGER, DocNo TEXT" + "".join(f", [{c}] TEXT" for c in header_cols) + ")"))
        doc = h.vendor.find("PO", doc_key)
        conn.execute(sa.text("INSERT INTO PO (DocKey, DocNo) VALUES (:k, :n)"), {"k": doc_key, "n": doc["DocNo"]})

    def resync() -> None:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM PODTL"))
            for r in h.vendor.rows("PO", doc_key):
                conn.execute(sa.text("INSERT INTO PODTL (DtlKey, DocKey, FurtherDescription, Qty) VALUES (:d, :k, :f, :q)"),
                             {"d": r["DtlKey"], "k": doc_key, "f": FD1, "q": r["Qty"]})

    resync()
    original = h.vendor._edit

    def edit(kind: str, body: Any):
        out = original(kind, body)
        resync()
        return out

    h.vendor._edit = edit
    return engine


def test_link_row_with_an_unset_notes_id_reads_the_database_through_the_companys_sql_source(h, monkeypatch):
    world = World(h)
    conn = _conn(h)
    h.company.connection_id = conn.id
    h.company.line_notes_connection_id = None
    h.db.commit()
    monkeypatch.setattr(WriteFrame, "_line_notes_source", REAL_SOURCE)  # bypass the conftest echo default
    RUNTIME.put_engine(conn.id, _engine_for(h))
    res = h.run("link_row", world.params["link_row"])
    assert res.error_code != "AUTOCOUNT_DB_UNREAD", (res.outcome, res.error_code)
    puts = [c for c in h.vendor.writes() if c.method == "PUT"]
    assert puts, (res.outcome, res.error_code)
    (new,) = [r for r in puts[0].body["Details"] if r["DtlKey"] == 0]
    assert new["FurtherDescription"].startswith(FD1[:-1]) and "89504e470d0a1a0a" in new["FurtherDescription"]
    assert res.outcome == "done", (res.outcome, res.error_code)
