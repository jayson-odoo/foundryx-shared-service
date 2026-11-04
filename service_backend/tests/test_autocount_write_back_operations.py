"""Plan 57 S4 (RED): operations, idempotency, recovery, receipts, resume, doc dates.

Contract under test: ``modules.autocount.write_back.operations.OperationService``
(plan 57 sections 5.3 / 5.4) and AC-57-20 on the primitives. Runs against
``FakeAutoCountVendor`` (AC-57-71): link only on new rows, forced HQ on a new row
linked to an SO row, omitted rows kept, delete = the placeholder shape.

Assumptions the coder must follow (see the hand-off note): ``run`` returns
``operation_id, outcome, error_code, warnings, replaced_lines [(old, new)], document``;
``delete_line`` is switched on per kind by the tests; SPO operations also need the
SPO ``add_line`` flag (shipped off), which the tests switch on too.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcStagedRecord, AcWriteAction
from tests.autocount_write_back_fake_vendor import new_doc
from tests.test_autocount_write_back_primitives import Harness, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

KEY_ID = "key-1"
DEL_PO = ("DELETE", "deletepurchaseorderdetailbydtlkey")
PUT_PO = ("PUT", "editpurchaseorderbydockey")
ZERO = lambda kind, doc, row: Decimal(0)  # noqa: E731 - receipt known: nothing received
OPS = ["link_row", "unlink_row", "relink_row", "spo_link_row", "spo_unlink_row", "spo_relink_row"]


def _ops_cls():
    from modules.autocount.write_back.operations import OperationService

    return OperationService


class OpHarness(Harness):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.alerts: List[Any] = []

    def delete_on(self) -> None:
        for kind in ("PO", "SPO"):
            self.flag(kind, "delete_line", True)
        self.flag("SPO", "add_line", True)

    def ops(self, db=None, *, receipt_reader="zero", notifier="collect"):
        kwargs = self.factories()
        if receipt_reader == "zero":
            kwargs["receipt_reader"] = ZERO
        elif receipt_reader != "default":
            kwargs["receipt_reader"] = receipt_reader
        if notifier == "collect":
            kwargs["notifier"] = self.alerts.append
        elif notifier != "default":
            kwargs["notifier"] = notifier
        return _ops_cls()(db or self.db, **kwargs)

    def run(self, op, params, key="idem-1", svc=None, **kw):
        svc = svc or self.ops(**kw)
        return svc.run(tenant_id=DEFAULT_TENANT_ID, company_id=self.company.id, key_id=KEY_ID,
                       idempotency_key=key, op=op, params=params)

    def steps(self):
        return [(c.method, c.leaf) for c in self.vendor.writes()]

    def op_actions(self, res) -> List[AcWriteAction]:
        self.db.expire_all()
        return (self.db.query(AcWriteAction).filter(AcWriteAction.operation_id == res.operation_id)
                .order_by(AcWriteAction.created_at, AcWriteAction.id).all())

    def operation(self, res):
        from modules.autocount.models import AcWriteOperation

        self.db.expire_all()
        return self.db.query(AcWriteOperation).filter(AcWriteOperation.id == res.operation_id).one()


class World:
    """PO 7001 + SO 7002 + SPO 7003, all staged. Params per op in ``params``."""

    def __init__(self, h: OpHarness, *, po_over=None, so_over=None, so_qty=10, received=None, so_loc="HQ"):
        self.h = h
        so_rows = [_line("ITEM-A", so_qty, 5.0, so_loc, **(so_over or {})), _line("ITEM-A", 10, 5.0, so_loc)]
        self.so = h.seed_doc("SO", 7002, so_rows)
        self.so_a, self.so_b = [r["DtlKey"] for r in self.so["Details"]]
        link_a = dict(FromDocType="SO", FromDocNo="SO-7002", FromDocDtlKey=self.so_a, FromSODtlKey=self.so_a)
        base = dict(Discount="5%", TaxCode="SR", DeliveryDate="2026-12-01T00:00:00", Description="d")
        po_rows = [
            _line("ITEM-A", 4, 5.0, "BR1", **base, **(po_over or {})),        # 0 unlinked
            _line("ITEM-A", 4, 5.0, "BR1", **base, **link_a),                  # 1 linked to so_a
            _line("ITEM-A", 4, 5.0, "BR1", **base),                            # 2 target of the SPO row
            _line("ITEM-A", 4, 5.0, "BR1", **base),                            # 3 second PO row for spo_relink
        ]
        self.po = h.seed_doc("PO", 7001, po_rows)
        self.p_free, self.p_linked, self.p_spo, self.p_other = [r["DtlKey"] for r in self.po["Details"]]
        spo_rows = [
            _line("ITEM-A", 4, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7001", FromDocDtlKey=self.p_spo),
            _line("ITEM-A", 4, 5.0, "BR1"),
        ]
        self.spo = h.seed_doc("SPO", 7003, spo_rows)
        self.s_linked, self.s_free = [r["DtlKey"] for r in self.spo["Details"]]
        self.params = {
            "link_row": dict(doc_key=7001, dtl_key=self.p_free, so_doc_key=7002, so_dtl_key=self.so_a),
            "unlink_row": dict(doc_key=7001, dtl_key=self.p_linked),
            "relink_row": dict(doc_key=7001, dtl_key=self.p_linked, so_doc_key=7002, so_dtl_key=self.so_b),
            "spo_link_row": dict(spo_doc_key=7003, spo_dtl_key=self.s_free, po_doc_key=7001, po_dtl_key=self.p_other),
            "spo_unlink_row": dict(spo_doc_key=7003, spo_dtl_key=self.s_linked),
            "spo_relink_row": dict(spo_doc_key=7003, spo_dtl_key=self.s_linked, po_doc_key=7001,
                                   po_dtl_key=self.p_other),
        }

    def po_rows(self):
        return self.h.vendor.rows("PO", 7001)

    def row_by_key(self, rows, key):
        return next((r for r in rows if r["DtlKey"] == key), None)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def h(db, session_factory, monkeypatch):
    return OpHarness(db, session_factory, monkeypatch)


@pytest.fixture
def w(h):
    h.delete_on()
    return World(h)


@pytest.fixture
def w_far(h):
    """SO rows at BRW-AM: neither the PO row's location (BR1) nor the HQ the vendor forces."""
    h.delete_on()
    return World(h, so_loc="BRW-AM")


