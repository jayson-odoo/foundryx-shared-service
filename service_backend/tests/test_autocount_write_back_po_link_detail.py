"""Plan 64 (lane OI-PO-LINK-SS, CRM UAC P-5): a whole-row ``po-links`` puts the new
linked row at the SO row's location inside the same call and answers the row as
``detail`` (``detail.Location`` = where the row really sits). A row with goods
received is refused ``ROW_RECEIVED`` with a plain reason. Additive: every field an
old caller reads keeps its value.

UAC: ``documentation/plans/sprint-5/64-autocount-po-link-at-so-location-acceptance-criteria.md``.
Rig: the plan 57 gateway rig (real operation services over the fake vendor).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.main import app
from modules.autocount.write_back.deps import get_operation_service
from tests.test_autocount_write_back_gateway import _hdr
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw  # noqa: F401
from tests.test_autocount_write_back_operations import (  # noqa: F401
    PUT_PO,
    World,
    db,
    h,
)
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

LINK = f"{PREFIX}/po-links"
OLD_KEYS = {"actionId", "outcome", "errorCode", "document", "operationId", "message", "warnings",
            "docKey", "docNo", "replacedLines"}


@pytest.fixture
def gw(h, db):
    h.delete_on()
    return Gw(h, db)


@pytest.fixture
def far(gw):
    """PO rows at BR1, SO rows at BRW-AM (the vendor forces a new linked row to HQ)."""
    return World(gw.h, so_loc="BRW-AM")


def _whole(w, **over):
    return {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": w.p_free, "soDocKey": 7002,
            "soDtlKey": w.so_a, "qty": 4, **over}


def _row(rows, key):
    return next(r for r in rows if r["DtlKey"] == key)


# ---- AC-64-01 / 02: whole row lands at the SO location in the same call ----------------------------------

def test_ac_64_01_whole_row_link_answers_detail_at_the_so_location(client, gw, far):
    r = client.post(LINK, json=_whole(far), headers=gw.hdr())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "done" and body["errorCode"] is None
    assert "LOCATION_NOT_MOVED" not in body["warnings"]
    (pair,) = body["replacedLines"]
    assert pair["oldDtlKey"] == far.p_free
    detail = body["detail"]
    assert detail["DtlKey"] == pair["newDtlKey"]
    assert detail["Location"] == "BRW-AM"  # the SO row's location
    assert detail["FromSODtlKey"] == far.so_a
    assert detail == _row(body["document"]["Details"], pair["newDtlKey"])  # the row as read back
    assert _row(far.po_rows(), pair["newDtlKey"])["Location"] == "BRW-AM"  # AutoCount holds it there


def test_ac_64_02_the_move_is_inside_the_same_po_links_call(client, gw, far):
    r = client.post(LINK, json=_whole(far), headers=gw.hdr())
    assert r.status_code == 200, r.text
    replace, move = gw.h.vendor.writes()  # one replace PUT, one move edit, nothing else
    assert gw.h.steps() == [PUT_PO, PUT_PO]
    assert move.body["Details"][0]["Location"] == "BRW-AM"


# ---- AC-64-03: move not landed -> today's LOCATION_NOT_MOVED, detail tells the truth ---------------------

def test_ac_64_03_move_not_landed_keeps_location_not_moved_and_detail_is_the_real_location(client, gw, far):
    gw.h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "no move", after=1)
    r = client.post(LINK, json=_whole(far), headers=gw.hdr())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "done" and "LOCATION_NOT_MOVED" in body["warnings"]
    assert body["detail"]["Location"] == "HQ"  # where it really sits, never the SO location it missed


# ---- AC-64-04: goods received -> plain refusal, nothing sent, key released --------------------------------

def _received(gw, qty):
    app.dependency_overrides[get_operation_service] = (
        lambda: gw.h.ops(receipt_reader=lambda kind, doc, row: Decimal(qty))
    )


def test_ac_64_04_received_row_is_refused_with_a_plain_reason(client, gw, far):
    _received(gw, 4)  # the whole row received
    r = client.post(LINK, json=_whole(far), headers=gw.hdr())
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["outcome"] == "refused" and body["errorCode"] == "ROW_RECEIVED"
    assert body["message"] and "ROW_RECEIVED" not in body["message"]
    assert "received" in body["message"].lower()
    assert body["detail"] is None and body["document"] is None
    assert gw.h.vendor.writes() == []
    # fixed in AutoCount (nothing received any more): the same key runs fresh
    _received(gw, 0)
    again = client.post(LINK, json=_whole(far), headers=gw.hdr())
    assert again.status_code == 200, again.text
    assert again.json()["detail"]["Location"] == "BRW-AM"


# ---- AC-64-05: replay answers the same detail -------------------------------------------------------------

def test_ac_64_05_replay_of_done_answers_the_same_detail(client, gw, far):
    first = client.post(LINK, json=_whole(far), headers=gw.hdr())
    calls = len(gw.h.vendor.calls)
    again = client.post(LINK, json=_whole(far), headers=gw.hdr())
    assert again.status_code == 200
    assert len(gw.h.vendor.calls) == calls  # nothing sent again
    assert again.json()["detail"] == first.json()["detail"]
    assert again.json()["operationId"] == first.json()["operationId"]


# ---- AC-64-06: split link answers the new linked row ------------------------------------------------------

@pytest.mark.parametrize("idem", ["gw-key-1", ""])
def test_ac_64_06_split_link_answers_the_new_linked_row(client, gw, far, idem):
    headers = gw.hdr(idem) if idem else _hdr(gw.plain)
    r = client.post(LINK, json=_whole(far, qty=1), headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    detail = body["detail"]
    assert detail["DtlKey"] != far.p_free
    assert detail["FromSODtlKey"] == far.so_a and Decimal(str(detail["Qty"])) == 1
    assert detail["Location"] == "BRW-AM"
    assert _row(body["document"]["Details"], far.p_free)["Qty"] == 3  # the free remainder stays


# ---- AC-64-07: old callers unchanged ----------------------------------------------------------------------

def test_ac_64_07_detail_is_the_only_new_key_and_null_when_not_done(client, gw, far):
    ok = client.post(LINK, json=_whole(far), headers=gw.hdr())
    assert set(ok.json()) == OLD_KEYS | {"detail"}
    linked = client.post(LINK, json=_whole(far, poDtlKey=far.p_linked), headers=gw.hdr("gw-key-2"))
    assert linked.status_code == 409 and linked.json()["errorCode"] == "ROW_ALREADY_LINKED"
    assert set(linked.json()) == OLD_KEYS | {"detail"} and linked.json()["detail"] is None


def test_ac_64_07_other_routes_keep_their_body(client, gw, far):
    r = client.post(f"{PREFIX}/po-links/unlink",
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": far.p_linked}, headers=gw.hdr())
    assert r.status_code == 200, r.text
    assert "detail" not in r.json()
