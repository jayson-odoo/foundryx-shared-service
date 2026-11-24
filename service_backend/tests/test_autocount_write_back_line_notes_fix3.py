"""Plan 73 fix round 3 (H1): when the AutoCount DB could not be read, EVERY PO / SPO PUT is refused
(AUTOCOUNT_DB_UNREAD) before it is sent, also a header-only edit, an add line and a delete line; SO / QT are
unaffected."""

from __future__ import annotations

import pytest

from modules.autocount.write_back import payloads as P
from modules.autocount.write_back.frame import WriteFrame
from tests.test_autocount_write_back_operations import World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

UNREAD = "AUTOCOUNT_DB_UNREAD"


class _ReadNone:
    def read(self, kind, doc):
        return None


@pytest.fixture(params=["no_source", "read_none"])
def unread(request, monkeypatch):
    source = None if request.param == "no_source" else _ReadNone()
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: source)


def _no_put(h):
    assert [c for c in h.vendor.calls if c.method == "PUT"] == []


def test_header_only_edit_is_refused_with_zero_puts(h, unread):
    World(h)
    res = h.edit("PO", 7001, header_changes={"Ref": "NEW"})
    assert (res.outcome, res.error_code) == ("refused", UNREAD), (res.outcome, res.error_code)
    _no_put(h)


def test_add_line_is_refused_with_zero_puts(h, unread):
    World(h)
    line = dict(ItemCode="ITEM-A", UOM="UNIT", Qty=1, UnitPrice=1.0, Location="HQ")
    res = h.service().add_line(**h.args("PO", doc_key=7001, line=line))
    assert (res.outcome, res.error_code) == ("refused", UNREAD), (res.outcome, res.error_code)
    _no_put(h)


def test_delete_line_is_refused_with_zero_puts(h, unread):
    w = World(h)
    h.delete_on()
    res = h.service().delete_line(**h.args("PO", doc_key=7001, dtl_key=w.p_free))
    assert (res.outcome, res.error_code) == ("refused", UNREAD), (res.outcome, res.error_code)
    _no_put(h)


def test_spo_header_only_edit_is_refused_too(h, unread):
    World(h)
    res = h.edit("SPO", 7003, header_changes={"Ref": "NEW"})
    assert (res.outcome, res.error_code) == ("refused", UNREAD), (res.outcome, res.error_code)
    _no_put(h)


def test_so_header_only_edit_is_unaffected(h, unread):
    World(h)
    res = h.edit("SO", 7002, header_changes={"Ref": "NEW"})
    assert res.error_code != UNREAD, (res.outcome, res.error_code)


def test_builders_refuse_a_doc_marked_unread_and_never_send_the_marker():
    from tests.test_autocount_write_back_line_notes import _po

    doc = _po()
    doc["_dbUnread"] = True
    with pytest.raises(P.WriteRefusal) as exc:
        P.build_edit("PO", doc, {"Ref": "N"}, [])
    assert exc.value.code == UNREAD
    ok = _po()
    assert "_dbUnread" not in P.build_edit("PO", ok, {"Ref": "N"}, []).body