# ---- AC-57-03 / 32: delete flag off = VENDOR_UNSUPPORTED, zero HTTP ---------------------------

@pytest.mark.parametrize("op", OPS)
def test_ac_57_32_delete_flag_off_refuses_every_operation_without_http(h, op):
    world = World(h)  # delete_line shipped off
    res = h.run(op, world.params[op])
    assert res.outcome == "refused" and res.error_code == "VENDOR_UNSUPPORTED"
    h.no_http()
    assert h.operation(res).status == "refused" and h.operation(res).error_code == "VENDOR_UNSUPPORTED"


# ---- AC-57-30 / 31: happy paths, step order ------------------------------------------------------

def test_ac_57_30_link_row_moves_the_new_row_to_the_so_rows_location(h, w_far):
    w = w_far
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "done", res.error_code
    assert h.steps() == [DEL_PO, PUT_PO, PUT_PO]  # delete, add (vendor forces HQ), move to the SO row's place
    delete, add, move = h.vendor.writes()
    assert delete.body == {"DocKey": 7001, "DtlKey": w.p_free}
    new_row = add.body["Details"][0]
    assert new_row["DtlKey"] == 0 and new_row["FromDocType"] == "SO" and new_row["FromDocDtlKey"] == w.so_a
    for field, value in (("ItemCode", "ITEM-A"), ("UOM", "UNIT"), ("Qty", 4), ("UnitPrice", 5.0),
                         ("Discount", "5%"), ("TaxCode", "SR"), ("Description", "d"),
                         ("DeliveryDate", "2026-12-01T00:00:00")):
        assert new_row[field] == value, field
    (old_key, new_key), = res.replaced_lines
    assert old_key == w.p_free and new_key != old_key
    assert [r["DtlKey"] for r in move.body["Details"]] == [new_key]
    assert move.body["Details"][0]["Location"] == "BRW-AM"
    stored = w.row_by_key(w.po_rows(), new_key)
    assert stored["FromSODtlKey"] == w.so_a and stored["Location"] == "BRW-AM"
    assert res.document and w.row_by_key(res.document["Details"], new_key)["Location"] == "BRW-AM"
    assert w.row_by_key(w.po_rows(), w.p_free) is None
    assert len(w.po_rows()) == 4


def test_ac_57_30_link_row_to_an_so_row_at_hq_skips_the_move(h, w):
    res = h.run("link_row", w.params["link_row"])  # SO row at HQ = where the vendor already puts it
    assert res.outcome == "done", res.error_code
    assert h.steps() == [DEL_PO, PUT_PO]
    (old_key, new_key), = res.replaced_lines
    row = w.row_by_key(w.po_rows(), new_key)
    assert row["FromSODtlKey"] == w.so_a and row["Location"] == "HQ"
    assert w.row_by_key(w.po_rows(), w.p_free) is None


def test_ac_57_30_link_row_location_move_failure_is_done_with_warning(h, w_far):
    w = w_far
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "no move", after=1)
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "done" and "LOCATION_NOT_MOVED" in res.warnings
    (old_key, new_key), = res.replaced_lines
    assert w.row_by_key(w.po_rows(), new_key)["Location"] == "HQ"
    assert h.steps() == [DEL_PO, PUT_PO, PUT_PO]


def test_ac_57_31_unlink_row_delete_then_add_without_link(h, w):
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "done", res.error_code
    assert h.steps() == [DEL_PO, PUT_PO]  # location kept, no move needed
    (old_key, new_key), = res.replaced_lines
    assert old_key == w.p_linked
    row = w.row_by_key(w.po_rows(), new_key)
    assert row["FromSODtlKey"] == 0 and row["FromDocType"] == "" and row["Location"] == "BR1" and row["Qty"] == 4


