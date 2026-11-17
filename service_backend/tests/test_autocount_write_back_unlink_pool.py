"""Plan 66 (RED, lane UNLINK-RETURN-POOL): an unlink returns the freed qty to the company's pool location.

Owner 17 Nov: the unlinked qty goes back to the pool. Rules (owner answers Q1/Q2/Q3/Q5, crew Q4):
Q1: the pool is the one the CRM project location is configured to come from; the caller sends it as
    ``poolLocation`` on ``/po-links/unlink`` (``pool_location`` on ``unlink_row``), an exact Location code.
1. Merge: a FREE row on the same PO AT THE POOL LOCATION with the same ItemCode + UOM (+ UnitPrice, kept until crew
   confirms) - NOT the delivery date (it is the SO's; irrelevant once unlinked) - not linked, no SPO row, no receipt,
   takes the qty: ONE PUT [linked row "D", pool row raised]; the pool row keeps its own date.
2. Otherwise: today's replace PUT, then the move puts the new free row at the POOL location (price + date as today).
3. A partly received row: the received part stays where it is; the remaining qty's new row goes to the pool.
4. No pool location sent = exactly today's behaviour (plan 62 D7 same-location merge).
Relink frees nothing: unchanged.

World PO 7001 (ITEM-A / UNIT / 5.0 / 2026-12-01, Qty 4): ``p_free`` BR1 free (today's same-location merge
target), ``p_linked`` BR1 linked to ``so_a``, ``p_spo`` BR1 (an SPO row points at it), ``p_other`` moved to the
pool location BRW, free. The pool location rides the call (``params`` / the route's ``poolLocation``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Optional

import pytest

from app.main import app  # noqa: F401
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

UNLINK = f"{PREFIX}/po-links/unlink"
POOL = "BRW"


def unlink(h, world, key, pool: Optional[str] = POOL, **kw):
    params = dict(world.params["unlink_row"])
    if pool is not None:
        params["pool_location"] = pool
    return h.run("unlink_row", params, key=key, **kw)


@pytest.fixture
def world(h, db):
    h.delete_on()
    w = World(h)
    h.vendor.find("PO", 7001)["Details"][1]["UnitPrice"] = 5.0  # the linked row matches the free rows' price
    row(h, w.p_other)["Location"] = POOL
    return w


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


def new_free_row(h, world, before):
    added = [r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] not in before]
    assert len(added) == 1, added
    return added[0]


def keys_before(h):
    return {r["DtlKey"] for r in h.vendor.rows("PO", 7001)}


# ============================== rule 1: merge into the pool row =================================

def test_unlink_merges_into_the_free_pool_row_not_the_same_location_row(h, world):
    res = unlink(h, world, "p-1")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    sent = puts(h)
    assert len(sent) == 1  # one PUT, no move
    assert [r["DtlKey"] for r in d_rows(sent[0])] == [world.p_linked]
    assert new_rows(sent[0]) == []
    assert res.replaced_lines == [(world.p_linked, world.p_other)]
    assert qty(row(h, world.p_other)) == Decimal(8) and row(h, world.p_other)["Location"] == POOL
    assert qty(row(h, world.p_free)) == Decimal(4)  # the BR1 free row is not the pool
    assert row(h, world.p_linked) is None


def test_route_answer_names_the_pool_row(client, h, gw, world):
    r = client.post(UNLINK, headers=gw.hdr("p-route"),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "poolLocation": POOL})
    assert r.status_code == 200, r.text
    assert r.json()["replacedLines"] == [{"oldDtlKey": world.p_linked, "newDtlKey": world.p_other}]
    detail = r.json()["detail"]  # Q5: the CRM words "Qty returned to <pool>" from the row the qty went to
    assert detail["DtlKey"] == world.p_other and detail["Location"] == POOL
    assert qty(row(h, world.p_other)) == Decimal(8)


def test_route_moved_row_detail_is_at_the_pool(client, h, gw, world):
    row(h, world.p_other)["Location"] = "BR1"
    r = client.post(UNLINK, headers=gw.hdr("p-route-move"),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "poolLocation": POOL})
    assert r.status_code == 200, r.text
    assert r.json()["detail"]["Location"] == POOL
    assert r.json()["detail"]["DtlKey"] == r.json()["replacedLines"][0]["newDtlKey"]


def test_route_without_pool_location_is_todays_unlink(client, h, gw, world):
    r = client.post(UNLINK, headers=gw.hdr("p-route-off"),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 200, r.text
    assert r.json()["replacedLines"] == [{"oldDtlKey": world.p_linked, "newDtlKey": world.p_free}]


def test_route_rejects_a_non_text_pool_location(client, h, gw, world):
    r = client.post(UNLINK, headers=gw.hdr("p-route-bad"),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "poolLocation": 7})
    assert r.status_code == 422, r.text
    assert puts(h) == []


def test_pool_location_is_part_of_the_idempotency_body(h, world):
    first = unlink(h, world, "p-idem")
    assert first.outcome == "done"
    again = unlink(h, world, "p-idem", pool="BR1")  # same key, different body
    assert again.outcome != "done" or again.error_code == "IDEMPOTENCY_CONFLICT"
    assert len(puts(h)) == 1


# ============================== rule 2: no pool row -> move to the pool ========================

def _assert_moved_to_pool(h, world, before, res):
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    assert "LOCATION_NOT_MOVED" not in res.warnings
    added = new_free_row(h, world, before)
    assert added["Location"] == POOL
    assert qty(added) == Decimal(4)
    assert Decimal(str(added["UnitPrice"])) == Decimal("5.0")
    assert str(added["DeliveryDate"]).startswith("2026-12-01")  # Q3: as today, the unlinked row's date
    assert not (added.get("FromSODtlKey") or added.get("FromDocDtlKey"))
    assert row(h, world.p_linked) is None
    assert res.replaced_lines == [(world.p_linked, added["DtlKey"])]
    return added


def test_no_pool_row_on_the_po_moves_the_unlinked_row_to_the_pool(h, world):
    row(h, world.p_other)["Location"] = "BR1"  # no row at the pool location any more
    before = keys_before(h)
    res = unlink(h, world, "p-none")
    _assert_moved_to_pool(h, world, before, res)
    assert qty(row(h, world.p_free)) == Decimal(4)  # same-location BR1 free row NOT merged into


def test_a_linked_pool_row_is_not_merged_into_and_the_row_goes_to_the_pool(h, world):
    row(h, world.p_other).update(FromSODtlKey=world.so_b, FromDocDtlKey=world.so_b)
    before = keys_before(h)
    res = unlink(h, world, "p-linked")
    _assert_moved_to_pool(h, world, before, res)
    assert qty(row(h, world.p_other)) == Decimal(4)


def test_a_pool_row_with_another_delivery_date_is_still_merged_into_and_keeps_its_date(h, world):
    """Q2/Q3 (owner): the delivery date is the SO's, irrelevant once unlinked: not part of the match."""
    row(h, world.p_other)["DeliveryDate"] = "2027-01-15T00:00:00"
    res = unlink(h, world, "p-date")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    assert res.replaced_lines == [(world.p_linked, world.p_other)]
    assert qty(row(h, world.p_other)) == Decimal(8)
    assert str(row(h, world.p_other)["DeliveryDate"]).startswith("2027-01-15")
    assert len(puts(h)) == 1


