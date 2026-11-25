"""Plan 73 r9 (RED): a split's new line carries ONLY the S/O note (owner 25 Nov: "keep the further description in original
lines only, don't bring that forward to new lines").

1. PARTIAL link (the original row stays with the rest): the original / cut row keeps its FurtherDescription byte for byte; the
   NEW linked row's FD = ``autocount_rtf(S/O note)`` and nothing of the original (no text, no picture, no object), also in the
   restore PUT.
2. WHOLE link (no rest: the original is deleted and re-added as the linked row): original FD + note appended (as today).
3. Batch (``build_link_doc``): a row with rest > 0: all its new rows note-only; a fully taken row (rest 0): the FIRST new row gets
   original FD + note, every other new row note-only.
4. Relink / unlink / relocate / edit unchanged. Both DB mode (the conftest echo default) and legacy + vendor-GET FD mode.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, List

import pytest

from modules.autocount.write_back import payloads as P
from modules.autocount.write_back.frame import WriteFrame
from tests.test_autocount_write_back_fd_from_get import FD_LINKED, FD_OTHER, OLE, PICT, fd, puts, row_in  # noqa: F401
from tests.test_autocount_write_back_line_notes import NOTE, _keys, _link_line, _new, _po, _so
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

N1, N2 = NOTE, "**OTHER S/O: 2"


def note_only(value: str, note: str) -> None:
    assert value == P.autocount_rtf(note), "the new line must carry only the S/O note"


def note_only_shape(value: str, original: str) -> None:
    """Operations: AutoCount's own wrapper holding the note, nothing of the original."""
    assert value.startswith(P._RTF_HEAD) and value.endswith(P._RTF_TAIL) and "S/O:" in value
    marker = "Special finish" if "Special finish" in original else "Drawing"
    assert marker not in value and "pict" not in value and "objdata" not in value


# ---- payloads ----------------------------------------------------------------------------------------

def test_build_link_partial_new_row_is_note_only_and_cut_row_keeps_fd(fd):
    po, so = _po(fds=(fd, FD_LINKED, FD_OTHER)), _so()
    k0 = _keys(po)[0]
    body = P.build_link(po, k0, so, _keys(so)[0], Decimal(1), note=N1)
    (cut,) = [r for r in body["Details"] if r["DtlKey"] == k0]
    assert cut["FurtherDescription"] == fd
    note_only(_new(body)[0]["FurtherDescription"], N1)


def test_build_link_whole_new_row_is_original_plus_note(fd):
    po, so = _po(fds=(fd, FD_LINKED, FD_OTHER)), _so()
    body = P.build_link(po, _keys(po)[0], so, _keys(so)[0], Decimal(4), note=N1)
    assert _new(body)[0]["FurtherDescription"] == P.append_note(fd, N1)


def test_build_link_doc_rest_above_zero_all_new_rows_note_only(fd):
    po = _po(fds=(fd, FD_LINKED, FD_OTHER))
    k0, src = _keys(po)[0], po["Details"][0]
    body = P.build_link_doc("PO", po, [(k0, [_link_line(src, qty=1, soNote=N1), _link_line(src, so_dtl=800102, qty=1, soNote=N2)])]).body
    (kept,) = [r for r in body["Details"] if r["DtlKey"] == k0]
    assert kept["FurtherDescription"] == fd
    first, second = _new(body)
    note_only(first["FurtherDescription"], N1)
    note_only(second["FurtherDescription"], N2)


def test_build_link_doc_fully_taken_row_first_new_row_original_plus_note_others_note_only(fd):
    po = _po(fds=(fd, FD_LINKED, FD_OTHER))
    k0, src = _keys(po)[0], po["Details"][0]
    body = P.build_link_doc("PO", po, [(k0, [_link_line(src, qty=2, soNote=N1), _link_line(src, so_dtl=800102, qty=2, soNote=N2)])]).body
    first, second = _new(body)
    assert first["FurtherDescription"] == P.append_note(fd, N1)
    note_only(second["FurtherDescription"], N2)


def test_build_link_batch_follows_the_same_rule(fd):
    po = _po(fds=(fd, FD_LINKED, FD_OTHER))
    body = P.build_link_batch("PO", po, _keys(po)[0], [_link_line(po["Details"][0], qty=1, soNote=N1)]).body
    note_only(_new(body)[0]["FurtherDescription"], N1)


def test_restore_of_a_split_new_row_stays_note_only(fd):
    """The second write of a split: the new row (already note-only) restored with the bare note value is not merged with any original FD."""
    po = _po(fds=(P.autocount_rtf(N1), FD_LINKED, FD_OTHER))
    body = P.build_restore_transfer_row(po, _keys(po)[0], {"FurtherDescription": P.autocount_rtf(N1), "Location": "HQ"})
    note_only(body["Details"][0]["FurtherDescription"], N1)


def test_relink_row_replace_still_appends_the_new_note_to_the_rows_own_fd(fd):
    po = _po(fds=(fd, FD_LINKED, FD_OTHER))
    body = P.build_row_replace("PO", po, {"DtlKey": _keys(po)[0]}, _link_line(po["Details"][0], qty=4, soNote=N1)).body
    assert _new(body)[0]["FurtherDescription"] == P.append_note(fd, N1)


def test_unlink_relocate_edit_unchanged(fd):
    po = _po(fds=(fd, FD_LINKED, FD_OTHER))
    k = _keys(po)
    assert P.build_edit("PO", po, {}, [{"DtlKey": k[0], "Qty": 2}]).body["Details"][0]["FurtherDescription"] == fd
    assert P.build_relocate(po, k[1], "HQ")["Details"][0]["FurtherDescription"] == FD_LINKED
    assert _new(P.build_unlink_row(po, k[1]))[0]["FurtherDescription"] == FD_LINKED


