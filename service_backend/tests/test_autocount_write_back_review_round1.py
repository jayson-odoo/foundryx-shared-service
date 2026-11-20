"""Plan 62 review round 1 (RED): neutral regression tests.

(1) a pending ``link_batch`` is only re-run when NOTHING of it landed; a partial match needs a person;
(2) a create retried after a stored vendor refusal looks the document up first (seam ``find_created_doc``);
(3) the over-link index follows a landed write even when the staged copy is left alone;
(4) re-keying a released operation never collides with a client-chosen key.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

import pytest

from app.main import app  # noqa: F401
from app.models import DEFAULT_TENANT_ID
from modules.autocount.write_back.primitives import PrimitiveResult
from tests.test_autocount_write_back_link_batch import Rig, puts
from tests.test_autocount_write_back_operations import KEY_ID, OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_live_books import live_books_open  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

OP = "link_batch"


@pytest.fixture
def rig(h):
    return Rig(h)


def put1s(h) -> List[Any]:
    """Edit PUTs that add rows (DtlKey 0): the batch's PUT 1, not its restore PUT."""
    return [c for c in puts(h) if any(r["DtlKey"] == 0 for r in c.body["Details"])]


def pend(h, rig, links):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    res = h.run(OP, rig.params(links), key="rr-1")
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    assert len(put1s(h)) == 1
    return res


def land(h):
    h.vendor._edit("PO", put1s(h)[0].body)  # the answer was lost but the change was applied


# ============================== (1) pending batch reconcile =====================================

def test_rr1_pending_and_everything_landed_is_done_with_no_second_put_1(h, rig):
    pend(h, rig, rig.three())
    land(h)
    res = h.run(OP, rig.params(rig.three()), key="rr-1")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(put1s(h)) == 1


def test_rr1_pending_and_nothing_landed_runs_one_fresh_put_1(h, rig):
    pend(h, rig, rig.three())
    res = h.run(OP, rig.params(rig.three()), key="rr-1")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(put1s(h)) == 2  # the first never changed AutoCount: exactly one more


def test_rr1_pending_whole_row_batch_with_the_old_row_still_there_runs_fresh(h, rig):
    links = [(7005, rig.s5[0], 2), (7005, rig.s5[1], 1), (7005, rig.s5[2], 1)]
    pend(h, rig, links)
    res = h.run(OP, rig.params(links), key="rr-1")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(put1s(h)) == 2


