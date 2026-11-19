"""Plan 70 (RED, lane PO-LINK-OI-LOCATION-SS): a link may name the PO row's location.

Owner ruling 19 Nov: a PO row linked from an Order Inquiry row lands at the OI row's location (an
order back = the donor, e.g. BRW-BB), not the SO line's. The CRM decides and sends it as ``location``;
SS only executes. No location = today's rule (the SO row's location). An unknown code is refused
``LOCATION_UNKNOWN`` before any write (the refusal releases the key); one logged ``GET /location``
checks every code of the request.

World: PO 7001 rows at BR1, SO 7002 rows at HQ (``w``) or BRW-AM (``w_far``). The fake Location
master holds HQ, BR1, BRW, BRW-AM, BRW-BB.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, List

import pytest

from app.main import app  # noqa: F401
from modules.autocount.models import AcApiCallLog
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw
from tests.test_autocount_write_back_link_batch import Rig
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

DONOR = "BRW-BB"


@pytest.fixture
def w(h):
    h.delete_on()
    return World(h)


@pytest.fixture
def w_far(h):
    h.delete_on()
    return World(h, so_loc="BRW-AM")


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def location_gets(h) -> List[Any]:
    return [c for c in h.vendor.calls if c.method == "GET" and c.leaf == "location"]


def row(h, key, doc_key=7001):
    return next((r for r in h.vendor.rows("PO", doc_key) if r["DtlKey"] == key), None)


def new_key_of(res) -> int:
    (_old, new), = res.replaced_lines
    return new


# ============================== AC-70-01 link_row (whole row) =================================

def test_link_row_with_location_lands_at_that_location_not_the_so_rows(h, w_far):
    res = h.run("link_row", dict(w_far.params["link_row"], location=DONOR))
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    stored = row(h, new_key_of(res))
    assert stored["FromSODtlKey"] == w_far.so_a and stored["Location"] == DONOR


def test_link_row_location_is_matched_to_the_master_code(h, w):
    res = h.run("link_row", dict(w.params["link_row"], location=" brw-bb "))
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert row(h, new_key_of(res))["Location"] == DONOR  # AutoCount's own spelling is written


# ============================== AC-70-07 no location = today =================================

@pytest.mark.parametrize("value", [None, "", "   "])
def test_link_row_without_location_is_todays_so_row_location(h, w_far, value):
    params = dict(w_far.params["link_row"])
    if value is not None:
        params["location"] = value
    res = h.run("link_row", params)
    assert res.outcome == "done", res.error_code
    assert row(h, new_key_of(res))["Location"] == "BRW-AM"
    assert location_gets(h) == []  # no extra AutoCount call without a location


# ============================== AC-70-06 unknown code =================================

def test_unknown_location_is_refused_before_any_write_and_releases_the_key(h, w):
    res = h.run("link_row", dict(w.params["link_row"], location="NOPE"), key="loc-1")
    assert (res.outcome, res.error_code) == ("refused", "LOCATION_UNKNOWN")
    assert "NOPE" in res.message
    assert puts(h) == []
    h.vendor.locations.append("NOPE")  # fixed in AutoCount: the same key may be sent again
    again = h.run("link_row", dict(w.params["link_row"], location="NOPE"), key="loc-1")
    assert again.outcome == "done", (again.outcome, again.error_code)
    assert row(h, new_key_of(again))["Location"] == "NOPE"


def test_location_master_unreadable_is_refused_read_failed_nothing_written(h, w):
    h.vendor.fail_reads_next("location")
    res = h.run("link_row", dict(w.params["link_row"], location=DONOR))
    assert (res.outcome, res.error_code) == ("refused", "READ_FAILED")
    assert puts(h) == []


# ============================== AC-70-09 the check is a logged call =================================

def test_location_check_is_one_logged_autocount_call(h, w):
    res = h.run("link_row", dict(w.params["link_row"], location=DONOR))
    assert res.outcome == "done", res.error_code
    assert len(location_gets(h)) == 1
    h.db.expire_all()
    paths = [r.path for r in h.db.query(AcApiCallLog).all()]
    assert any(p.rstrip("/").endswith("/location") for p in paths), paths


# ============================== AC-70-08 idempotency =================================

def test_location_is_part_of_the_request(h, w):
    first = h.run("link_row", dict(w.params["link_row"], location=DONOR), key="loc-i")
    assert first.outcome == "done"
    clash = h.run("link_row", dict(w.params["link_row"], location="BRW"), key="loc-i")
    assert clash.error_code == "IDEMPOTENCY_CONFLICT"


# ============================== AC-70-04 relink =================================

def test_relink_with_location_lands_at_that_location(h, w_far):
    res = h.run("relink_row", dict(w_far.params["relink_row"], location=DONOR))
    assert res.outcome == "done", (res.outcome, res.error_code)
    stored = row(h, new_key_of(res))
    assert stored["FromSODtlKey"] == w_far.so_b and stored["Location"] == DONOR


def test_unlink_ignores_a_link_location(h, w):
    res = h.run("unlink_row", dict(w.params["unlink_row"], location=DONOR))
    assert res.outcome == "done", res.error_code
    assert row(h, new_key_of(res))["Location"] == "BR1"
    assert location_gets(h) == []


# ============================== AC-70-02 split (part of a row) =================================

def test_split_link_with_location_lands_the_new_row_there(h, w_far):
    res = h.run("split_link", dict(po_doc_key=7001, po_dtl_key=w_far.p_free, so_doc_key=7002,
                                   so_dtl_key=w_far.so_a, qty=Decimal(2), location=DONOR))
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    assert res.detail["Location"] == DONOR
    linked = [r for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey") == w_far.so_a and r["Qty"] == 2]
    assert len(linked) == 1 and linked[0]["Location"] == DONOR
    assert row(h, w_far.p_free)["Location"] == "BR1"  # the rest stays where it was


def test_split_link_unknown_location_writes_nothing(h, w):
    res = h.run("split_link", dict(po_doc_key=7001, po_dtl_key=w.p_free, so_doc_key=7002,
                                   so_dtl_key=w.so_a, qty=Decimal(2), location="NOPE"))
    assert (res.outcome, res.error_code) == ("refused", "LOCATION_UNKNOWN")
    assert puts(h) == []


# ============================== AC-70-03 batch + doc-batch =================================

def test_batch_entries_land_at_their_own_location_or_the_so_rows(h):
    rig = Rig(h)
    params = rig.params([(7005, k, 1) for k in rig.s5])
    params["links"][0]["location"] = DONOR
    res = h.run("link_batch", params, key="b-loc")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    by_so = {r["FromSODtlKey"]: r for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey")}
    assert by_so[rig.s5[0]]["Location"] == DONOR
    assert by_so[rig.s5[1]]["Location"] == "HQ" and by_so[rig.s5[2]]["Location"] == "HQ"
    assert len(location_gets(h)) == 1


def test_batch_unknown_location_skips_that_line_only(h):
    rig = Rig(h)
    params = rig.params([(7005, k, 1) for k in rig.s5])
    params["links"][1]["location"] = "NOPE"
    res = h.run("link_batch", params, key="b-bad")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert {"soDocKey": 7005, "soDtlKey": rig.s5[1], "code": "LOCATION_UNKNOWN"} in res.batch["skipped"]
    linked = {r["FromSODtlKey"] for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey")}
    assert rig.s5[1] not in linked and rig.s5[0] in linked


def test_doc_batch_lines_land_at_their_own_location(h):
    rig = Rig(h)
    w = rig.w
    params = dict(doc_key=7001, links=[
        dict(po_dtl_key=w.p_free, so_doc_key=7005, so_dtl_key=rig.s5[0], qty=1, location=DONOR),
        dict(po_dtl_key=w.p_free, so_doc_key=7005, so_dtl_key=rig.s5[1], qty=1),
        dict(po_dtl_key=w.p_other, so_doc_key=7006, so_dtl_key=rig.s6[0], qty=1, location="NOPE"),
    ])
    res = h.run("link_doc_batch", params, key="d-loc")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    lines = {line["soDtlKey"]: line for line in res.batch["lines"]}
    assert lines[rig.s6[0]]["result"] == "skipped" and lines[rig.s6[0]]["code"] == "LOCATION_UNKNOWN"
    by_so = {r["FromSODtlKey"]: r for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey")}
    assert by_so[rig.s5[0]]["Location"] == DONOR and by_so[rig.s5[1]]["Location"] == "HQ"
    assert len(location_gets(h)) == 1


# ============================== AC-70-05 relocate (Move location) =================================

def _relocate(h, w, **kw):
    from modules.autocount.write_back.service import WriteBackService

    svc = WriteBackService(h.db, **h.factories())
    return svc.relocate(tenant_id=h.company.tenant_id, company_id=h.company.id, po_doc_key=7001,
                        po_dtl_key=w.p_linked, key_id="k1", **kw)


def test_relocate_with_location_moves_the_row_there(h, w):
    res = _relocate(h, w, location=DONOR)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert row(h, w.p_linked)["Location"] == DONOR


def test_relocate_without_location_still_goes_to_the_so_row(h, w):
    res = _relocate(h, w)  # PO row at BR1, SO row at HQ
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert row(h, w.p_linked)["Location"] == "HQ"


def test_relocate_unknown_location_is_refused_nothing_written(h, w):
    res = _relocate(h, w, location="NOPE")
    assert (res.outcome, res.error_code) == ("refused", "LOCATION_UNKNOWN")
    assert puts(h) == []


# ============================== the routes =================================

@pytest.fixture
def gw(h, db, w_far):
    return Gw(h, db)


def test_route_po_links_takes_location(client, h, gw, w_far):
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr("r-1"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": w_far.p_free, "soDocKey": 7002,
        "soDtlKey": w_far.so_a, "qty": 4, "location": DONOR})
    assert r.status_code == 200, r.text
    assert r.json()["detail"]["Location"] == DONOR


def test_route_po_links_unknown_location_is_422(client, h, gw, w_far):
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr("r-2"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": w_far.p_free, "soDocKey": 7002,
        "soDtlKey": w_far.so_a, "qty": 4, "location": "NOPE"})
    assert r.status_code == 422, r.text
    assert r.json()["errorCode"] == "LOCATION_UNKNOWN"


def test_route_rejects_a_non_text_location(client, h, gw, w_far):
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr("r-3"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": w_far.p_free, "soDocKey": 7002,
        "soDtlKey": w_far.so_a, "qty": 4, "location": 7})
    assert r.status_code == 422, r.text
    assert puts(h) == []


def test_route_relink_takes_location(client, h, gw, w_far):
    r = client.post(f"{PREFIX}/po-links/relink", headers=gw.hdr("r-4"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": w_far.p_linked, "soDocKey": 7002,
        "soDtlKey": w_far.so_b, "location": DONOR})
    assert r.status_code == 200, r.text
    new = r.json()["replacedLines"][0]["newDtlKey"]
    assert row(h, new)["Location"] == DONOR


def test_route_doc_batch_takes_a_location_per_line(client, h, gw, w_far):
    r = client.post(f"{PREFIX}/po-links/doc-batch", headers=gw.hdr("r-5"), json={
        "companyCode": "SRT", "poDocKey": 7001, "links": [
            {"poDtlKey": w_far.p_free, "soDocKey": 7002, "soDtlKey": w_far.so_a, "qty": 4, "location": DONOR}]})
    assert r.status_code == 200, r.text
    assert r.json()["lines"][0]["result"] == "linked"
    assert row(h, r.json()["lines"][0]["newPoDtlKey"])["Location"] == DONOR


def test_route_batch_takes_a_location_per_link(client, h, gw, w_far):
    r = client.post(f"{PREFIX}/po-links/batch", headers=gw.hdr("r-6"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": w_far.p_free, "links": [
            {"soDocKey": 7002, "soDtlKey": w_far.so_a, "qty": 4, "location": DONOR}]})
    assert r.status_code == 200, r.text
    new = r.json()["links"][0]["poDtlKey"]
    assert row(h, new)["Location"] == DONOR


def test_route_relocate_takes_location(client, h, gw, w_far):
    r = client.post(f"{PREFIX}/po-links/relocate", headers=gw.hdr("r-7"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": w_far.p_linked, "location": DONOR})
    assert r.status_code == 200, r.text
    assert row(h, w_far.p_linked)["Location"] == DONOR

