"""Plan 62 S2 (RED): the batch link, AC-62-01..08 (plan D1-D5).

One PO row X is linked to N SO rows in ONE edit PUT (operation ``link_batch``, route
``POST /api/v1/autocount/po-links/batch``). Operation params (snake case, like ``link_row``):
``doc_key``, ``dtl_key`` (the PO row) and ``links`` = ``[{so_doc_key, so_dtl_key, qty, so_doc_date?}]``.
Wire body: ``{companyCode, poDocKey, poDtlKey, links: [{soDocKey, soDtlKey, qty}]}``; answer = the
operation answer plus ``links: [{soDocKey, soDtlKey, qty, poDtlKey}]`` and
``freeLine: {poDtlKey, qty} | null``. Runs against ``FakeAutoCountVendor`` (multi-row PUT, F5 reset of
new linked rows, all or nothing). A refusal must be a REAL refusal: every case pins the error code (or
at least rules out ``UNKNOWN_OPERATION``, which is what the operation answers before it exists).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple

import pytest

from app.main import app  # noqa: F401 - the gateway rig overrides dependencies on it
from tests.autocount_write_back_fake_vendor import FULL_ROW_KEYS
from tests.test_autocount_write_back_call_log import assert_one_row_per_call
from tests.test_autocount_write_back_gateway import OTHER_TENANT, _company, _hdr, _key, _other_tenant
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import DBNAME, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

ROUTE = f"{PREFIX}/po-links/batch"
OP = "link_batch"
BASE_DATE = "2026-12-01T00:00:00"  # World's PO rows carry this delivery date and price 5.0


class Rig:
    """World (PO 7001 free row qty 4, SO 7002 rows so_a/so_b qty 10) + SO 7005 (3 rows) + SO 7006 (2 rows)."""

    def __init__(self, h: OpHarness):
        self.h = h
        h.delete_on()
        self.w = World(h)
        self.s5 = self._so(7005, 3)
        self.s6 = self._so(7006, 2)

    def _so(self, key: int, n: int) -> List[int]:
        doc = self.h.seed_doc("SO", key, [_line("ITEM-A", 10, 5.0, "HQ") for _ in range(n)])
        return [r["DtlKey"] for r in doc["Details"]]

    # (soDocKey, soDtlKey, qty)
    def params(self, links: List[Tuple[int, int, Any]], dtl_key=None) -> Dict[str, Any]:
        return dict(doc_key=7001, dtl_key=dtl_key or self.w.p_free, links=[
            dict(so_doc_key=d, so_dtl_key=k, qty=q) for d, k, q in links])

    def body(self, links: List[Tuple[int, int, Any]], dtl_key=None) -> Dict[str, Any]:
        return {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": dtl_key or self.w.p_free, "links": [
            {"soDocKey": d, "soDtlKey": k, "qty": q} for d, k, q in links]}

    def three(self) -> List[Tuple[int, int, int]]:  # sum 3 < 4: one free row of 1 stays
        return [(7005, k, 1) for k in self.s5]


@pytest.fixture
def rig(h):
    return Rig(h)


@pytest.fixture
def gw(h, db, rig):
    return Gw(h, db)


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def new_rows(call) -> List[Dict[str, Any]]:
    return [r for r in call.body["Details"] if r["DtlKey"] == 0]


def d_rows(call) -> List[Dict[str, Any]]:
    return [r for r in call.body["Details"] if r.get("FullTransferOption") == "D"]


def linked_rows(h) -> Dict[int, Dict[str, Any]]:
    """{SO DtlKey: PO row} for every PO 7001 row the vendor holds linked."""
    return {r["FromSODtlKey"]: r for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey")}


def batch_rows(h, rig) -> Dict[int, Dict[str, Any]]:
    """The batch's own new rows only ({SO DtlKey: PO row}); World's pre-linked row is not one of them."""
    return {k: r for k, r in linked_rows(h).items() if k in rig.s5}


def run(h, rig, links, key="b-1", **kw):
    return h.run(OP, rig.params(links), key=key, **kw)


# ============================== AC-62-01 / 02 / 03 happy paths ==================================

def test_ac_62_01_three_links_below_the_row_qty_is_one_put_1_and_one_put_2(h, rig):
    res = run(h, rig, rig.three())
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    sent = puts(h)
    assert len(sent) == 2, [c.body for c in sent]  # exactly ONE PUT 1 and at most ONE PUT 2
    first = sent[0]
    assert d_rows(first) == []  # sum < Qty: row X stays, with the rest
    keep = [r for r in first.body["Details"] if r["DtlKey"] == rig.w.p_free]
    assert len(keep) == 1 and Decimal(str(keep[0]["Qty"])) == Decimal(1)
    added = new_rows(first)
    assert len(added) == 3
    assert sorted(r["FromDocDtlKey"] for r in added) == sorted(rig.s5)
    assert all(r["FromDocType"] == "SO" and r["FromDocNo"] == "SO-7005" for r in added)
    assert all(r["FullTransferOption"] == " " for r in added)
    assert all(k in r for r in added for k in FULL_ROW_KEYS)  # the full vendor row shape
    assert all(Decimal(str(r["Qty"])) == 1 for r in added)


def test_ac_62_01_put_2_restores_price_and_date_on_all_new_rows_and_the_links_stay(h, rig):
    res = run(h, rig, rig.three())
    assert res.outcome == "done" and res.warnings == []
    second = puts(h)[1]
    linked = batch_rows(h, rig)
    assert sorted(linked) == sorted(rig.s5)  # all three links survived PUT 2
    sent_keys = sorted(r["DtlKey"] for r in second.body["Details"])
    assert sent_keys == sorted(r["DtlKey"] for r in linked.values())  # PUT 2 covers ALL new rows
    for row in linked.values():
        assert row["UnitPrice"] == 5.0 and row["DeliveryDate"] == BASE_DATE
    free = next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == rig.w.p_free)
    assert Decimal(str(free["Qty"])) == Decimal(1)


def test_ac_62_01_route_answer_carries_each_new_po_dtl_key_and_the_free_line(client, h, gw, rig):
    r = client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("b-route"))
    assert r.status_code == 200, r.text
    ans = r.json()
    assert ans["outcome"] == "done" and ans.get("errorCode") is None
    linked = linked_rows(h)
    assert sorted((x["soDtlKey"], x["poDtlKey"], x["soDocKey"]) for x in ans["links"]) == sorted(
        (k, linked[k]["DtlKey"], 7005) for k in rig.s5)
    assert all(Decimal(str(x["qty"])) == 1 for x in ans["links"])
    assert ans["freeLine"]["poDtlKey"] == rig.w.p_free and Decimal(str(ans["freeLine"]["qty"])) == 1
    for field in ("operationId", "outcome", "errorCode", "message", "warnings", "docKey", "docNo", "document"):
        assert field in ans


def test_ac_62_02_sum_equal_to_the_row_qty_deletes_the_row_and_has_no_free_line(client, h, gw, rig):
    links = [(7005, rig.s5[0], 2), (7005, rig.s5[1], 1), (7005, rig.s5[2], 1)]
    r = client.post(ROUTE, json=rig.body(links), headers=gw.hdr("b-full"))
    assert r.status_code == 200, r.text
    first = puts(h)[0]
    assert [x["DtlKey"] for x in d_rows(first)] == [rig.w.p_free]
    assert len(new_rows(first)) == 3
    assert [x for x in first.body["Details"] if x["DtlKey"] == rig.w.p_free and x not in d_rows(first)] == []
    assert "freeLine" in r.json() and r.json()["freeLine"] is None
    assert all(x["DtlKey"] != rig.w.p_free for x in h.vendor.rows("PO", 7001))
    assert len(puts(h)) <= 2


def test_ac_62_03_links_across_two_sos_each_row_carries_its_own_doc_no(h, rig):
    links = [(7005, rig.s5[0], 1), (7006, rig.s6[0], 1), (7002, rig.w.so_a, 1)]
    res = run(h, rig, links)
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    added = {r["FromDocDtlKey"]: r["FromDocNo"] for r in new_rows(puts(h)[0])}
    assert added == {rig.s5[0]: "SO-7005", rig.s6[0]: "SO-7006", rig.w.so_a: "SO-7002"}
    assert len(puts(h)) <= 2
    assert {k for k in linked_rows(h)} >= {rig.s5[0], rig.s6[0], rig.w.so_a}


# ============================== AC-62-04 pre-check refusals send NO PUT =========================

def _item_differs(h, rig):
    h.vendor.find("SO", 7005)["Details"][0]["ItemCode"] = "ITEM-Z"
    return rig.three(), {}


def _uom_differs(h, rig):
    h.vendor.find("SO", 7005)["Details"][0]["UOM"] = "BOX"
    return rig.three(), {}


def _so_cancelled(h, rig):
    h.vendor.find("SO", 7005)["Cancelled"] = "T"
    return rig.three(), {}


def _po_cancelled(h, rig):
    h.vendor.find("PO", 7001)["Cancelled"] = "T"
    return rig.three(), {}


def _outstanding(h, rig):
    h.vendor.find("SO", 7005)["Details"][0]["Qty"] = 2
    return [(7005, rig.s5[0], 3)], {}


def _received(h, rig):
    return rig.three(), dict(receipt_reader=lambda kind, doc, row: Decimal(4))


# id, setup(h, rig) -> (links, ops kwargs), params override, expected code (None = any real refusal)
REFUSALS = [
    ("unknown_so_row", lambda h, r: ([(7002, 999999, 1)], {}), {}, "ROW_NOT_FOUND"),
    ("item_differs", _item_differs, {}, "ITEM_MISMATCH"),
    ("uom_differs", _uom_differs, {}, "UOM_MISMATCH"),
    ("so_cancelled", _so_cancelled, {}, "DOC_CANCELLED"),
    ("po_cancelled", _po_cancelled, {}, "DOC_CANCELLED"),
    ("row_already_linked", lambda h, r: (r.three(), {}), {"dtl": "p_linked"}, "ROW_ALREADY_LINKED"),
    ("row_transferred_onward", lambda h, r: (r.three(), {}), {"dtl": "p_spo"}, None),
    ("row_received", _received, {}, "ROW_RECEIVED"),
    ("sum_above_free", lambda h, r: ([(7005, r.s5[0], 3), (7005, r.s5[1], 2)], {}), {}, "QTY_ABOVE_FREE"),
    ("one_above_outstanding", _outstanding, {}, "QTY_ABOVE_OUTSTANDING"),
    ("duplicate_so_dtl_key", lambda h, r: ([(7005, r.s5[0], 1), (7005, r.s5[0], 1)], {}), {}, None),
    ("empty_links", lambda h, r: ([], {}), {}, None),
    ("more_than_20_links", lambda h, r: ([(7005, 100000 + i, 1) for i in range(21)], {}), {}, None),
    ("qty_zero", lambda h, r: ([(7005, r.s5[0], 0)], {}), {}, "QTY_INVALID"),
    ("qty_negative", lambda h, r: ([(7005, r.s5[0], -1)], {}), {}, "QTY_INVALID"),
]


@pytest.mark.parametrize("setup,over,want", [c[1:] for c in REFUSALS], ids=[c[0] for c in REFUSALS])
def test_ac_62_04_every_pre_check_refusal_sends_zero_puts(h, rig, setup, over, want):
    links, kw = setup(h, rig)
    dtl = getattr(rig.w, over["dtl"]) if over else None
    res = h.run(OP, rig.params(links, dtl_key=dtl), key="b-ref", **kw)
    assert res.outcome == "refused", (res.outcome, res.error_code)
    assert res.error_code != "UNKNOWN_OPERATION", "the operation does not exist yet"
    if want:
        assert res.error_code == want, (res.error_code, res.message)
    assert h.vendor.writes() == []  # nothing was sent: no PUT, no DELETE


def test_ac_62_04_qty_above_outstanding_names_the_so_dtl_key(h, rig):
    h.vendor.find("SO", 7005)["Details"][1]["Qty"] = 2
    links = [(7005, rig.s5[0], 1), (7005, rig.s5[1], 3)]
    res = h.run(OP, rig.params(links), key="b-out")
    assert res.outcome == "refused" and res.error_code == "QTY_ABOVE_OUTSTANDING"
    assert str(rig.s5[1]) in res.message and str(rig.s5[0]) not in res.message
    assert h.vendor.writes() == []


def test_ac_62_04_an_so_row_linked_from_another_po_by_the_index_counts_against_outstanding(h, rig):
    from modules.autocount.models import AcPoSoLink

    h.db.add(AcPoSoLink(tenant_id=h.company.tenant_id, company_id=h.company.id, po_source_ref=f"{DBNAME}:9999",
                        po_dtl_key=1, so_dtl_key=rig.s5[0], qty=Decimal(9)))
    h.db.commit()  # SO row qty 10, 9 already linked from PO 9999: 1 outstanding
    res = h.run(OP, rig.params([(7005, rig.s5[0], 2)]), key="b-idx")
    assert res.outcome == "refused" and res.error_code == "QTY_ABOVE_OUTSTANDING", (res.outcome, res.error_code)
    assert str(rig.s5[0]) in res.message
    assert h.vendor.writes() == []
    ok = h.run(OP, rig.params([(7005, rig.s5[0], 1)]), key="b-idx-ok")  # control: the remaining 1 is allowed
    assert ok.outcome == "done", (ok.outcome, ok.error_code)


def test_ac_62_04_route_refusal_is_a_4xx_with_the_code_and_zero_puts(client, h, gw, rig):
    h.vendor.find("SO", 7005)["Details"][0]["Qty"] = 2
    r = client.post(ROUTE, json=rig.body([(7005, rig.s5[0], 3)]), headers=gw.hdr("b-r4"))
    assert r.status_code in (409, 422), r.text
    assert code(r) == "QTY_ABOVE_OUTSTANDING" and str(rig.s5[0]) in r.json()["message"]
    assert h.vendor.writes() == []


def test_ac_62_04_route_requires_the_idempotency_key(client, h, gw, rig):
    r = client.post(ROUTE, json=rig.body(rig.three()), headers=_hdr(gw.plain))
    assert r.status_code == 422 and code(r) == "IDEMPOTENCY_KEY_REQUIRED", r.text
    assert h.vendor.writes() == []


@pytest.mark.parametrize("links", [[], [{"soDocKey": 7005, "soDtlKey": 1, "qty": 0}], "nope"])
def test_ac_62_04_route_bad_links_shape_is_rejected_with_zero_puts(client, h, gw, rig, links):
    body = dict(rig.body(rig.three()), links=links)
    r = client.post(ROUTE, json=body, headers=gw.hdr("b-shape"))
    assert r.status_code in (409, 422), r.text
    assert h.vendor.writes() == []


# ============================== AC-62-05 vendor refuses PUT 1 ===================================

def test_ac_62_05_vendor_refusal_is_vendor_error_with_no_put_2_and_nothing_linked(h, rig):
    h.vendor.invalid_items = {"ITEM-A"}
    before = [dict(r) for r in h.vendor.rows("PO", 7001)]
    res = run(h, rig, rig.three())
    assert res.outcome == "vendor_error" and res.error_code == "VENDOR_REFUSED", (res.outcome, res.error_code)
    assert "Item code does not exist" in res.message
    assert len(puts(h)) == 1  # no PUT 2
    assert [dict(r) for r in h.vendor.rows("PO", 7001)] == before
    assert res.replaced_lines == []


def test_ac_62_05_route_vendor_error_reports_no_linked_row(client, h, gw, rig):
    h.vendor.invalid_items = {"ITEM-A"}
    r = client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("b-v"))
    assert r.status_code == 502 and r.json()["outcome"] == "vendor_error", r.text
    assert not r.json().get("links")
    assert len(puts(h)) == 1


def test_ac_62_05_the_fake_vendor_refuses_a_put_with_one_bad_linked_row_and_lands_nothing(h, rig):
    """Fake-vendor teaching (F-G): a bad new row (unknown SO DtlKey) = 500 and the whole PO is unchanged."""
    from tests.autocount_write_back_fake_vendor import new_doc  # noqa: F401
    from modules.autocount.write_back.client import AutoCountWriteClient
    from tests.test_autocount_write_back_primitives import DB3

    h.vendor.reject_unknown_so_link = True
    before = [dict(r) for r in h.vendor.rows("PO", 7001)]
    po = h.vendor.find("PO", 7001)
    good = dict(DtlKey=0, ItemCode="ITEM-A", UOM="UNIT", Qty=1, UnitPrice=5.0, Location="BR1",
                FromDocType="SO", FromDocNo="SO-7005", FromDocDtlKey=rig.s5[0])
    bad = dict(good, FromDocDtlKey=999999)
    client = AutoCountWriteClient(DB3, transport=h.vendor.transport)
    resp = client.put("/EditPurchaseOrderbydockey", {"DocKey": po["DocKey"], "Details": [good, bad]})
    assert not resp.ok and resp.status_code == 500
    assert [dict(r) for r in h.vendor.rows("PO", 7001)] == before


# ============================== AC-62-06 PUT 2 fails ============================================

def test_ac_62_06_put_2_failure_is_done_with_the_warnings_and_the_links_kept(h, rig):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "restore refused", after=1)
    res = run(h, rig, rig.three())
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert "LOCATION_NOT_MOVED" in res.warnings and "ROW_VALUES_NOT_KEPT" in res.warnings
    assert len(puts(h)) == 2  # PUT 2 is never retried
    assert sorted(batch_rows(h, rig)) == sorted(rig.s5)


# ============================== AC-62-07 replay =================================================

def test_ac_62_07_done_replay_is_the_stored_answer_with_no_vendor_call(h, rig):
    first = run(h, rig, rig.three(), key="b-rep")
    assert first.outcome == "done"
    calls = len(h.vendor.calls)
    again = run(h, rig, rig.three(), key="b-rep")
    assert again.outcome == "done" and again.operation_id == first.operation_id
    assert len(h.vendor.calls) == calls


def test_ac_62_07_done_key_with_another_body_is_an_idempotency_conflict(h, rig):
    assert run(h, rig, rig.three(), key="b-conf").outcome == "done"
    calls = len(h.vendor.calls)
    other = [(7005, rig.s5[0], 1)]
    res = h.run(OP, rig.params(other), key="b-conf")
    assert res.outcome == "refused" and res.error_code == "IDEMPOTENCY_CONFLICT"
    assert len(h.vendor.calls) == calls


def test_ac_62_07_route_replay_and_conflict(client, h, gw, rig):
    r1 = client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("b-r7"))
    assert r1.status_code == 200, r1.text
    calls = len(h.vendor.calls)
    r2 = client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("b-r7"))
    assert r2.status_code == 200 and r2.json()["operationId"] == r1.json()["operationId"]
    r3 = client.post(ROUTE, json=rig.body([(7005, rig.s5[0], 1)]), headers=gw.hdr("b-r7"))
    assert r3.status_code in (409, 422) and code(r3) == "IDEMPOTENCY_CONFLICT"
    assert len(h.vendor.calls) == calls


# ============================== AC-62-08 auth / scope / tenant ==================================

def test_ac_62_08_no_key_is_401_and_nothing_is_sent(client, h, gw, rig):
    r = client.post(ROUTE, json=rig.body(rig.three()), headers={"Idempotency-Key": "b-401"})
    assert r.status_code == 401
    h.no_http()


def test_ac_62_08_a_pull_only_key_is_403_scope_required(client, h, db, gw, rig):
    _row, plain = _key(db, [h.company.id])  # default scope: pull
    r = client.post(ROUTE, json=rig.body(rig.three()), headers={**_hdr(plain), "Idempotency-Key": "b-403"})
    assert r.status_code == 403 and code(r) == "SCOPE_REQUIRED", r.text
    h.no_http()


def test_ac_62_08_another_tenants_company_is_never_resolved(client, h, db, gw, rig):
    _other_tenant(db)
    theirs = _company(db, OTHER_TENANT, code="THEIRS", database="AED_THEIRS")
    body = dict(rig.body(rig.three()), companyCode="THEIRS")
    r = client.post(ROUTE, json=body, headers=gw.hdr("b-ten"))
    assert r.status_code in (403, 404), r.text
    assert theirs.id != h.company.id
    h.no_http()


def test_ac_62_08_body_tenant_and_company_ids_are_ignored(client, h, db, gw, rig):
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.models import AcWriteOperation

    body = dict(rig.body(rig.three()), tenantId="evil", companyId="evil")
    r = client.post(ROUTE, json=body, headers=gw.hdr("b-ign"))
    assert r.status_code == 200, r.text
    op = db.query(AcWriteOperation).filter_by(op=OP).one()
    assert op.tenant_id == DEFAULT_TENANT_ID and op.company_id == h.company.id and op.key_id == gw.key.id


# ============================== every vendor call is logged =====================================

def test_ac_62_every_vendor_call_of_a_batch_is_in_the_api_call_log(h, rig):
    res = run(h, rig, rig.three())
    assert res.outcome == "done"
    assert_one_row_per_call(h)
    from modules.autocount.models import AcApiCallLog

    session = h.session_factory()
    try:
        rows = session.query(AcApiCallLog).filter(AcApiCallLog.method == "PUT").all()
        assert len(rows) == 2 and all(r.operation_id == res.operation_id for r in rows)
    finally:
        session.close()
