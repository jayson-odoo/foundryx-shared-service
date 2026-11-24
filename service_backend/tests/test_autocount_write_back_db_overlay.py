"""Plan 73 round 2 (RED): every PO / SPO write is read-modify-write from the AutoCount DB.

hapi's PO GET returns Remark2-4 = Remark1 and never FurtherDescription (vendor bugs section 1), so a body
built from the bare GET writes "" over stored values. Contract: ``line_notes.DocDbSource.read(kind, doc)
-> {"header": {col: v}, "rows": {DtlKey: {col: v}}} | None``; ``attach_db_doc(doc, db)`` overlays the stored
header keys (payloads.HEADER_KEYS / EDIT_HEADER_KEYS) and, per row, FurtherDescription + payloads.ROW_KEYS;
``NotesReader(inner, source)`` applies it to PO / SPO reads. Every builder then sends the stored values.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any, Dict, List

import pytest

from modules.autocount.write_back import payloads as P
from tests.autocount_write_back_fake_vendor import new_doc
from tests.test_autocount_write_back_line_notes import (
    FD1, FD2, FD3, NOTE, PICT1, _InnerReader, _keys, _link_line, _new, _po, _row, _so,
)
from tests.test_autocount_write_back_operations import (  # noqa: F401
    OpHarness,
    World,
    db,
    h,
)
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

STORED_HEADER = {
    "Remark4": "L", "Ref": "REF-L", "RefDocNo": "RD-1", "ShipInfo": "SHIP-I", "Attention": "ATT-L",
    "Phone1": "011-111", "Fax1": "022-222", "DeliverContact": "DC-L", "DeliverAddr1": "DA1-L",
}
HAPI_BLANKED = {k: "" for k in STORED_HEADER}  # hapi returns "" for these (Remark4 = Remark1 = "")


def _hapi_po(kind="PO") -> Dict[str, Any]:
    """The PO as hapi's GET returns it: no FurtherDescription, the header fields above blank."""
    doc = _po(kind, fds=(None, None, None))
    doc.update(HAPI_BLANKED)
    return doc


def _db_for(doc, header=None) -> Dict[str, Any]:
    keys = _keys(doc)
    return {
        "header": dict(STORED_HEADER, UDF_X="not-a-key", **(header or {})),
        "rows": {k: {"FurtherDescription": fd, "UDF_Y": "no"} for k, fd in zip(keys, (FD1, FD2, FD3))},
    }


def _overlaid(kind="PO") -> Dict[str, Any]:
    from modules.autocount.write_back.line_notes import attach_db_doc

    doc = _hapi_po(kind)
    return attach_db_doc(doc, _db_for(doc))


def _assert_stored_header(body, name=""):
    for key, value in STORED_HEADER.items():
        assert body.get(key) == value, f"{name}: {key} = {body.get(key)!r}, stored {value!r}"


# ---- attach_db_doc -------------------------------------------------------------------------------

def test_db_header_values_override_the_blank_hapi_header():
    out = _overlaid()
    for key, value in STORED_HEADER.items():
        assert out[key] == value


def test_remark4_stored_l_beats_hapi_remark1_copy():
    from modules.autocount.write_back.line_notes import attach_db_doc

    doc = _hapi_po()
    doc.update(Remark1="", Remark4="")
    assert attach_db_doc(doc, {"header": {"Remark4": "L"}, "rows": {}})["Remark4"] == "L"


def test_db_column_outside_the_key_lists_is_not_added():
    out = _overlaid()
    assert "UDF_X" not in out
    assert all("UDF_Y" not in r for r in out["Details"])


def test_every_row_gets_fd_and_row_keys_from_the_db():
    from modules.autocount.write_back.line_notes import attach_db_doc

    doc = _hapi_po()
    keys = _keys(doc)
    db_doc = {"header": {}, "rows": {keys[0]: {"FurtherDescription": FD1, "Desc2": "stored-d2", "UDF_Y": "x"},
                                     keys[1]: {"FurtherDescription": FD2}, keys[2]: {"FurtherDescription": FD3}}}
    out = attach_db_doc(doc, db_doc)
    assert [r["FurtherDescription"] for r in out["Details"]] == [FD1, FD2, FD3]
    assert out["Details"][0]["Desc2"] == "stored-d2"
    assert "Desc2" not in doc["Details"][1] and "Desc2" not in out["Details"][1]  # unread on both sides: never invented
    assert out["Details"][0]["Desc2"] == "stored-d2"  # the db row carries Desc2: it is sent as stored


def test_attach_db_doc_does_not_mutate_the_input():
    from modules.autocount.write_back.line_notes import attach_db_doc

    doc = _hapi_po()
    before = copy.deepcopy(doc)
    out = attach_db_doc(doc, _db_for(doc))
    assert doc == before and out is not doc


def test_attach_db_doc_unknown_db_returns_the_doc_unchanged():
    from modules.autocount.write_back.line_notes import attach_db_doc

    doc = _hapi_po()
    out = attach_db_doc(doc, None)
    assert out == doc and all("FurtherDescription" not in r for r in out["Details"])


