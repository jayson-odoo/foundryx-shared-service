"""Plan 71 slice 2 (lane SPO-LINK-PO-SS, crew ruling 20 Nov): when ``/po-links/batch`` SPLITS a PO line, the
SPO line that sits on that PO line with the same quantity (put there by ``/spo-links/move``) follows to the NEW
split PO line, in the same operation.

Fixture (fake): PO 7201 row B1 qty 100, nothing linked; SO 7202 row needing 40; SPO 7203 line S1 qty 40 tied
to B1. ``link_batch`` of 40: PUT 1 on the PO (B1 kept at 60, a new row of 40 linked to the SO row), then ONE
PUT on the SPO (S1 ``"D"``, a new line of 40 tied to the NEW PO row). Both PUTs are action rows of the operation.
"""

from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType

import pytest

from modules.autocount.write_back.repository import SpoPoLinkRepository
from tests.test_autocount_write_back_operations import OpHarness, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

OP = "link_batch"
LEAF = "editpurchaseorderbydockey"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def h(db, session_factory, monkeypatch):
    harness = OpHarness(db, session_factory, monkeypatch)
    harness.delete_on()
    return harness


def switch(h, on: bool = True) -> None:
    from modules.autocount.write_back import capabilities

    table = dict(capabilities.VENDOR_CAPABILITIES)
    table["spo_move"] = on
    h.monkeypatch.setattr(capabilities, "VENDOR_CAPABILITIES", MappingProxyType(table), raising=True)