def test_ac_57_31_relink_row_moves_link_and_row_to_the_new_so_rows_location(h, w_far):
    w = w_far
    res = h.run("relink_row", w.params["relink_row"])
    assert res.outcome == "done", res.error_code
    assert h.steps() == [DEL_PO, PUT_PO, PUT_PO]
    (old_key, new_key), = res.replaced_lines
    row = w.row_by_key(w.po_rows(), new_key)
    assert old_key == w.p_linked and row["FromSODtlKey"] == w.so_b and row["Location"] == "BRW-AM"


def test_ac_57_31_relink_to_an_so_row_at_hq_skips_the_move(h, w):
    res = h.run("relink_row", w.params["relink_row"])
    assert res.outcome == "done", res.error_code
    assert h.steps() == [DEL_PO, PUT_PO]
    (_old, new_key), = res.replaced_lines
    assert w.row_by_key(w.po_rows(), new_key)["Location"] == "HQ"


def test_ac_57_31_spo_link_unlink_relink(h, w):
    spo_rows = lambda: h.vendor.rows("SPO", 7003)  # noqa: E731
    res = h.run("spo_link_row", w.params["spo_link_row"], key="k-link")
    assert res.outcome == "done", res.error_code
    (_old, new_key), = res.replaced_lines
    assert w.row_by_key(spo_rows(), new_key)["FromDocDtlKey"] == w.p_other
    res = h.run("spo_unlink_row", w.params["spo_unlink_row"], key="k-unlink")
    assert res.outcome == "done", res.error_code
    (_old, new_key), = res.replaced_lines
    assert w.row_by_key(spo_rows(), new_key)["FromDocDtlKey"] == 0


def test_ac_57_31_spo_relink_row_alone(h, w):
    res = h.run("spo_relink_row", w.params["spo_relink_row"])
    assert res.outcome == "done", res.error_code
    (old_key, new_key), = res.replaced_lines
    row = w.row_by_key(h.vendor.rows("SPO", 7003), new_key)
    assert old_key == w.s_linked and row["FromDocDtlKey"] == w.p_other


def test_ac_57_30_doc_date_param_for_an_unstaged_document(h, w):
    h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7001").delete()
    h.db.commit()
    res = h.run("link_row", dict(w.params["link_row"], doc_date=date(2026, 11, 4)))
    assert res.outcome == "done", res.error_code


def test_ac_57_30_expected_last_modified_mismatch_is_doc_stale(h, w):
    res = h.run("link_row", dict(w.params["link_row"], expected_last_modified="1999-01-01T00:00:00.00"))
    assert res.outcome == "refused" and res.error_code == "DOC_STALE"
    assert h.vendor.writes() == []


# ---- AC-57-32: guards before any write -------------------------------------------------------------

def _refused(h, w, op, code, **over):
    res = h.run(op, dict(w.params[op], **over))
    assert res.outcome == "refused" and res.error_code == code, (res.outcome, res.error_code)
    assert h.vendor.writes() == []
    return res


def test_ac_57_32_item_mismatch(h):
    h.delete_on()
    w = World(h, so_over={"ItemCode": "ITEM-Z"})
    _refused(h, w, "link_row", "ITEM_MISMATCH")


def test_ac_57_32_uom_mismatch(h):
    h.delete_on()
    w = World(h, so_over={"UOM": "BOX"})
    _refused(h, w, "link_row", "UOM_MISMATCH")


def test_ac_57_32_qty_above_so_outstanding(h):
    h.delete_on()
    w = World(h, so_qty=3)  # PO row qty 4 > 3
    _refused(h, w, "link_row", "QTY_ABOVE_OUTSTANDING")


def test_ac_57_32_qty_above_outstanding_counts_other_linked_po_rows(h, w):
    # so_a has 10, p_linked already covers 4; relink of a 4-qty row to so_a again is NO_CHANGE
    # elsewhere; here a 7-qty free row cannot fit the remaining 6.
    row = w.row_by_key(h.vendor.rows("PO", 7001), w.p_free)
    row["Qty"] = 7
    staged = h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7001").one()
    raw = json.loads(json.dumps(staged.raw_json))
    next(r for r in raw["_lines"] if r["DtlKey"] == w.p_free)["Qty"] = 7
    staged.raw_json = raw
    h.db.commit()
    _refused(h, w, "link_row", "QTY_ABOVE_OUTSTANDING")


@pytest.mark.parametrize("op", ["link_row", "unlink_row", "relink_row"])
def test_ac_57_32_po_row_an_spo_points_at_is_row_on_spo(h, w, op):
    _refused(h, w, op, "ROW_ON_SPO", dtl_key=w.p_spo)


def test_ac_57_32_link_on_linked_row(h, w):
    _refused(h, w, "link_row", "ROW_ALREADY_LINKED", dtl_key=w.p_linked)


def test_ac_57_32_unlink_on_unlinked_row(h, w):
    _refused(h, w, "unlink_row", "ROW_NOT_LINKED", dtl_key=w.p_free)


def test_ac_57_32_relink_to_same_so_row_is_no_change(h, w):
    _refused(h, w, "relink_row", "NO_CHANGE", so_dtl_key=w.so_a)


def test_ac_57_32_unknown_row_is_row_not_found(h, w):
    _refused(h, w, "unlink_row", "ROW_NOT_FOUND", dtl_key=999999)


# ---- AC-57-33: received / delivered lines ----------------------------------------------------------------

