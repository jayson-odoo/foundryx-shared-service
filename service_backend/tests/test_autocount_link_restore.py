"""Plan 65 S1 (RED): AutoCount Link PO restore + Resume repair, AC-65-01..22.

Phase 1 contract under test (plan 65 section 2):

* ``payloads.so_link_note(so, so_row) -> str``, ``payloads.autocount_rtf(text) -> str``,
  ``payloads.link_discount(value) -> str`` (pure);
* snapshot ``links[]`` gains ``soDeliveryDate`` (``YYYY-MM-DD`` | null) and ``note`` (plain text);
* codes ``RESTORE_NOT_LANDED`` (op ``needs_attention``) and ``ROW_NEEDS_ATTENTION`` (refusal);
* skip code ``FOC_ON_ROW``; a link on a PO with different remarks runs as normal (no flag, no remark code).

Everything else is asserted as behaviour (outcome, codes, PUT count, PUT body fields) through
``OperationService`` against ``FakeAutoCountVendor``, with the vendor behaviours db3 proved on 16 Nov
(probe P1/P2, runs FXT-1116A..F) layered on by ``realistic_vendor``:

* PO Remark2..4 are rewritten to Remark1 on every PUT;
* a NEW SO-linked row loses Location / UnitPrice / DeliveryDate (the base fake) AND Discount, and FOCQty is
  never writable (reads 0 on new rows, unchanged on existing ones);
* ``FurtherDescription`` is accepted on a PUT and never returned by a read.

Docstring "control" = the test passes on ddb53cbe by design (it pins behaviour the fix must not lose).
Fixtures are masked: fake customer names, small prices, SO numbers shaped like the incident's.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest

from app.main import app  # noqa: F401 - the gateway rig overrides dependencies on it
from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteAction
from modules.autocount.write_back import payloads
from tests.autocount_write_back_fake_vendor import new_doc
from tests.test_autocount_write_back_call_log import logs
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import DB3, _line
from tests.test_autocount_write_back_review_fixes2 import _clock_jump_after_writes
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

OP = "link_batch"
PUT_PO = "editpurchaseorderbydockey"
PO_KEY, SO_KEY, SO2_KEY = 7101, 7102, 7103
PO_DATE = "2026-11-26T00:00:00"  # the PO rows' delivery date (must NOT end up on a linked row)
SO_DATE = "2026-12-31T00:00:00"  # the SO row's delivery date (must)
SO2_DATE = "2027-01-05T00:00:00"
NO_DATE = "0001-01-01T00:00:00"
NOTE = "**CUSTA SDN BHD/PROJECT X S/O: 428480 DD: 31/12/2026"
RTF_HEAD = r"{\rtf1\ansi\ansicpg1252\deff0\deflang1033{\fonttbl{\f0\fswiss\fcharset0 Arial;}}\viewkind4\uc1\pard\f0\fs20 "
RTF_TAIL = "\\par\r\n}"


def rtf(text: str) -> str:
    """Independent of ``payloads.autocount_rtf``: the D4 wrapper around ALREADY-escaped ``text``."""
    return RTF_HEAD + text + RTF_TAIL


# ============================== the vendor, as db3 behaves (probe P1/P2/P3) ======================

def realistic_vendor(h: OpHarness, *, mirror_remarks: bool = True, drift_description: bool = False) -> None:
    original = h.vendor._edit

    def edit(kind, body):
        doc = h.vendor.find(kind, body.get("DocKey"))
        before_keys = {r["DtlKey"] for r in doc["Details"]}
        focs = {r["DtlKey"]: r.get("FOCQty", 0.0) for r in doc["Details"]}
        resp = original(kind, body)
        if resp.status_code != 200:
            return resp
        doc = h.vendor.find(kind, body.get("DocKey"))
        if mirror_remarks and kind == "PO":
            for n in (2, 3, 4):
                doc[f"Remark{n}"] = doc.get("Remark1", "")
        if drift_description:
            doc["Description"] = "VENDOR REWROTE THIS"
        for row in doc["Details"]:
            if row["DtlKey"] not in before_keys:  # a new row: the link PUT resets Discount, FOCQty reads 0
                if row.get("FromSODtlKey"):
                    row["Discount"] = ""
                row["FOCQty"] = 0.0
            else:  # FOCQty cannot be written through hapi
                row["FOCQty"] = focs.get(row["DtlKey"], 0.0)
            row.pop("FurtherDescription", None)  # accepted on a PUT, never returned by a read
        return resp

    h.vendor._edit = edit


class Rig65:
    """PO 7101 (source row qty 5 / price 2.5 / 5% discount / FOC 1, two free rows qty 3) + SO 7102 (the
    incident's shape: sub-location row with a date, a row without one) + SO 7103 (blank Ref, dated row)."""

    def __init__(self, h: OpHarness, *, src_over: Optional[Dict[str, Any]] = None, remarks=("FXT R1",) * 4,
                 mirror_remarks: bool = True, drift_description: bool = False):
        self.h = h
        h.delete_on()
        realistic_vendor(h, mirror_remarks=mirror_remarks, drift_description=drift_description)
        so = h.seed_doc(
            "SO", SO_KEY,
            [_line("ITEM-A", 10, 5.0, "BRW-AM", DeliveryDate=SO_DATE, FOCQty=0.0),
             _line("ITEM-A", 10, 5.0, "HQ", DeliveryDate=NO_DATE, FOCQty=0.0)],
            doc_no="SO428480", DebtorName="CUSTA SDN BHD", Ref="PROJECT X")
        self.so_dated, self.so_undated = [r["DtlKey"] for r in so["Details"]]
        so2 = h.seed_doc(
            "SO", SO2_KEY, [_line("ITEM-A", 10, 5.0, "HQ", DeliveryDate=SO2_DATE, FOCQty=0.0)],
            doc_no="SO428481", DebtorName="CUSTB SDN BHD", Ref="")
        self.so2_dated = so2["Details"][0]["DtlKey"]
        base = dict(DeliveryDate=PO_DATE, FOCQty=0.0, Discount="", TaxCode="")
        src = dict(base, Discount="5%", FOCQty=1.0)
        src.update(src_over or {})
        po = h.seed_doc(
            "PO", PO_KEY, [_line("ITEM-A", 5, 2.5, "HQ", **src), _line("ITEM-A", 3, 2.5, "HQ", **base),
                           _line("ITEM-A", 3, 2.5, "HQ", **base)],
            doc_no="PO-7101", Description="FXT DESC", Remark1=remarks[0], Remark2=remarks[1],
            Remark3=remarks[2], Remark4=remarks[3])
        self.src, self.free_a, self.free_b = [r["DtlKey"] for r in po["Details"]]

    def params(self, links, dtl_key: Optional[int] = None) -> Dict[str, Any]:
        return dict(doc_key=PO_KEY, dtl_key=dtl_key or self.src, links=[
            dict(so_doc_key=d, so_dtl_key=k, qty=q) for d, k, q in links])

    def one(self, qty=1):
        return [(SO_KEY, self.so_dated, qty)]

    def po_rows(self) -> List[Dict[str, Any]]:
        return self.h.vendor.rows("PO", PO_KEY)

    def row(self, key: int) -> Optional[Dict[str, Any]]:
        return next((r for r in self.po_rows() if r["DtlKey"] == key), None)

    def linked(self, so_dtl: int) -> List[Dict[str, Any]]:
        return [r for r in self.po_rows() if r.get("FromSODtlKey") == so_dtl]

    def new_key(self, so_dtl: int) -> int:
        (row,) = self.linked(so_dtl)
        return row["DtlKey"]

    def header(self) -> Dict[str, Any]:
        return self.h.vendor.find("PO", PO_KEY)


@pytest.fixture
def rig(h):
    return Rig65(h)


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def day(value: Any) -> str:
    return str(value or "")[:10]


def has_day(row: Dict[str, Any]) -> bool:
    """The row carries a real delivery date (the vendor takes nothing below 1753)."""
    return int(day(row.get("DeliveryDate")).split("-")[0] or 0) >= 1753 if row.get("DeliveryDate") else False


def run(h, rig, links=None, key="k-1", **kw):
    return h.run(OP, rig.params(links or rig.one()), key=key, **kw)


def landed_link(h, rig, links=None, dtl_key=None, key="k-landed"):
    """The link PUT landed and the answer was lost: the real way an op is left with the restore not run
    (``pending_verification``, resumable). Same on ddb53cbe and on the fix."""
    h.vendor.apply_then_500_next("PUT", PUT_PO)
    res = h.run(OP, rig.params(links or rig.one(), dtl_key), key=key)
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    return res


def incident_state(h, rig, res, *, old_snapshot: bool = False) -> str:
    """The row exactly as ddb53cbe left the incident: ``needs_attention`` / ``COLLATERAL_CHANGE``, the stored link
    step judged ``mismatch`` with its read-back (the vendor mirrored the remarks)."""
    op = h.operation(res)
    op.status, op.error_code = "needs_attention", "COLLATERAL_CHANGE"
    steps = copy.deepcopy(list(op.steps_json or []))
    steps[0].update(outcome="mismatch", code="COLLATERAL_CHANGE")
    op.steps_json = steps
    action = (h.db.query(AcWriteAction)
              .filter(AcWriteAction.operation_id == op.id, AcWriteAction.step == "link").one())
    action.outcome, action.error_code = "mismatch", "COLLATERAL_CHANGE"
    action.after_json = copy.deepcopy(h.vendor.find("PO", PO_KEY))
    if old_snapshot:
        snap = copy.deepcopy(op.snapshot_json)
        for link in snap["links"]:
            link.pop("soDeliveryDate", None)
            link.pop("note", None)
        op.snapshot_json = snap
    h.db.commit()
    return op.id


def resume(h, res, **kw):
    return h.ops(**kw).resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)