# ---- operations end to end: DB mode (echo default) and legacy + vendor-GET FD -------------------------------

@pytest.fixture(params=["db", "legacy"])
def world(request, h, monkeypatch, fd):
    if request.param == "legacy":
        monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: None)
    h.delete_on()
    w = World(h)
    fds = {w.p_free: fd, w.p_linked: FD_LINKED, w.p_spo: FD_OTHER, w.p_other: FD_OTHER}
    for r in h.vendor.rows("PO", 7001):
        r["FurtherDescription"] = fds[r["DtlKey"]]
    w.fd = fd
    return w


def minted_rows(h, before) -> List[Any]:
    return [r for call in puts(h) for r in call.body["Details"]
            if r["DtlKey"] not in before and r.get("FullTransferOption") != "D"]


def test_split_link_new_row_is_note_only_in_every_put_and_cut_row_keeps_fd(h, world):
    before = {r["DtlKey"] for r in h.vendor.rows("PO", 7001)}
    res = h.run("split_link", dict(po_doc_key=7001, po_dtl_key=world.p_free, so_doc_key=7002, so_dtl_key=world.so_a,
                                   qty=2), key="k-split")
    assert res.outcome == "done", (res.outcome, res.error_code)
    first = puts(h)[0]
    assert row_in(first, world.p_free)["FurtherDescription"] == world.fd
    (new,) = [r for r in first.body["Details"] if r["DtlKey"] == 0]
    note_only_shape(new["FurtherDescription"], world.fd)
    for r in minted_rows(h, before):  # the restore PUT (second write) re-sends the new row
        if "FurtherDescription" in r:
            note_only_shape(r["FurtherDescription"], world.fd)
    cut = [r for call in puts(h) for r in call.body["Details"] if r["DtlKey"] == world.p_free and "FurtherDescription" in r]
    assert all(r["FurtherDescription"] == world.fd for r in cut)


def test_link_row_whole_new_row_is_original_plus_note(h, world):
    res = h.run("link_row", world.params["link_row"], key="k-whole")
    assert res.outcome == "done", (res.outcome, res.error_code)
    (new,) = [r for r in puts(h)[0].body["Details"] if r["DtlKey"] == 0]
    fdn = new["FurtherDescription"]
    assert fdn.startswith(world.fd[:-1]) and fdn.endswith("}") and "S/O:" in fdn[len(world.fd) - 1:]


def test_link_row_partial_qty_through_the_link_route_is_note_only(h, world):
    """``link_row`` with a quantity below the row's (the service picks the split flow): same rule as ``split_link``."""
    from modules.autocount.write_back.service import WriteBackService

    svc = WriteBackService(h.db, **h.factories())
    res = svc.link(tenant_id=h.company.tenant_id, company_id=h.company.id, po_doc_key=7001, po_dtl_key=world.p_free,
                   so_doc_key=7002, so_dtl_key=world.so_a, qty=Decimal(2), key_id="k1", operations=h.ops())
    assert res.outcome == "done", (res.outcome, res.error_code)
    (new,) = [r for r in puts(h)[0].body["Details"] if r["DtlKey"] == 0]
    note_only_shape(new["FurtherDescription"], world.fd)


def test_link_batch_rest_above_zero_new_rows_note_only(h, world):
    res = h.run("link_batch", dict(doc_key=7001, dtl_key=world.p_free, links=[
        dict(so_doc_key=7002, so_dtl_key=world.so_a, qty=1), dict(so_doc_key=7002, so_dtl_key=world.so_b, qty=1)]), key="k-b1")
    assert res.outcome == "done", (res.outcome, res.error_code)
    first = puts(h)[0]
    assert row_in(first, world.p_free)["FurtherDescription"] == world.fd
    rows = [r for r in first.body["Details"] if r["DtlKey"] == 0]
    assert len(rows) == 2
    for r in rows:
        note_only_shape(r["FurtherDescription"], world.fd)


def test_link_batch_fully_taken_row_first_new_row_original_plus_note_second_note_only(h, world):
    res = h.run("link_batch", dict(doc_key=7001, dtl_key=world.p_free, links=[
        dict(so_doc_key=7002, so_dtl_key=world.so_a, qty=2), dict(so_doc_key=7002, so_dtl_key=world.so_b, qty=2)]), key="k-b2")
    assert res.outcome == "done", (res.outcome, res.error_code)
    first, second = [r for r in puts(h)[0].body["Details"] if r["DtlKey"] == 0]
    assert first["FurtherDescription"].startswith(world.fd[:-1]) and "S/O:" in first["FurtherDescription"][len(world.fd) - 1:]
    note_only_shape(second["FurtherDescription"], world.fd)


def test_whole_line_link_has_no_new_line_in_our_code_it_is_delete_and_re_add_so_the_new_row_keeps_the_full_fd(fd):
    """Owner 25 Nov rule (3): "whole-line link with no new line". AutoCount never links an existing row, so a whole link
    always deletes the original ("D", qty 0 left) and re-adds it as the linked row: the same case as rule (2), the new
    row carries the original's FULL FD byte for byte plus the note."""
    po, so = _po(fds=(fd, FD_LINKED, FD_OTHER)), _so()
    body = P.build_link(po, _keys(po)[0], so, _keys(so)[0], Decimal(4), note=N1)
    assert len([r for r in body["Details"] if r.get("FullTransferOption") == "D"]) == 1  # the original goes away
    (new,) = _new(body)
    out = new["FurtherDescription"]
    assert out == P.append_note(fd, N1) and out.startswith(fd[:-1])
