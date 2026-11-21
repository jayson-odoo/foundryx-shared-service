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
    h.vendor.refuse_json_next("PUT", LEAF, after=2)  # the PO link + restore PUTs pass, the SPO PUT is refused
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
    h.vendor.apply_then_500_next("PUT", LEAF, after=2)
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
    h.vendor.refuse_json_next("PUT", LEAF, after=2)
    res = h.run(OP, w.params(40), key="kf3")
    assert res.outcome == "needs_attention"
    w.spo_rows()[0]["Qty"] = 39  # edited in AutoCount meanwhile
    spo_puts = len(puts(h, 7203))
    out = resume(h, res)
    assert out.outcome == "needs_attention" and out.error_code == "SPO_NOT_FOLLOWED", (out.outcome, out.error_code)
    assert len(puts(h, 7203)) == spo_puts  # nothing sent on a line that is not as it was


# ---- the route: POST /api/v1/autocount/po-links/batch answers the SPO lines that followed ------------------------

BATCH = "/api/v1/autocount/po-links/batch"


@pytest.fixture
def gw(h, db):
    from tests.test_autocount_write_back_gateway_qtso import Gw

    switch(h)
    return Gw(h, db)


def body(w, qty=40):
    return {"companyCode": "SRT", "poDocKey": 7201, "poDtlKey": w.b1,
            "links": [{"soDocKey": 7202, "soDtlKey": w.so_a, "qty": qty}]}


def test_route_answers_the_spo_lines_that_followed(client, gw):
    w = World(gw.h)
    r = client.post(BATCH, json=body(w), headers=gw.hdr())
    assert r.status_code == 200, r.text
    got = r.json()
    new_po = got["links"][0]["poDtlKey"]
    assert got["outcome"] == "done" and len(got["spoLines"]) == 1
    line = got["spoLines"][0]
    assert line["spoDocKey"] == 7203 and line["fromSpoDtlKey"] == w.s1 and line["toPoDtlKey"] == new_po
    assert line["fromPoDtlKey"] == w.b1 and line["qty"] == "40" and line["spoDtlKey"] != w.s1


def test_route_refusal_carries_an_empty_spo_lines(client, gw):
    w = World(gw.h)
    r = client.post(BATCH, json=body(w, qty=30), headers=gw.hdr())
    assert r.status_code == 409, r.text
    assert r.json()["errorCode"] == "ROW_ON_SPO" and r.json()["spoLines"] == []


# ---- review round 1 -------------------------------------------------------------------------------------------

def test_review_a_second_split_cannot_take_the_spo_line_an_unfinished_one_planned(h, w):
    h.vendor.refuse_json_next("PUT", LEAF, after=2)
    first = h.run(OP, w.params(40), key="r1a")
    assert first.error_code == "SPO_NOT_FOLLOWED", (first.outcome, first.error_code)
    writes = len(h.vendor.writes())
    second = h.run(OP, w.params(40, so_dtl=w.so_b), key="r1b")
    assert second.outcome == "refused" and second.error_code == "ROW_NEEDS_ATTENTION", (second.outcome, second.error_code)
    assert len(h.vendor.writes()) == writes  # nothing sent
    done = resume(h, first)  # the first one still finishes, onto ITS new PO line
    assert done.outcome == "done", (done.outcome, done.error_code)
    assert w.spo_rows()[0]["FromDocDtlKey"] == w.new_po_row()["DtlKey"]
    again = h.run(OP, w.params(20, so_dtl=w.so_b), key="r1c")  # resolved: the kept line is free again
    assert again.outcome == "done", (again.outcome, again.error_code)