def po_total(rows) -> Decimal:
    total = Decimal(0)
    for r in rows:
        line = Decimal(str(r["Qty"])) * Decimal(str(r["UnitPrice"]))
        for term in str(r.get("Discount") or "").split("+"):
            if term.strip().endswith("%"):
                line *= (Decimal(100) - Decimal(term.strip()[:-1])) / Decimal(100)
        total += line
    return total


# ============================== pure documents for the verify tests ===============================

REMARKS_HAND_SET = dict(Remark1="R1", Remark2="R2", Remark3="R3", Remark4="R4")


def verify_pair(*, remarks_before=None, remarks_after=None):
    """before / after of a link PUT: source row 5 -> 4, one new linked row, nothing else moved."""
    rows = [_line("ITEM-A", 5, 2.5, "HQ"), _line("ITEM-A", 3, 2.5, "HQ")]
    before = new_doc("PO", 8001, "PO-8001", "CRED", copy.deepcopy(rows), Description="FXT DESC",
                     **(remarks_before or REMARKS_HAND_SET))
    after = copy.deepcopy(before)
    after.update(remarks_after or dict(Remark1="R1", Remark2="R1", Remark3="R1", Remark4="R1"))
    after["Details"][0]["Qty"] = 4.0
    after["Details"].append(dict(copy.deepcopy(after["Details"][0]), DtlKey=99, Qty=1.0, FromSODtlKey=555,
                                 Location="HQ", UnitPrice=0.0, DeliveryDate=NO_DATE))
    lines = [dict(FromDocDtlKey=555, Qty=1, ItemCode="ITEM-A", UOM="UNIT")]
    return before, before["Details"][0]["DtlKey"], lines, after