@pytest.mark.parametrize("field,value", [("UnitPrice", 5.5), ("UOM", "BOX"), ("ItemCode", "ITEM-Z")])
def test_a_pool_row_that_differs_is_not_merged_into(h, world, field, value):
    """Q2: item + UOM must match (unit price kept in the match until crew confirms); else rule 2."""
    row(h, world.p_other)[field] = value
    before = keys_before(h)
    res = unlink(h, world, f"p-diff-{field}")
    _assert_moved_to_pool(h, world, before, res)
    assert qty(row(h, world.p_other)) == Decimal(4)


def test_pool_code_is_exact_brw_bb_is_not_brw(h, world):
    row(h, world.p_other)["Location"] = "BRW-BB"
    before = keys_before(h)
    res = unlink(h, world, "p-exact")
    _assert_moved_to_pool(h, world, before, res)
    assert qty(row(h, world.p_other)) == Decimal(4)


def test_a_pool_row_an_spo_points_at_is_not_merged_into(h, world):
    row(h, world.p_other)["Location"] = "BR1"
    row(h, world.p_spo)["Location"] = POOL  # the only pool row, but an SPO row takes it
    before = keys_before(h)
    res = unlink(h, world, "p-spo")
    _assert_moved_to_pool(h, world, before, res)
    assert qty(row(h, world.p_spo)) == Decimal(4)


def test_a_received_pool_row_is_not_merged_into(h, world):
    def reader(kind, doc, r):
        return Decimal(1) if r.get("DtlKey") == world.p_other else Decimal(0)

    before = keys_before(h)
    res = unlink(h, world, "p-recv", receipt_reader=reader)
    _assert_moved_to_pool(h, world, before, res)


def test_the_linked_row_already_at_the_pool_still_ends_at_the_pool(h, world):
    row(h, world.p_linked)["Location"] = POOL
    row(h, world.p_other)["Location"] = "BR1"
    before = keys_before(h)
    res = unlink(h, world, "p-at-pool")
    _assert_moved_to_pool(h, world, before, res)


# ============================== rule 3: partly received ========================================

def test_partly_received_row_keeps_the_received_part_and_sends_the_rest_to_the_pool(h, world):
    def reader(kind, doc, r):
        return Decimal(1) if r.get("DtlKey") == world.p_linked else Decimal(0)

    res = unlink(h, world, "p-part", receipt_reader=reader)
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    cut = row(h, world.p_linked)
    assert cut is not None and qty(cut) == Decimal(1) and cut["Location"] == "BR1"
    rest = [r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] not in
            {world.p_free, world.p_linked, world.p_spo, world.p_other}]
    assert len(rest) == 1 and qty(rest[0]) == Decimal(3) and rest[0]["Location"] == POOL
    assert qty(row(h, world.p_other)) == Decimal(4)  # partial: no merge (today's rule)


# ============================== rule 4: setting off = today ====================================

@pytest.mark.parametrize("off", [None, "", "  "])
def test_no_pool_location_sent_is_todays_same_location_merge(h, world, off):
    res = unlink(h, world, f"p-off-{off!r}", pool=off)
    assert res.outcome == "done"
    assert res.replaced_lines == [(world.p_linked, world.p_free)]  # plan 62 D7, BR1 row
    assert qty(row(h, world.p_free)) == Decimal(8) and qty(row(h, world.p_other)) == Decimal(4)


def test_relink_ignores_a_pool_location(h, world):
    res = h.run("relink_row", dict(world.params["relink_row"], pool_location=POOL), key="p-relink")
    assert res.outcome == "done"
    assert qty(row(h, world.p_other)) == Decimal(4)
    assert all(r["Location"] != POOL for r in h.vendor.rows("PO", 7001) if r["DtlKey"] != world.p_other)
