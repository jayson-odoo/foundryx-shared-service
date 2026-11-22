"""Plan 71 (RED, lane UNLINK-RETURN-TO-SOURCE-SS): an unlink returns the freed qty to the PO row it came from.

Owner 20 Nov: "the unlink ... should return to whatever line it linked from, for example this case is HQ".
The CRM sends ``returnToDtlKey`` on ``/po-links/unlink`` (``return_to_dtl_key`` on ``unlink_row``): the PO row
the qty was linked FROM.

1. Usable source row (same PO, open, same ItemCode + UOM, not tied to an SO, no SPO row, no unresolved op):
   ONE PUT [tied row "D", source row raised by the tied qty]; the source row keeps its own location, price
   and date. No move step. ``detail`` = the source row, ``replacedLines`` = [] and ``returnedTo`` =
   {fromDtlKey, toDtlKey, qty, location} (CRM SS contract). Read-back is exact: the source row's Location,
   DeliveryDate and link equal its own before-image.
2. Not usable (or not found): today's pool behaviour (plan 66 / plan 62 D7) runs and ``warnings`` carries
   ``RETURN_SOURCE_NOT_OPEN`` (CRM SS contract, sorento-crm#2607: one code), no ``returnedTo``.
3. No ``returnToDtlKey`` = exactly today's request, hash and body.

World PO 7001 (see ``World``): ``p_linked`` BR1 tied to ``so_a`` (price 5.5), ``p_other`` = the source row,
moved to HQ here; ``p_free`` BR1 free; ``p_spo`` BR1 (an SPO row points at it). Pool = BRW, no pool row.
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
SOURCE_LOC = "HQ"


@pytest.fixture
def world(h, db):
    h.delete_on()
    w = World(h)
    row(h, w.p_other)["Location"] = SOURCE_LOC
    return w


@pytest.fixture
def gw(h, db, world):
    return Gw(h, db)


def unlink(h, world, key, return_to: Optional[int], pool: Optional[str] = POOL, **kw):
    params = dict(world.params["unlink_row"])
    if pool is not None:
        params["pool_location"] = pool
    if return_to is not None:
        params["return_to_dtl_key"] = return_to
    return h.run("unlink_row", params, key=key, **kw)


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def row(h, key):
    return next((r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == key), None)


def qty(r) -> Decimal:
    return Decimal(str(r["Qty"]))


def keys_before(h):
    return {r["DtlKey"] for r in h.vendor.rows("PO", 7001)}


def added_rows(h, before):
    return [r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] not in before]


# ============================== rule 1: merge back into the source row ===========================

def test_unlink_merges_the_qty_back_into_the_source_row_in_one_put(h, world):
    res = unlink(h, world, "r-1", world.p_other)
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    sent = puts(h)
    assert len(sent) == 1  # one PUT, no move
    assert [r["DtlKey"] for r in sent[0].body["Details"] if r.get("FullTransferOption") == "D"] == [world.p_linked]
    assert [r for r in sent[0].body["Details"] if r["DtlKey"] == 0] == []
    assert res.replaced_lines == []
    assert res.returned_to == {"fromDtlKey": world.p_linked, "toDtlKey": world.p_other, "qty": 4,
                               "location": SOURCE_LOC}
    src = row(h, world.p_other)
    assert qty(src) == Decimal(8)
    assert src["Location"] == SOURCE_LOC  # the source location, not the pool
    assert Decimal(str(src["UnitPrice"])) == Decimal("5.0")  # its own price, not the tied row's 5.5
    assert row(h, world.p_linked) is None
    assert res.warnings == []


def test_the_source_row_wins_over_a_pool_row(h, world):
    row(h, world.p_free)["Location"] = POOL  # a merge-able pool row exists too
    res = unlink(h, world, "r-pool-too", world.p_other)
    assert res.outcome == "done"
    assert res.replaced_lines == [] and res.returned_to["toDtlKey"] == world.p_other
    assert qty(row(h, world.p_free)) == Decimal(4)


def test_no_pool_location_sent_still_returns_to_the_source(h, world):
    res = unlink(h, world, "r-nopool", world.p_other, pool=None)
    assert res.outcome == "done"
    assert res.replaced_lines == [] and res.returned_to["toDtlKey"] == world.p_other
    assert qty(row(h, world.p_other)) == Decimal(8)


def test_a_partly_received_source_row_is_still_open_and_takes_the_qty(h, world):
    def reader(kind, doc, r):
        return Decimal(1) if r.get("DtlKey") == world.p_other else Decimal(0)

    res = unlink(h, world, "r-src-part", world.p_other, receipt_reader=reader)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert res.replaced_lines == [] and res.returned_to["toDtlKey"] == world.p_other
    assert res.warnings == []


def test_an_unknown_receipt_on_the_source_row_still_takes_the_qty(h, world):
    def reader(kind, doc, r):
        return None if r.get("DtlKey") == world.p_other else Decimal(0)

    res = unlink(h, world, "r-src-unknown", world.p_other, receipt_reader=reader)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert res.replaced_lines == [] and res.returned_to["toDtlKey"] == world.p_other
    assert qty(row(h, world.p_other)) == Decimal(8)


def test_route_answer_names_the_source_row(client, h, gw, world):
    r = client.post(UNLINK, headers=gw.hdr("r-route"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked,
        "poolLocation": POOL, "returnToDtlKey": world.p_other})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["replacedLines"] == []
    assert body["returnedTo"] == {"fromDtlKey": world.p_linked, "toDtlKey": world.p_other, "qty": 4,
                                  "location": SOURCE_LOC}
    assert body["detail"]["DtlKey"] == world.p_other and body["detail"]["Location"] == SOURCE_LOC
    assert body["detail"]["Qty"] == 8
    assert body["warnings"] == []
    assert world.p_linked not in [d["DtlKey"] for d in body["document"]["Details"]]


def test_route_replay_returns_the_stored_returned_to(client, h, gw, world):
    req = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked,
           "poolLocation": POOL, "returnToDtlKey": world.p_other}
    first = client.post(UNLINK, headers=gw.hdr("r-route-replay"), json=req).json()
    again = client.post(UNLINK, headers=gw.hdr("r-route-replay"), json=req)
    assert again.status_code == 200, again.text
    assert again.json()["returnedTo"] == first["returnedTo"]
    assert len(puts(h)) == 1


def test_route_fallback_answer_has_the_warning_and_no_returned_to(client, h, gw, world):
    r = client.post(UNLINK, headers=gw.hdr("r-route-fb"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked,
        "poolLocation": POOL, "returnToDtlKey": 999999})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["warnings"] == ["RETURN_SOURCE_NOT_OPEN"]
    assert "returnedTo" not in body
    assert body["detail"]["Location"] == POOL


def test_route_without_return_to_has_no_returned_to(client, h, gw, world):
    r = client.post(UNLINK, headers=gw.hdr("r-route-plain"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "poolLocation": POOL})
    assert r.status_code == 200, r.text
    assert "returnedTo" not in r.json()


@pytest.mark.parametrize("field,value", [("Location", "BRW-NTC"), ("DeliveryDate", "0001-01-01T00:00:00"),
                                         ("FromSODtlKey", 46340001)])
def test_source_row_read_back_must_match_its_own_before_image(h, world, monkeypatch, field, value):
    """Contract read-back: the source row's Location / DeliveryDate / link equal ITS before-image (sorento-crm
    #2603 saw AutoCount re-derive these from a tied SO line right after the PUT): any drift is a mismatch."""
    real = h.vendor._route

    def route(method, leaf, call):
        resp = real(method, leaf, call)
        if method == "PUT":
            row(h, world.p_other)[field] = value
        return resp

    monkeypatch.setattr(h.vendor, "_route", route)
    res = unlink(h, world, f"r-drift-{field}", world.p_other)
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert res.returned_to is None