def test_review_past_the_deadline_no_spo_put_is_sent_and_resume_finishes(h, w, monkeypatch):
    from modules.autocount.write_back import operations

    real = operations.OperationService._batch_done

    def late(self, *a, **kw):
        self._op_deadline = 0.0  # the budget ran out after the link PUT landed
        return real(self, *a, **kw)

    monkeypatch.setattr(operations.OperationService, "_batch_done", late)
    res = h.run(OP, w.params(40), key="r2")
    assert res.outcome == "needs_attention" and res.error_code == "SPO_NOT_FOLLOWED", (res.outcome, res.error_code)
    assert puts(h, 7203) == []
    monkeypatch.setattr(operations.OperationService, "_batch_done", real)
    done = resume(h, res)
    assert done.outcome == "done", (done.outcome, done.error_code)
    assert len(done.batch["spoLines"]) == 1


def test_review_doc_batch_keeps_row_on_spo_with_the_switch_on(h, w):
    res = h.run("link_doc_batch", dict(doc_key=7201, links=[
        dict(po_dtl_key=w.b1, so_doc_key=7202, so_dtl_key=w.so_a, qty=Decimal(40))]), key="r3")
    assert res.outcome == "refused", (res.outcome, res.error_code)
    assert res.batch["lines"][0]["code"] == "ROW_ON_SPO" and h.vendor.writes() == []


def test_review_a_received_spo_line_does_not_follow(h, w):
    def received(kind, doc, row):
        return Decimal(5) if kind == "SPO" else Decimal(0)

    res = h.run(OP, w.params(40), key="r4", receipt_reader=received)
    assert res.outcome == "refused" and res.error_code == "ROW_ON_SPO", (res.outcome, res.error_code)
    assert h.vendor.writes() == []


# ---- review round 2 (second reviewer + security review, 21 Nov) --------------------------------------------------

def live_book(h) -> None:
    """Production: a writable live book skips the test-company check, and the sync job owns the staged copies."""
    from modules.autocount.write_back import guard

    h.monkeypatch.setattr(guard, "assert_test_company", lambda *a, **kw: None)


def index_qty(h, po_dtl_key):
    return SpoPoLinkRepository(h.db).linked_qty(h.company.tenant_id, h.company.id, po_dtl_key)


def sync_owned(h, doc_key=7203):
    """The sync job staged the SPO's newest copy: strictly newer than the fixture's write-back copy (the test
    database stamps ``created_at`` to the second, and equal stamps would tie)."""
    from datetime import datetime, timedelta, timezone

    row = h.stage("SPO", h.vendor.find("SPO", doc_key), job_id="sync-job")
    row.created_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    h.db.commit()


def fail_follow(h, w, key, inject="refuse"):
    """The PO link and its restore land; the SPO PUT is refused (nothing applied) or answers a bare 500."""
    if inject == "refuse":
        h.vendor.refuse_json_next("PUT", LEAF, after=2)
    else:
        h.vendor.fail_next("PUT", LEAF, after=2)
    res = h.run(OP, w.params(40), key=key)
    assert res.outcome == "needs_attention" and res.error_code == "SPO_NOT_FOLLOWED", (res.outcome, res.error_code)
    return res


def busy_spo(h, doc_key=7203):
    """Another SS operation is writing the SPO right now."""
    from modules.autocount.models import AcWriteOperation

    row = AcWriteOperation(tenant_id=h.company.tenant_id, company_id=h.company.id, key_id=None,
                           idempotency_key=f"busy-{doc_key}", request_hash="x", op="spo_move_row", doc_type="SPO",
                           doc_key=doc_key, dtl_key=1, status="in_progress")
    h.db.add(row)
    h.db.commit()
    return row


def test_r2_live_book_the_spo_index_follows_a_sync_owned_spo(h, w):
    live_book(h)
    sync_owned(h)
    res = h.run(OP, w.params(40), key="r2-1")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert index_qty(h, w.b1) == 0 and index_qty(h, w.new_po_row()["DtlKey"]) == 40