def test_ac_57_33_fully_received_row_refused(h, w):
    res = h.run("link_row", w.params["link_row"], receipt_reader=lambda kind, doc, row: Decimal(4))
    assert res.outcome == "refused" and res.error_code == "ROW_RECEIVED"
    assert h.vendor.writes() == []


def test_ac_57_33_partly_received_link_row_edits_to_received_qty_and_adds_remainder_no_delete(h, w_far):
    w = w_far
    res = h.run("link_row", w.params["link_row"],
                receipt_reader=lambda kind, doc, row: Decimal(1) if row["DtlKey"] == w.p_free else Decimal(0))
    assert res.outcome == "done", res.error_code
    assert DEL_PO not in h.steps()
    assert h.steps() == [PUT_PO, PUT_PO, PUT_PO]  # cut, add remainder, move
    cut, add, _move = h.vendor.writes()
    assert cut.body["Details"] == [dict(cut.body["Details"][0], DtlKey=w.p_free, Qty=1)] or (
        cut.body["Details"][0]["DtlKey"] == w.p_free and cut.body["Details"][0]["Qty"] == 1)
    assert add.body["Details"][0]["Qty"] == 3 and add.body["Details"][0]["FromDocDtlKey"] == w.so_a
    original = w.row_by_key(w.po_rows(), w.p_free)
    assert original["Qty"] == 1 and original["FromSODtlKey"] == 0
    linked = [r for r in w.po_rows() if r["FromSODtlKey"] == w.so_a and r["DtlKey"] != w.p_linked]
    assert len(linked) == 1 and linked[0]["Qty"] == 3 and linked[0]["Location"] == "BRW-AM"  # the SO row's place


def test_ac_57_33_partly_received_unlink_keeps_link_on_received_part(h, w):
    res = h.run("unlink_row", w.params["unlink_row"],
                receipt_reader=lambda kind, doc, row: Decimal(1) if row["DtlKey"] == w.p_linked else Decimal(0))
    assert res.outcome == "done", res.error_code
    assert DEL_PO not in h.steps() and h.steps() == [PUT_PO, PUT_PO]
    kept = w.row_by_key(w.po_rows(), w.p_linked)
    assert kept["Qty"] == 1 and kept["FromSODtlKey"] == w.so_a
    remainder = [r for r in w.po_rows() if r["DtlKey"] not in (w.p_linked, w.p_free, w.p_spo, w.p_other)]
    assert len(remainder) == 1 and remainder[0]["Qty"] == 3 and remainder[0]["FromSODtlKey"] == 0


def test_ac_57_33_unknown_received_qty_proceeds_with_warning(h, w_far):
    # owner ruling 4 Nov: the refusal comes from AutoCount, not from us
    w = w_far  # SO at BRW-AM: delete, add, move
    res = h.run("link_row", w.params["link_row"], receipt_reader=lambda kind, doc, row: None)
    assert res.outcome == "done", res.error_code
    assert "TRANSFER_STATE_UNKNOWN" in res.warnings
    assert h.steps() == [DEL_PO, PUT_PO, PUT_PO]


def test_ac_57_33_known_received_qty_has_no_unknown_warning(h, w):
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "done" and "TRANSFER_STATE_UNKNOWN" not in res.warnings


def test_ac_57_33_autocount_refusing_the_delete_is_vendor_refused_and_nothing_else_is_written(h, w):
    h.vendor.mark_received("PO", 7001, w.p_free, "Cannot delete: line already received.")
    res = h.run("link_row", w.params["link_row"], receipt_reader=lambda kind, doc, row: None)
    assert res.outcome == "vendor_error" and res.error_code == "VENDOR_REFUSED"
    assert "Cannot delete: line already received." in (res.message or "")
    assert "ac.example.test" not in (res.message or "") and "api/db3" not in (res.message or "")
    assert h.steps() == [DEL_PO]  # no add, no recovery: the delete did not land
    assert w.row_by_key(w.po_rows(), w.p_free) is not None and len(w.po_rows()) == 4
    assert h.alerts == []
    assert len(h.op_actions(res)) == 1


@pytest.mark.parametrize("op", ["unlink_row", "relink_row"])
def test_ac_57_33_vendor_refused_delete_for_other_po_ops(h, w, op):
    h.vendor.mark_received("PO", 7001, w.p_linked, "line received")
    res = h.run(op, w.params[op], receipt_reader=lambda kind, doc, row: None)
    assert res.outcome == "vendor_error" and res.error_code == "VENDOR_REFUSED"
    assert h.steps() == [DEL_PO]


def test_ac_57_33_switch_off_any_receipt_is_row_received(h, w, monkeypatch):
    from modules.autocount.write_back import capabilities

    monkeypatch.setattr(capabilities, "PARTIAL_RECEIPT_SPLIT", False, raising=True)
    res = h.run("link_row", w.params["link_row"], receipt_reader=lambda kind, doc, row: Decimal(1))
    assert res.outcome == "refused" and res.error_code == "ROW_RECEIVED"
    assert h.vendor.writes() == []
    ok = h.run("link_row", w.params["link_row"], key="idem-2", receipt_reader=ZERO)
    assert ok.outcome == "done", ok.error_code


