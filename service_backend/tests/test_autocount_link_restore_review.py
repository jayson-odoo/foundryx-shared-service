"""Plan 65 round 4 (RED): the reviewer's findings, AC-65-23..27 (plan "Review round 1 rulings" R1-R5).

* AC-65-23 (R1) an unlink merge never picks a row an unresolved link op covers;
* AC-65-24 (R2) ``link_row`` / ``relink_row`` whose restore does not land end ``needs_attention``
  ``RESTORE_NOT_LANDED``; Resume re-runs the restore;
* AC-65-25 (R3) Resume of a ``link_row`` snapshot with no SO values re-reads the SO;
* AC-65-26 (R4) the remark-mirror tolerance is for PO / SPO / QT only, never an SO verify;
* AC-65-27 (R5) the note joins the non-blank DebtorName and Ref by "/", the SO prefix strip ignores case.

Docstring "control" = passes on the code before the round-4 fix by design.
Helpers and the db3-shaped fake vendor come from ``test_autocount_link_restore``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from modules.autocount.models import AcWriteAction  # noqa: F401
from modules.autocount.write_back import payloads
from tests.autocount_write_back_fake_vendor import new_doc
from tests.test_autocount_link_restore import (  # noqa: F401
    NO_DATE, NOTE, PO_DATE, PO_KEY, PUT_PO, SO_DATE, SO_KEY, Rig65, REMARKS_HAND_SET, day, has_day,
    incident_state, landed_link, puts, resume, rtf,
)
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


@pytest.fixture
def rig(h):
    return Rig65(h)


# ================================ AC-65-23 the unlink merge skips a covered row (R1) ================

def _other_linked_row(rig):
    """A second linked row: same item, HQ, price 2.5, no date: exactly what an unlink of it would merge into."""
    row = rig.row(rig.free_a)
    row.update(FromSODtlKey=rig.so_undated, FromDocDtlKey=rig.so_undated, Location="HQ", DeliveryDate=NO_DATE,
               Discount="", FOCQty=0.0)
    return row["DtlKey"]


def test_ac_65_23_an_unlink_does_not_merge_into_the_source_row_of_an_unresolved_link_and_resume_still_repairs(h):
    rig = Rig65(h, src_over=dict(DeliveryDate=NO_DATE))
    first = landed_link(h, rig)  # source row 5 -> 4, one new row linked to the SO row
    incident_state(h, rig, first)
    other = _other_linked_row(rig)
    assert rig.row(rig.src)["Qty"] == 4
    res = h.run("unlink_row", dict(doc_key=PO_KEY, dtl_key=other), key="k-unlink")
    assert rig.row(rig.src)["Qty"] == 4, (res.outcome, res.error_code, res.replaced_lines)  # never grown
    assert all(new != rig.src for _old, new in res.replaced_lines)
    again = resume(h, first)  # Resume still matches the kept row at its expected qty
    assert again.outcome == "done", (again.outcome, again.error_code)


def test_ac_65_23_control_with_no_unresolved_op_the_unlink_still_merges_into_the_matching_free_row(h):
    """control: plan 62 D7 behaviour that the round-4 skip must not remove."""
    rig = Rig65(h, src_over=dict(DeliveryDate=NO_DATE))
    other = _other_linked_row(rig)
    res = h.run("unlink_row", dict(doc_key=PO_KEY, dtl_key=other), key="k-merge")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert rig.row(rig.src)["Qty"] == 8 and rig.row(other) is None  # 5 + 3 merged into the free source row


# ================================ AC-65-24 link_row / relink_row restore not landed (R2) ============

def _whole_link_params(rig, so_dtl):
    rig.row(rig.free_a)["Discount"] = "5%"
    return dict(doc_key=PO_KEY, dtl_key=rig.free_a, so_doc_key=SO_KEY, so_dtl_key=so_dtl)


def _assert_one_restore_resume(h, rig, first, new_key, sent_before):
    res = resume(h, first)
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    after = puts(h)[sent_before:]
    assert len(after) == 1, [c.body for c in after]  # exactly ONE restore PUT, the replace never re-sent
    assert [r["DtlKey"] for r in after[0].body["Details"]] == [new_key]
    final = rig.row(new_key)
    assert (final["Location"], final["UnitPrice"], day(final["DeliveryDate"]), final["Discount"]) == (
        "BRW-AM", 2.5, "2026-12-31", "5%")


def test_ac_65_24_link_row_whose_restore_is_refused_is_needs_attention_and_resume_restores_once(h, rig):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "restore refused", after=1)
    first = h.run("link_row", _whole_link_params(rig, rig.so_dated), key="k-lr")
    assert first.outcome == "needs_attention" and first.error_code == "RESTORE_NOT_LANDED", (
        first.outcome, first.error_code, first.warnings)
    assert "LOCATION_NOT_MOVED" not in first.warnings and "ROW_VALUES_NOT_KEPT" not in first.warnings
    (new,) = rig.linked(rig.so_dated)
    _assert_one_restore_resume(h, rig, first, new["DtlKey"], len(puts(h)))


def test_ac_65_24_relink_row_whose_restore_is_refused_is_needs_attention_and_resume_restores_once(h, rig):
    done = h.run("link_row", _whole_link_params(rig, rig.so_undated), key="k-first")
    assert done.outcome == "done", (done.outcome, done.error_code)
    (old,) = rig.linked(rig.so_undated)
    old.update(UnitPrice=2.5, Discount="5%")
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "restore refused", after=1)
    first = h.run("relink_row", dict(doc_key=PO_KEY, dtl_key=old["DtlKey"], so_doc_key=SO_KEY,
                                     so_dtl_key=rig.so_dated), key="k-rl")
    assert first.outcome == "needs_attention" and first.error_code == "RESTORE_NOT_LANDED", (
        first.outcome, first.error_code, first.warnings)
    (new,) = rig.linked(rig.so_dated)
    _assert_one_restore_resume(h, rig, first, new["DtlKey"], len(puts(h)))


# ================================ AC-65-25 Resume of an old link_row snapshot (R3) ==================

@pytest.mark.parametrize("op", ["link_row", "relink_row"])
def test_ac_65_25_resume_of_a_link_row_snapshot_without_so_values_re_reads_the_so_and_restores_its_date_and_note(h, rig, op):
    if op == "relink_row":
        done = h.run("link_row", _whole_link_params(rig, rig.so_undated), key="k-first")
        assert done.outcome == "done"
        (old,) = rig.linked(rig.so_undated)
        old.update(UnitPrice=2.5, Discount="5%")
        params = dict(doc_key=PO_KEY, dtl_key=old["DtlKey"], so_doc_key=SO_KEY, so_dtl_key=rig.so_dated)
    else:
        params = _whole_link_params(rig, rig.so_dated)
    h.vendor.apply_then_500_next("PUT", PUT_PO)  # the replace landed, the answer was lost
    first = h.run(op, params, key="k-old")
    assert first.outcome == "pending_verification", (first.outcome, first.error_code)
    row = h.operation(first)
    snap = copy.deepcopy(row.snapshot_json)
    snap.pop("soLink", None)  # a ddb53cbe snapshot: no SO values
    row.snapshot_json = snap
    h.db.commit()
    calls_before, sent_before = len(h.vendor.calls), len(puts(h))
    res = resume(h, first)
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    reads = [c for c in h.vendor.calls[calls_before:] if c.method == "GET" and c.leaf.startswith("salesorder")]
    assert reads, [(c.method, c.leaf) for c in h.vendor.calls[calls_before:]]  # the SO re-read, logged
    after = puts(h)[sent_before:]
    assert len(after) == 1, [c.body for c in after]
    sent = after[0].body["Details"][0]
    assert day(sent.get("DeliveryDate")) == "2026-12-31" and sent.get("FurtherDescription") == rtf(NOTE), sent


# ================================ AC-65-26 the mirror tolerance by kind (R4) ========================

def _mirrored_pair(kind: str):
    header = dict(REMARKS_HAND_SET, Description="D")
    extra = {"ShippingPO": "T"} if kind == "SPO" else {}
    doc_kind = {"SPO": "SPO"}.get(kind, kind)
    before = new_doc(doc_kind, 9001, f"{kind}-9001", "P", [_line("ITEM-A", 5, 2.5, "HQ")], **header, **extra)
    after = copy.deepcopy(before)
    after.update(Remark1="R1", Remark2="R1", Remark3="R1", Remark4="R1", Description="E")
    return before, after


def test_ac_65_26_an_so_edit_whose_read_back_mirrors_remark2_to_4_is_still_flagged():
    before, after = _mirrored_pair("SO")
    flagged = payloads.verify_edit("SO", before, {"Description": "E"}, [], after)
    assert {"Remark2", "Remark3", "Remark4"} <= set(flagged), flagged


@pytest.mark.parametrize("kind", ["PO", "SPO", "QT"])
def test_ac_65_26_po_spo_and_qt_tolerate_the_remark_mirror(kind):
    before, after = _mirrored_pair(kind)
    assert payloads.verify_edit(kind, before, {"Description": "E"}, [], after) == []


def test_ac_65_26_control_an_so_edit_with_no_mirror_is_clean():
    """control: strictness for SO must not flag a clean edit."""
    before, after = _mirrored_pair("SO")
    after.update({k: before[k] for k in ("Remark1", "Remark2", "Remark3", "Remark4")})
    assert payloads.verify_edit("SO", before, {"Description": "E"}, [], after) == []


# ================================ AC-65-27 the note: blank DebtorName, SO prefix case (R5) ==========

DATED = {"DeliveryDate": SO_DATE}


@pytest.mark.parametrize("name", ["", "   ", None])
def test_ac_65_27_a_blank_debtor_name_leaves_the_ref_alone_without_a_slash(name):
    so = {"DocNo": "SO428480", "DebtorName": name, "Ref": "PROJECT X"}
    assert payloads.so_link_note(so, DATED) == "**PROJECT X S/O: 428480 DD: 31/12/2026"


@pytest.mark.parametrize("doc_no", ["so123", "So123", "sO123", "SO123"])
def test_ac_65_27_the_so_prefix_strip_ignores_case(doc_no):
    so = {"DocNo": doc_no, "DebtorName": "CUSTA SDN BHD", "Ref": "PROJECT X"}
    assert payloads.so_link_note(so, DATED) == "**CUSTA SDN BHD/PROJECT X S/O: 123 DD: 31/12/2026"


# ================================ AC-65-28 a single whole-row link of a FOC row is refused ==========

def _foc_row(rig, foc: float):
    rig.row(rig.free_a)["FOCQty"] = foc  # the read carries FOCQty (the fake only forbids WRITING it)
    return dict(poDocKey=PO_KEY, poDtlKey=rig.free_a, soDocKey=SO_KEY, soDtlKey=rig.so_dated)


def test_ac_65_28_link_row_of_a_whole_row_carrying_foc_is_refused_foc_on_row_with_no_put(h, rig):
    _foc_row(rig, 1.0)
    res = h.run("link_row", dict(doc_key=PO_KEY, dtl_key=rig.free_a, so_doc_key=SO_KEY, so_dtl_key=rig.so_dated),
                key="k-foc")
    assert res.outcome == "refused" and res.error_code == "FOC_ON_ROW", (res.outcome, res.error_code)
    assert h.vendor.writes() == [] and rig.row(rig.free_a)["Qty"] == 3


def test_ac_65_28_the_po_links_route_refuses_a_whole_row_with_foc_and_sends_no_put(client, h, db, rig):
    gw = Gw(h, db)
    body = dict(_foc_row(rig, 1.0), companyCode="SRT", qty=3)  # the route needs qty; 3 = the whole row
    r = client.post(f"{PREFIX}/po-links", json=body, headers=gw.hdr("k-foc-route"))
    assert r.status_code in (409, 422), (r.status_code, r.text)
    assert code(r) == "FOC_ON_ROW", r.text
    assert h.vendor.writes() == []


def test_ac_65_28_control_the_same_row_without_foc_links_as_today(client, h, db, rig):
    """control: FOCQty 0 on the whole row links through the route as before."""
    gw = Gw(h, db)
    body = dict(_foc_row(rig, 0.0), companyCode="SRT", qty=3)
    r = client.post(f"{PREFIX}/po-links", json=body, headers=gw.hdr("k-nofoc-route"))
    assert r.status_code == 200, (r.status_code, r.text)
    assert len(rig.linked(rig.so_dated)) == 1 and rig.row(rig.free_a) is None


def test_ac_65_28_control_a_part_row_link_of_a_row_with_foc_is_not_refused(client, h, db, rig):
    """control: only a link taking the WHOLE row is refused; a part keeps the FOC on the kept row."""
    gw = Gw(h, db)
    body = dict(_foc_row(rig, 1.0), companyCode="SRT", qty=1)
    r = client.post(f"{PREFIX}/po-links", json=body, headers=gw.hdr("k-part-foc"))
    assert r.status_code == 200, (r.status_code, r.text)
    assert rig.row(rig.free_a)["Qty"] == 2 and rig.row(rig.free_a)["FOCQty"] == 1.0