def test_r2_live_book_crm_save_move_then_split_carries_the_spo_line(h):
    """The CRM Save on a live book: ``/spo-links/move`` puts the 80 SPO line on B1, then ``/po-links/batch``
    splits B1. The line must follow onto the new PO line, never stay on the 20 left."""
    switch(h)
    live_book(h)
    base = dict(DeliveryDate="2026-12-01T00:00:00", Description="d")
    h.seed_doc("SO", 7202, [_line("ITEM-A", 80, 5.0, "HQ")])
    so_a = h.vendor.rows("SO", 7202)[0]["DtlKey"]
    h.seed_doc("PO", 7201, [_line("ITEM-A", 100, 5.0, "BR1", **base)])
    b1 = h.vendor.rows("PO", 7201)[0]["DtlKey"]
    h.seed_doc("PO", 7101, [_line("ITEM-A", 80, 5.0, "BR1", **base)])
    a1 = h.vendor.rows("PO", 7101)[0]["DtlKey"]
    h.seed_doc("SPO", 7203, [_line("ITEM-A", 80, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7101",
                                   FromDocDtlKey=a1)], stage=False)
    sync_owned(h)
    s1 = h.vendor.rows("SPO", 7203)[0]["DtlKey"]
    mv = h.run("spo_move_row", dict(spo_doc_key=7203, spo_dtl_key=s1, po_doc_key=7201, po_dtl_key=b1,
                                    qty=Decimal(80)), key="r2-2m")
    assert mv.outcome == "done", (mv.outcome, mv.error_code)
    assert index_qty(h, b1) == 80 and index_qty(h, a1) == 0  # the move's read-back is in the index
    res = h.run(OP, dict(doc_key=7201, dtl_key=b1, links=[dict(so_doc_key=7202, so_dtl_key=so_a,
                                                              qty=Decimal(80))]), key="r2-2b")
    assert res.outcome == "done", (res.outcome, res.error_code)
    new_po = next(r for r in h.vendor.rows("PO", 7201) if r.get("FromSODtlKey") == so_a)["DtlKey"]
    spo = h.vendor.rows("SPO", 7203)
    assert len(spo) == 1 and spo[0]["Qty"] == 80 and spo[0]["FromDocDtlKey"] == new_po
    assert len(res.batch["spoLines"]) == 1 and index_qty(h, b1) == 0 and index_qty(h, new_po) == 80


def test_r2_resume_leaves_a_hand_edited_spo_line_with_a_person(h, w):
    res = fail_follow(h, w, "r2-3")
    line = w.spo_rows()[0]
    line["UnitPrice"], line["Location"], line["Description"] = 7.5, "BRW", "edited"  # Qty and link unchanged
    sent = len(puts(h, 7203))
    out = resume(h, res)
    assert out.outcome == "needs_attention" and out.error_code == "SPO_NOT_FOLLOWED", (out.outcome, out.error_code)
    assert len(puts(h, 7203)) == sent  # nothing sent: the edit is never reverted
    row = w.spo_rows()[0]
    assert (row["UnitPrice"], row["Location"], row["Description"]) == (7.5, "BRW", "edited")


def test_r2_resume_never_deletes_a_spo_line_received_since_the_plan(h, w):
    res = fail_follow(h, w, "r2-4")
    sent = len(puts(h, 7203))

    def received(kind, doc, row):
        return Decimal(5) if kind == "SPO" else Decimal(0)

    out = h.ops(receipt_reader=received).resume(
        tenant_id=h.company.tenant_id, company_id=h.company.id, operation_id=res.operation_id)
    assert out.outcome == "needs_attention" and out.error_code == "SPO_NOT_FOLLOWED", (out.outcome, out.error_code)
    assert len(puts(h, 7203)) == sent and w.spo_rows()[0]["DtlKey"] == w.s1


