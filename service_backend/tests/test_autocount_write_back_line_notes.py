"""Plan 73 (RED): a PO / SPO write keeps the line Further Description (FD, RTF with pictures).

Contract under test (documentation/plans/sprint-5/73-po-link-keep-further-desc.md):
``modules.autocount.write_back.line_notes`` (DocDbSource, attach_db_doc,
NotesReader) and the ``payloads`` builders (append_note, FURTHER_DESC, AUTOCOUNT_DB_UNREAD).
Every row a builder re-sends or copies carries the source row's FD byte for byte; a new linked
row gets the S/O note appended; an unknown FD is refused (``AUTOCOUNT_DB_UNREAD``) before any PUT.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest

from modules.autocount.write_back import payloads as P
from modules.autocount.write_back.payloads import WriteRefusal
from tests.autocount_write_back_fake_vendor import new_doc
from tests.test_autocount_write_back_operations import (  # noqa: F401
    OpHarness,
    World,
    db,
    h,
)
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

PICT1 = "89504e470d0a1a0a0000000d49484452"
PICT2 = "ffd8ffe000104a46494600010100000100"
FD1 = (r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fswiss Arial;}}\viewkind4\uc1\pard\f0\fs20 Special finish\par"
       r"{\pict\pngblip\picw10\pich10 " + PICT1 + "}\\par\r\n}")
FD2 = (r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fswiss Arial;}}\viewkind4\uc1\pard\f0\fs20 Second line\par"
       r"{\pict\jpegblip\picw20\pich20 " + PICT2 + "}\\par\r\n}")
FD3 = r"{\rtf1\ansi\deff0\pard\f0\fs20 Third line\par" + "\r\n}"
NOTE = "**ACME S/O: 389293 DD: 04/11/2026"


# ---- fixtures -----------------------------------------------------------------------------------

def _row(item="ITEM-1", qty=4, price=10.0, **over) -> Dict[str, Any]:
    out = {"ItemCode": item, "UOM": "UNIT", "Qty": qty, "UnitPrice": price, "Location": "BR1",
           "Description": item, "Discount": "", "TaxCode": ""}
    out.update(over)
    return out


def _po(kind="PO", fds=(FD1, FD2, FD3)) -> Dict[str, Any]:
    """Rows: 0 free (FD1), 1 linked to SO row 800101 (FD2), 2 free (FD3). Every row carries FD."""
    link = dict(FromDocType="SO", FromDocNo="SO-8001", FromDocDtlKey=800101, FromSODtlKey=800101)
    rows = [_row(), _row(price=11.0, **link), _row(price=12.0)]
    for r, fd in zip(rows, fds):
        if fd is not None:
            r["FurtherDescription"] = fd
    return new_doc(kind, 7001, f"{kind}-7001", "P", rows)


def _so() -> Dict[str, Any]:
    return new_doc("SO", 8001, "SO-8001", "D", [_row(qty=20)])


def _keys(doc):
    return [r["DtlKey"] for r in doc["Details"]]


def _without_fd(doc, index):
    out = copy.deepcopy(doc)
    del out["Details"][index]["FurtherDescription"]
    return out


def _body(res):
    return res.body if hasattr(res, "body") else res


def _new(body):
    return [r for r in body["Details"] if r["DtlKey"] == 0]


def _marked_d(body):
    return [r for r in body["Details"] if r.get("FullTransferOption") == "D"]


def _live(body):
    return [r for r in body["Details"] if r.get("FullTransferOption") != "D"]


def _link_line(source, so_dtl=800101, qty=1, **over):
    line = {k: source.get(k) for k in ("ItemCode", "UOM", "UnitPrice", "Location", "Description")}
    line.update(Qty=qty, FromDocType="SO", FromDocNo="SO-8001", FromDocDtlKey=so_dtl)
    line.update(over)
    return line


def _refuses(fn):
    with pytest.raises(WriteRefusal) as exc:
        fn()
    assert exc.value.code == "AUTOCOUNT_DB_UNREAD"


# ---- constants + append_note --------------------------------------------------------------------

def test_constants():
    assert P.FURTHER_DESC == "FurtherDescription"
    assert P.AUTOCOUNT_DB_UNREAD == "AUTOCOUNT_DB_UNREAD"


def test_append_note_empty_fd_is_the_default_wrapper():
    assert P.append_note("", NOTE) == P.autocount_rtf(NOTE)
    assert P.append_note(None, NOTE) == P.autocount_rtf(NOTE)


def test_append_note_rtf_inserts_a_paragraph_before_the_final_brace_and_keeps_the_rest_byte_identical():
    out = P.append_note(FD1, NOTE)
    assert out == FD1[:-1] + "\\par " + NOTE + "}"
    assert out.startswith(FD1[:-1]) and PICT1 in out


def test_append_note_escapes_rtf_specials_of_the_note():
    out = P.append_note(FD1, "a{b}\\c")
    assert out == FD1[:-1] + "\\par " + "a\\{b\\}\\\\c" + "}"


def test_append_note_plain_text_fd_is_wrapped_with_the_note_on_a_new_line():
    assert P.append_note("Special finish", NOTE) == P.autocount_rtf("Special finish\n" + NOTE)


@pytest.mark.parametrize("fd", ["", FD1, "Plain text"])
def test_append_note_is_idempotent(fd):
    once = P.append_note(fd, NOTE)
    assert P.append_note(once, NOTE) == once


def test_append_note_fd_already_holding_the_note_is_unchanged():
    assert P.append_note(FD1[:-1] + "\\par " + NOTE + "}", NOTE) == FD1[:-1] + "\\par " + NOTE + "}"


# ---- line_notes module --------------------------------------------------------------------------

class _InnerReader:
    def __init__(self, docs):
        self.docs = docs
        self.calls: List[Any] = []
        self.marker = "inner-attr"

    def get_document(self, kind, doc_key, doc_date, doc_no=None):
        self.calls.append(("get_document", kind, doc_key, doc_date, doc_no))
        return copy.deepcopy(self.docs[kind])

    def get_by_doc_no(self, kind, doc_no):
        self.calls.append(("get_by_doc_no", kind, doc_no))
        return copy.deepcopy(self.docs[kind])

    def location_codes(self):
        return {"HQ": "HQ"}


class _Source:
    """A DocDbSource: the stored header (none) and every row's Further Description."""

    def __init__(self, answer=None):
        self.calls: List[Any] = []
        self.answer = answer

    def read(self, kind, doc):
        self.calls.append((kind, doc["DocKey"]))
        if self.answer is not None:
            return self.answer
        return {"header": {}, "rows": {k: {"FurtherDescription": fd} for k, fd in zip(_keys(doc), (FD1, FD2, FD3))}}