def test_ac_57_33_default_receipt_reader_uses_transfered_qty_else_unknown(h):
    h.delete_on()
    w = World(h, po_over={"TransferedQty": 0})
    assert h.run("link_row", w.params["link_row"], receipt_reader="default").outcome == "done"
    # a hapi document row without TransferedQty is unknown: proceed, warn (owner ruling 4 Nov)
    row = next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == w.p_linked)
    assert "TransferedQty" not in row
    res = h.run("unlink_row", w.params["unlink_row"], key="idem-2", receipt_reader="default")
    assert res.outcome == "done", res.error_code
    assert "TRANSFER_STATE_UNKNOWN" in res.warnings


def test_ac_57_33_default_receipt_reader_full_receipt(h):
    h.delete_on()
    w = World(h, po_over={"TransferedQty": 4})
    res = h.run("link_row", w.params["link_row"], receipt_reader="default")
    assert res.outcome == "refused" and res.error_code == "ROW_RECEIVED"


# ---- AC-57-34 / 35: recovery, needs_attention -----------------------------------------------------------------

def test_ac_57_34_add_fails_after_delete_original_is_readded_and_outcome_recovered(h, w):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "add failed")
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "recovered"
    failed_step = [a for a in h.op_actions(res) if a.outcome == "vendor_error"]
    assert len(failed_step) == 1 and res.error_code == failed_step[0].error_code and res.error_code
    assert h.steps() == [DEL_PO, PUT_PO, PUT_PO]  # delete, failed add, recovery add (unlinked: no move)
    (old_key, new_key), = res.replaced_lines
    assert old_key == w.p_free
    row = w.row_by_key(w.po_rows(), new_key)
    assert row["Qty"] == 4 and row["ItemCode"] == "ITEM-A" and row["FromSODtlKey"] == 0 and row["Location"] == "BR1"
    assert h.alerts == []


def test_ac_57_34_link_row_recovery_re_adds_at_the_snapshot_location_not_the_so_rows(h, w_far):
    w = w_far
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "add failed")
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "recovered"
    (old_key, new_key), = res.replaced_lines
    row = w.row_by_key(w.po_rows(), new_key)
    assert row["Location"] == "BR1" and row["FromSODtlKey"] == 0  # snapshot place, original (no) link


def test_ac_57_34_recovery_restores_old_link_and_moves_back_to_snapshot_location(h, w):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "add failed")
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "recovered"
    assert h.steps() == [DEL_PO, PUT_PO, PUT_PO, PUT_PO]  # delete, failed add, re-add linked, move
    (old_key, new_key), = res.replaced_lines
    row = w.row_by_key(w.po_rows(), new_key)
    assert row["FromSODtlKey"] == w.so_a and row["Location"] == "BR1"


def test_ac_57_34_add_that_leaves_no_new_row_is_also_recovered(h, w):
    # 200 but the wrapper dropped the row: the read-back shows no new row
    original = h.vendor._edit
    state = {"n": 0}

    def drop_first_add(kind, body):
        state["n"] += 1
        if state["n"] == 1:
            import httpx

            return httpx.Response(200, text="DocNo=PO-7001 ,DocKey=7001 ... Done Edit.")
        return original(kind, body)

    h.vendor._edit = drop_first_add
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "recovered"
    assert len([r for r in w.po_rows() if r["ItemCode"] == "ITEM-A"]) == 4


def test_ac_57_35_recovery_fails_too_needs_attention_snapshot_notifier_no_more_calls(h, w):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "add failed")
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "recovery failed", after=0)
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "needs_attention"
    assert h.steps() == [DEL_PO, PUT_PO, PUT_PO]
    calls_before = len(h.vendor.calls)
    op = h.operation(res)
    assert op.status == "needs_attention"
    snap = json.dumps(op.snapshot_json, default=str)
    assert "ITEM-A" in snap and str(w.so_a) in snap and "BR1" in snap
    assert len(h.alerts) == 1
    event = h.alerts[0]
    blob = json.dumps(event if isinstance(event, dict) else vars(event), default=str)
    for needle in ("AED Co", "PO-7001", "7001", "ITEM-A", "UNIT", "BR1", str(w.so_a)):
        assert needle in blob, needle
    assert len(h.vendor.calls) == calls_before  # nothing automatic afterwards


def test_ac_57_35_default_notifier_writes_one_outbox_row_to_same_tenant_manager(h, w):
    from app.models.email_outbox import EmailOutbox
    from tests.test_s33_integration_alerts import MANAGE, OTHER_TENANT, _only_recipients, _other_tenant, _user

    _only_recipients(h.db)
    _other_tenant(h.db)
    _user(h.db, "mgr@example.com", perms=[MANAGE])
    _user(h.db, "outsider@other.com", perms=[MANAGE], tenant_id=OTHER_TENANT)
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "add failed")
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "recovery failed")
    res = h.run("unlink_row", w.params["unlink_row"], notifier="default")
    assert res.outcome == "needs_attention"
    h.db.expire_all()
    mails = h.db.query(EmailOutbox).all()
    assert [m.to_email for m in mails] == ["mgr@example.com"]
    assert mails[0].tenant_id == DEFAULT_TENANT_ID
    assert "ITEM-A" in mails[0].html_body + mails[0].text_body