# ================================ AC-65-01 / 02 link verify (D1) ==================================

def test_ac_65_01_the_vendor_remark_mirror_alone_verifies_done():
    before, old_key, lines, after = verify_pair()
    verdict = payloads.verify_link_batch("PO", before, old_key, lines, after)
    assert verdict.outcome == payloads.DONE, (verdict.outcome, verdict.code)


def test_ac_65_02_control_another_header_field_drifting_is_still_collateral_change():
    before, old_key, lines, after = verify_pair()
    after["Description"] = "SOMETHING ELSE"
    verdict = payloads.verify_link_batch("PO", before, old_key, lines, after)
    assert (verdict.outcome, verdict.code) == (payloads.MISMATCH, "COLLATERAL_CHANGE")


def test_ac_65_02_control_a_field_drift_on_another_row_is_still_collateral_change():
    before, old_key, lines, after = verify_pair()
    after["Details"][1]["UnitPrice"] = 9.9  # the other (untouched) PO row
    verdict = payloads.verify_link_batch("PO", before, old_key, lines, after)
    assert (verdict.outcome, verdict.code) == (payloads.MISMATCH, "COLLATERAL_CHANGE")


def test_ac_65_02_control_remarks_drifting_to_a_value_that_is_not_remark1_is_still_collateral_change():
    before, old_key, lines, after = verify_pair(remarks_after=dict(Remark1="R1", Remark2="R1", Remark3="OTHER",
                                                                   Remark4="R1"))
    verdict = payloads.verify_link_batch("PO", before, old_key, lines, after)
    assert (verdict.outcome, verdict.code) == (payloads.MISMATCH, "COLLATERAL_CHANGE")


def test_ac_65_02_control_the_mirror_never_hides_a_real_drift_next_to_it():
    before, old_key, lines, after = verify_pair()
    after["Details"][1]["DeliveryDate"] = "2030-01-01T00:00:00"
    verdict = payloads.verify_link_batch("PO", before, old_key, lines, after)
    assert (verdict.outcome, verdict.code) == (payloads.MISMATCH, "COLLATERAL_CHANGE")


def test_ac_65_02_control_remark1_itself_changing_is_still_collateral_change():
    before, old_key, lines, after = verify_pair()
    after.update(Remark1="CHANGED", Remark2="CHANGED", Remark3="CHANGED", Remark4="CHANGED")
    verdict = payloads.verify_link_batch("PO", before, old_key, lines, after)
    assert (verdict.outcome, verdict.code) == (payloads.MISMATCH, "COLLATERAL_CHANGE")


# ================================ AC-65-03 restore verify (verify_edit) ===========================

def _restore_pair(mirror: bool = True):
    before, _old, _lines, after = verify_pair(remarks_before=REMARKS_HAND_SET)
    before = copy.deepcopy(after)  # the restore's before-read: the link already landed
    if mirror:
        before.update(REMARKS_HAND_SET)  # remarks as the PO held them (nothing wrote since)
    restored = dict(Location="BRW-AM", UnitPrice=2.5, DeliveryDate=SO_DATE, Discount="5%")
    after = copy.deepcopy(before)
    after.update(Remark1="R1", Remark2="R1", Remark3="R1", Remark4="R1")
    after["Details"][2].update(restored)
    return before, dict(DtlKey=99, **restored), after


def test_ac_65_03_the_restore_verify_tolerates_the_remark_mirror():
    before, change, after = _restore_pair()
    assert payloads.verify_edit("PO", before, {}, [change], after) == []


def test_ac_65_03_control_the_restore_verify_still_flags_an_ignored_field():
    before, change, after = _restore_pair(mirror=False)
    after["Details"][2]["UnitPrice"] = 0.0  # the vendor ignored the price
    assert payloads.verify_edit("PO", before, {}, [change], after) == ["Details[99].UnitPrice"]


def test_ac_65_03_control_the_restore_verify_still_flags_other_row_drift_next_to_the_mirror():
    before, change, after = _restore_pair(mirror=False)
    after["Details"][0]["Qty"] = 1.0
    assert "Details[%s].Qty" % before["Details"][0]["DtlKey"] in payloads.verify_edit("PO", before, {}, [change], after)


# ================================ AC-65-07 pure: the note, the RTF, the discount rule ==============

SO_HEAD = {"DocNo": "SO428480", "DebtorName": "CUSTA SDN BHD", "Ref": "PROJECT X"}


def test_ac_65_07_so_link_note_full_shape():
    note = payloads.so_link_note(SO_HEAD, {"DeliveryDate": SO_DATE})
    assert note == NOTE


