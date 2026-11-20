"""Plan 62 owner rule (RED): one bad line never fails a whole batch.

Per-LINE pre-checks skip that line (ROW_NOT_FOUND, ITEM_MISMATCH, UOM_MISMATCH, DOC_CANCELLED of its SO,
QTY_ABOVE_OUTSTANDING, QTY_INVALID, QTY_ABOVE_FREE when the running sum in request order passes the PO row's
free quantity). PO-level checks still refuse the whole request. The answer always carries ``skipped``
(``[{soDtlKey, code}]``, ``[]`` when none). Every line skipped = ``refused`` / ``ALL_LINKS_SKIPPED``, zero writes,
key released.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

import pytest

from app.main import app  # noqa: F401
from tests.test_autocount_write_back_gateway_qtso import Gw, code
from tests.test_autocount_write_back_link_batch import OP, ROUTE, Rig, d_rows, linked_rows, new_rows, puts
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


@pytest.fixture
def rig(h):
    return Rig(h)


@pytest.fixture
def gw(h, db, rig):
    return Gw(h, db)


def skipped_of(r) -> Dict[int, str]:
    return {x["soDtlKey"]: x["code"] for x in r.json()["skipped"]}


def post(client, gw, rig, links, key):
    return client.post(ROUTE, json=rig.body(links), headers=gw.hdr(key))


# ============================== mixed batches ===================================================

def test_skip_two_good_and_one_above_outstanding_link_the_two_and_name_the_third(client, h, gw, rig):
    h.vendor.find("SO", 7005)["Details"][2]["Qty"] = 1  # that row has 1 outstanding; the request asks 2
    links = [(7005, rig.s5[0], 1), (7005, rig.s5[1], 1), (7005, rig.s5[2], 2)]
    r = post(client, gw, rig, links, "sk-1")
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    first = puts(h)[0]
    assert sorted(x["FromDocDtlKey"] for x in new_rows(first)) == sorted(rig.s5[:2])  # only the good lines go out
    assert len(puts(h)) <= 2
    ans = r.json()
    assert sorted(x["soDtlKey"] for x in ans["links"]) == sorted(rig.s5[:2])
    assert skipped_of(r) == {rig.s5[2]: "QTY_ABOVE_OUTSTANDING"}
    assert ans["freeLine"]["poDtlKey"] == rig.w.p_free and Decimal(str(ans["freeLine"]["qty"])) == 2  # 4 - 2
    assert sorted(linked_rows(h)) == sorted([rig.w.so_a, *rig.s5[:2]])


def test_skip_every_bad_line_is_named_with_its_own_code(client, h, gw, rig):
    h.vendor.find("SO", 7006)["Details"][0]["ItemCode"] = "ITEM-Z"
    h.vendor.find("SO", 7006)["Details"][1]["UOM"] = "BOX"
    links = [(7005, rig.s5[0], 1), (7002, 999999, 1), (7006, rig.s6[0], 1), (7006, rig.s6[1], 1),
             (7005, rig.s5[1], 0)]
    r = post(client, gw, rig, links, "sk-2")
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert skipped_of(r) == {999999: "ROW_NOT_FOUND", rig.s6[0]: "ITEM_MISMATCH", rig.s6[1]: "UOM_MISMATCH",
                             rig.s5[1]: "QTY_INVALID"}
    assert [x["soDtlKey"] for x in r.json()["links"]] == [rig.s5[0]]


def test_skip_a_cancelled_so_skips_its_lines_only(client, h, gw, rig):
    h.vendor.find("SO", 7006)["Cancelled"] = "T"
    links = [(7005, rig.s5[0], 1), (7006, rig.s6[0], 1)]
    r = post(client, gw, rig, links, "sk-3")
    assert r.json()["outcome"] == "done", r.text
    assert skipped_of(r) == {rig.s6[0]: "DOC_CANCELLED"}
    assert [x["soDtlKey"] for x in r.json()["links"]] == [rig.s5[0]]


def test_skip_the_line_that_overflows_the_free_quantity_is_skipped_and_later_lines_that_fit_are_linked(
        client, h, gw, rig):
    links = [(7005, rig.s5[0], 3), (7005, rig.s5[1], 2), (7005, rig.s5[2], 1)]  # running 3, 5 (over 4), 4
    r = post(client, gw, rig, links, "sk-4")
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert skipped_of(r) == {rig.s5[1]: "QTY_ABOVE_FREE"}
    assert sorted(x["soDtlKey"] for x in r.json()["links"]) == sorted([rig.s5[0], rig.s5[2]])
    assert [x["DtlKey"] for x in d_rows(puts(h)[0])] == [rig.w.p_free]  # the two linked lines used the whole row
    assert r.json()["freeLine"] is None


# ============================== all bad / PO-level ==============================================

def test_skip_all_lines_bad_is_refused_with_zero_writes_naming_every_line_and_the_key_is_released(
        client, h, gw, rig):
    h.vendor.find("SO", 7005)["Details"][0]["Qty"] = 1
    links = [(7005, rig.s5[0], 2), (7002, 999999, 1)]
    r = post(client, gw, rig, links, "sk-5")
    assert r.status_code in (409, 422) and code(r) == "ALL_LINKS_SKIPPED", r.text
    assert r.json()["outcome"] == "refused"
    assert skipped_of(r) == {rig.s5[0]: "QTY_ABOVE_OUTSTANDING", 999999: "ROW_NOT_FOUND"}
    assert r.json()["links"] == [] and r.json()["freeLine"] is None
    assert h.vendor.writes() == []
    h.vendor.find("SO", 7005)["Details"][0]["Qty"] = 10  # the cause is fixed; the same key runs again
    again = post(client, gw, rig, [(7005, rig.s5[0], 2)], "sk-5")
    assert again.status_code == 200 and again.json()["outcome"] == "done", again.text


def test_po_level_refusals_still_refuse_the_whole_request_with_zero_writes(client, h, gw, rig):
    good = (7005, rig.s5[0], 1)
    h.vendor.find("PO", 7001)["Cancelled"] = "T"
    r = post(client, gw, rig, [good, (7005, rig.s5[1], 1)], "sk-6a")
    assert r.json()["outcome"] == "refused" and code(r) == "DOC_CANCELLED" and h.vendor.writes() == []
    assert r.json()["skipped"] == []
    h.vendor.find("PO", 7001)["Cancelled"] = "F"
    linked_row = client.post(ROUTE, json=rig.body([good, (7005, rig.s5[1], 1)], dtl_key=rig.w.p_linked),
                             headers=gw.hdr("sk-6b"))
    assert code(linked_row) == "ROW_ALREADY_LINKED" and h.vendor.writes() == []
    dup = post(client, gw, rig, [good, good, (7005, rig.s5[1], 1)], "sk-6c")
    assert dup.status_code in (409, 422) and h.vendor.writes() == []
    assert "skipped" in dup.json()


# ============================== the answer shape, vendor refusal, pending, replay ===============

def test_skip_key_is_present_on_every_batch_answer(client, h, gw, rig):
    ok = post(client, gw, rig, rig.three(), "sk-7a")
    assert ok.json()["outcome"] == "done" and ok.json()["skipped"] == []
    conflict = post(client, gw, rig, [(7005, rig.s5[0], 1)], "sk-7a")
    assert code(conflict) == "IDEMPOTENCY_CONFLICT" and conflict.json()["skipped"] == []
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    # the free row is cut by now: the pending case uses the PO's other free row
    pend = client.post(ROUTE, json=rig.body([(7006, rig.s6[0], 1)], dtl_key=rig.w.p_other), headers=gw.hdr("sk-7b"))
    assert pend.json()["outcome"] == "pending_verification" and pend.json()["skipped"] == []


def test_skip_a_vendor_refusal_of_put_1_stays_whole_lists_only_the_pre_check_skips_and_releases_the_key(
        client, h, gw, rig):
    h.vendor.find("SO", 7005)["Details"][2]["Qty"] = 1
    links = [(7005, rig.s5[0], 1), (7005, rig.s5[1], 1), (7005, rig.s5[2], 2)]
    h.vendor.invalid_items = {"ITEM-A"}
    r = post(client, gw, rig, links, "sk-8")
    assert r.status_code == 502 and r.json()["outcome"] == "vendor_error" and code(r) == "VENDOR_REFUSED", r.text
    assert r.json()["links"] == [] and skipped_of(r) == {rig.s5[2]: "QTY_ABOVE_OUTSTANDING"}
    assert len(puts(h)) == 1
    h.vendor.invalid_items = set()
    again = post(client, gw, rig, links, "sk-8")
    assert again.status_code == 200 and again.json()["outcome"] == "done", again.text


def test_skip_pending_reconcile_expects_only_the_applied_lines(h, rig):
    h.vendor.find("SO", 7005)["Details"][2]["Qty"] = 1
    links = [(7005, rig.s5[0], 1), (7005, rig.s5[1], 1), (7005, rig.s5[2], 2)]
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = h.run(OP, rig.params(links), key="sk-9")
    assert first.outcome == "pending_verification", (first.outcome, first.error_code)
    sent = next(c for c in puts(h) if new_rows(c))
    assert len(new_rows(sent)) == 2  # the skipped line was never sent
    h.vendor._edit("PO", sent.body)  # it had landed
    res = h.run(OP, rig.params(links), key="sk-9")
    assert res.outcome == "done", (res.outcome, res.error_code)  # not needs_attention for the "missing" third line
    assert len([c for c in puts(h) if new_rows(c)]) == 1


def test_skip_done_with_skips_locks_the_key_and_replays_links_and_skipped(client, h, gw, rig):
    h.vendor.find("SO", 7005)["Details"][2]["Qty"] = 1
    links = [(7005, rig.s5[0], 1), (7005, rig.s5[1], 1), (7005, rig.s5[2], 2)]
    r1 = post(client, gw, rig, links, "sk-10")
    assert r1.json()["outcome"] == "done"
    calls = len(h.vendor.calls)
    r2 = post(client, gw, rig, links, "sk-10")
    assert r2.status_code == 200 and r2.json()["operationId"] == r1.json()["operationId"]
    assert r2.json()["links"] == r1.json()["links"] and r2.json()["skipped"] == r1.json()["skipped"]
    assert r2.json()["freeLine"] == r1.json()["freeLine"]
    assert len(h.vendor.calls) == calls