def test_route_answer_carries_detail_with_return_to_and_no_pool(client, h, gw, world):
    r = client.post(UNLINK, headers=gw.hdr("r-route-nopool"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "returnToDtlKey": world.p_other})
    assert r.status_code == 200, r.text
    assert r.json()["detail"]["DtlKey"] == world.p_other


@pytest.mark.parametrize("bad", ["12", 1.5, True, 0, -3])
def test_route_rejects_a_bad_return_to_dtl_key(client, h, gw, world, bad):
    r = client.post(UNLINK, headers=gw.hdr(f"r-route-bad-{bad}"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "returnToDtlKey": bad})
    assert r.status_code == 422, r.text
    assert puts(h) == []


def test_route_null_return_to_is_todays_unlink(client, h, gw, world):
    r = client.post(UNLINK, headers=gw.hdr("r-route-null"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "returnToDtlKey": None})
    assert r.status_code == 200, r.text
    assert "detail" not in r.json()


def test_return_to_is_part_of_the_idempotency_body(h, world):
    first = unlink(h, world, "r-idem", world.p_other)
    assert first.outcome == "done"
    again = unlink(h, world, "r-idem", world.p_free)
    assert again.error_code == "IDEMPOTENCY_CONFLICT", (again.outcome, again.error_code)
    assert len(puts(h)) == 1