def test_r2_a_pending_move_onto_the_po_line_counts_when_the_index_has_none(h):
    """A move onto B1 whose outcome is unknown (it landed, answered 500) is not in the index yet."""
    switch(h)
    base = dict(DeliveryDate="2026-12-01T00:00:00", Description="d")
    h.seed_doc("SO", 7202, [_line("ITEM-A", 80, 5.0, "HQ")])
    so_a = h.vendor.rows("SO", 7202)[0]["DtlKey"]
    h.seed_doc("PO", 7201, [_line("ITEM-A", 100, 5.0, "BR1", **base)])
    b1 = h.vendor.rows("PO", 7201)[0]["DtlKey"]
    h.seed_doc("PO", 7101, [_line("ITEM-A", 80, 5.0, "BR1", **base)])
    a1 = h.vendor.rows("PO", 7101)[0]["DtlKey"]
    h.seed_doc("SPO", 7203, [_line("ITEM-A", 80, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7101",
                                   FromDocDtlKey=a1)])
    s1 = h.vendor.rows("SPO", 7203)[0]["DtlKey"]
    h.vendor.apply_then_500_next("PUT", LEAF)
    mv = h.run("spo_move_row", dict(spo_doc_key=7203, spo_dtl_key=s1, po_doc_key=7201, po_dtl_key=b1,
                                    qty=Decimal(80)), key="r2-5m")
    assert mv.outcome == "pending_verification", (mv.outcome, mv.error_code)
    writes = len(h.vendor.writes())
    res = h.run(OP, dict(doc_key=7201, dtl_key=b1, links=[dict(so_doc_key=7202, so_dtl_key=so_a,
                                                              qty=Decimal(80))]), key="r2-5b")
    assert res.outcome == "refused" and res.error_code == "ROW_ON_SPO", (res.outcome, res.error_code)
    assert len(h.vendor.writes()) == writes  # nothing sent


def test_r2_a_pending_move_onto_the_po_line_counts_against_the_kept_line(h, w):
    """B1 100 with S1 40 on it; a pending move of 50 more onto B1; a batch of 40 (S1 follows) + 20 keeps 40:
    the 50 that may be on B1 does not fit."""
    h.seed_doc("PO", 7101, [_line("ITEM-A", 50, 5.0, "BR1")])
    a1 = h.vendor.rows("PO", 7101)[0]["DtlKey"]
    h.seed_doc("SPO", 7303, [_line("ITEM-A", 50, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7101",
                                   FromDocDtlKey=a1)])
    x1 = h.vendor.rows("SPO", 7303)[0]["DtlKey"]
    h.vendor.apply_then_500_next("PUT", LEAF)
    mv = h.run("spo_move_row", dict(spo_doc_key=7303, spo_dtl_key=x1, po_doc_key=7201, po_dtl_key=w.b1,
                                    qty=Decimal(50)), key="r2-6m")
    assert mv.outcome == "pending_verification", (mv.outcome, mv.error_code)
    writes = len(h.vendor.writes())
    res = h.run(OP, dict(doc_key=7201, dtl_key=w.b1, links=[
        dict(so_doc_key=7202, so_dtl_key=w.so_a, qty=Decimal(40)),
        dict(so_doc_key=7202, so_dtl_key=w.so_b, qty=Decimal(20))]), key="r2-6b")
    assert res.outcome == "refused" and res.error_code == "ROW_ON_SPO", (res.outcome, res.error_code)
    assert len(h.vendor.writes()) == writes


def test_r2_a_busy_follower_spo_is_doc_busy_and_nothing_is_sent(h, w):
    busy_spo(h)
    res = h.run(OP, w.params(40), key="r2-7")
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY", (res.outcome, res.error_code)
    assert h.vendor.writes() == []


def test_r2_resume_waits_while_another_operation_writes_the_spo(h, w):
    res = fail_follow(h, w, "r2-8")
    held = busy_spo(h)
    sent = len(puts(h, 7203))
    out = resume(h, res)
    assert out.outcome == "needs_attention" and out.error_code == "SPO_NOT_FOLLOWED", (out.outcome, out.error_code)
    assert len(puts(h, 7203)) == sent
    held.status = "done"
    h.db.commit()
    done = resume(h, res)
    assert done.outcome == "done", (done.outcome, done.error_code)
    assert w.spo_rows()[0]["FromDocDtlKey"] == w.new_po_row()["DtlKey"]