@pytest.mark.parametrize("ref", ["", "   ", None])
def test_ac_65_07_so_link_note_leaves_out_a_blank_ref(ref):
    so = dict(SO_HEAD, Ref=ref)
    assert payloads.so_link_note(so, {"DeliveryDate": SO_DATE}) == "**CUSTA SDN BHD S/O: 428480 DD: 31/12/2026"


def test_ac_65_07_so_link_note_leaves_out_a_missing_ref_key():
    so = {k: v for k, v in SO_HEAD.items() if k != "Ref"}
    assert payloads.so_link_note(so, {"DeliveryDate": SO_DATE}) == "**CUSTA SDN BHD S/O: 428480 DD: 31/12/2026"


def test_ac_65_07_so_link_note_zero_pads_the_date():
    assert payloads.so_link_note(SO_HEAD, {"DeliveryDate": "2026-01-05T00:00:00"}).endswith(" DD: 05/01/2026")


@pytest.mark.parametrize("row", [{"DeliveryDate": NO_DATE}, {"DeliveryDate": ""}, {"DeliveryDate": None}, {}])
def test_ac_65_07_so_link_note_leaves_out_dd_when_the_so_row_has_no_date(row):
    assert payloads.so_link_note(SO_HEAD, row) == "**CUSTA SDN BHD/PROJECT X S/O: 428480"


def test_ac_65_07_autocount_rtf_is_the_default_wrapper_around_the_text():
    assert payloads.autocount_rtf("**A B S/O: 1") == rtf("**A B S/O: 1")


def test_ac_65_07_autocount_rtf_escapes_backslash_and_braces():
    assert payloads.autocount_rtf("a{b}c\\d") == rtf("a\\{b\\}c\\\\d")


def test_ac_65_07_autocount_rtf_encodes_non_ascii():
    assert payloads.autocount_rtf("caf\u00e9") == rtf("caf\\'e9")  # in cp1252: \'hh
    assert payloads.autocount_rtf("\u4e2d") == rtf("\\u20013?")  # not in cp1252: \uN?


@pytest.mark.parametrize("value,want", [
    ("5%", "5%"), ("5%+2%", "5%+2%"), ("10", ""), ("5%+2", ""), ("10%+5", ""), ("", ""), (None, ""),
])
def test_ac_65_08_link_discount_is_a_percentage_chain_or_blank(value, want):
    assert payloads.link_discount(value) == want


# ================================ AC-65-05 / 06 restore values =====================================

def test_ac_65_05_the_linked_row_reads_back_with_the_so_rows_location_the_po_rows_price_and_the_so_rows_date(h, rig):
    res = run(h, rig)
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    (row,) = rig.linked(rig.so_dated)
    assert row["Location"] == "BRW-AM" and row["UnitPrice"] == 2.5
    assert day(row["DeliveryDate"]) == "2026-12-31", row["DeliveryDate"]  # the SO row's, not the PO row's 2026-11-26


def test_ac_65_06_an_so_row_without_a_date_leaves_the_linked_row_dateless_never_the_po_rows(h, rig):
    res = run(h, rig, [(SO_KEY, rig.so_undated, 1)])
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    sent = puts(h)
    assert len(sent) == 2, [c.body for c in sent]  # the link and the one restore (price still has to go back)
    new_key = rig.new_key(rig.so_undated)
    restore = sent[-1]
    assert [r["DtlKey"] for r in restore.body["Details"]] == [new_key]
    assert not any(has_day(r) for r in restore.body["Details"]), restore.body["Details"]  # sends no date
    assert not has_day(rig.row(new_key)), rig.row(new_key)["DeliveryDate"]


# ================================ AC-65-07 the note on the restore PUT =============================

def test_ac_65_07_the_restore_put_carries_the_rtf_note_on_the_new_row_only(h, rig):
    res = run(h, rig)
    assert res.outcome == "done", (res.outcome, res.error_code)
    sent = puts(h)
    new_key = rig.new_key(rig.so_dated)
    carrying = [(i, r) for i, c in enumerate(sent) for r in c.body["Details"] if "FurtherDescription" in r]
    # plan 66: the new row in the link PUT (DtlKey 0) and the same row in the restore PUT, nothing else
    assert [(i, r.get("DtlKey") or 0) for i, r in carrying] == [(0, 0), (len(sent) - 1, new_key)]
    assert all(r["FurtherDescription"] == rtf(NOTE) for _i, r in carrying)


def test_ac_65_07_blank_ref_and_a_zero_padded_date_in_the_sent_note(h, rig):
    res = run(h, rig, [(SO2_KEY, rig.so2_dated, 1)])
    assert res.outcome == "done", (res.outcome, res.error_code)
    last = puts(h)[-1]
    rows = [r for r in last.body["Details"] if "FurtherDescription" in r]
    assert len(rows) == 1, last.body["Details"]
    row = rows[0]
    assert row["FurtherDescription"] == rtf("**CUSTB SDN BHD S/O: 428481 DD: 05/01/2027")


def test_ac_65_07_an_so_row_without_a_date_sends_the_note_without_dd(h, rig):
    res = run(h, rig, [(SO_KEY, rig.so_undated, 1)])
    assert res.outcome == "done", (res.outcome, res.error_code)
    rows = [r for r in puts(h)[-1].body["Details"] if "FurtherDescription" in r]
    assert len(rows) == 1, puts(h)[-1].body["Details"]
    assert rows[0]["FurtherDescription"] == rtf("**CUSTA SDN BHD/PROJECT X S/O: 428480")