@pytest.mark.parametrize("kind", ["PO", "SPO"])
def test_notes_reader_enriches_po_and_spo_on_both_reads(kind):
    from modules.autocount.write_back.line_notes import NotesReader

    plain = _po(kind, fds=(None, None, None))
    reader = NotesReader(_InnerReader({kind: plain}), _Source())
    for doc in (reader.get_document(kind, 7001, None), reader.get_document(kind, 7001, None, "X"),
                reader.get_by_doc_no(kind, f"{kind}-7001")):
        assert [r["FurtherDescription"] for r in doc["Details"]] == [FD1, FD2, FD3]


@pytest.mark.parametrize("kind", ["SO", "QT"])
def test_notes_reader_leaves_so_and_qt_untouched(kind):
    from modules.autocount.write_back.line_notes import NotesReader

    doc = new_doc(kind, 8001, "X-1", "D", [_row()])
    source = _Source()
    reader = NotesReader(_InnerReader({kind: doc}), source)
    for got in (reader.get_document(kind, 8001, None), reader.get_by_doc_no(kind, "X-1")):
        assert got == doc and all("FurtherDescription" not in r for r in got["Details"])
    assert source.calls == []


@pytest.mark.parametrize("source", ["read_none"])
def test_notes_reader_unread_db_leaves_rows_without_the_key_even_when_hapi_carries_it(source):
    from modules.autocount.write_back.line_notes import NotesReader

    class _Unread:
        def read(self, kind, doc):
            return None

    doc = _po()  # the vendor GET itself carries FurtherDescription on every row
    got = NotesReader(_InnerReader({"PO": doc}), None if source is None else _Unread()).get_document("PO", 7001, None)
    assert all("FurtherDescription" not in r for r in got["Details"])


def test_notes_reader_no_source_keeps_the_get_fd_when_every_row_carries_it_else_drops_it():
    from modules.autocount.write_back.line_notes import NotesReader

    doc = _po()  # legacy mode, the vendor GET carries FurtherDescription on every row (vendor 25 Nov): kept as read
    got = NotesReader(_InnerReader({"PO": doc}), None).get_document("PO", 7001, None)
    assert [r["FurtherDescription"] for r in got["Details"]] == [FD1, FD2, FD3]
    partial = _without_fd(_po(), 1)  # one row without the key: none is kept
    got = NotesReader(_InnerReader({"PO": partial}), None).get_document("PO", 7001, None)
    assert all("FurtherDescription" not in r for r in got["Details"])


