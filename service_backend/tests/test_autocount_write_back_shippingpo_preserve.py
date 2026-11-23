"""SS-SHIPPINGPO-PRESERVE: SS never turns a PO into an SPO (or back) on an edit.

1. Every PO / SPO edit body SS sends carries ``ShippingPO`` explicitly, copied from the
   document as SS just read it ("F" stays "F", "T" stays "T").
2. A read-back whose ``ShippingPO`` differs from the pre-write value fails the write
   (``SHIPPING_PO_CHANGED``), never a quiet ``done``.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from modules.autocount.write_back import payloads as P
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

FIX = Path(__file__).parent / "fixtures" / "autocount_write_back"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture()
def po():
    doc = _load("po_202602_S0007.json")
    assert doc["ShippingPO"] == "F"
    return doc


@pytest.fixture()
def so():
    return _load("so_SO389293.json")


@pytest.fixture()
def spo():
    doc = _load("spo_db1_sample.json")
    assert doc["ShippingPO"] == "T"
    return doc


def _linked_key(doc):
    return next(r["DtlKey"] for r in doc["Details"] if r.get("FromSODtlKey"))


def _free_keys(doc):
    return [r["DtlKey"] for r in doc["Details"] if not r.get("FromSODtlKey")]


def _line_of(row, **over):
    line = {k: row.get(k) for k in ("ItemCode", "UOM", "Qty", "UnitPrice", "Location", "Description")}
    line.update(over)
    return line


# ---- 1. every edit body carries ShippingPO as read ---------------------------------

def _po_bodies(po, so):
    free, other_free = _free_keys(po)[:2]
    linked = _linked_key(po)
    free_row = next(r for r in po["Details"] if r["DtlKey"] == free)
    so_row = next(r for r in so["Details"] if r["ItemCode"] == free_row["ItemCode"]
                  and r["UOM"] == free_row["UOM"])
    return {
        "build_link": P.build_link(po, free, so, so_row["DtlKey"], Decimal(1)),
        "build_relocate": P.build_relocate(po, linked, "ELSEWHERE"),
        "build_restore_transfer_row": P.build_restore_transfer_row(po, free, {"UnitPrice": 1}),
        "build_unlink_row": P.build_unlink_row(po, linked),
        "build_edit (qty)": P.build_edit("PO", po, {}, [{"DtlKey": free, "Qty": 1}]).body,
        "build_edit (header)": P.build_edit("PO", po, {"Remark1": "x"}, []).body,
        "build_add_line": P.build_add_line("PO", po, _line_of(free_row, Qty=1)).body,
        "build_delete_line": P.build_delete_line("PO", po, free).body,
        "build_row_replace": P.build_row_replace("PO", po, {"DtlKey": free}, _line_of(free_row)).body,
        "build_link_batch": P.build_link_batch("PO", po, free, [
            _line_of(free_row, Qty=1, FromDocType="SO", FromDocNo=so["DocNo"],
                     FromDocDtlKey=so_row["DtlKey"])]).body,
        "build_unlink_merge": P.build_unlink_merge("PO", po, linked, other_free).body,
    }


def test_every_po_edit_body_carries_shipping_po_f_as_read(po, so):
    for name, body in _po_bodies(po, so).items():
        assert body.get("ShippingPO") == "F", f"{name}: {body.get('ShippingPO')!r}"


def test_every_spo_edit_body_carries_shipping_po_t_as_read(spo):
    key = spo["Details"][0]["DtlKey"]
    other = spo["Details"][1]["DtlKey"]
    row = spo["Details"][0]
    bodies = {
        "build_edit": P.build_edit("SPO", spo, {}, [{"DtlKey": key, "Qty": 1}]).body,
        "build_delete_line": P.build_delete_line("SPO", spo, key).body,
        "build_restore_transfer_row": P.build_restore_transfer_row(spo, key, {"UnitPrice": 1}),
        "build_unlink_merge": P.build_unlink_merge("SPO", spo, key, other).body,
        "build_row_replace": P.build_row_replace("SPO", spo, {"DtlKey": key}, _line_of(row)).body,
    }
    for name, body in bodies.items():
        assert body.get("ShippingPO") == "T", f"{name}: {body.get('ShippingPO')!r}"


def test_shipping_po_is_copied_never_invented(po):
    """A read without the field sends none (SS never computes it); QT / SO never carry it."""
    bare = copy.deepcopy(po)
    del bare["ShippingPO"]
    key = _free_keys(bare)[0]
    assert "ShippingPO" not in P.build_edit("PO", bare, {}, [{"DtlKey": key, "Qty": 1}]).body
    assert "ShippingPO" not in P.build_relocate(bare, _linked_key(bare), "ELSEWHERE")
    so_doc = _load("so_SO389293.json")
    so_doc["ShippingPO"] = "T"  # noise on a non-PO kind is never copied
    so_key = so_doc["Details"][0]["DtlKey"]
    assert "ShippingPO" not in P.build_edit("SO", so_doc, {}, [{"DtlKey": so_key, "Qty": 1}]).body


def test_header_of_template_is_unchanged(po):
    """``header_of`` (the runner's create template) keeps its old shape."""
    assert "ShippingPO" not in P.header_of(po)


# ---- 2. the read-back check ---------------------------------------------------------

@pytest.mark.parametrize("before,after,changed", [
    ("F", "F", False), ("T", "T", False), ("F", "T", True), ("T", "F", True),
    ("T", None, True), (None, "T", True), (None, None, False), (None, "F", False),
])
def test_shipping_po_changed(before, after, changed):
    b = {} if before is None else {"ShippingPO": before}
    a = {} if after is None else {"ShippingPO": after}
    assert P.shipping_po_changed(b, a) is changed


# ---- 2b. the legacy link / unlink / relocate path (service.py) -----------------------

def test_service_link_readback_flipped_to_spo_is_not_done(db, session_factory):
    from tests.test_autocount_write_back_service import Harness

    h = Harness(db, session_factory)
    real_apply = h.ac._apply

    def flipping_apply(body):
        assert body.get("ShippingPO") == "F"  # SS sent the value it read
        real_apply(body)
        doc = next(d for d in h.ac.docs["purchaseorderbydocdate"] if d["DocKey"] == body["DocKey"])
        doc["ShippingPO"] = "T"  # AutoCount turned the PO into an SPO

    h.ac._apply = flipping_apply
    res = h.link_split()
    assert res.outcome != "done"
    assert res.error_code == P.SHIPPING_PO_CHANGED
    assert "Shipping Order" in (res.message or "")
    assert h.sink_calls == []


def test_service_split_second_write_flipped_to_spo_is_not_done(db, session_factory):
    """The split's restore PUT is checked too: a flip there is not a quiet ``done``."""
    from tests.test_autocount_write_back_service import Harness

    h = Harness(db, session_factory)
    real_apply = h.ac._apply

    def flip_on_second(body):
        real_apply(body)
        if len(h.ac.put_bodies) == 2:
            doc = next(d for d in h.ac.docs["purchaseorderbydocdate"] if d["DocKey"] == body["DocKey"])
            doc["ShippingPO"] = "T"

    h.ac._apply = flip_on_second
    res = h.link_split()
    assert len(h.ac.put_bodies) == 2 and all(b.get("ShippingPO") == "F" for b in h.ac.put_bodies)
    assert res.outcome == "mismatch"
    assert res.error_code == P.SHIPPING_PO_CHANGED


def test_service_link_sends_shipping_po_and_stays_done(db, session_factory):
    from tests.test_autocount_write_back_service import Harness

    h = Harness(db, session_factory)
    res = h.link_split()
    assert res.outcome == "done", res.error_code
    assert h.ac.put_bodies and all(b.get("ShippingPO") == "F" for b in h.ac.put_bodies)


# ---- 2c. the primitive path every operation runs through (primitives.py) -------------

def test_primitive_edit_readback_flipped_to_spo_is_not_done(db, session_factory, monkeypatch):
    from tests.test_autocount_write_back_primitives import Harness, _line

    h = Harness(db, session_factory, monkeypatch)
    doc = h.seed_doc("PO", 7001, [_line("A", 10, 5.0)], ShippingPO="F")
    key = doc["Details"][0]["DtlKey"]
    real_edit = h.vendor._edit

    def flipping_edit(kind, body):
        assert body.get("ShippingPO") == "F"
        answer = real_edit(kind, body)
        h.vendor.find(kind, body["DocKey"])["ShippingPO"] = "T"
        return answer

    monkeypatch.setattr(h.vendor, "_edit", flipping_edit)
    res = h.edit("PO", 7001, {}, [{"DtlKey": key, "Qty": 8}])
    assert res.outcome == "mismatch"
    assert res.error_code == P.SHIPPING_PO_CHANGED
    assert "Shipping Order" in (res.message or "")
    assert h.action(res).outcome == "mismatch"


def test_primitive_edit_keeps_shipping_po_and_stays_done(db, session_factory, monkeypatch):
    from tests.test_autocount_write_back_primitives import Harness, _line

    h = Harness(db, session_factory, monkeypatch)
    doc = h.seed_doc("PO", 7002, [_line("A", 10, 5.0)], ShippingPO="F")
    res = h.edit("PO", 7002, {}, [{"DtlKey": doc["Details"][0]["DtlKey"], "Qty": 8}])
    assert res.outcome == "done", res.error_code
    assert h.vendor.writes()[0].body["ShippingPO"] == "F"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