def test_resume_of_a_pending_return_merge_answers_the_source_row(h, world):
    from app.models import DEFAULT_TENANT_ID

    h.vendor.apply_then_500_next("PUT", "EditPurchaseOrderbydockey")  # the merge landed, answered 500
    res = unlink(h, world, "r-resume", world.p_other)
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    out = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)
    assert out.outcome == "done", (out.outcome, out.error_code)
    assert out.replaced_lines == []
    assert out.returned_to == {"fromDtlKey": world.p_linked, "toDtlKey": world.p_other, "qty": 4,
                               "location": SOURCE_LOC}
    assert out.detail and out.detail["DtlKey"] == world.p_other


# ============================== rule 2: not usable -> pool + warning ============================

def _assert_fell_back_to_pool(h, world, before, res, code):
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    assert code in res.warnings, res.warnings
    added = added_rows(h, before)
    assert len(added) == 1 and added[0]["Location"] == POOL and qty(added[0]) == Decimal(4)
    assert row(h, world.p_linked) is None


def test_unknown_return_row_falls_back_to_the_pool_with_a_warning(h, world):
    before = keys_before(h)
    res = unlink(h, world, "r-404", 999999)
    _assert_fell_back_to_pool(h, world, before, res, "RETURN_SOURCE_NOT_OPEN")
    assert qty(row(h, world.p_other)) == Decimal(4)


def test_the_tied_row_itself_is_not_a_return_row(h, world):
    before = keys_before(h)
    res = unlink(h, world, "r-self", world.p_linked)
    _assert_fell_back_to_pool(h, world, before, res, "RETURN_SOURCE_NOT_OPEN")


def test_a_source_row_tied_to_another_so_falls_back(h, world):
    row(h, world.p_other).update(FromDocType="SO", FromDocNo="SO-7002", FromDocDtlKey=world.so_b,
                                 FromSODtlKey=world.so_b)
    before = keys_before(h)
    res = unlink(h, world, "r-tied", world.p_other)
    _assert_fell_back_to_pool(h, world, before, res, "RETURN_SOURCE_NOT_OPEN")
    assert qty(row(h, world.p_other)) == Decimal(4)


@pytest.mark.parametrize("field,value", [("ItemCode", "ITEM-B"), ("UOM", "BOX")])
def test_a_source_row_of_another_item_or_unit_falls_back(h, world, field, value):
    row(h, world.p_other)[field] = value
    before = keys_before(h)
    res = unlink(h, world, f"r-item-{field}", world.p_other)
    _assert_fell_back_to_pool(h, world, before, res, "RETURN_SOURCE_NOT_OPEN")