def test_r2_an_unknown_follow_put_is_not_sent_again_before_it_settles(h, w, monkeypatch):
    from modules.autocount.write_back import operations

    res = fail_follow(h, w, "r2-9", inject="bare500")  # nothing applied, but the answer cannot prove it
    sent = len(puts(h, 7203))
    out = resume(h, res)
    assert out.outcome == "needs_attention" and out.error_code == "SPO_NOT_FOLLOWED", (out.outcome, out.error_code)
    assert len(puts(h, 7203)) == sent  # a PUT still in flight could land: no second one yet
    monkeypatch.setattr(operations, "LOOKUP_SETTLE_SECONDS", 0)  # the first PUT has had time to finish
    done = resume(h, res)
    assert done.outcome == "done", (done.outcome, done.error_code)
    assert len(w.spo_rows()) == 1 and w.spo_rows()[0]["FromDocDtlKey"] == w.new_po_row()["DtlKey"]


def test_r2_a_move_onto_the_new_po_line_of_an_unfinished_follow_waits(h, w):
    res = fail_follow(h, w, "r2-10")
    new_po = w.new_po_row()["DtlKey"]
    h.seed_doc("PO", 7301, [_line("ITEM-A", 30, 5.0, "BR1")])
    c1 = h.vendor.rows("PO", 7301)[0]["DtlKey"]
    h.seed_doc("SPO", 7303, [_line("ITEM-A", 30, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7301",
                                   FromDocDtlKey=c1)])
    x1 = h.vendor.rows("SPO", 7303)[0]["DtlKey"]
    writes = len(h.vendor.writes())
    mv = h.run("spo_move_row", dict(spo_doc_key=7303, spo_dtl_key=x1, po_doc_key=7201, po_dtl_key=new_po,
                                    qty=Decimal(30)), key="r2-10m")
    assert mv.outcome == "refused" and mv.error_code == "ROW_NEEDS_ATTENTION", (mv.outcome, mv.error_code)
    assert len(h.vendor.writes()) == writes
    done = resume(h, res)
    assert done.outcome == "done", (done.outcome, done.error_code)
    again = h.run("spo_move_row", dict(spo_doc_key=7303, spo_dtl_key=x1, po_doc_key=7201, po_dtl_key=new_po,
                                       qty=Decimal(30)), key="r2-10n")
    assert again.outcome == "refused" and again.error_code == "QTY_ABOVE_OUTSTANDING", (again.outcome, again.error_code)


def test_r2_a_relink_onto_the_new_po_line_of_an_unfinished_follow_waits(h, w):
    fail_follow(h, w, "r2-10r")
    new_po = w.new_po_row()["DtlKey"]
    h.seed_doc("PO", 7301, [_line("ITEM-A", 30, 5.0, "BR1")])
    c1 = h.vendor.rows("PO", 7301)[0]["DtlKey"]
    h.seed_doc("SPO", 7303, [_line("ITEM-A", 30, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7301",
                                   FromDocDtlKey=c1)])
    x1 = h.vendor.rows("SPO", 7303)[0]["DtlKey"]
    writes = len(h.vendor.writes())
    out = h.run("spo_relink_row", dict(spo_doc_key=7303, spo_dtl_key=x1, po_doc_key=7201, po_dtl_key=new_po),
                key="r2-10s")
    assert out.outcome == "refused" and out.error_code == "ROW_NEEDS_ATTENTION", (out.outcome, out.error_code)
    assert len(h.vendor.writes()) == writes