# ---- AC-57-36: resume ----------------------------------------------------------------------------------------------

def _resume(h, res, **kw):
    return h.ops(**kw).resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)


def test_ac_57_36_resume_with_snapshot_row_still_present_makes_no_write(h, w):
    h.vendor.timeout_next("DELETE", "deletepurchaseorderdetailbydtlkey")
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "pending_verification"
    assert w.row_by_key(w.po_rows(), w.p_free) is not None  # the delete never landed
    writes_before = len(h.vendor.writes())
    out = _resume(h, res)
    assert out.outcome not in ("needs_attention", "pending_verification")
    assert len(h.vendor.writes()) == writes_before


def test_ac_57_36_resume_when_row_absent_recreates_from_snapshot(h, w):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")  # delete landed, add timed out
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "pending_verification"
    assert w.row_by_key(w.po_rows(), w.p_linked) is None
    writes_before = len(h.vendor.writes())
    out = _resume(h, res)
    assert out.outcome in ("done", "recovered")
    assert len(h.vendor.writes()) > writes_before
    matching = [r for r in w.po_rows() if r["ItemCode"] == "ITEM-A" and r["Qty"] == 4 and r["Location"] == "BR1"]
    assert len(matching) == 4  # every original row exists exactly once again


def test_ac_57_36_resume_after_needs_attention_recreates_once(h, w):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "add failed")
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "recovery failed")
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "needs_attention"
    out = _resume(h, res)
    assert out.outcome in ("done", "recovered")
    assert len([r for r in w.po_rows() if r["ItemCode"] == "ITEM-A"]) == 4
    again_writes = len(h.vendor.writes())
    _resume(h, res)
    assert len(h.vendor.writes()) == again_writes  # now present: resolved without a write


def test_ac_57_36_resume_is_tenant_scoped(h, w):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    res = h.run("unlink_row", w.params["unlink_row"])
    with pytest.raises(Exception):
        h.ops().resume(tenant_id="other-tenant-id", company_id=h.company.id, operation_id=res.operation_id)
    with pytest.raises(Exception):
        h.ops().get(tenant_id="other-tenant-id", company_id=h.company.id, operation_id=res.operation_id)
    assert h.ops().get(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                       operation_id=res.operation_id).operation_id == res.operation_id


# ---- AC-57-05 / 38: timeout mid-op, busy across steps --------------------------------------------------------------

def test_ac_57_05_timeout_mid_operation_is_pending_verification_and_not_retried(h, w):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "pending_verification"
    assert h.steps() == [DEL_PO, PUT_PO]
    assert h.operation(res).status == "pending_verification"
    assert h.alerts == []


def test_ac_57_38_document_stays_busy_across_all_steps(h, w):
    seen: Dict[str, Any] = {}
    original = h.vendor._delete_line

    def during(kind, body):
        db2 = h.session_factory()
        try:
            svc2 = h.ops(db=db2)
            other = svc2.run(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=KEY_ID,
                             idempotency_key="other-key", op="unlink_row", params=w.params["unlink_row"])
            seen["res"] = (other.outcome, other.error_code)
            same = svc2.run(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=KEY_ID,
                            idempotency_key="idem-1", op="link_row", params=w.params["link_row"])
            seen["same"] = (same.outcome, same.error_code)
        finally:
            db2.close()
        return original(kind, body)

    h.vendor._delete_line = during
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "done"
    assert seen["res"] == ("refused", "DOC_BUSY")
    assert seen["same"][1] == "OPERATION_IN_PROGRESS"


def test_ac_57_38_busy_lock_is_released_after_the_operation(h, w):
    assert h.run("link_row", w.params["link_row"]).outcome == "done"
    res = h.run("unlink_row", dict(dtl_key=h.vendor.rows("PO", 7001)[-1]["DtlKey"], doc_key=7001), key="idem-2")
    assert res.error_code != "DOC_BUSY"


# ---- AC-57-37: idempotency -------------------------------------------------------------------------------------------

def test_ac_57_37_same_key_same_params_returns_stored_answer_without_http(h, w):
    first = h.run("link_row", w.params["link_row"])
    assert first.outcome == "done"
    calls = len(h.vendor.calls)
    second = h.run("link_row", w.params["link_row"])
    assert len(h.vendor.calls) == calls
    assert second.operation_id == first.operation_id and second.outcome == "done"
    assert second.replaced_lines == first.replaced_lines


def test_ac_57_37_same_key_other_params_is_idempotency_conflict(h, w):
    h.run("link_row", w.params["link_row"])
    calls = len(h.vendor.calls)
    other = h.run("link_row", dict(w.params["link_row"], so_dtl_key=w.so_b))
    assert other.outcome == "refused" and other.error_code == "IDEMPOTENCY_CONFLICT"
    assert len(h.vendor.calls) == calls


def test_ac_57_37_same_key_other_op_is_idempotency_conflict(h, w):
    h.run("link_row", w.params["link_row"])
    other = h.run("unlink_row", w.params["unlink_row"])
    assert other.error_code == "IDEMPOTENCY_CONFLICT"