def test_a_fully_received_source_row_falls_back(h, world):
    def reader(kind, doc, r):
        return Decimal(4) if r.get("DtlKey") == world.p_other else Decimal(0)

    before = keys_before(h)
    res = unlink(h, world, "r-closed", world.p_other, receipt_reader=reader)
    _assert_fell_back_to_pool(h, world, before, res, "RETURN_SOURCE_NOT_OPEN")


def test_a_source_row_an_spo_points_at_falls_back(h, world):
    row(h, world.p_spo)["Location"] = SOURCE_LOC
    before = keys_before(h)
    res = unlink(h, world, "r-spo", world.p_spo)
    _assert_fell_back_to_pool(h, world, before, res, "RETURN_SOURCE_NOT_OPEN")
    assert qty(row(h, world.p_spo)) == Decimal(4)


def test_a_source_row_an_unresolved_link_op_covers_falls_back(h, world, monkeypatch):
    """Plan 65 R1: growing a row an unresolved link operation covers breaks that operation's Resume."""
    from modules.autocount.write_back.primitives import PrimitiveService

    real = PrimitiveService.row_needs_attention

    def covered(self, company, doc_key, r, *, exclude_id=None):
        return r.get("DtlKey") == world.p_other or real(self, company, doc_key, r, exclude_id=exclude_id)

    monkeypatch.setattr(PrimitiveService, "row_needs_attention", covered)
    before = keys_before(h)
    res = unlink(h, world, "r-busy", world.p_other)
    _assert_fell_back_to_pool(h, world, before, res, "RETURN_SOURCE_NOT_OPEN")
    assert qty(row(h, world.p_other)) == Decimal(4)


def test_a_resumed_fallback_still_says_why(h, world):
    from app.models import DEFAULT_TENANT_ID

    h.vendor.apply_then_500_next("PUT", "EditPurchaseOrderbydockey")  # the pool replace landed, answered 500
    res = unlink(h, world, "r-fb-resume", 999999)
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    out = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)
    assert out.outcome == "done", (out.outcome, out.error_code, out.message)
    assert "RETURN_SOURCE_NOT_OPEN" in out.warnings


def test_fallback_without_pool_is_todays_same_location_merge_plus_the_warning(h, world):
    before = keys_before(h)
    res = unlink(h, world, "r-fb-nopool", 999999, pool=None)
    assert res.outcome == "done"
    assert "RETURN_SOURCE_NOT_OPEN" in res.warnings
    added = added_rows(h, before)  # today's replace (the tied row's 5.5 price matches no free row, plan 62)
    assert len(added) == 1 and added[0]["Location"] == "BR1"
    assert res.replaced_lines == [(world.p_linked, added[0]["DtlKey"])]


def test_a_partly_received_tied_row_falls_back_to_cut_and_pool(h, world):
    def reader(kind, doc, r):
        return Decimal(1) if r.get("DtlKey") == world.p_linked else Decimal(0)

    res = unlink(h, world, "r-tied-part", world.p_other, receipt_reader=reader)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert "RETURN_SOURCE_NOT_OPEN" in res.warnings
    assert qty(row(h, world.p_other)) == Decimal(4)  # untouched
    cut = row(h, world.p_linked)
    assert cut is not None and qty(cut) == Decimal(1)


# ============================== rule 3: absent = today ==========================================

def test_relink_ignores_a_return_to(h, world):
    def reader(kind, doc, r):  # a partly received row: a relink must not pick up RETURN_PARTLY_RECEIVED
        return Decimal(1) if r.get("DtlKey") == world.p_linked else Decimal(0)

    params = dict(world.params["relink_row"], return_to_dtl_key=world.p_other)
    res = h.run("relink_row", params, key="r-relink", receipt_reader=reader)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert not [w for w in res.warnings if w.startswith("RETURN_")], res.warnings
    assert qty(row(h, world.p_other)) == Decimal(4)


