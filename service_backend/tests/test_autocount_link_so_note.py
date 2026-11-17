"""Plan 66 (RED): every Link PO writes the S/O note on the NEW linked PO row inside the PUT that creates it.

Live evidence (17 Nov, plan 66 section 3): the restore PUT (an edit of an EXISTING row) carried the note and
AutoCount answered 200, kept its DeliveryDate, but stored no FurtherDescription. So the note also goes on the
new row in the link PUT itself (a DtlKey-0 row = an added row, which AutoCount documents FurtherDescription on),
and stays in the restore PUT. Unlink's new plain row never carries a note.

Fixtures and the db3-shaped fake vendor come from ``test_autocount_link_restore`` (``Rig65``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

import pytest

from tests.test_autocount_link_restore import (  # noqa: F401
    NOTE, PO_KEY, SO_KEY, Rig65, puts, rtf,
)
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

NOTE_UNDATED = "**CUSTA SDN BHD/PROJECT X S/O: 428480"


@pytest.fixture
def rig(h):
    return Rig65(h)


def new_rows(body: Dict[str, Any], so_dtl: int) -> List[Dict[str, Any]]:
    """Rows a PUT adds (no DtlKey) linked to ``so_dtl``."""
    return [r for r in body.get("Details") or [] if not r.get("DtlKey") and r.get("FromDocDtlKey") == so_dtl]


def link_put(h, so_dtl: int) -> Dict[str, Any]:
    """The one PUT that created the new row linked to ``so_dtl``, and that row."""
    found = [(c, r) for c in puts(h) for r in new_rows(c.body, so_dtl)]
    assert len(found) == 1, [c.body for c in puts(h)]
    return found[0][1]


def test_ac_66_01_whole_row_link_row_puts_the_note_on_the_new_row_in_the_link_put(h, rig):
    res = h.run("link_row", dict(doc_key=PO_KEY, dtl_key=rig.free_a, so_doc_key=SO_KEY, so_dtl_key=rig.so_dated),
                key="n-link")
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    assert link_put(h, rig.so_dated).get("FurtherDescription") == rtf(NOTE)
    assert puts(h)[-1].body["Details"][0].get("FurtherDescription") == rtf(NOTE)  # the restore keeps it


def test_ac_66_01_an_so_row_without_a_date_puts_the_note_without_dd_in_the_link_put(h, rig):
    res = h.run("link_row", dict(doc_key=PO_KEY, dtl_key=rig.free_a, so_doc_key=SO_KEY,
                                 so_dtl_key=rig.so_undated), key="n-undated")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert link_put(h, rig.so_undated).get("FurtherDescription") == rtf(NOTE_UNDATED)


def test_ac_66_02_relink_row_puts_the_new_so_rows_note_in_the_replace_put(h, rig):
    first = h.run("link_row", dict(doc_key=PO_KEY, dtl_key=rig.free_a, so_doc_key=SO_KEY,
                                   so_dtl_key=rig.so_undated), key="n-first")
    assert first.outcome == "done", (first.outcome, first.error_code)
    (_old, linked), = first.replaced_lines
    h.vendor.calls.clear()
    res = h.run("relink_row", dict(doc_key=PO_KEY, dtl_key=linked, so_doc_key=SO_KEY, so_dtl_key=rig.so_dated),
                key="n-relink")
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    assert link_put(h, rig.so_dated).get("FurtherDescription") == rtf(NOTE)


@pytest.mark.parametrize("qty", [1, 3], ids=["part", "whole"])
def test_ac_66_03_link_batch_puts_the_note_on_each_new_row_in_the_link_put(h, rig, qty):
    res = h.run("link_batch", dict(doc_key=PO_KEY, dtl_key=rig.free_a, links=[
        dict(so_doc_key=SO_KEY, so_dtl_key=rig.so_dated, qty=qty)]), key=f"n-batch-{qty}")
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    assert link_put(h, rig.so_dated).get("FurtherDescription") == rtf(NOTE)


def test_ac_66_04_a_part_row_single_link_puts_the_note_on_the_new_row_in_the_split_put(h, rig):
    res = h.run("split_link", dict(po_doc_key=PO_KEY, po_dtl_key=rig.free_a, so_doc_key=SO_KEY,
                                   so_dtl_key=rig.so_dated, qty=Decimal(1)), key="n-split")
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    assert link_put(h, rig.so_dated).get("FurtherDescription") == rtf(NOTE)


def test_ac_66_05_only_the_new_linked_row_carries_a_note(h, rig):
    """The kept / deleted rows of the link PUT never carry FurtherDescription (it would overwrite their note)."""
    res = h.run("link_batch", dict(doc_key=PO_KEY, dtl_key=rig.src, links=[
        dict(so_doc_key=SO_KEY, so_dtl_key=rig.so_dated, qty=1)]), key="n-only")
    assert res.outcome == "done", (res.outcome, res.error_code)
    for call in puts(h):
        for row in call.body["Details"]:
            if row.get("DtlKey"):
                is_restore_of_new = row["DtlKey"] == rig.new_key(rig.so_dated)
                assert is_restore_of_new or "FurtherDescription" not in row, row


def test_ac_66_06_control_unlink_puts_no_note_on_the_plain_row(h, rig):
    first = h.run("link_row", dict(doc_key=PO_KEY, dtl_key=rig.free_a, so_doc_key=SO_KEY,
                                   so_dtl_key=rig.so_dated), key="n-l")
    assert first.outcome == "done", (first.outcome, first.error_code)
    (_old, linked), = first.replaced_lines
    h.vendor.calls.clear()
    res = h.run("unlink_row", dict(doc_key=PO_KEY, dtl_key=linked), key="n-u")
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    assert puts(h), "unlink sent no PUT"
    assert not any("FurtherDescription" in r for c in puts(h) for r in c.body["Details"])


def test_ac_66_07_control_the_public_add_line_door_still_refuses_or_drops_a_note(h, rig):
    """FurtherDescription is set only by the link flows, never by a caller's line."""
    res = h.service().add_line(**h.args("PO", doc_key=PO_KEY, line=dict(
        ItemCode="ITEM-A", UOM="UNIT", Qty=1, UnitPrice=1.0, Location="HQ", FurtherDescription="x")))
    sent = [r for c in puts(h) for r in c.body["Details"]]
    assert res.outcome == "refused" or not any("FurtherDescription" in r for r in sent), (res.outcome, sent)
