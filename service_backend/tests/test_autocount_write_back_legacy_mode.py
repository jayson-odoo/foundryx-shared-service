"""Plan 73 B2 (RED), crew ruling s20: a write NEVER refuses before a line notes connection is set.

NO source resolved (``WriteFrame._line_notes_source`` -> None) = LEGACY mode: no DB read, every PO / SPO write goes
out as on main before #344: no AUTOCOUNT_DB_UNREAD refusal, no FurtherDescription re-sent on kept rows, the S/O note
on the new linked row as today, EXCEPT the header never carries "" for a field (a text field the vendor read returned
blank is left out of the body). No STORED_FIELDS_CHANGED check. A resolved source = DB mode (plan 73): read fails ->
AUTOCOUNT_DB_UNREAD before any PUT. The release guard ``check-line-notes`` prints NO_CONNECTION but exits 0 (warning);
exit 1 only when a source is resolved and the probe fails. These tests bypass the conftest echo default source.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.write_back import admin, payloads as P
from modules.autocount.write_back.frame import WriteFrame
from modules.autocount.write_back.line_notes import SqlDocDb
from modules.autocount.write_back.service import WriteBackService
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

REAL_SOURCE = WriteFrame._line_notes_source


def _legacy(monkeypatch):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: None)


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


@pytest.fixture
def world(h, monkeypatch):
    _legacy(monkeypatch)
    h.delete_on()
    w = World(h)
    po = h.vendor.find("PO", 7001)
    po.update(Remark1="R1 kept", Remark2="", Remark3="", Remark4="", Ref="", Description="Keep desc", Attention="ATT kept")
    return w


def _args(h, **over):
    return dict(h.args("PO", doc_key=7001), **over)


def _drive(h, w) -> Dict[str, Any]:
    """Every PO write, in legacy mode: name -> callable returning a result with ``.outcome``."""
    svc = lambda: WriteBackService(h.db, **h.factories())  # noqa: E731
    return {
        "link_row whole": lambda: h.run("link_row", w.params["link_row"], key="k-whole"),
        "link_row partial": lambda: h.run("split_link", dict(po_doc_key=7001, po_dtl_key=w.p_free, so_doc_key=7002,
                                                              so_dtl_key=w.so_a, qty=2), key="k-part"),
        "unlink_row": lambda: h.run("unlink_row", w.params["unlink_row"], key="k-unl"),
        "relink_row": lambda: h.run("relink_row", w.params["relink_row"], key="k-rel"),
        "relocate": lambda: svc().relocate(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=7001,
                                           po_dtl_key=w.p_linked, location="HQ"),
        "link_batch": lambda: h.run("link_batch", dict(doc_key=7001, dtl_key=w.p_free, links=[
            dict(so_doc_key=7002, so_dtl_key=w.so_a, qty=2)]), key="k-batch"),
        "header-only edit": lambda: h.edit("PO", 7001, header_changes={"Remark1": "R1 new"}),
        "add_line": lambda: h.service().add_line(**_args(h), line=_line("ITEM-A", 1, 5.0, "HQ")),
        "delete_line": lambda: h.service().delete_line(**_args(h), dtl_key=w.p_other),
    }


NAMES = ["link_row whole", "link_row partial", "unlink_row", "relink_row", "relocate", "link_batch",
         "header-only edit", "add_line", "delete_line"]


# ---- (1) nothing is refused, a PUT goes out -----------------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_legacy_write_is_done_and_sends_a_put(h, world, name):
    res = _drive(h, world)[name]()
    assert res.error_code != "AUTOCOUNT_DB_UNREAD", (name, res.outcome, res.error_code)
    assert res.outcome == "done", (name, res.outcome, res.error_code)
    assert puts(h), name


# ---- (2) the header never carries "" ------------------------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_legacy_body_header_has_no_blank_text_field_and_keeps_the_non_blank_ones(h, world, name):
    _drive(h, world)[name]()
    sent = puts(h)
    assert sent, name
    for call in sent:
        blanks = [k for k, v in call.body.items() if k != "Details" and isinstance(v, str) and v == ""]
        assert blanks == [], (name, blanks)
        assert call.body.get("Description") == "Keep desc" and call.body.get("Attention") == "ATT kept"
    # the header-only edit asked for a new Remark1: that one is sent as asked, the blank mirrors are not
    if name == "header-only edit":
        assert sent[0].body["Remark1"] == "R1 new" and "Remark2" not in sent[0].body


# ---- (3) rows: no FD re-sent on kept rows, the note on the new linked row as today --------------------

@pytest.mark.parametrize("name", ["link_row whole", "link_row partial", "unlink_row", "relink_row", "relocate",
                                  "link_batch", "header-only edit", "delete_line"])
def test_legacy_pre_existing_rows_carry_no_further_description(h, world, name):
    before = {r["DtlKey"] for r in h.vendor.rows("PO", 7001)}
    _drive(h, world)[name]()
    sent = puts(h)
    assert sent, name  # a refused write sends nothing and would pass the loop below for the wrong reason
    resent = [r for call in sent for r in call.body["Details"] if r["DtlKey"] in before]
    if name != "header-only edit":  # the only path that sends no row at all
        assert resent, name  # re-sent at least one row that existed before the operation (a "D" row counts)
    for r in resent:
        assert "FurtherDescription" not in r, (name, r["DtlKey"])
    # a row that is NEW (DtlKey 0 or minted by this operation) may carry the S/O note, exactly AutoCount's wrapper
    for call in sent:
        for r in call.body["Details"]:
            if r["DtlKey"] not in before and "FurtherDescription" in r:
                fd = r["FurtherDescription"]
                assert fd.startswith(P._RTF_HEAD) and fd.endswith(P._RTF_TAIL) and "S/O:" in fd, (name, fd)


def test_legacy_partial_link_resends_the_cut_row_without_fd(h, world):
    res = _drive(h, world)["link_row partial"]()
    assert res.outcome == "done"
    cut = [r for r in puts(h)[0].body["Details"] if r["DtlKey"] == world.p_free]
    assert len(cut) == 1 and "FurtherDescription" not in cut[0]


@pytest.mark.parametrize("name", ["link_row whole", "link_row partial"])
def test_legacy_new_linked_row_carries_the_so_note_as_before(h, world, name):
    res = _drive(h, world)[name]()
    assert res.outcome == "done"
    (new,) = [r for r in puts(h)[0].body["Details"] if r["DtlKey"] == 0]
    fd = new["FurtherDescription"]
    assert fd.startswith(P._RTF_HEAD) and "S/O:" in fd  # AutoCount's own wrapper holding the note, nothing before it


def test_legacy_has_no_stored_fields_check(h, world):
    res = _drive(h, world)["header-only edit"]()
    assert P.STORED_FIELDS_CHANGED not in (res.warnings or [])


# ---- (4) control: DB mode with an unreadable database still refuses -------------------------------------

class _Unread:
    def read(self, kind, doc):
        return None


@pytest.mark.parametrize("name", ["link_row whole", "header-only edit", "relocate"])
def test_db_mode_unread_database_still_refuses_with_zero_puts(h, monkeypatch, name):
    h.delete_on()
    w = World(h)
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _Unread())
    res = _drive(h, w)[name]()
    assert (res.outcome, res.error_code) == ("refused", "AUTOCOUNT_DB_UNREAD"), (res.outcome, res.error_code)
    assert puts(h) == []


# ---- (5) the release guard ----------------------------------------------------------------------------

@pytest.fixture
def cli(h, monkeypatch):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", REAL_SOURCE)
    import app.database as database

    class _Session:
        def __enter__(self):
            return h.db

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(database, "SessionLocal", lambda: _Session())
    h.company.write_connection_id = h.conn.id
    h.company.line_notes_connection_id = None
    h.db.commit()
    return h


def test_check_line_notes_without_a_source_prints_no_connection_but_exits_0(cli, capsys):
    assert admin.main(["check-line-notes"]) == 0
    assert f"{cli.company.id} NO_CONNECTION" in capsys.readouterr().out


def test_check_line_notes_with_a_failing_probe_exits_1(cli, monkeypatch, capsys):
    conn = Connection(tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="database", name="Notes DB",
                      config_json={"dbType": "mssql", "host": "x", "database": "d"},
                      credentials_json=encrypt_secret({"password": "pw"}), is_active=True)
    cli.db.add(conn)
    cli.db.commit()
    cli.company.line_notes_connection_id = conn.id
    cli.db.commit()
    monkeypatch.setattr(SqlDocDb, "probe", lambda self: False)
    assert admin.main(["check-line-notes"]) == 1
    assert f"{cli.company.id} READ_FAILED" in capsys.readouterr().out