def test_no_return_to_unlink_params_are_todays():
    from modules.autocount.write_back.service import WriteBackService

    seen = {}

    class Ops:
        def run(self, **kw):
            seen.update(kw)
            raise RuntimeError("stop")

    with pytest.raises(RuntimeError):
        WriteBackService.__new__(WriteBackService).unlink(tenant_id="t", company_id="c", po_doc_key=1, po_dtl_key=2,
                                                           operations=Ops(), idempotency_key="k")
    assert "return_to_dtl_key" not in seen["params"]
    with pytest.raises(RuntimeError):
        WriteBackService.__new__(WriteBackService).unlink(tenant_id="t", company_id="c", po_doc_key=1, po_dtl_key=2,
                                                           operations=Ops(), idempotency_key="k",
                                                           return_to_dtl_key=9)
    assert seen["params"]["return_to_dtl_key"] == 9


def test_resume_of_a_return_merge_whose_source_row_drifted_needs_attention(h, world):
    """Contract read-back on Resume: the merge landed (500), then the source row's Location no longer equals its
    before-image (AutoCount re-derived it): Resume never answers done."""
    from app.models import DEFAULT_TENANT_ID

    h.vendor.apply_then_500_next("PUT", "EditPurchaseOrderbydockey")
    res = unlink(h, world, "r-resume-drift", world.p_other)
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    row(h, world.p_other)["Location"] = "BRW-NTC"
    out = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)
    assert out.outcome == "needs_attention", (out.outcome, out.error_code)
    assert out.returned_to is None


@pytest.mark.parametrize("field,before,after", [
    ("Description", None, ""), ("Description", "", None),
    ("DeliveryDate", "2026-12-01T00:00:00", "2026-12-01"), ("DeliveryDate", None, "0001-01-01T00:00:00"),
    ("UnitPrice", 1.5, "1.50"), ("UnitPrice", "5", 5.0),
])
def test_merge_row_drift_ignores_a_read_spelling_the_same_value_differently(field, before, after):
    """Review: a plan 62 / 66 / 71 merge that landed must not read as drift because AutoCount spells a value
    differently (null vs empty, date format, number type)."""
    from modules.autocount.write_back.payloads import merge_row_drift

    assert merge_row_drift("PO", {field: before, "Location": "HQ"}, {field: after, "Location": "HQ"}) == []


@pytest.mark.parametrize("field,before,after", [
    ("Location", "HQ", "BRW-NTC"), ("DeliveryDate", "2026-10-06T00:00:00", "0001-01-01T00:00:00"),
    ("UnitPrice", 5, "5.5"), ("Description", "a", "b"),
])
def test_merge_row_drift_names_a_real_change(field, before, after):
    from modules.autocount.write_back.payloads import merge_row_drift

    assert merge_row_drift("PO", {field: before}, {field: after}) == [field]


def test_merge_row_drift_names_a_new_link():
    from modules.autocount.write_back.payloads import merge_row_drift

    assert merge_row_drift("PO", {"FromSODtlKey": 0}, {"FromSODtlKey": 46340001}) == ["FromSODtlKey"]
    assert merge_row_drift("PO", {"FromSODtlKey": None}, {"FromSODtlKey": 0}) == []


def test_a_resumed_partly_received_tied_row_fallback_still_says_why(h, world):
    from app.models import DEFAULT_TENANT_ID

    def reader(kind, doc, r):
        return Decimal(1) if r.get("DtlKey") == world.p_linked else Decimal(0)

    h.vendor.apply_then_500_next("PUT", "EditPurchaseOrderbydockey")
    res = unlink(h, world, "r-part-resume", world.p_other, receipt_reader=reader)
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    out = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)
    assert "RETURN_SOURCE_NOT_OPEN" in out.warnings, (out.outcome, out.warnings)
    assert out.returned_to is None