def test_r2_only_the_new_po_line_a_follower_waits_for_is_held(h, w):
    """A batch of 40 (its SPO line follows) + 20 (no SPO line) whose follow did not land: the 20 line's new PO line
    has nothing coming, so another SPO line may move onto it; the 40 line's new PO line waits."""
    h.vendor.refuse_json_next("PUT", LEAF, after=2)
    res = h.run(OP, dict(doc_key=7201, dtl_key=w.b1, links=[
        dict(so_doc_key=7202, so_dtl_key=w.so_a, qty=Decimal(40)),
        dict(so_doc_key=7202, so_dtl_key=w.so_b, qty=Decimal(20))]), key="r2-17")
    assert res.error_code == "SPO_NOT_FOLLOWED", (res.outcome, res.error_code)
    h.seed_doc("PO", 7301, [_line("ITEM-A", 20, 5.0, "BR1")])
    c1 = h.vendor.rows("PO", 7301)[0]["DtlKey"]
    h.seed_doc("SPO", 7303, [_line("ITEM-A", 10, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7301",
                                   FromDocDtlKey=c1), _line("ITEM-A", 10, 5.0, "BR1", FromDocType="PO",
                                                            FromDocNo="PO-7301", FromDocDtlKey=c1)])
    x1, x2 = [r["DtlKey"] for r in h.vendor.rows("SPO", 7303)]
    waits = h.run("spo_move_row", dict(spo_doc_key=7303, spo_dtl_key=x1, po_doc_key=7201,
                                       po_dtl_key=w.new_po_row()["DtlKey"], qty=Decimal(10)), key="r2-17a")
    assert waits.outcome == "refused" and waits.error_code == "ROW_NEEDS_ATTENTION", (waits.outcome, waits.error_code)
    free = h.run("spo_move_row", dict(spo_doc_key=7303, spo_dtl_key=x2, po_doc_key=7201,
                                      po_dtl_key=w.new_po_row(w.so_b)["DtlKey"], qty=Decimal(10)), key="r2-17b")
    assert free.outcome == "done", (free.outcome, free.error_code)


def lock_spy(h):
    """Every ``link_locks`` the operations take: ``(PO documents, SPO documents)``."""
    from modules.autocount.write_back import operations

    seen = []
    real = operations.link_locks

    def spy(db, company_id, *, po_doc_keys=(), so_dtl_keys=(), spo_doc_keys=()):
        seen.append((list(po_doc_keys), list(spo_doc_keys)))
        return real(db, company_id, po_doc_keys=po_doc_keys, so_dtl_keys=so_dtl_keys, spo_doc_keys=spo_doc_keys)

    h.monkeypatch.setattr(operations, "link_locks", spy)
    return seen


def test_r2_the_follow_writes_the_spo_under_its_lock(h, w):
    seen = lock_spy(h)
    res = h.run(OP, w.params(40), key="r2-15")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert seen[0] == ([7201], []) and ([], [7203]) in seen[1:], seen  # the batch's PO, then the follow's SPO


def test_r2_resume_of_an_spo_operation_holds_the_spo_document(h, w):
    h.seed_doc("PO", 7301, [_line("ITEM-A", 100, 5.0, "BR1")])
    c1 = h.vendor.rows("PO", 7301)[0]["DtlKey"]
    h.vendor.apply_then_500_next("PUT", LEAF)
    mv = h.run("spo_move_row", dict(spo_doc_key=7203, spo_dtl_key=w.s1, po_doc_key=7301, po_dtl_key=c1,
                                    qty=Decimal(40)), key="r2-16")
    assert mv.outcome == "pending_verification", (mv.outcome, mv.error_code)
    seen = lock_spy(h)
    out = resume(h, mv)
    assert out.outcome == "done", (out.outcome, out.error_code)
    assert seen and seen[0] == ([], [7203]), seen