def test_ac_65_07_the_public_edit_door_still_refuses_further_description(h, rig):
    """control: ``FurtherDescription`` joins the whitelist for the restore only, never the edit primitive."""
    res = h.edit("PO", PO_KEY, line_changes=[{"DtlKey": rig.free_a, "FurtherDescription": "x"}])
    assert res.outcome == "refused" and res.error_code == "FIELD_NOT_EDITABLE", (res.outcome, res.error_code)
    assert h.vendor.writes() == []


# ================================ AC-65-08 FOC and discount (D2a) ==================================

def test_ac_65_08_control_a_part_link_puts_foc_zero_on_the_linked_row_and_the_foc_stays_on_the_kept_row(h, rig):
    res = run(h, rig)
    assert res.outcome == "done", (res.outcome, res.error_code)
    kept = rig.row(rig.src)
    assert kept["Qty"] == 4 and kept["FOCQty"] == 1.0
    (linked,) = rig.linked(rig.so_dated)
    assert linked["FOCQty"] == 0
    link_put = puts(h)[0]
    assert [r["FOCQty"] for r in link_put.body["Details"] if r["DtlKey"] == 0] == [0]
    assert [r["FOCQty"] for r in link_put.body["Details"] if r["DtlKey"] == rig.src] == [1.0]


@pytest.mark.parametrize("source,want", [("5%", "5%"), ("5%+2%", "5%+2%"), ("10", ""), ("5%+2", ""), ("", "")])
def test_ac_65_08_discount_is_restored_on_the_linked_row_only_when_it_is_a_percentage(h, source, want):
    """The blank-discount case is a control (nothing to restore); the others are red."""
    rig = Rig65(h, src_over=dict(Discount=source))
    res = run(h, rig)
    assert res.outcome == "done", (res.outcome, res.error_code)
    (linked,) = rig.linked(rig.so_dated)
    assert linked["Discount"] == want
    for call in puts(h):  # an amount discount is never sent on the linked row
        for r in call.body["Details"]:
            if r["DtlKey"] != rig.src:
                assert r.get("Discount", "") in (want, ""), (call.body["Details"], source)
    assert rig.row(rig.src)["Discount"] == source  # the kept row keeps its own


def test_ac_65_08_the_po_total_is_the_same_before_and_after_a_part_link(h, rig):
    before = po_total(rig.po_rows())
    res = run(h, rig)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert po_total(rig.po_rows()) == before


def test_ac_65_08_a_line_taking_the_whole_row_carrying_foc_is_skipped_foc_on_row_with_no_put(h, rig):
    res = run(h, rig, rig.one(5))  # the source row is qty 5 with FOCQty 1
    assert res.outcome == "refused" and res.error_code == "ALL_LINKS_SKIPPED", (res.outcome, res.error_code)
    assert [(s["soDtlKey"], s["code"]) for s in res.batch["skipped"]] == [(rig.so_dated, "FOC_ON_ROW")]
    assert h.vendor.writes() == []
    assert rig.row(rig.src)["Qty"] == 5


def test_ac_65_08_control_a_whole_row_without_foc_is_not_skipped_and_the_row_goes(h, rig):
    res = h.run(OP, rig.params([(SO_KEY, rig.so_dated, 3)], dtl_key=rig.free_a), key="k-whole")
    assert res.outcome == "done", (res.outcome, res.error_code, res.batch and res.batch.get("skipped"))
    assert rig.row(rig.free_a) is None and len(rig.linked(rig.so_dated)) == 1


# ================================ AC-65-08b remarks (owner ruling 16 Nov: no flag, no warning) =====

DIFFER = ("FXT R1", "FXT R2", "FXT R3", "FXT R4")


def test_ac_65_08b_a_link_on_a_po_with_different_remarks_ends_done_with_no_remark_code_and_keeps_the_old_texts(h):
    rig = Rig65(h, remarks=DIFFER)
    res = run(h, rig)
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    assert not [w for w in res.warnings if "REMARK" in w.upper()], res.warnings  # no remark code anywhere
    assert res.error_code is None and len(rig.linked(rig.so_dated)) == 1
    link_action = (h.db.query(AcWriteAction)
                   .filter(AcWriteAction.operation_id == res.operation_id, AcWriteAction.step == "link").one())
    before = link_action.before_json  # the old texts live only in the stored before-read
    assert [before[f"Remark{n}"] for n in (1, 2, 3, 4)] == list(DIFFER)


@pytest.mark.parametrize("remarks", [("X", "", "", ""), ("X", "X", "X", "X"), ("", "", "", "")],
                         ids=["blank-2-4", "equal", "all-blank"])
def test_ac_65_08b_blank_or_equal_remarks_end_done_with_no_remark_code(h, remarks):
    """The ('X', blank...) case is red on ddb53cbe (the mirror writes X into Remark2..4); the rest are control."""
    rig = Rig65(h, remarks=remarks)
    res = run(h, rig)
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    assert not [w for w in res.warnings if "REMARK" in w.upper()], res.warnings
    assert len(rig.linked(rig.so_dated)) == 1


# ================================ AC-65-09 / 10 the restore PUT, the snapshot ======================

