"""Plan 62 (RED): the retry rule for every write operation, AC-62-20..23 (plan D6).

Spec: ``documentation/plans/sprint-5/62-autocount-po-link-batch-acceptance-criteria.md``.
Today ``OperationService.run`` replays ANY stored key as the stored answer, and
``run_primitive`` replays a stored refused / vendor_error answer as is. Wanted:

* stored ``refused`` / ``vendor_error``  -> same key runs FRESH (vendor called again), a corrected
  body runs the corrected body (no IDEMPOTENCY_CONFLICT); the old row is kept (re-keyed);
* stored ``pending_verification``        -> same key + body reconciles first (reads the PO back):
  landed -> ``done`` with no second replace PUT, not landed -> the PUT is sent once;
* ``done``                               -> stored answer, no vendor call, changed body conflicts;
* ``needs_attention``                    -> stored answer on a resend (``resume`` is the way).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, List

import pytest

from app.main import app  # noqa: F401 - the gateway rig overrides dependencies on it
from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteOperation
from modules.autocount.write_back.primitives import PrimitiveResult
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw
from tests.test_autocount_write_back_operations import (  # noqa: F401
    KEY_ID,
    OpHarness,
    World,
    db,
    drop_new_row_once,
    h,
)
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


@pytest.fixture
def world(h):
    return World(h)


@pytest.fixture
def gw(h, db):
    return Gw(h, db)


def replace_puts(h) -> List[Any]:
    """PUTs that carry a "D" row (the replace PUT of a link / unlink / relink)."""
    return [
        c for c in h.vendor.writes()
        if c.method == "PUT" and any(r.get("FullTransferOption") == "D" for r in (c.body or {}).get("Details") or [])
    ]


def all_puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def op_rows(h) -> List[AcWriteOperation]:
    h.db.expire_all()
    return h.db.query(AcWriteOperation).filter(AcWriteOperation.company_id == h.company.id).all()


def received(kind, doc, row):
    return Decimal(4)


# ============================== AC-62-20 vendor_error / refused rerun ==========================

@pytest.mark.parametrize("op", ["unlink_row", "link_row"])
def test_ac_62_20_vendor_error_resend_same_key_runs_fresh(h, world, op):
    h.vendor.invalid_items = {"ITEM-A"}
    first = h.run(op, world.params[op], key="k-20a")
    assert first.outcome == "vendor_error" and first.error_code == "VENDOR_REFUSED"
    assert len(all_puts(h)) == 1
    h.vendor.invalid_items = set()  # the cause is fixed; the caller resends the SAME key and body
    again = h.run(op, world.params[op], key="k-20a")
    assert again.outcome == "done", (again.outcome, again.error_code)
    assert again.error_code != "IDEMPOTENCY_CONFLICT"
    assert len(replace_puts(h)) == 2  # the vendor was called again, fresh


def test_ac_62_20_vendor_error_with_a_corrected_body_runs_the_corrected_body(h, world):
    h.vendor.invalid_items = {"ITEM-A"}
    bad = dict(world.params["link_row"])
    first = h.run("link_row", bad, key="k-20b")
    assert first.outcome == "vendor_error"
    h.vendor.invalid_items = set()
    fixed = dict(bad, so_dtl_key=world.so_b)  # a DIFFERENT body under the same key
    res = h.run("link_row", fixed, key="k-20b")
    assert res.error_code != "IDEMPOTENCY_CONFLICT", (res.outcome, res.error_code)
    assert res.outcome == "done", (res.outcome, res.error_code)
    rows = [r for r in world.po_rows() if r.get("FromSODtlKey") == world.so_b]
    assert rows, "the corrected body (link to so_b) was not the one sent"


def test_ac_62_20_the_old_row_is_kept_re_keyed_for_history(h, world):
    h.vendor.invalid_items = {"ITEM-A"}
    first = h.run("unlink_row", world.params["unlink_row"], key="k-20c")
    old_id = first.operation_id
    h.vendor.invalid_items = set()
    again = h.run("unlink_row", world.params["unlink_row"], key="k-20c")
    assert again.operation_id != old_id
    rows = {r.id: r for r in op_rows(h)}
    assert old_id in rows, "the old operation row was deleted instead of kept"
    assert rows[old_id].idempotency_key != "k-20c"  # re-keyed so the key is free
    assert rows[again.operation_id].idempotency_key == "k-20c"
    assert [r for r in rows.values() if r.idempotency_key == "k-20c"] == [rows[again.operation_id]]


def test_ac_62_20_refused_resend_same_key_runs_fresh(h, world):
    refused = h.run("unlink_row", world.params["unlink_row"], key="k-20d", receipt_reader=received)
    assert refused.outcome == "refused", (refused.outcome, refused.error_code)
    assert all_puts(h) == []
    again = h.run("unlink_row", world.params["unlink_row"], key="k-20d")  # nothing received any more
    assert again.outcome == "done", (again.outcome, again.error_code)
    assert len(replace_puts(h)) == 1  # the vendor was called on the resend


def test_ac_62_20_gateway_unlink_route_resend_after_vendor_error_runs_fresh(client, h, gw, world):
    h.vendor.invalid_items = {"ITEM-A"}
    body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked}
    r1 = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("k-gw-20"), json=body)
    assert r1.status_code == 502 and r1.json()["outcome"] == "vendor_error", r1.text
    h.vendor.invalid_items = set()
    r2 = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("k-gw-20"), json=body)
    assert r2.status_code == 200 and r2.json()["outcome"] == "done", r2.text
    assert len(replace_puts(h)) == 2


@pytest.mark.parametrize("first_outcome,code", [("vendor_error", "VENDOR_REFUSED"), ("refused", "DOC_STALE")])
def test_ac_62_20_run_primitive_resend_after_refused_or_vendor_error_runs_fresh(h, first_outcome, code):
    ops = h.ops()
    calls: List[int] = []

    def call():
        calls.append(1)
        if len(calls) == 1:
            return PrimitiveResult(None, first_outcome, code, "nope")
        return PrimitiveResult(None, "done", None, "")

    args = dict(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=KEY_ID, idempotency_key="k-prim",
                name="edit_doc", kind="PO", doc_key=7001, params={"a": 1}, call=call)
    one = ops.run_primitive(**args)
    assert one["outcome"] == first_outcome
    two = ops.run_primitive(**args)
    assert len(calls) == 2, "the resend replayed the stored refusal instead of running fresh"
    assert two["outcome"] == "done"
    rows = [r for r in op_rows(h) if r.op == "edit_doc:PO"]
    assert len(rows) == 2 and [r.idempotency_key for r in rows].count("k-prim") == 1  # old row kept, re-keyed


def test_ac_62_20_run_primitive_with_a_corrected_body_is_not_a_conflict(h):
    ops = h.ops()
    seen: List[str] = []

    def make(tag, outcome, code=None):
        def call():
            seen.append(tag)
            return PrimitiveResult(None, outcome, code, "")
        return call

    base = dict(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=KEY_ID, idempotency_key="k-prim2",
                name="edit_doc", kind="PO", doc_key=7001)
    ops.run_primitive(params={"a": 1}, call=make("bad", "vendor_error", "VENDOR_REFUSED"), **base)
    out = ops.run_primitive(params={"a": 2}, call=make("fixed", "done"), **base)
    assert out.get("errorCode") != "IDEMPOTENCY_CONFLICT", out
    assert seen == ["bad", "fixed"] and out["outcome"] == "done"


# ============================== AC-62-21 pending_verification ==================================

@pytest.mark.parametrize("op", ["unlink_row", "link_row"])
def test_ac_62_21_pending_resend_that_had_landed_is_done_with_no_second_replace_put(h, world, op):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")  # the request never reached AutoCount ...
    first = h.run(op, world.params[op], key="k-21a")
    assert first.outcome == "pending_verification"
    sent = replace_puts(h)
    assert len(sent) == 1
    h.vendor._edit("PO", sent[0].body)  # ... then show it landed after all (answer lost, change applied)
    res = h.run(op, world.params[op], key="k-21a")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(replace_puts(h)) == 1, "a second replace PUT was sent although the first had landed"
    assert res.replaced_lines, "the answer must carry the new DtlKeys"
    assert any(c.method == "GET" for c in h.vendor.calls[1:]), "the PO was not read back first"


@pytest.mark.parametrize("op", ["unlink_row", "link_row"])
def test_ac_62_21_pending_resend_that_had_not_landed_sends_the_put_once(h, world, op):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = h.run(op, world.params[op], key="k-21b")
    assert first.outcome == "pending_verification"
    assert len(replace_puts(h)) == 1
    res = h.run(op, world.params[op], key="k-21b")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(replace_puts(h)) == 2  # the first never changed AutoCount, so exactly one more is sent


# ============================== AC-62-22 done locks ============================================

def test_ac_62_22_done_resend_is_the_stored_answer_with_no_vendor_call(h, world):
    first = h.run("unlink_row", world.params["unlink_row"], key="k-22")
    assert first.outcome == "done"
    calls = len(h.vendor.calls)
    again = h.run("unlink_row", world.params["unlink_row"], key="k-22")
    assert again.outcome == "done" and again.operation_id == first.operation_id
    assert len(h.vendor.calls) == calls


def test_ac_62_22_done_resend_with_a_changed_body_is_an_idempotency_conflict(h, world):
    first = h.run("link_row", world.params["link_row"], key="k-22b")
    assert first.outcome == "done"
    calls = len(h.vendor.calls)
    other = dict(world.params["link_row"], so_dtl_key=world.so_b)
    res = h.run("link_row", other, key="k-22b")
    assert res.outcome == "refused" and res.error_code == "IDEMPOTENCY_CONFLICT"
    assert len(h.vendor.calls) == calls


def test_ac_62_22_gateway_done_resend_answers_the_stored_result_without_the_vendor(client, h, gw, world):
    body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked}
    r1 = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("k-gw-22"), json=body)
    assert r1.status_code == 200
    calls = len(h.vendor.calls)
    r2 = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("k-gw-22"), json=body)
    assert r2.status_code == 200 and r2.json()["operationId"] == r1.json()["operationId"]
    assert len(h.vendor.calls) == calls


# ============================== AC-62-23 needs_attention =======================================

def test_ac_62_23_needs_attention_resend_is_the_stored_answer_not_a_rerun(h, world):
    drop_new_row_once(h)
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "recovery failed", after=1)
    first = h.run("unlink_row", world.params["unlink_row"], key="k-23")
    assert first.outcome == "needs_attention"
    calls = len(h.vendor.calls)
    again = h.run("unlink_row", world.params["unlink_row"], key="k-23")
    assert again.outcome == "needs_attention" and again.operation_id == first.operation_id
    assert len(h.vendor.calls) == calls  # nothing automatic: resume stays the way