def test_ac_57_37_a_refused_answer_is_stored_too(h, w):
    first = h.run("link_row", w.params["link_row"], receipt_reader=lambda kind, doc, row: Decimal(4))
    assert first.error_code == "ROW_RECEIVED"
    calls = len(h.vendor.calls)
    again = h.run("link_row", w.params["link_row"])  # reader now fine, same key: stored answer
    assert again.error_code == "ROW_RECEIVED" and len(h.vendor.calls) == calls


def test_ac_57_37_key_scope_is_per_api_key_and_company(h, w):
    first = h.run("link_row", w.params["link_row"])
    svc = h.ops()
    other_key = svc.run(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id="key-2",
                        idempotency_key="idem-1", op="unlink_row", params=w.params["unlink_row"])
    assert other_key.operation_id != first.operation_id and other_key.error_code != "IDEMPOTENCY_CONFLICT"


# ---- AC-57-40: plan 55 split link keeps behaviour and takes a key ----------------------------------------------------------

def _split(w, qty=4):
    return dict(po_doc_key=7001, po_dtl_key=w.p_free, so_doc_key=7002, so_dtl_key=w.so_a, qty=Decimal(qty))


def test_ac_57_40_split_link_keeps_plan_55_behaviour_and_is_idempotent(h, w):
    first = h.run("split_link", _split(w, 2))
    assert first.outcome == "done", first.error_code
    assert DEL_PO not in h.steps() and PUT_PO in h.steps()
    calls = len(h.vendor.calls)
    again = h.run("split_link", _split(w, 2))
    assert again.operation_id == first.operation_id and len(h.vendor.calls) == calls
    clash = h.run("split_link", _split(w, 3))
    assert clash.error_code == "IDEMPOTENCY_CONFLICT"


# ---- recording --------------------------------------------------------------------------------------------------------------

def test_ac_57_19_every_vendor_write_of_an_operation_is_an_action_row_with_operation_and_step(h, w_far):
    w = w_far
    res = h.run("link_row", w.params["link_row"])
    actions = h.op_actions(res)
    assert len(actions) == len(h.vendor.writes()) == 3
    assert all(a.operation_id == res.operation_id and a.step for a in actions)
    assert [(a.request_method, a.request_path) for a in actions] == [
        ("DELETE", "/DeletePurchaseOrderDetailbydtlkey"),
        ("PUT", "/EditPurchaseOrderbydockey"), ("PUT", "/EditPurchaseOrderbydockey")]
    blob = json.dumps([[a.request_json, a.response_json, a.before_json, a.after_json, a.request_path]
                       for a in actions], default=str)
    assert "ac.example.test" not in blob and "api/db3" not in blob
    op = h.operation(res)
    assert op.op == "link_row" and op.doc_type == "PO" and op.doc_key == 7001 and op.dtl_key == w.p_free
    assert op.status == "done" and op.steps_json and op.result_json
    assert "ITEM-A" in json.dumps(op.snapshot_json, default=str)


def test_ac_57_19_recovery_steps_are_recorded_too(h, w):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "add failed")
    res = h.run("link_row", w.params["link_row"])
    assert len(h.op_actions(res)) == len(h.vendor.writes())


# ---- AC-57-20: doc date resolution on the primitives -----------------------------------------------------------------------

def _unstaged_so(h):
    doc = h.seed_doc("SO", 9001, [_line("A", 5, 5.0)], stage=False)
    return doc, doc["Details"][0]["DtlKey"]


def _prim(h, prim, dtl, **kw):
    svc = h.service()
    common = h.args("SO", doc_key=9001, **kw)
    if prim == "edit":
        return svc.edit_doc(**common, header_changes={"Remark1": "x"}, line_changes=[])
    if prim == "add":
        return svc.add_line(**common, line=_line("C", 1, 1.0))
    if prim == "delete":
        return svc.delete_line(**common, dtl_key=dtl)
    return svc.cancel_doc(**common)


@pytest.mark.parametrize("prim", ["edit", "add", "delete", "cancel"])
def test_ac_57_20_no_date_anywhere_is_doc_date_required_before_any_http(h, prim):
    for p in ("delete_line", "cancel_doc"):
        h.flag("SO", p, True)
    _doc, dtl = _unstaged_so(h)
    res = _prim(h, prim, dtl)
    assert res.outcome == "refused" and res.error_code == "DOC_DATE_REQUIRED"
    h.no_http()


@pytest.mark.parametrize("prim", ["edit", "add"])
def test_ac_57_20_callers_doc_date_is_used(h, prim):
    _doc, dtl = _unstaged_so(h)
    res = _prim(h, prim, dtl, doc_date=date(2026, 11, 4))
    assert res.outcome == "done", res.error_code
    assert h.vendor.gets()[0].query["DocDate"] == "20261104"


def test_ac_57_20_wrong_date_misses_the_dockey_is_doc_not_found(h):
    _unstaged_so(h)
    res = _prim(h, "edit", 0, doc_date=date(2026, 11, 5))
    assert res.outcome == "refused" and res.error_code == "DOC_NOT_FOUND"
    assert h.vendor.writes() == []