def test_notes_reader_delegates_other_attributes_and_arguments():
    from modules.autocount.write_back.line_notes import NotesReader

    inner = _InnerReader({"PO": _po(fds=(None, None, None))})
    reader = NotesReader(inner, _Source())
    assert reader.location_codes() == {"HQ": "HQ"} and reader.marker == "inner-attr"
    reader.get_by_doc_no("PO", "PO-7001")
    assert ("get_by_doc_no", "PO", "PO-7001") in inner.calls


# ---- build_link ---------------------------------------------------------------------------------

def test_link_whole_qty_new_row_keeps_fd_and_appends_the_note():
    po, so = _po(), _so()
    k0 = _keys(po)[0]
    body = P.build_link(po, k0, so, _keys(so)[0], Decimal(4), note=NOTE)
    (new,) = _new(body)
    assert new["FurtherDescription"] == P.append_note(FD1, NOTE) and PICT1 in new["FurtherDescription"]
    assert body["ShippingPO"] == "F"


def test_link_whole_qty_without_a_note_copies_fd_byte_identical():
    po, so = _po(), _so()
    body = P.build_link(po, _keys(po)[0], so, _keys(so)[0], Decimal(4))
    assert _new(body)[0]["FurtherDescription"] == FD1


def test_link_partial_edited_row_keeps_fd_and_new_row_is_note_only():
    po, so = _po(), _so()
    k0 = _keys(po)[0]
    body = P.build_link(po, k0, so, _keys(so)[0], Decimal(1), note=NOTE)
    (edited,) = [r for r in body["Details"] if r["DtlKey"] == k0]
    (new,) = _new(body)
    assert edited["FurtherDescription"] == FD1
    assert new["FurtherDescription"] == P.autocount_rtf(NOTE)  # owner 25 Nov: a split's new row carries only the note


@pytest.mark.parametrize("qty", [Decimal(4), Decimal(1)])
def test_link_unknown_fd_is_refused(qty):
    po, so = _without_fd(_po(), 0), _so()
    _refuses(lambda: P.build_link(po, _keys(po)[0], so, _keys(so)[0], qty))


def test_link_other_rows_without_fd_do_not_matter():
    po, so = _without_fd(_po(), 2), _so()
    body = P.build_link(po, _keys(po)[0], so, _keys(so)[0], Decimal(4))
    assert _new(body)[0]["FurtherDescription"] == FD1


def test_link_whole_row_marked_d_needs_no_fd_of_its_own_in_the_body_but_the_new_row_has_it():
    po, so = _po(), _so()
    body = P.build_link(po, _keys(po)[0], so, _keys(so)[0], Decimal(4))
    assert len(_marked_d(body)) == 1 and _new(body)[0]["FurtherDescription"] == FD1


# ---- relocate / restore / unlink ----------------------------------------------------------------

def test_relocate_resends_the_linked_row_with_its_fd():
    po = _po()
    body = P.build_relocate(po, _keys(po)[1], "HQ")
    assert body["Details"][0]["FurtherDescription"] == FD2 and body["ShippingPO"] == "F"


def test_relocate_unknown_fd_refused():
    po = _without_fd(_po(), 1)
    _refuses(lambda: P.build_relocate(po, _keys(po)[1], "HQ"))


def test_restore_transfer_row_keeps_fd_when_the_values_carry_none():
    po = _po()
    body = P.build_restore_transfer_row(po, _keys(po)[0], {"UnitPrice": 1})
    assert body["Details"][0]["FurtherDescription"] == FD1


def test_restore_transfer_row_sends_the_note_value_exactly_as_given_never_rebuilt_from_the_read():
    """AutoCount reads a new SO-linked row back with an empty note (live db3 25 Nov): the caller's value is the intended
    one (what PUT 1 sent), so the restore sends it byte for byte and never merges it into the read-back note."""
    po = _po()
    given = P.append_note(FD1, NOTE)
    body = P.build_restore_transfer_row(po, _keys(po)[0], {"FurtherDescription": given})
    assert body["Details"][0]["FurtherDescription"] == given
    note_only = P.autocount_rtf(NOTE)
    body = P.build_restore_transfer_row(po, _keys(po)[0], {"FurtherDescription": note_only})
    assert body["Details"][0]["FurtherDescription"] == note_only  # a bare value is a split's intended note, not a merge


