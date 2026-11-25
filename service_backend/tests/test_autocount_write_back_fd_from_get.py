"""Plan 73 r8 (RED): in LEGACY mode (no line notes database) the vendor GET's Further Description is carried byte for byte.

Vendor 25 Nov: hapi POST / PUT now store the row ``FurtherDescription`` and the GET returns it on every row. So when the
GET of a PO / SPO carries the key on EVERY row, FD is known: every re-sent existing row and every row re-added from it
(delete + add) carries the row's FD exactly as read (never rebuilt); a new linked row gets ``append_note(source FD,
S/O note)`` as in DB mode. If ANY row lacks the key: legacy as today (no FD sent, nothing refused). SO / QT edits pass a
row's FD through unchanged. Never a refusal in legacy mode.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.write_back import payloads as P
from modules.autocount.write_back.frame import WriteFrame
from modules.autocount.write_back.service import WriteBackService
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

PICT = (r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fswiss Arial;}}\viewkind4\uc1\pard\f0\fs20 Special finish\par"
        r"{\pict\pngblip\picw10\pich10 89504e470d0a1a0a0000000d49484452}\par" + "\r\n}")
OLE = (r"{\rtf1\ansi\deff0\pard\f0\fs20 Drawing\par "
       r"{\object\objemb{\*\objclass Paint.Picture}\objw100\objh100{\*\objdata 0105000002000000" + "ab12cd34" * 25000 + "}}"
       + "\\par\r\n}")
FD_LINKED = r"{\rtf1\ansi\deff0\pard\f0\fs20 Linked row note\par" + "\r\n}"
FD_OTHER = r"{\rtf1\ansi\deff0\pard\f0\fs20 Other row\par" + "\r\n}"


@pytest.fixture(params=["pict", "ole"])
def fd(request):
    return PICT if request.param == "pict" else OLE


@pytest.fixture
def world(h, monkeypatch, fd):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: None)  # legacy: no database
    h.delete_on()
    w = World(h)
    fds = {w.p_free: fd, w.p_linked: FD_LINKED, w.p_spo: FD_OTHER, w.p_other: FD_OTHER}
    for r in h.vendor.rows("PO", 7001):
        r["FurtherDescription"] = fds[r["DtlKey"]]
    w.fd = fd
    return w


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def row_in(call, key) -> Dict[str, Any]:
    (r,) = [r for r in call.body["Details"] if r["DtlKey"] == key]
    return r


def new_rows(call) -> List[Dict[str, Any]]:
    return [r for r in call.body["Details"] if r["DtlKey"] == 0]


def assert_source_plus_note(new_fd: str, source: str) -> None:
    """``append_note(source, S/O note)``: the source byte for byte up to its final brace, then the note paragraph."""
    assert new_fd.startswith(source[:-1]) and new_fd.endswith("}"), "the source FD was rebuilt"
    tail = new_fd[len(source) - 1:]
    assert "S/O:" in tail and len(new_fd) > len(source)


def test_partial_link_cut_row_identical_and_new_row_is_source_plus_note(h, world):
    res = h.run("split_link", dict(po_doc_key=7001, po_dtl_key=world.p_free, so_doc_key=7002, so_dtl_key=world.so_a,
                                   qty=2), key="k-part")
    assert res.outcome == "done", (res.outcome, res.error_code)
    first = puts(h)[0]
    assert row_in(first, world.p_free)["FurtherDescription"] == world.fd  # the cut row, byte for byte
    (new,) = new_rows(first)
    assert_source_plus_note(new["FurtherDescription"], world.fd)


def test_whole_link_re_added_row_is_source_plus_note(h, world):
    res = h.run("link_row", world.params["link_row"], key="k-whole")
    assert res.outcome == "done", (res.outcome, res.error_code)
    first = puts(h)[0]
    (new,) = new_rows(first)
    assert_source_plus_note(new["FurtherDescription"], world.fd)
    for call in puts(h):  # a later restore PUT re-sends the new row: still the source + note, never a bare note
        for r in call.body["Details"]:
            if r.get("FromDocDtlKey") and "FurtherDescription" in r and r["DtlKey"] != 0:
                assert r["FurtherDescription"].startswith(world.fd[:-1])


def test_qty_only_edit_resends_the_row_fd_identical(h, world):
    res = h.edit("PO", 7001, line_changes=[{"DtlKey": world.p_free, "Qty": 3}])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert row_in(puts(h)[0], world.p_free)["FurtherDescription"] == world.fd


def test_relocate_resends_the_linked_row_fd_identical(h, world):
    res = WriteBackService(h.db, **h.factories()).relocate(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=7001, po_dtl_key=world.p_linked,
        location="HQ")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert row_in(puts(h)[0], world.p_linked)["FurtherDescription"] == FD_LINKED


def test_unlink_re_added_row_is_the_source_fd_identical_with_no_new_note(h, world):
    res = h.run("unlink_row", world.params["unlink_row"], key="k-unl")
    assert res.outcome == "done", (res.outcome, res.error_code)
    (new,) = new_rows(puts(h)[0])
    assert new["FurtherDescription"] == FD_LINKED  # exactly the old row's FD: no S/O note, nothing rebuilt


def test_unlink_merge_raised_row_fd_identical(h, world):
    for r in h.vendor.rows("PO", 7001):  # make p_free the same-location merge target of the linked row (plan 62 D7)
        if r["DtlKey"] == world.p_free:
            r["UnitPrice"] = 5.5
    res = h.run("unlink_row", world.params["unlink_row"], key="k-merge")
    assert res.outcome == "done", (res.outcome, res.error_code)
    first = puts(h)[0]
    assert new_rows(first) == [], "expected the merge shape (no new row)"
    assert row_in(first, world.p_free)["FurtherDescription"] == world.fd


def test_batch_link_cut_row_identical_and_new_row_is_source_plus_note(h, world):
    res = h.run("link_batch", dict(doc_key=7001, dtl_key=world.p_free, links=[
        dict(so_doc_key=7002, so_dtl_key=world.so_a, qty=2)]), key="k-batch")
    assert res.outcome == "done", (res.outcome, res.error_code)
    first = puts(h)[0]
    assert row_in(first, world.p_free)["FurtherDescription"] == world.fd
    (new,) = new_rows(first)
    assert_source_plus_note(new["FurtherDescription"], world.fd)


# ---- one row without the key: legacy as today ---------------------------------------------------------

@pytest.mark.parametrize("name", ["split_link", "link_row", "edit", "unlink_row"])
def test_one_row_missing_the_key_sends_no_fd_and_refuses_nothing(h, world, name):
    for r in h.vendor.rows("PO", 7001):
        if r["DtlKey"] == world.p_other:
            del r["FurtherDescription"]
    run = {
        "split_link": lambda: h.run("split_link", dict(po_doc_key=7001, po_dtl_key=world.p_free, so_doc_key=7002,
                                                        so_dtl_key=world.so_a, qty=2), key="k-m1"),
        "link_row": lambda: h.run("link_row", world.params["link_row"], key="k-m2"),
        "edit": lambda: h.edit("PO", 7001, line_changes=[{"DtlKey": world.p_free, "Qty": 3}]),
        "unlink_row": lambda: h.run("unlink_row", world.params["unlink_row"], key="k-m3"),
    }[name]
    before = {r["DtlKey"] for r in h.vendor.rows("PO", 7001)}
    res = run()
    assert res.outcome == "done" and res.error_code not in ("AUTOCOUNT_DB_UNREAD", "LINE_NOTES_UNKNOWN"), (res.outcome, res.error_code)
    assert puts(h)
    for call in puts(h):
        for r in call.body["Details"]:
            if r.get("FullTransferOption") == "D":
                continue  # a deleted row is sent exactly as read, as today
            if r["DtlKey"] in before:
                assert "FurtherDescription" not in r, (name, r["DtlKey"])
            elif "FurtherDescription" in r:  # the new linked row: AutoCount's wrapper holding the note, as today
                assert r["FurtherDescription"].startswith(P._RTF_HEAD) and world.fd[:40] not in r["FurtherDescription"]


# ---- SO / QT: the row's FD passes through an edit unchanged ----------------------------------------------

def test_so_edit_passes_the_row_fd_through_identical(h, monkeypatch, fd):
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: None)
    doc = h.seed_doc("SO", 5001, [_line("ITEM-A", 5, 5.0, "HQ"), _line("ITEM-B", 2, 6.0, "HQ")])
    keys = [r["DtlKey"] for r in doc["Details"]]
    for r in h.vendor.rows("SO", 5001):
        r["FurtherDescription"] = fd if r["DtlKey"] == keys[0] else FD_OTHER
    res = h.edit("SO", 5001, {}, [{"DtlKey": keys[0], "Qty": 4}])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert row_in(puts(h)[0], keys[0])["FurtherDescription"] == fd