def test_rr1_pending_and_one_batch_row_changed_later_needs_attention_with_no_put(h, rig):
    pend(h, rig, rig.three())
    land(h)
    mine = next(r for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey") == rig.s5[0])
    mine["FromSODtlKey"] = 0  # that row was unlinked afterwards; the other two are still there
    before = len(puts(h))
    res = h.run(OP, rig.params(rig.three()), key="rr-1")
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert len(puts(h)) == before


def test_rr1_pending_and_one_batch_row_edited_later_needs_attention_with_no_put(h, rig):
    pend(h, rig, rig.three())
    land(h)
    mine = next(r for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey") == rig.s5[1])
    mine["Qty"] = 7  # edited afterwards
    before = len(puts(h))
    res = h.run(OP, rig.params(rig.three()), key="rr-1")
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert len(puts(h)) == before


def test_rr1_pending_and_the_old_row_changed_with_no_batch_rows_needs_attention(h, rig):
    pend(h, rig, rig.three())
    row = next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == rig.w.p_free)
    row["Qty"] = 3  # someone cut the old row; none of the batch's rows exist
    before = len(puts(h))
    res = h.run(OP, rig.params(rig.three()), key="rr-1")
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert len(puts(h)) == before


def test_rr1_pending_whole_row_batch_with_the_old_row_gone_and_no_batch_rows_needs_attention(h, rig):
    links = [(7005, rig.s5[0], 2), (7005, rig.s5[1], 1), (7005, rig.s5[2], 1)]
    pend(h, rig, links)
    po = h.vendor.find("PO", 7001)
    po["Details"] = [r for r in po["Details"] if r["DtlKey"] != rig.w.p_free]
    before = len(puts(h))
    res = h.run(OP, rig.params(links), key="rr-1")
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert len(puts(h)) == before


# ============================== (2) create retry looks the document up first ====================

def _create(ops, key, name, call, params):
    return ops.run_primitive(tenant_id=DEFAULT_TENANT_ID, company_id=ops.company_id, key_id=KEY_ID,
                             idempotency_key=key, name=name, kind="PO", doc_key=None, params=params, call=call)


class _Create:
    def __init__(self, h):
        self.ops = h.ops()
        self.ops.company_id = h.company.id
        self.calls: List[int] = []

    def call(self):
        self.calls.append(1)
        if len(self.calls) == 1:
            return PrimitiveResult(None, "vendor_error", "VENDOR_REFUSED", "refused")
        return PrimitiveResult(None, "done", None, "", doc_key=999, doc_no="PO-NEW")


@pytest.mark.parametrize("params", [{"header": {"docNo": "PO-X"}}, {"header": {}}], ids=["named", "new_number"])
def test_rr2_create_resend_finds_the_document_and_answers_done_without_a_second_post(h, monkeypatch, params):
    from modules.autocount.write_back.operations import OperationService

    c = _Create(h)
    monkeypatch.setattr(OperationService, "find_created_doc",
                        lambda self, *a, **k: {"DocKey": 321, "DocNo": "PO-X"}, raising=False)
    first = _create(c.ops, "cr-1", "create_doc", c.call, params)
    assert first["outcome"] == "vendor_error"
    again = _create(c.ops, "cr-1", "create_doc", c.call, params)
    assert again["outcome"] == "done" and again["docNo"] == "PO-X", again
    assert len(c.calls) == 1  # no second create POST
    third = _create(c.ops, "cr-1", "create_doc", c.call, params)
    assert third["outcome"] == "done" and len(c.calls) == 1  # the key is locked now


def test_rr2_create_resend_with_nothing_found_posts_once_more(h, monkeypatch):
    from modules.autocount.write_back.operations import OperationService

    c = _Create(h)
    monkeypatch.setattr(OperationService, "find_created_doc", lambda self, *a, **k: None, raising=False)
    params = {"header": {"docNo": "PO-X"}}
    assert _create(c.ops, "cr-2", "create_doc", c.call, params)["outcome"] == "vendor_error"
    again = _create(c.ops, "cr-2", "create_doc", c.call, params)
    assert again["outcome"] == "done" and len(c.calls) == 2


@pytest.mark.parametrize("name", ["edit_doc", "delete_line:5", "cancel_doc"])
def test_rr2_other_primitives_keep_the_plain_release_with_no_lookup(h, monkeypatch, name):
    from modules.autocount.write_back.operations import OperationService

    def boom(self, *a, **k):
        raise AssertionError("only a create looks the document up")

    monkeypatch.setattr(OperationService, "find_created_doc", boom, raising=False)
    c = _Create(h)
    assert _create(c.ops, "cr-3", name, c.call, {"a": 1})["outcome"] == "vendor_error"
    again = _create(c.ops, "cr-3", name, c.call, {"a": 1})
    assert again["outcome"] == "done" and len(c.calls) == 2


def test_rr2_link_batch_keeps_the_plain_release_with_no_lookup(h, rig, monkeypatch):
    from modules.autocount.write_back.operations import OperationService

    def boom(self, *a, **k):
        raise AssertionError("only a create looks the document up")

    monkeypatch.setattr(OperationService, "find_created_doc", boom, raising=False)
    h.vendor.invalid_items = {"ITEM-A"}
    assert h.run(OP, rig.params(rig.three()), key="cr-4").outcome == "vendor_error"
    h.vendor.invalid_items = set()
    assert h.run(OP, rig.params(rig.three()), key="cr-4").outcome == "done"


# ============================== (3) the index follows a landed write ============================

def test_rr3_a_link_on_one_po_counts_for_the_next_link_on_another_po_even_when_its_copy_is_left_alone(
        h, live_books_open):
    from modules.autocount.models import AcStagedRecord

    h.delete_on()
    so = h.seed_doc("SO", 7010, [_line("ITEM-A", 5, 5.0, "HQ")])
    so_key = so["Details"][0]["DtlKey"]
    for key in (7011, 7012):
        h.seed_doc("PO", key, [_line("ITEM-A", 4, 5.0, "BR1")])
    # PO 7011's staged copy belongs to another job (a sync): write-back leaves it alone
    h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7011").update({"job_id": "sql-sync-job"})
    h.db.commit()
    rows = {k: h.vendor.rows("PO", k)[0]["DtlKey"] for k in (7011, 7012)}
    a = h.run("link_row", dict(doc_key=7011, dtl_key=rows[7011], so_doc_key=7010, so_dtl_key=so_key), key="ix-a")
    assert a.outcome == "done", (a.outcome, a.error_code)
    b = h.run("link_row", dict(doc_key=7012, dtl_key=rows[7012], so_doc_key=7010, so_dtl_key=so_key), key="ix-b")
    assert b.outcome == "refused" and b.error_code == "QTY_ABOVE_OUTSTANDING", (b.outcome, b.error_code)
    from modules.autocount.models import AcPoSoLink

    h.db.expire_all()
    mine = h.db.query(AcPoSoLink).filter_by(company_id=h.company.id, po_source_ref=f"AED_TEST:7011").all()
    assert [(r.so_dtl_key, Decimal(r.qty)) for r in mine] == [(so_key, Decimal(4))]


# ============================== (4) re-key never collides with a client key =====================

def test_rr4_a_client_key_equal_to_the_released_form_never_breaks_the_release(h):
    w = World(h)
    received = lambda kind, doc, row: Decimal(4)  # noqa: E731
    first = h.run("unlink_row", w.params["unlink_row"], key="k", receipt_reader=received)
    assert first.outcome == "refused"
    squatter = f"k~released~{first.operation_id}"  # a client chose exactly the form the release would take
    other = h.run("unlink_row", w.params["unlink_row"], key=squatter, receipt_reader=received)
    assert other.outcome == "refused"
    again = h.run("unlink_row", w.params["unlink_row"], key="k")  # the release must still work
    assert again.error_code != "INTERNAL_ERROR", (again.outcome, again.error_code)
    assert again.outcome in ("done", "refused")
    assert again.outcome == "done" or again.error_code