def test_restore_transfer_row_unknown_fd_refused():
    po = _without_fd(_po(), 0)
    _refuses(lambda: P.build_restore_transfer_row(po, _keys(po)[0], {"UnitPrice": 1}))


def test_transfer_restore_so_link_appends_the_note_to_the_source_fd():
    source = {"UnitPrice": 10.0, "Location": "BR1", "DeliveryDate": "2026-12-01T00:00:00",
              "FurtherDescription": FD1}
    out = P.transfer_restore(source, "HQ", {"soDeliveryDate": "2026-11-04", "note": NOTE})
    assert out["FurtherDescription"] == P.append_note(FD1, NOTE) and PICT1 in out["FurtherDescription"]


def test_unlink_row_new_row_copies_the_old_fd_without_a_note():
    po = _po()
    body = P.build_unlink_row(po, _keys(po)[1])
    (new,) = _new(body)
    assert new["FurtherDescription"] == FD2 and len(_marked_d(body)) == 1


def test_unlink_row_unknown_fd_refused():
    po = _without_fd(_po(), 1)
    _refuses(lambda: P.build_unlink_row(po, _keys(po)[1]))


# ---- row replace / edit / add / link doc / batch / unlink merge / delete ------------------------

def test_row_replace_new_row_copies_the_old_fd():
    po = _po()
    k0 = _keys(po)[0]
    body = P.build_row_replace("PO", po, {"DtlKey": k0}, _link_line(po["Details"][0], qty=4)).body
    assert _new(body)[0]["FurtherDescription"] == FD1


def test_row_replace_with_a_note_appends_it():
    po = _po()
    k0 = _keys(po)[0]
    line = _link_line(po["Details"][0], qty=4, soNote=NOTE)
    body = P.build_row_replace("PO", po, {"DtlKey": k0}, line).body
    assert _new(body)[0]["FurtherDescription"] == P.append_note(FD1, NOTE)


def test_row_replace_unknown_fd_refused():
    po = _without_fd(_po(), 0)
    _refuses(lambda: P.build_row_replace("PO", po, {"DtlKey": _keys(po)[0]}, _link_line(po["Details"][0], qty=4)))


def test_build_edit_resends_the_touched_row_with_its_fd():
    po = _po()
    k0 = _keys(po)[0]
    body = P.build_edit("PO", po, {}, [{"DtlKey": k0, "Qty": 2}]).body
    assert body["Details"][0]["FurtherDescription"] == FD1 and body["ShippingPO"] == "F"


def test_build_edit_unknown_fd_on_a_touched_row_refused_untouched_rows_do_not_matter():
    po = _without_fd(_po(), 0)
    _refuses(lambda: P.build_edit("PO", po, {}, [{"DtlKey": _keys(po)[0], "Qty": 2}]))
    po2 = _without_fd(_po(), 2)
    ok = P.build_edit("PO", po2, {}, [{"DtlKey": _keys(po2)[0], "Qty": 2}]).body
    assert ok["Details"][0]["FurtherDescription"] == FD1


def test_build_edit_spo_keeps_fd_and_shipping_po_t():
    spo = _po("SPO")
    body = P.build_edit("SPO", spo, {}, [{"DtlKey": _keys(spo)[0], "Qty": 2}]).body
    assert body["Details"][0]["FurtherDescription"] == FD1 and body["ShippingPO"] == "T"


def test_add_line_copy_sends_the_fd_it_is_given_byte_identical():
    po = _po()
    line = _link_line(po["Details"][0], qty=4)
    line["FurtherDescription"] = FD1
    body = P.build_add_line("PO", po, line).body
    assert _new(body)[0]["FurtherDescription"] == FD1


def test_link_doc_whole_row_first_new_row_copies_the_old_fd_the_others_are_note_only():
    po = _po()
    k0 = _keys(po)[0]
    src = po["Details"][0]
    rows = [_link_line(src, qty=3, soNote=NOTE), _link_line(src, so_dtl=800102, qty=1, soNote="**OTHER S/O: 2")]
    body = P.build_link_doc("PO", po, [(k0, rows)]).body
    fds = [r["FurtherDescription"] for r in _new(body)]
    assert fds == [P.append_note(FD1, NOTE), P.autocount_rtf("**OTHER S/O: 2")]


