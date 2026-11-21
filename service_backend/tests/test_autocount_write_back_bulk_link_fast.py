"""Plan 69 (RED first): bulk PO-SO link, fast.

Slice B (AC-69-10..12): a link / restore PUT that answers non-2xx is followed by ONE read of the PO, and the
read decides: nothing changed = refused (released, AutoCount's reason); landed = carry on; cannot read =
pending_verification. Never "refused" on the answer text alone (owner rule 11 Nov: an unknown outcome is
looked up before it is called refused).

Slice A (AC-69-02 / 05 / 06): no 20-entry cap error; times on every answer.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.main import app  # noqa: F401
from tests.test_autocount_write_back_link_batch import OP, ROUTE, Rig, batch_rows, puts, run
from tests.test_autocount_write_back_gateway import _hdr
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

EDIT = "EditPurchaseOrderbydockey"
PO_GET = "GetPurchaseOrderbydockey"


@pytest.fixture
def rig(h):
    return Rig(h)


@pytest.fixture
def gw(h, db, rig):
    return Gw(h, db)


def _get_leaf(h) -> str:
    leaves = {c.leaf for c in h.vendor.gets()}
    return next((x for x in leaves if "purchaseorder" in x), PO_GET.lower())


# ============================== AC-69-10: answered 500, but it landed ===========================

def test_ac_69_10_link_put_500_with_a_message_that_landed_is_done_and_restored(h, rig):
    h.vendor.apply_then_refuse_next("PUT", EDIT, "Timeout expired.")
    res = run(h, rig, rig.three())
    assert (res.outcome, res.error_code) == ("done", None), (res.outcome, res.error_code, res.message)
    assert sorted(batch_rows(h, rig)) == sorted(rig.s5)
    assert len(puts(h)) == 2  # the link PUT once (never re-sent) + the restore
    for row in batch_rows(h, rig).values():
        assert row["UnitPrice"] == 5.0  # the restore ran on the landed rows


def test_ac_69_10_restore_put_500_with_a_message_that_landed_is_done(h, rig):
    h.vendor.apply_then_refuse_next("PUT", EDIT, "Timeout expired.", after=1)
    res = run(h, rig, rig.three())
    assert (res.outcome, res.error_code) == ("done", None), (res.outcome, res.error_code, res.message)
    assert len(puts(h)) == 2


# ============================== AC-69-11: answered 500, nothing changed =========================

def test_ac_69_11_link_put_500_with_a_message_and_nothing_changed_is_refused_after_one_read(h, rig):
    before = [dict(r) for r in h.vendor.rows("PO", 7001)]
    h.vendor.refuse_json_next("PUT", EDIT, "Lock request time out period exceeded.")
    gets_before = len(h.vendor.gets())
    res = run(h, rig, rig.three())
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_REFUSED"), (res.outcome, res.error_code)
    assert "Lock request time out" in res.message  # AutoCount's own reason, shown plainly
    assert [dict(r) for r in h.vendor.rows("PO", 7001)] == before
    assert len(puts(h)) == 1
    put_at = h.vendor.calls.index(puts(h)[0])
    assert any(c.method == "GET" for c in h.vendor.calls[put_at + 1:]), "no read after the failed PUT"
    assert len(h.vendor.gets()) > gets_before


def test_ac_69_11_the_refused_key_is_released_and_try_again_links(h, rig):
    h.vendor.refuse_json_next("PUT", EDIT, "Lock request time out period exceeded.")
    first = run(h, rig, rig.three(), key="b-try")
    assert first.outcome == "vendor_error"
    again = run(h, rig, rig.three(), key="b-try")
    assert again.outcome == "done", (again.outcome, again.error_code, again.message)
    assert sorted(batch_rows(h, rig)) == sorted(rig.s5)


# ============================== AC-69-12: answered 500 and cannot be read =======================

def test_ac_69_12_failed_put_and_failed_read_is_pending_never_refused(h, rig):
    h.vendor.apply_then_refuse_next("PUT", EDIT, "Timeout expired.")
    original = h.vendor._route
    state = {"put": False}

    def route(method, leaf, call):
        if method == "PUT":
            state["put"] = True
        elif state["put"] and method == "GET" and "purchaseorder" in leaf:
            import httpx
            return httpx.Response(500, text="read failed")
        return original(method, leaf, call)

    h.vendor._route = route
    res = run(h, rig, rig.three())
    # PO-LINK-STUCK-RECONCILE-B s3/s4: an AutoCount timeout that cannot be read back is parked for a person
    # (the CRM's needs_attention = Resume), never refused
    assert (res.outcome, res.error_code) == ("needs_attention", "VENDOR_TIMEOUT"), (res.outcome, res.error_code)


# ============================== AC-69-02 / 05: no cap error =====================================

def _big(h, n: int):
    po = h.seed_doc("PO", 7101, [_line("ITEM-A", n + 5, 5.0, "BR1")])
    so = h.seed_doc("SO", 7105, [_line("ITEM-A", 10, 5.0, "HQ") for _ in range(n)])
    return po["Details"][0]["DtlKey"], [r["DtlKey"] for r in so["Details"]]


def test_ac_69_05_more_than_20_links_on_one_row_are_all_linked(h, rig):
    po_dtl, so_rows = _big(h, 25)
    res = h.run(OP, dict(doc_key=7101, dtl_key=po_dtl,
                         links=[dict(so_doc_key=7105, so_dtl_key=k, qty=1) for k in so_rows]), key="b-big")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    linked = {r["FromSODtlKey"] for r in h.vendor.rows("PO", 7101) if r.get("FromSODtlKey")}
    assert linked == set(so_rows)
    assert len(res.batch["links"]) == 25 and res.batch["skipped"] == []


def test_ac_69_05_route_accepts_more_than_20_links(client, h, gw, rig):
    po_dtl, so_rows = _big(h, 25)
    body = {"companyCode": "SRT", "poDocKey": 7101, "poDtlKey": po_dtl,
            "links": [{"soDocKey": 7105, "soDtlKey": k, "qty": 1} for k in so_rows]}
    r = client.post(ROUTE, json=body, headers=gw.hdr("b-big-route"))
    assert r.status_code == 200, r.text
    assert len(r.json()["links"]) == 25


# ============================== AC-69-06: times on the answer ===================================

def test_ac_69_06_answer_carries_requested_linked_and_finished_times(client, h, gw, rig):
    r = client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("b-times"))
    assert r.status_code == 200, r.text
    ans = r.json()
    for name in ("requestedAt", "linkedAt", "finishedAt"):
        assert isinstance(ans.get(name), str) and ans[name].endswith("Z"), (name, ans.get(name))
    assert ans["requestedAt"] <= ans["linkedAt"] <= ans["finishedAt"]
    op = client.get(f"{PREFIX}/write-operations/{ans['operationId']}?companyCode=SRT", headers=_hdr(gw.plain))
    assert op.status_code == 200, op.text
    assert op.json()["linkedAt"] == ans["linkedAt"]


def test_ac_69_06_a_refused_answer_has_no_linked_time(client, h, gw, rig):
    h.vendor.refuse_json_next("PUT", EDIT, "Lock request time out period exceeded.")
    r = client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("b-times-ref"))
    ans = r.json()
    assert ans.get("requestedAt") and ans.get("finishedAt") and ans.get("linkedAt") is None, ans