class World:
    def __init__(self, h: OpHarness, *, b_qty=100, spo_qtys=(40,)):
        self.h = h
        base = dict(DeliveryDate="2026-12-01T00:00:00", Description="d")
        self.so = h.seed_doc("SO", 7202, [_line("ITEM-A", 40, 5.0, "HQ"), _line("ITEM-A", 40, 5.0, "HQ")])
        self.so_a, self.so_b = [r["DtlKey"] for r in self.so["Details"]]
        self.po = h.seed_doc("PO", 7201, [_line("ITEM-A", b_qty, 5.0, "BR1", **base)])
        self.b1 = self.po["Details"][0]["DtlKey"]
        self.spo = h.seed_doc("SPO", 7203, [
            _line("ITEM-A", q, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7201", FromDocDtlKey=self.b1)
            for q in spo_qtys])
        self.s_keys = [r["DtlKey"] for r in self.spo["Details"]]
        self.s1 = self.s_keys[0]

    def params(self, qty=40, so_dtl=None):
        return dict(doc_key=7201, dtl_key=self.b1,
                    links=[dict(so_doc_key=7202, so_dtl_key=so_dtl or self.so_a, qty=Decimal(qty))])

    def po_rows(self):
        return self.h.vendor.rows("PO", 7201)

    def spo_rows(self):
        return self.h.vendor.rows("SPO", 7203)

    def new_po_row(self, so_dtl=None):
        return next(r for r in self.po_rows() if r.get("FromSODtlKey") == (so_dtl or self.so_a))


@pytest.fixture
def w(h):
    switch(h)
    return World(h)


def puts(h, doc_key):
    return [c for c in h.vendor.writes() if c.method == "PUT" and (c.body or {}).get("DocKey") == doc_key]


def resume(h, res):
    return h.ops().resume(tenant_id=h.company.tenant_id, company_id=h.company.id, operation_id=res.operation_id)


# ---- the SPO line follows the new split PO line ------------------------------------------------------------

def test_split_moves_the_same_qty_spo_line_onto_the_new_po_line(h, w):
    res = h.run(OP, w.params(40))
    assert res.outcome == "done", (res.error_code, res.message)
    new_po = w.new_po_row()
    assert new_po["Qty"] == 40 and new_po["DtlKey"] != w.b1
    kept = next(r for r in w.po_rows() if r["DtlKey"] == w.b1)
    assert kept["Qty"] == 60
    # ONE PUT on the SPO, after the PO PUT: the old line "D", one new line tied to the NEW PO line
    order = [c.body["DocKey"] for c in h.vendor.writes() if c.method == "PUT"]
    assert order.index(7201) < order.index(7203) and order.count(7203) == 1
    sent = puts(h, 7203)[0].body["Details"]
    assert [r["DtlKey"] for r in sent if r.get("FullTransferOption") == "D"] == [w.s1]
    added = [r for r in sent if r["DtlKey"] == 0]
    assert len(added) == 1 and added[0]["Qty"] == 40 and added[0]["FromDocDtlKey"] == new_po["DtlKey"]
    assert added[0]["FromDocType"] == "PO" and added[0]["FromDocNo"] == "PO-7201"
    # AutoCount: the SPO holds one line of 40, on the new PO line; nothing on B1 any more
    rows = w.spo_rows()
    assert len(rows) == 1 and rows[0]["Qty"] == 40 and rows[0]["FromDocDtlKey"] == new_po["DtlKey"]
    assert res.batch["spoLines"] == [{
        "spoDocKey": 7203, "fromSpoDtlKey": w.s1, "spoDtlKey": rows[0]["DtlKey"],
        "fromPoDtlKey": w.b1, "toPoDtlKey": new_po["DtlKey"], "qty": "40"}]
    assert res.batch["links"][0]["poDtlKey"] == new_po["DtlKey"]


def test_both_puts_are_action_rows_of_the_one_operation(h, w):
    res = h.run(OP, w.params(40))
    assert res.outcome == "done", (res.error_code, res.message)
    actions = h.op_actions(res)
    assert {a.doc_type for a in actions} >= {"PO", "SPO"}
    assert all(a.operation_id == res.operation_id for a in actions)


def test_the_spo_index_follows(h, w):
    assert h.run(OP, w.params(40)).outcome == "done"
    repo = SpoPoLinkRepository(h.db)
    assert repo.linked_qty(h.company.tenant_id, h.company.id, w.b1) == Decimal(0)
    assert repo.linked_qty(h.company.tenant_id, h.company.id, w.new_po_row()["DtlKey"]) == Decimal(40)


def test_another_spo_line_stays_on_the_kept_po_line_when_it_has_room(h):
    switch(h)
    w = World(h, spo_qtys=(40, 50))  # kept PO line = 60 >= 50
    res = h.run(OP, w.params(40))
    assert res.outcome == "done", (res.error_code, res.message)
    stay = next(r for r in w.spo_rows() if r["DtlKey"] == w.s_keys[1])
    assert stay["Qty"] == 50 and stay["FromDocDtlKey"] == w.b1
    assert len(res.batch["spoLines"]) == 1 and res.batch["spoLines"][0]["fromSpoDtlKey"] == w.s1


# ---- refusals: nothing sent, exactly as before ----------------------------------------------------------------

def _refused(h, w, **kw):
    res = h.run(OP, w.params(**kw))
    assert res.outcome == "refused" and res.error_code == "ROW_ON_SPO", (res.outcome, res.error_code, res.message)
    assert h.vendor.writes() == []


def test_switch_off_is_row_on_spo_as_before(h):
    switch(h, False)
    _refused(h, World(h))


def test_no_spo_line_of_that_qty_is_row_on_spo(h, w):
    _refused(h, w, qty=30)


def test_whole_po_line_taken_is_row_on_spo(h):
    switch(h)
    _refused(h, World(h, b_qty=40))


def test_other_spo_lines_the_kept_po_line_cannot_hold_is_row_on_spo(h):
    switch(h)
    _refused(h, World(h, spo_qtys=(40, 70)))  # kept PO line = 60 < 70


# ---- the follow PUT fails: the PO link stands, the SPO line still has a PO line, Resume finishes it --------------

def test_follow_refused_by_autocount_needs_attention_and_resume_finishes_it(h, w):
    h.vendor.refuse_json_next("PUT", LEAF, after=1)  # the PO PUT passes, the SPO PUT is refused
    res = h.run(OP, w.params(40), key="kf1")
    assert res.outcome == "needs_attention" and res.error_code == "SPO_NOT_FOLLOWED", (res.outcome, res.error_code)
    assert res.batch["links"][0]["poDtlKey"] == w.new_po_row()["DtlKey"]  # the PO link landed and is answered
    assert res.batch["spoLines"] == []
    rows = w.spo_rows()  # the SPO line is untouched: still tied to a PO line that exists
    assert len(rows) == 1 and rows[0]["DtlKey"] == w.s1 and rows[0]["FromDocDtlKey"] == w.b1
    po_puts = len(puts(h, 7201))
    done = resume(h, res)
    assert done.outcome == "done", (done.outcome, done.error_code)
    rows = w.spo_rows()
    assert len(rows) == 1 and rows[0]["FromDocDtlKey"] == w.new_po_row()["DtlKey"]
    assert len(done.batch["spoLines"]) == 1
    link_puts = [c for c in puts(h, 7201)[po_puts:] if any(r["DtlKey"] == 0 for r in c.body["Details"])]
    assert link_puts == []  # the link PUT is never sent twice


def test_follow_that_landed_but_timed_out_is_confirmed_by_resume_without_a_second_spo_put(h, w):
    h.vendor.apply_then_500_next("PUT", LEAF, after=1)
    res = h.run(OP, w.params(40), key="kf2")
    if res.outcome == "done":
        pytest.skip("the read-back already confirmed it")
    assert res.outcome == "needs_attention" and res.error_code == "SPO_NOT_FOLLOWED", (res.outcome, res.error_code)
    spo_puts = len(puts(h, 7203))
    done = resume(h, res)
    assert done.outcome == "done", (done.outcome, done.error_code)
    assert len([c for c in puts(h, 7203)[spo_puts:] if any(r["DtlKey"] == 0 for r in c.body["Details"])]) == 0
    assert len(w.spo_rows()) == 1 and w.spo_rows()[0]["FromDocDtlKey"] == w.new_po_row()["DtlKey"]


def test_spo_line_changed_by_hand_before_the_follow_needs_a_person(h, w):
    h.vendor.refuse_json_next("PUT", LEAF, after=1)
    res = h.run(OP, w.params(40), key="kf3")
    assert res.outcome == "needs_attention"
    w.spo_rows()[0]["Qty"] = 39  # edited in AutoCount meanwhile
    spo_puts = len(puts(h, 7203))
    out = resume(h, res)
    assert out.outcome == "needs_attention" and out.error_code == "SPO_NOT_FOLLOWED", (out.outcome, out.error_code)
    assert len(puts(h, 7203)) == spo_puts  # nothing sent on a line that is not as it was