def test_ac_65_09_control_the_restore_put_holds_only_the_new_linked_rows_and_echoes_the_header(h, rig):
    links = [(SO_KEY, rig.so_dated, 1), (SO_KEY, rig.so_undated, 1)]
    res = run(h, rig, links)
    assert res.outcome == "done", (res.outcome, res.error_code)
    sent = puts(h)
    assert len(sent) == 2, [c.body for c in sent]  # PUT 1 and ONE restore PUT
    new_keys = sorted(r["DtlKey"] for so in (rig.so_dated, rig.so_undated) for r in rig.linked(so))
    restore = sent[1].body
    assert sorted(r["DtlKey"] for r in restore["Details"]) == new_keys  # no kept row, no other row, nothing deleted
    assert all(r.get("FullTransferOption") != "D" for r in restore["Details"])
    assert restore["Description"] == "FXT DESC" and restore["Remark1"] == "FXT R1"  # the header as read, unchanged


def test_ac_65_10_the_snapshot_stores_per_link_the_so_row_date_and_the_note(h, rig):
    res = run(h, rig, [(SO_KEY, rig.so_dated, 1), (SO_KEY, rig.so_undated, 1)])
    assert res.outcome == "done", (res.outcome, res.error_code)
    links = {l["soDtlKey"]: l for l in h.operation(res).snapshot_json["links"]}
    assert links[rig.so_dated]["soDeliveryDate"] == "2026-12-31"
    assert links[rig.so_dated]["note"] == NOTE
    assert links[rig.so_undated]["soDeliveryDate"] is None  # no date: null, never borrowed
    assert links[rig.so_undated]["note"] == "**CUSTA SDN BHD/PROJECT X S/O: 428480"


# ================================ AC-65-11 / 12 restore verified (D3) ==============================

def test_ac_65_11_a_restore_the_vendor_refused_leaves_the_operation_needs_attention_resumable(h, rig):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "restore refused", after=1)
    res = run(h, rig)
    assert res.outcome == "needs_attention" and res.error_code == "RESTORE_NOT_LANDED", (
        res.outcome, res.error_code, res.warnings)
    assert "LOCATION_NOT_MOVED" not in res.warnings and "ROW_VALUES_NOT_KEPT" not in res.warnings
    assert len(puts(h)) == 2
    again = resume(h, res)  # retried: Resume re-runs only the restore
    assert again.outcome == "done", (again.outcome, again.error_code)
    (row,) = rig.linked(rig.so_dated)
    assert row["Location"] == "BRW-AM" and row["UnitPrice"] == 2.5 and day(row["DeliveryDate"]) == "2026-12-31"
    assert len(puts(h)) == 3  # one more PUT, the restore: the link PUT never re-sent
    assert [r["DtlKey"] for r in puts(h)[2].body["Details"]] == [row["DtlKey"]]


def test_ac_65_11_a_restore_whose_read_back_lacks_a_restored_field_is_not_done(h, rig):
    h.vendor.ignored_fields = {"UnitPrice"}  # the vendor ignores the price on an edit of an existing row
    res = run(h, rig)
    assert res.outcome == "needs_attention" and res.error_code == "RESTORE_NOT_LANDED", (
        res.outcome, res.error_code, res.warnings)
    assert res.warnings == [] or "ROW_VALUES_NOT_KEPT" not in res.warnings


def test_ac_65_12_a_restore_skipped_for_the_deadline_leaves_the_operation_needs_attention(h, rig, monkeypatch):
    _clock_jump_after_writes(h, monkeypatch, 1)  # the deadline passes right after the link PUT's read-back
    res = run(h, rig)
    assert res.outcome == "needs_attention", (res.outcome, res.error_code, res.warnings)
    assert len(puts(h)) == 1  # no restore sent
    assert h.operation(res).status == "needs_attention"


# ================================ AC-65-13 .. 17 Resume repair (D5) ================================

def test_ac_65_13_resume_after_a_landed_link_sends_one_restore_put_on_the_new_row_and_ends_done(h, rig):
    first = landed_link(h, rig)
    incident_state(h, rig, first)
    sent_before = len(puts(h))
    res = resume(h, first)
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    after = puts(h)[sent_before:]
    assert len(after) == 1, [c.body for c in after]  # ONE restore PUT; the link PUT is never re-sent
    new_key = rig.new_key(rig.so_dated)
    assert [r["DtlKey"] for r in after[0].body["Details"]] == [new_key]  # the new row only
    (row,) = rig.linked(rig.so_dated)
    assert (row["Location"], row["UnitPrice"], day(row["DeliveryDate"]), row["Discount"]) == (
        "BRW-AM", 2.5, "2026-12-31", "5%")
    assert after[0].body["Details"][0].get("FurtherDescription") == rtf(NOTE)
    assert h.operation(first).status == "done"


def test_ac_65_14_resume_rejudges_the_stored_link_step_and_real_collateral_drift_stays_needs_attention(h, monkeypatch):
    rig = Rig65(h, drift_description=True)  # the vendor rewrites a header field on every PUT: not the mirror
    first = run(h, rig)
    assert first.outcome == "needs_attention" and first.error_code == "COLLATERAL_CHANGE", (
        first.outcome, first.error_code)
    sent_before = len(h.vendor.writes())
    res = resume(h, first)
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert len(h.vendor.writes()) == sent_before  # no PUT
    assert h.operation(first).status == "needs_attention"