def test_r2_the_follow_checks_the_new_po_line_has_room(h, w):
    """An SPO line tied by hand to the new PO line while the follow waited: the follower no longer fits."""
    res = fail_follow(h, w, "r2-11")
    new_po = w.new_po_row()["DtlKey"]
    h.seed_doc("SPO", 7303, [_line("ITEM-A", 10, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7201",
                                   FromDocDtlKey=new_po)])
    sent = len(puts(h, 7203))
    out = resume(h, res)
    assert out.outcome == "needs_attention" and out.error_code == "SPO_NOT_FOLLOWED", (out.outcome, out.error_code)
    assert len(puts(h, 7203)) == sent and w.spo_rows()[0]["FromDocDtlKey"] == w.b1


def test_r2_a_follow_that_landed_does_not_hold_the_po_line(h, w):
    h.vendor.refuse_json_next("PUT", LEAF, after=1)  # the link lands, its restore is refused, the follow lands
    res = h.run(OP, w.params(40), key="r2-12")
    assert res.error_code == "RESTORE_NOT_LANDED" and len(res.batch["spoLines"]) == 1, (res.outcome, res.error_code)
    again = h.run(OP, w.params(20, so_dtl=w.so_b), key="r2-12b")
    assert again.outcome == "done", (again.outcome, again.error_code)


def test_r2_the_alert_names_the_spo_line_a_person_must_check(h, w):
    fail_follow(h, w, "r2-13")
    assert h.alerts and "SPO-7203" in str(h.alerts[-1].get("spoLines")), h.alerts


def test_r2_the_follow_restore_reads_the_spo_fresh(h, w, monkeypatch):
    """The batch holds the PO, not the SPO: the edit that puts the new SPO line back is built on a fresh read,
    never on the follow PUT's read-back."""
    from modules.autocount.write_back.primitives import PrimitiveService

    add_link = h.vendor._apply_new_row_link

    def default_location(kind, stored, sent):  # AutoCount puts the new SPO line at another location
        add_link(kind, stored, sent)
        if kind == "SPO":
            stored["Location"] = "HQ"

    h.vendor._apply_new_row_link = default_location
    seen = []
    edit = PrimitiveService.edit_doc

    def spy(self, **kw):
        seen.append((kw.get("kind"), kw.get("fresh_doc")))
        return edit(self, **kw)

    monkeypatch.setattr(PrimitiveService, "edit_doc", spy)
    res = h.run(OP, w.params(40), key="r2-14")
    assert res.outcome == "done", (res.outcome, res.error_code)
    spo_edits = [fresh for kind, fresh in seen if kind == "SPO"]
    assert spo_edits and all(fresh is None for fresh in spo_edits), seen
    assert w.spo_rows()[0]["Location"] == "BR1"


# ---- kill tests ------------------------------------------------------------------------------------------------

def test_kill_the_follower_is_the_spo_line_of_the_links_quantity_not_the_first_one(h):
    switch(h)
    w = World(h, spo_qtys=(50, 40))  # the 50 line stays (kept PO line = 60), the 40 line follows
    res = h.run(OP, w.params(40))
    assert res.outcome == "done", (res.error_code, res.message)
    assert [s["fromSpoDtlKey"] for s in res.batch["spoLines"]] == [w.s_keys[1]]
    stay = next(r for r in w.spo_rows() if r["DtlKey"] == w.s_keys[0])
    assert stay["Qty"] == 50 and stay["FromDocDtlKey"] == w.b1


def test_kill_spo_line_re_pointed_by_hand_is_not_moved_by_resume(h, w):
    h.vendor.refuse_json_next("PUT", LEAF, after=2)
    res = h.run(OP, w.params(40), key="k4")
    assert res.error_code == "SPO_NOT_FOLLOWED"
    w.spo_rows()[0]["FromDocDtlKey"] = 999999  # a person tied it to another PO line meanwhile (qty unchanged)
    spo_puts = len(puts(h, 7203))
    out = resume(h, res)
    assert out.outcome == "needs_attention" and out.error_code == "SPO_NOT_FOLLOWED", (out.outcome, out.error_code)
    assert len(puts(h, 7203)) == spo_puts