def test_ac_57_20_staged_date_beats_the_action_log_and_callers_date_beats_staged(h):
    doc = h.seed_doc("SO", 9002, [_line("A", 5, 5.0)])
    staged = h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:9002").one()
    raw = json.loads(json.dumps(staged.raw_json))
    raw["DocDate"] = "2026-11-01T00:00:00"
    staged.raw_json = raw
    h.db.commit()
    svc = h.service()
    miss = svc.edit_doc(**h.args("SO", doc_key=9002, header_changes={"Remark1": "x"}, line_changes=[]))
    assert miss.outcome == "refused" and miss.error_code == "DOC_NOT_FOUND"
    assert h.vendor.gets()[0].query["DocDate"] == "20261101"
    ok = svc.edit_doc(**h.args("SO", doc_key=9002, header_changes={"Remark1": "x"}, line_changes=[],
                               doc_date=date(2026, 11, 4)))
    assert ok.outcome == "done", ok.error_code


def test_ac_57_20_date_of_our_last_confirmed_read_back_is_used(h):
    created = h.create("QT")
    assert created.outcome == "done"
    h.vendor.calls.clear()
    res = h.service().add_line(**h.args("QT", doc_key=created.doc_key, line=_line("Z", 1, 2.0)))
    assert res.outcome == "done", res.error_code
    assert h.vendor.gets()[0].query["DocDate"] == "20261104"


def test_ac_57_20_a_failed_create_does_not_supply_a_date(h):
    h.vendor.drop_rows_next_create()
    bad = h.create("QT")  # mismatch: not a confirmed read-back
    assert bad.outcome == "mismatch"
    h.vendor.calls.clear()
    res = h.service().add_line(**h.args("QT", doc_key=bad.doc_key, line=_line("Z", 1, 2.0)))
    assert res.outcome == "refused" and res.error_code == "DOC_DATE_REQUIRED"
    h.no_http()


# ---- SPO target outstanding (AC-57-32 extended to SPO ops) ----------------------------------------------------

def _spo_qty(h, w, dtl_key, qty):
    import copy as _copy

    next(r for r in h.vendor.rows("SPO", 7003) if r["DtlKey"] == dtl_key)["Qty"] = qty
    row = h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7003").one()
    raw = _copy.deepcopy(row.raw_json)
    next(r for r in raw["_lines"] if r["DtlKey"] == dtl_key)["Qty"] = qty
    row.raw_json = raw
    h.db.commit()


def _extra_spo_row(h, w, po_dtl, qty):
    """Another SPO row (staged too) that already takes ``qty`` from PO row ``po_dtl``."""
    import copy as _copy

    doc = h.vendor.find("SPO", 7003)
    key = 700399
    doc["Details"].append(dict(doc["Details"][0], DtlKey=key, Qty=qty, FromDocDtlKey=po_dtl, FromDocType="PO"))
    row = h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7003").one()
    raw = _copy.deepcopy(row.raw_json)
    raw["_lines"].append(dict(raw["_lines"][0], DtlKey=key, Qty=qty, FromDocDtlKey=po_dtl, FromDocType="PO"))
    row.raw_json = raw
    h.db.commit()
    return key


@pytest.mark.parametrize("op", ["spo_link_row", "spo_relink_row"])
def test_ac_57_32_spo_row_above_the_target_po_rows_qty_is_qty_above_outstanding(h, w, op):
    dtl = w.params[op]["spo_dtl_key"]
    _spo_qty(h, w, dtl, 5)  # the target PO row p_other has qty 4
    _refused(h, w, op, "QTY_ABOVE_OUTSTANDING")


@pytest.mark.parametrize("op", ["spo_link_row", "spo_relink_row"])
def test_ac_57_32_other_spo_rows_already_taking_from_the_target_count(h, w, op):
    _extra_spo_row(h, w, w.p_other, 3)  # leaves 1 of 4
    dtl = w.params[op]["spo_dtl_key"]
    _spo_qty(h, w, dtl, 2)
    _refused(h, w, op, "QTY_ABOVE_OUTSTANDING")
    _spo_qty(h, w, dtl, 1)
    ok = h.run(op, w.params[op], key="idem-2")
    assert ok.outcome == "done", ok.error_code


def test_ac_57_32_the_row_being_moved_is_excluded_from_what_the_target_already_takes(h, w):
    # s_linked (qty 4) points at p_spo (qty 4): relinking it AWAY and back must pass, because
    # its own qty is not counted against the target it is about to join
    first = h.run("spo_relink_row", w.params["spo_relink_row"], key="away")
    assert first.outcome == "done", first.error_code
    (_old, moved), = first.replaced_lines
    back = h.run("spo_relink_row", dict(spo_doc_key=7003, spo_dtl_key=moved, po_doc_key=7001,
                                         po_dtl_key=w.p_spo), key="back")
    assert back.outcome == "done", back.error_code


def test_ac_57_32_relink_within_capacity_passes_when_the_target_is_partly_taken(h, w):
    _extra_spo_row(h, w, w.p_other, 1)  # 3 of 4 left
    _spo_qty(h, w, w.s_linked, 3)
    ok = h.run("spo_relink_row", w.params["spo_relink_row"])
    assert ok.outcome == "done", ok.error_code