def _resume_stays_needs_attention(h, first):
    sent_before = len(h.vendor.writes())
    res = resume(h, first)
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert len(h.vendor.writes()) == sent_before, [c.body for c in h.vendor.writes()[sent_before:]]  # 0 PUTs


def test_ac_65_15_resume_with_the_kept_row_not_cut_to_the_expected_qty_sends_nothing(h, rig):
    first = landed_link(h, rig)
    incident_state(h, rig, first)
    rig.row(rig.src)["Qty"] = 3.0  # snapshot qty 5 - linked 1 = 4 expected
    _resume_stays_needs_attention(h, first)


def test_ac_65_15_resume_with_the_old_row_still_there_when_all_was_taken_sends_nothing(h, rig):
    first = landed_link(h, rig, [(SO_KEY, rig.so_dated, 3)], dtl_key=rig.free_a, key="k-all")
    assert rig.row(rig.free_a) is None  # the whole row went
    incident_state(h, rig, first)
    old = copy.deepcopy(h.operation(first).snapshot_json["row"])
    rig.po_rows().append(old)  # the old row reappears (someone re-added it)
    _resume_stays_needs_attention(h, first)


def test_ac_65_15_resume_with_two_new_rows_for_one_link_sends_nothing(h, rig):
    first = landed_link(h, rig)
    incident_state(h, rig, first)
    extra = dict(copy.deepcopy(rig.linked(rig.so_dated)[0]), DtlKey=99999)
    rig.po_rows().append(extra)  # a second row linked to the same SO row, same qty
    _resume_stays_needs_attention(h, first)


def test_ac_65_16_resume_of_an_older_snapshot_re_reads_the_so_and_restores_its_date_and_note(h, rig):
    first = landed_link(h, rig)
    incident_state(h, rig, first, old_snapshot=True)  # no soDeliveryDate / note stored
    calls_before = len(h.vendor.calls)
    res = resume(h, first)
    assert res.outcome == "done", (res.outcome, res.error_code, res.warnings)
    so_reads = [c for c in h.vendor.calls[calls_before:] if c.method == "GET" and c.leaf.startswith("salesorder")]
    assert so_reads, [(c.method, c.leaf) for c in h.vendor.calls[calls_before:]]  # re-read through the reader
    (row,) = rig.linked(rig.so_dated)
    assert day(row["DeliveryDate"]) == "2026-12-31"
    assert puts(h)[-1].body["Details"][0].get("FurtherDescription") == rtf(NOTE)


def test_ac_65_17_resume_when_the_row_is_already_restored_still_sends_the_note_in_one_put_and_keeps_the_so_date(h, rig):
    first = landed_link(h, rig)
    incident_state(h, rig, first)
    new = rig.linked(rig.so_dated)[0]
    new.update(Location="BRW-AM", UnitPrice=2.5, DeliveryDate=SO_DATE, Discount="5%")  # a person restored it
    sent_before = len(puts(h))
    res = resume(h, first)
    assert res.outcome == "done", (res.outcome, res.error_code)
    after = puts(h)[sent_before:]
    assert len(after) == 1, [c.body for c in after]
    assert [r["DtlKey"] for r in after[0].body["Details"]] == [new["DtlKey"]]
    assert after[0].body["Details"][0].get("FurtherDescription") == rtf(NOTE)
    assert day(rig.row(new["DtlKey"])["DeliveryDate"]) == "2026-12-31"  # never moved back to the PO row's date


# ================================ AC-65-18 .. 20 unlink while unresolved (D6) ======================

def _aged(h, res) -> None:
    from datetime import datetime, timedelta, timezone

    op = h.operation(res)
    op.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)  # past the busy window
    h.db.commit()


def _guarded_ops(rig, source: bool):
    key = rig.src if source else rig.new_key(rig.so_dated)
    return [
        ("unlink_row", dict(doc_key=PO_KEY, dtl_key=key)),
        ("relink_row", dict(doc_key=PO_KEY, dtl_key=key, so_doc_key=SO_KEY, so_dtl_key=rig.so_undated)),
    ]


@pytest.mark.parametrize("state", ["needs_attention", "pending_aged"])
@pytest.mark.parametrize("source", [True, False], ids=["source-row", "new-linked-row"])
@pytest.mark.parametrize("op_index", [0, 1], ids=["unlink_row", "relink_row"])
def test_ac_65_18_a_row_covered_by_an_unresolved_link_is_refused_row_needs_attention_with_no_put(
        h, rig, state, source, op_index):
    first = landed_link(h, rig)
    if state == "needs_attention":
        incident_state(h, rig, first)
    else:
        _aged(h, first)  # pending_verification, no longer young (a young one holds the document as DOC_BUSY)
    op, params = _guarded_ops(rig, source)[op_index]
    sent_before = len(h.vendor.writes())
    res = h.run(op, params, key="k-guard")
    assert res.outcome == "refused" and res.error_code == "ROW_NEEDS_ATTENTION", (res.outcome, res.error_code)
    assert len(h.vendor.writes()) == sent_before  # reads allowed, no PUT