def test_link_doc_rest_kept_row_keeps_its_fd():
    po = _po()
    k0 = _keys(po)[0]
    body = P.build_link_doc("PO", po, [(k0, [_link_line(po["Details"][0], qty=1, soNote=NOTE)])]).body
    (kept,) = [r for r in body["Details"] if r["DtlKey"] == k0]
    assert kept["FurtherDescription"] == FD1 and kept.get("FullTransferOption") != "D"
    assert _new(body)[0]["FurtherDescription"] == P.autocount_rtf(NOTE)  # the original keeps a rest: note only


def test_link_batch_new_row_keeps_fd():
    po = _po()
    k0 = _keys(po)[0]
    body = P.build_link_batch("PO", po, k0, [_link_line(po["Details"][0], qty=4)]).body
    assert _new(body)[0]["FurtherDescription"] == FD1


def test_link_doc_unknown_fd_refused():
    po = _without_fd(_po(), 0)
    _refuses(lambda: P.build_link_doc("PO", po, [(_keys(po)[0], [_link_line(po["Details"][0], qty=4)])]))


def test_unlink_merge_raised_row_keeps_fd_and_the_deleted_row_needs_none():
    po = _po()
    body = P.build_unlink_merge("PO", po, _keys(po)[1], _keys(po)[2]).body
    (raised,) = _live(body)
    assert raised["FurtherDescription"] == FD3 and body["ShippingPO"] == "F"
    no_linked_fd = _without_fd(po, 1)
    ok = P.build_unlink_merge("PO", no_linked_fd, _keys(po)[1], _keys(po)[2]).body
    assert _live(ok)[0]["FurtherDescription"] == FD3


def test_unlink_merge_unknown_fd_on_the_raised_row_refused():
    po = _without_fd(_po(), 2)
    _refuses(lambda: P.build_unlink_merge("PO", po, _keys(po)[1], _keys(po)[2]))


def test_unlink_merge_spo_keeps_shipping_po_t():
    spo = _po("SPO")
    assert P.build_unlink_merge("SPO", spo, _keys(spo)[1], _keys(spo)[2]).body["ShippingPO"] == "T"


def test_delete_line_needs_no_fd():
    po = _po(fds=(None, None, None))
    body = P.build_delete_line("PO", po, _keys(po)[0]).body
    assert [r["FullTransferOption"] for r in body["Details"]] == ["D"]


# ---- end to end through the operation service (fake vendor, no network) --------------------------

class _FakeSource:
    def __init__(self):
        self.calls = 0

    def read(self, kind, doc):
        self.calls += 1
        return {"header": {}, "rows": {r["DtlKey"]: {"FurtherDescription": FD1} for r in doc["Details"]}}


def _patch_source(monkeypatch, source):
    from modules.autocount.write_back.frame import WriteFrame

    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: source, raising=False)


class _UnreadSource:
    def read(self, kind, doc):
        return None


def test_link_row_with_an_unreadable_db_source_is_refused_and_nothing_is_put(h, monkeypatch):
    world = World(h)  # the fake PO read carries no FurtherDescription
    _patch_source(monkeypatch, _UnreadSource())
    res = h.run("link_row", world.params["link_row"])
    assert (res.outcome, res.error_code) == ("refused", "AUTOCOUNT_DB_UNREAD"), (res.outcome, res.error_code)
    assert [c for c in h.vendor.calls if c.method == "PUT"] == []
    assert h.vendor.writes() == []


def test_link_row_with_a_db_source_sends_the_fd_on_the_new_row(h, monkeypatch):
    world = World(h)
    source = _FakeSource()
    _patch_source(monkeypatch, source)
    res = h.run("link_row", world.params["link_row"])
    assert res.error_code != "AUTOCOUNT_DB_UNREAD", res
    puts = [c for c in h.vendor.writes() if c.method == "PUT"]
    assert puts and source.calls >= 1
    sent = [r for c in puts for r in c.body["Details"] if r.get("FullTransferOption") != "D"]
    assert sent, "no live row was sent"
    first = [r for r in puts[0].body["Details"] if r["DtlKey"] == 0]
    assert len(first) == 1 and first[0]["FurtherDescription"].startswith(FD1[:-1]) and PICT1 in first[0]["FurtherDescription"]
    for r in sent:  # no later write (the restore PUT) swaps the FD for a bare note
        if "FurtherDescription" in r:
            assert PICT1 in r["FurtherDescription"]
