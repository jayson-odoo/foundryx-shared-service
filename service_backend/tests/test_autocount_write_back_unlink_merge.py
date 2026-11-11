"""Plan 62 S3 (RED): the unlink merge, AC-62-30 / 31 (plan D7).

Unlinking a linked PO row looks for a FREE row on the same PO with the same ItemCode, UOM, Location,
UnitPrice and DeliveryDate (not linked, not transferred onward, nothing received). Found -> ONE PUT
[linked row "D", free row with Qty + freed qty] and the answer names the free row's DtlKey; none -> today's
one PUT [linked row "D", new free row]. Applies to ``unlink_row`` and ``/po-links/unlink``; relink is unchanged.

World PO 7001 rows (all ITEM-A / UNIT / BR1 / 5.0 / 2026-12-01, Qty 4): ``p_free`` (free), ``p_linked``
(linked to ``so_a``), ``p_spo`` (an SPO row points at it = transferred onward), ``p_other`` (free). With
several matching free rows the FIRST by row order wins: ``p_free``; ``p_spo`` is never a candidate.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, List

import pytest

from app.main import app  # noqa: F401
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

UNLINK = f"{PREFIX}/po-links/unlink"
FIELDS = ("ItemCode", "UOM", "Location", "UnitPrice", "DeliveryDate")
DIFFERENT = {"ItemCode": "ITEM-Z", "UOM": "BOX", "Location": "BR9", "UnitPrice": 9.5,
             "DeliveryDate": "2027-01-15T00:00:00"}


@pytest.fixture
def world(h):
    h.delete_on()
    return World(h)


@pytest.fixture
def gw(h, db, world):
    return Gw(h, db)


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def d_rows(call):
    return [r for r in call.body["Details"] if r.get("FullTransferOption") == "D"]


def new_rows(call):
    return [r for r in call.body["Details"] if r["DtlKey"] == 0]


def row(h, key):
    return next((r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == key), None)


def qty(r) -> Decimal:
    return Decimal(str(r["Qty"]))


def mutate(h, keys, **fields):
    for key in keys:
        row(h, key).update(fields)


def assert_todays_unlink(h, world, before_keys):
    """One PUT, the linked row "D", a NEW free row (DtlKey 0), no existing free row touched."""
    sent = puts(h)
    assert len(sent) == 1
    assert [r["DtlKey"] for r in d_rows(sent[0])] == [world.p_linked]
    assert len(new_rows(sent[0])) == 1 and qty(new_rows(sent[0])[0]) == 4
    assert row(h, world.p_linked) is None
    after = {r["DtlKey"] for r in h.vendor.rows("PO", 7001)}
    assert len(after) == len(before_keys) and before_keys - {world.p_linked} <= after


def keys_before(h):
    return {r["DtlKey"] for r in h.vendor.rows("PO", 7001)}


# ============================== AC-62-30 merge ==================================================

def test_ac_62_30_unlink_merges_into_the_first_matching_free_row_with_one_put(h, world):
    res = h.run("unlink_row", world.params["unlink_row"], key="m-1")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    sent = puts(h)
    assert len(sent) == 1
    assert [r["DtlKey"] for r in d_rows(sent[0])] == [world.p_linked]
    assert new_rows(sent[0]) == []  # no new row: the free row is raised instead
    raised = [r for r in sent[0].body["Details"] if r["DtlKey"] == world.p_free]
    assert len(raised) == 1 and qty(raised[0]) == Decimal(8)  # 4 free + 4 freed
    assert res.replaced_lines == [(world.p_linked, world.p_free)]  # the answer names the free row
    assert row(h, world.p_linked) is None
    assert qty(row(h, world.p_free)) == Decimal(8)
    assert len(h.vendor.rows("PO", 7001)) == 3  # one row fewer than before
    assert "LOCATION_NOT_MOVED" not in res.warnings


def test_ac_62_30_merge_leaves_the_other_free_row_and_the_spo_row_alone(h, world):
    h.run("unlink_row", world.params["unlink_row"], key="m-2")
    assert qty(row(h, world.p_other)) == Decimal(4)
    assert qty(row(h, world.p_spo)) == Decimal(4)


def test_ac_62_30_with_several_matches_the_first_by_row_order_wins_and_an_spo_target_is_skipped(h, world):
    mutate(h, [world.p_free], UnitPrice=9.5)  # the first free row no longer matches ...
    res = h.run("unlink_row", world.params["unlink_row"], key="m-3")
    assert res.outcome == "done"
    # ... p_spo is next in row order but an SPO row points at it, so p_other takes the qty
    assert res.replaced_lines == [(world.p_linked, world.p_other)]
    assert qty(row(h, world.p_other)) == Decimal(8) and qty(row(h, world.p_spo)) == Decimal(4)
    assert len(puts(h)) == 1


def test_ac_62_30_the_unlinked_qty_leaves_the_so_row(h, world):
    h.run("unlink_row", world.params["unlink_row"], key="m-4")
    assert all(r.get("FromSODtlKey") != world.so_a for r in h.vendor.rows("PO", 7001))


def test_ac_62_30_route_answer_names_the_free_rows_dtl_key(client, h, gw, world):
    r = client.post(UNLINK, headers=gw.hdr("m-route"),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done"
    assert r.json()["replacedLines"] == [{"oldDtlKey": world.p_linked, "newDtlKey": world.p_free}]
    assert len(puts(h)) == 1 and new_rows(puts(h)[0]) == []
    assert qty(row(h, world.p_free)) == Decimal(8)


def test_ac_62_30_relink_is_unchanged_it_still_replaces_with_a_new_linked_row(h, world):
    res = h.run("relink_row", world.params["relink_row"], key="m-relink")
    assert res.outcome == "done"
    first = puts(h)[0]
    assert [r["DtlKey"] for r in d_rows(first)] == [world.p_linked] and len(new_rows(first)) == 1
    assert qty(row(h, world.p_free)) == Decimal(4)  # its freed qty went to the new SO row, not a free row


# ============================== AC-62-31 no merge ===============================================

@pytest.mark.parametrize("field", FIELDS)
def test_ac_62_31_a_field_that_differs_on_every_candidate_means_no_merge(h, world, field):
    mutate(h, [world.p_free, world.p_spo, world.p_other], **{field: DIFFERENT[field]})
    before = keys_before(h)
    res = h.run("unlink_row", world.params["unlink_row"], key=f"m-diff-{field}")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    assert_todays_unlink(h, world, before)
    assert qty(row(h, world.p_free)) == Decimal(4) and qty(row(h, world.p_other)) == Decimal(4)


def test_ac_62_31_a_linked_free_row_candidate_is_never_merged_into(h, world):
    mutate(h, [world.p_free, world.p_other], FromSODtlKey=world.so_b, FromDocDtlKey=world.so_b)
    mutate(h, [world.p_spo], UnitPrice=9.5)
    before = keys_before(h)
    res = h.run("unlink_row", world.params["unlink_row"], key="m-linked")
    assert res.outcome == "done"
    assert_todays_unlink(h, world, before)
    assert qty(row(h, world.p_free)) == Decimal(4)


def test_ac_62_31_a_row_an_spo_points_at_is_never_merged_into(h, world):
    mutate(h, [world.p_free, world.p_other], UnitPrice=9.5)  # p_spo is the only matching row
    before = keys_before(h)
    res = h.run("unlink_row", world.params["unlink_row"], key="m-spo")
    assert res.outcome == "done"
    assert_todays_unlink(h, world, before)
    assert qty(row(h, world.p_spo)) == Decimal(4)


def test_ac_62_31_a_received_free_row_is_never_merged_into(h, world):
    free_rows = {world.p_free, world.p_spo, world.p_other}

    def reader(kind, doc, r):  # the free rows have receipts; the row being unlinked has none
        return Decimal(1) if r.get("DtlKey") in free_rows else Decimal(0)

    before = keys_before(h)
    res = h.run("unlink_row", world.params["unlink_row"], key="m-recv", receipt_reader=reader)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert_todays_unlink(h, world, before)
    assert qty(row(h, world.p_free)) == Decimal(4)


def test_ac_62_31_a_free_row_the_vendor_marks_received_is_never_merged_into(h, world):
    h.vendor.mark_received("PO", 7001, world.p_free)
    h.vendor.mark_received("PO", 7001, world.p_other)
    mutate(h, [world.p_spo], UnitPrice=9.5)
    before = keys_before(h)
    res = h.run("unlink_row", world.params["unlink_row"], key="m-recv2")
    assert res.outcome == "done"
    assert_todays_unlink(h, world, before)


def test_ac_62_31_route_without_a_match_answers_the_new_free_row_key(client, h, gw, world):
    mutate(h, [world.p_free, world.p_spo, world.p_other], UnitPrice=9.5)
    r = client.post(UNLINK, headers=gw.hdr("m-route2"),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    pair = r.json()["replacedLines"]
    assert len(pair) == 1 and pair[0]["oldDtlKey"] == world.p_linked
    assert pair[0]["newDtlKey"] not in (world.p_free, world.p_spo, world.p_other)
    assert len(puts(h)) == 1 and len(new_rows(puts(h)[0])) == 1