class _Db:
    def __init__(self):
        self.calls: List[Any] = []

    def read(self, kind, doc):
        self.calls.append((kind, doc["DocKey"]))
        return _db_for(doc)


@pytest.mark.parametrize("kind", ["PO", "SPO"])
def test_notes_reader_overlays_header_and_rows_on_both_reads(kind):
    from modules.autocount.write_back.line_notes import NotesReader

    reader = NotesReader(_InnerReader({kind: _hapi_po(kind)}), _Db())
    for doc in (reader.get_document(kind, 7001, None), reader.get_by_doc_no(kind, f"{kind}-7001")):
        _assert_stored_header(doc)
        assert [r["FurtherDescription"] for r in doc["Details"]] == [FD1, FD2, FD3]


@pytest.mark.parametrize("kind", ["SO", "QT"])
def test_notes_reader_db_overlay_leaves_so_and_qt_alone(kind):
    from modules.autocount.write_back.line_notes import NotesReader

    doc = new_doc(kind, 8001, "X-1", "D", [_row()])
    source = _Db()
    got = NotesReader(_InnerReader({kind: doc}), source).get_document(kind, 8001, None)
    assert got == doc and source.calls == []


# ---- builders on the overlaid doc ----------------------------------------------------------------

def _bodies():
    po, so = _overlaid(), _so()
    k0, k1, k2 = _keys(po)
    src = po["Details"][0]
    return {
        "link whole": P.build_link(po, k0, so, _keys(so)[0], Decimal(4), note=NOTE),
        "link partial": P.build_link(po, k0, so, _keys(so)[0], Decimal(1), note=NOTE),
        "relocate": P.build_relocate(po, k1, "HQ"),
        "restore row": P.build_restore_transfer_row(po, k0, {"UnitPrice": 1}),
        "unlink row": P.build_unlink_row(po, k1),
        "row replace": P.build_row_replace("PO", po, {"DtlKey": k0}, _link_line(src, qty=4)).body,
        "link doc": P.build_link_doc("PO", po, [(k0, [_link_line(src, qty=1, soNote=NOTE)])]).body,
        "link batch": P.build_link_batch("PO", po, k0, [_link_line(src, qty=4)]).body,
        "unlink merge": P.build_unlink_merge("PO", po, k1, k2).body,
        "edit": P.build_edit("PO", po, {}, [{"DtlKey": k0, "Qty": 2}]).body,
    }


@pytest.mark.parametrize("name", ["link whole", "link partial", "relocate", "restore row", "unlink row",
                                  "row replace", "link doc", "link batch", "unlink merge", "edit"])
def test_builder_body_header_is_the_stored_header_never_blank(name):
    _assert_stored_header(_bodies()[name], name)


def test_builders_keep_shipping_po_and_the_stored_fd_on_the_overlaid_doc():
    bodies = _bodies()
    assert all(b["ShippingPO"] == "F" for b in bodies.values())
    assert _new(bodies["link whole"])[0]["FurtherDescription"] == P.append_note(FD1, NOTE)
    assert bodies["relocate"]["Details"][0]["FurtherDescription"] == FD2


def test_spo_builders_carry_the_stored_header_too():
    spo = _overlaid("SPO")
    k0, k1, k2 = _keys(spo)
    _assert_stored_header(P.build_edit("SPO", spo, {}, [{"DtlKey": k0, "Qty": 2}]).body, "spo edit")
    _assert_stored_header(P.build_unlink_merge("SPO", spo, k1, k2).body, "spo merge")
    assert P.build_edit("SPO", spo, {}, [{"DtlKey": k0, "Qty": 2}]).body["ShippingPO"] == "T"


# ---- end to end: the owner's "fails today on Remark4 = L" ----------------------------------------

class _FakeDbSource:
    """Serves both shapes (``read`` = the DocDbSource, ``notes`` = the earlier LineNotesSource), so the
    test does not depend on which one the frame consults."""

    def __init__(self):
        self.reads = 0

    def read(self, kind, doc):
        self.reads += 1
        return {"header": {"Remark4": "L"},
                "rows": {r["DtlKey"]: {"FurtherDescription": FD1} for r in doc["Details"]}}

    def notes(self, kind, doc):
        return {r["DtlKey"]: FD1 for r in doc["Details"]}


def test_link_row_put_carries_the_stored_remark4_and_the_fd_while_hapi_returns_blank(h, monkeypatch):
    from modules.autocount.write_back.frame import WriteFrame

    world = World(h)
    po = h.vendor.find("PO", 7001)
    po["Remark1"] = po["Remark4"] = ""  # hapi's GET: Remark4 = Remark1 = ""
    source = _FakeDbSource()
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: source, raising=False)
    res = h.run("link_row", world.params["link_row"])
    assert res.error_code != "LINE_NOTES_UNKNOWN", res
    puts = [c for c in h.vendor.writes() if c.method == "PUT"]
    assert puts
    first = puts[0].body
    assert first["Remark4"] == "L", first.get("Remark4")
    (new,) = [r for r in first["Details"] if r["DtlKey"] == 0]
    assert PICT1 in new["FurtherDescription"] and new["FurtherDescription"].startswith(FD1[:-1])
    for call in puts:  # the restore PUT after the link must not blank it either
        assert call.body["Remark4"] == "L"