@pytest.mark.parametrize("source", [True, False], ids=["source-row", "new-linked-row"])
def test_ac_65_18_delete_line_on_a_covered_row_is_refused_row_needs_attention_with_no_put(client, h, db, rig, source):
    """``delete_line`` is NOT an OperationService op: it is the primitive route ``POST /documents/{kind}/{docKey}/
    lines/{dtlKey}/delete`` (``write_v1.delete_document_line``), so it is tested through that route."""
    gw = Gw(h, db)
    first = landed_link(h, rig)
    incident_state(h, rig, first)
    dtl = rig.src if source else rig.new_key(rig.so_dated)
    sent_before = len(h.vendor.writes())
    r = client.post(f"{PREFIX}/documents/purchase-orders/{PO_KEY}/lines/{dtl}/delete", json={"companyCode": "SRT"},
                    headers=gw.hdr("k-del"))
    assert r.status_code in (409, 422), (r.status_code, r.text)
    assert code(r) == "ROW_NEEDS_ATTENTION", r.text
    assert len(h.vendor.writes()) == sent_before


def test_ac_65_19_control_another_row_of_the_po_is_not_refused_and_a_new_link_on_it_still_runs(h, rig):
    first = landed_link(h, rig)
    incident_state(h, rig, first)
    res = h.run(OP, rig.params([(SO_KEY, rig.so_undated, 1)], dtl_key=rig.free_a), key="k-other-link")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(rig.linked(rig.so_undated)) == 1


def test_ac_65_19_control_unlink_of_a_row_the_unresolved_op_does_not_cover_is_not_refused_for_this_reason(h, rig):
    done = run(h, rig, [(SO_KEY, rig.so_undated, 1)], key="k-first")  # a resolved link elsewhere
    assert done.outcome == "done"
    other = rig.new_key(rig.so_undated)
    first = landed_link(h, rig, rig.one(), key="k-unresolved")
    incident_state(h, rig, first)
    res = h.run("unlink_row", dict(doc_key=PO_KEY, dtl_key=other), key="k-unlink-other")
    assert res.error_code != "ROW_NEEDS_ATTENTION", (res.outcome, res.error_code)


def test_ac_65_20_the_refusal_lifts_after_resume_ends_done(h, rig):
    first = landed_link(h, rig)
    incident_state(h, rig, first)
    key = rig.new_key(rig.so_dated)
    refused = h.run("unlink_row", dict(doc_key=PO_KEY, dtl_key=key), key="k-before")
    assert refused.error_code == "ROW_NEEDS_ATTENTION", (refused.outcome, refused.error_code)
    assert resume(h, first).outcome == "done"
    lifted = h.run("unlink_row", dict(doc_key=PO_KEY, dtl_key=key), key="k-after")
    assert lifted.error_code != "ROW_NEEDS_ATTENTION", (lifted.outcome, lifted.error_code)


# ================================ AC-65-21 / 22 logging and books ==================================

def test_ac_65_21_every_get_and_put_of_the_resume_path_is_one_call_log_row_with_the_operation_id(h, rig):
    """control: the call log already covers these paths; pins that the fix keeps one row per call."""
    first = landed_link(h, rig)
    incident_state(h, rig, first)
    calls_before, logged_before = len(h.vendor.calls), len(logs(h))
    res = resume(h, first)
    assert res.outcome == "done", (res.outcome, res.error_code)
    new_calls = h.vendor.calls[calls_before:]
    new_logs = logs(h)[logged_before:]
    assert [(c.method, c.raw_target[len("/api/db3"):]) for c in new_calls] == [(r.method, r.path) for r in new_logs]
    assert new_logs and {r.operation_id for r in new_logs} == {first.operation_id}
    assert [r.method for r in new_logs].count("PUT") == 1  # the one restore PUT


def test_ac_65_21_every_get_and_put_of_the_link_and_restore_path_carries_the_operation_id(h, rig):
    """control: the call log already covers these paths; pins that the fix keeps one row per call."""
    res = run(h, rig)
    assert res.outcome == "done", (res.outcome, res.error_code)
    rows = logs(h)
    assert [(r.method, r.path) for r in rows] == [
        (c.method, c.raw_target[len("/api/db3"):]) for c in h.vendor.calls]  # one row per call
    assert {r.operation_id for r in rows if r.method == "PUT"} == {res.operation_id}
    assert [r.method for r in rows].count("PUT") == 2  # link + one restore
    assert len(puts(h)) == 2


def test_ac_65_22_control_the_restore_suite_refuses_a_non_db3_write_connection_before_any_request(h):
    from modules.autocount.write_back import runner

    other = h._connection("https://ac.example.test/api/db1", DEFAULT_TENANT_ID)
    h.company.write_connection_id = other.id
    h.db.commit()
    with pytest.raises(Exception) as exc:
        runner.run_restore_suite(
            h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, creditor_code="400-N004",
            debtor_code="300-S057", run_tag="T65", **h.factories())
    assert getattr(exc.value, "code", None) == "WRITE_NOT_ALLOWED"
    assert h.vendor.calls == []


def test_ac_65_22_control_the_resume_mode_refuses_a_non_db3_write_connection_before_any_request(h):
    from modules.autocount.write_back import runner

    other = h._connection("https://ac.example.test/api/db1", DEFAULT_TENANT_ID)
    h.company.write_connection_id = other.id
    h.db.commit()
    with pytest.raises(Exception) as exc:
        runner.resume_restore_op(
            h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id="nope", run_tag="T65",
            **h.factories())
    assert getattr(exc.value, "code", None) == "WRITE_NOT_ALLOWED"
    assert h.vendor.calls == []
