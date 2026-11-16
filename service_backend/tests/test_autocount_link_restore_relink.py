"""Plan 65 AC-65-05b (RED): the restore of the new linked row of ``relink_row`` and of a whole-row ``link_row``
uses the same rule as the batch (D2): Location = the SO row's, UnitPrice = the old row's, DeliveryDate = the SO
ROW's date (omitted when it has none), Discount only when a percentage, FurtherDescription = the RTF note on
that row only. Fixtures and the db3-shaped fake vendor come from ``test_autocount_link_restore``.
"""

from __future__ import annotations

import pytest

from tests.test_autocount_link_restore import (  # noqa: F401
    NOTE, PO_KEY, SO_KEY, Rig65, day, has_day, puts, rtf,
)
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


@pytest.fixture
def rig(h):
    return Rig65(h)


def link_row(h, rig, so_dtl, *, key="r-link", discount="5%"):
    """Whole-row link of the free row (qty 3, price 2.5, FOC 0) to an SO row."""
    rig.row(rig.free_a)["Discount"] = discount
    res = h.run("link_row", dict(doc_key=PO_KEY, dtl_key=rig.free_a, so_doc_key=SO_KEY, so_dtl_key=so_dtl), key=key)
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    (old, new), = res.replaced_lines
    return res, new


def restore_put(h, new_key):
    sent = puts(h)
    assert len(sent) == 2, [c.body for c in sent]  # the replace PUT and ONE restore PUT
    details = sent[-1].body["Details"]
    assert [r["DtlKey"] for r in details] == [new_key], details  # the new linked row only
    return details[0]


def test_ac_65_05b_whole_row_link_row_restores_the_so_rows_location_date_note_and_a_percentage_discount(h, rig):
    res, new = link_row(h, rig, rig.so_dated)
    row = restore_put(h, new)
    assert (row["Location"], row["UnitPrice"], day(row["DeliveryDate"]), row["Discount"]) == (
        "BRW-AM", 2.5, "2026-12-31", "5%")
    assert row.get("FurtherDescription") == rtf(NOTE)
    final = rig.row(new)
    assert (final["Location"], final["UnitPrice"], day(final["DeliveryDate"]), final["Discount"]) == (
        "BRW-AM", 2.5, "2026-12-31", "5%")


def test_ac_65_05b_relink_row_restores_the_new_so_rows_values_and_the_note_on_the_new_row_only(h, rig):
    _res, linked = link_row(h, rig, rig.so_undated, key="r-first")  # a linked row to move
    rig.row(linked)["Discount"] = "5%"
    rig.row(linked).update(UnitPrice=2.5)
    h.vendor.calls.clear()
    res = h.run("relink_row", dict(doc_key=PO_KEY, dtl_key=linked, so_doc_key=SO_KEY, so_dtl_key=rig.so_dated),
                key="r-relink")
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    (old, new), = res.replaced_lines
    assert old == linked
    row = restore_put(h, new)
    assert (row["Location"], row["UnitPrice"], day(row["DeliveryDate"]), row["Discount"]) == (
        "BRW-AM", 2.5, "2026-12-31", "5%")
    assert row.get("FurtherDescription") == rtf(NOTE)


@pytest.mark.parametrize("op", ["link_row", "relink_row"])
def test_ac_65_05b_an_so_row_without_a_date_sends_no_delivery_date_and_a_note_without_dd(h, rig, op):
    if op == "link_row":
        _res, new = link_row(h, rig, rig.so_undated)
        row = restore_put(h, new)
    else:
        _res, linked = link_row(h, rig, rig.so_dated, key="r-first")
        rig.row(linked).update(UnitPrice=2.5)
        h.vendor.calls.clear()
        res = h.run("relink_row", dict(doc_key=PO_KEY, dtl_key=linked, so_doc_key=SO_KEY,
                                       so_dtl_key=rig.so_undated), key="r-relink")
        assert res.outcome == "done", (res.outcome, res.error_code)
        (_old, new), = res.replaced_lines
        row = restore_put(h, new)
    assert not has_day(row), row.get("DeliveryDate")  # never the old row's date
    assert not has_day(rig.row(new))
    assert row.get("FurtherDescription") == rtf("**CUSTA SDN BHD/PROJECT X S/O: 428480")


def test_ac_65_05b_an_amount_discount_is_not_copied_to_the_relinked_row(h, rig):
    """control: passes on ddb53cbe (the restore never sends a discount); pins that the fix does not copy an amount."""
    _res, new = link_row(h, rig, rig.so_dated, discount="10")
    row = restore_put(h, new)
    assert row.get("Discount", "") == "" and rig.row(new)["Discount"] == ""