# ---- refusal: the AutoCount DB could not be read (crew ruling a, 24 Nov) ------------------------
# Replaces LINE_NOTES_UNKNOWN: no DocDbSource, or one that answers None, refuses every write before any PUT.

UNREAD = "AUTOCOUNT_DB_UNREAD"
UNREAD_TEXT = "The purchase order could not be read from AutoCount, so the change was not made. Try again."


def _refuses_unread(fn):
    with pytest.raises(P.WriteRefusal) as exc:
        fn()
    assert exc.value.code == UNREAD
    assert UNREAD_TEXT in str(exc.value)


def test_unread_constant_and_message():
    assert P.AUTOCOUNT_DB_UNREAD == UNREAD
    assert P.AUTOCOUNT_DB_UNREAD_MESSAGE == UNREAD_TEXT


def _no_fd(index):
    doc = _overlaid()
    del doc["Details"][index]["FurtherDescription"]  # the db overlay did not run: the row is unread
    return doc


def test_builders_refuse_an_unread_row_as_autocount_db_unread():
    so = _so()
    for build in (
        lambda d, k: P.build_link(d, k[0], so, _keys(so)[0], Decimal(4)),
        lambda d, k: P.build_link(d, k[0], so, _keys(so)[0], Decimal(1)),
        lambda d, k: P.build_restore_transfer_row(d, k[0], {"UnitPrice": 1}),
        lambda d, k: P.build_edit("PO", d, {}, [{"DtlKey": k[0], "Qty": 2}]),
        lambda d, k: P.build_row_replace("PO", d, {"DtlKey": k[0]}, _link_line(d["Details"][0], qty=4)),
        lambda d, k: P.build_link_doc("PO", d, [(k[0], [_link_line(d["Details"][0], qty=4)])]),
        lambda d, k: P.build_link_batch("PO", d, k[0], [_link_line(d["Details"][0], qty=4)]),
    ):
        doc = _no_fd(0)
        _refuses_unread(lambda: build(doc, _keys(doc)))
    doc = _no_fd(1)
    _refuses_unread(lambda: P.build_relocate(doc, _keys(doc)[1], "HQ"))
    _refuses_unread(lambda: P.build_unlink_row(doc, _keys(doc)[1]))
    doc = _no_fd(2)
    _refuses_unread(lambda: P.build_unlink_merge("PO", doc, _keys(doc)[1], _keys(doc)[2]))


class _NoRead:
    def read(self, kind, doc):
        return None

    def notes(self, kind, doc):
        return None


def _patch(monkeypatch, source):
    from modules.autocount.write_back.frame import WriteFrame

    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: source, raising=False)


def _no_puts(h):
    assert [c for c in h.vendor.calls if c.method == "PUT"] == []
    assert h.vendor.writes() == []


@pytest.mark.parametrize("source", ["none", "read_none"])
@pytest.mark.parametrize("op", ["link_row", "unlink_row", "relink_row", "split_link"])
def test_operation_refused_before_any_put_when_the_db_is_unread(h, monkeypatch, source, op):
    world = World(h)
    _patch(monkeypatch, None if source == "none" else _NoRead())
    params = dict(world.params["relink_row" if op == "relink_row" else op if op != "split_link" else "link_row"])
    if op == "split_link":
        params = dict(po_doc_key=7001, po_dtl_key=world.p_free, so_doc_key=7002, so_dtl_key=world.so_a, qty=2)
    res = h.run(op, params)
    assert (res.outcome, res.error_code) == ("refused", UNREAD), (res.outcome, res.error_code)
    assert res.message == UNREAD_TEXT or UNREAD_TEXT in res.message
    _no_puts(h)


def test_hapi_fd_alone_is_not_enough_the_header_must_be_read_from_the_db_too(h, monkeypatch):
    world = World(h)
    for r in h.vendor.rows("PO", 7001):
        r["FurtherDescription"] = FD1  # even when the vendor GET carried FD on every row
    _patch(monkeypatch, None)
    res = h.run("link_row", world.params["link_row"])
    assert (res.outcome, res.error_code) == ("refused", UNREAD)
    _no_puts(h)


def test_primitive_edit_refused_before_any_put_when_the_db_is_unread(h, monkeypatch):
    world = World(h)
    _patch(monkeypatch, None)
    res = h.edit("PO", 7001, line_changes=[{"DtlKey": world.p_free, "Qty": 2}])
    assert (res.outcome, res.error_code) == ("refused", UNREAD), (res.outcome, res.error_code)
    _no_puts(h)


def test_a_refused_unread_link_locks_nothing_and_a_retry_runs(h, monkeypatch):
    world = World(h)
    _patch(monkeypatch, None)
    first = h.run("link_row", world.params["link_row"], key="k-1")
    assert first.error_code == UNREAD
    _patch(monkeypatch, _FakeDbSource())
    again = h.run("link_row", world.params["link_row"], key="k-2")
    assert again.outcome == "done", (again.outcome, again.error_code)
    assert any(c.method == "PUT" for c in h.vendor.writes())
