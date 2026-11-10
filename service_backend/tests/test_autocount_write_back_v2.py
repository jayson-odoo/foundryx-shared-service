"""Plan 61 (RED): AutoCount write API v2 (vendor update 10 Nov 2026), AC-61-01..41.

Spec: ``documentation/plans/sprint-5/61-autocount-write-v2-acceptance-criteria.md`` and
``61-autocount-write-v2.md`` sections 3a (facts F1..F15) and 4 (seams). The vendor is
``FakeAutoCountVendor`` taught the 10 Nov behaviour: GET ``/<Doc>bydocno``, DELETE
``/Cancel<Doc>bydocno?DocNo=``, a PUT row with ``FullTransferOption "D"`` deletes that row,
a PUT is all or nothing, a new PO row linked to an SO row is forced to HQ with an empty
delivery date. New names are imported inside each test, so each test fails on its own.

Open points the tests deliberately do NOT pin (the coder decides, the captain may rule):
the Location a link's move PUT writes (the SO row's place, as plan 57 ruled, or the old
row's place); only the DeliveryDate restore is asserted exactly.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from app.main import app  # noqa: F401 - the gateway rig overrides dependencies on it
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back.reader import AutoCountDocReader, DocReadError
from tests.autocount_write_back_fake_vendor import FakeAutoCountVendor, new_doc
from tests.test_autocount_write_back_gateway import _hdr
from tests.test_autocount_write_back_gateway_qtso import PREFIX, SLUG, Gw, code
from tests.test_autocount_write_back_operations import (  # noqa: F401
    OpHarness,
    World,
    db,
    h,
)
from tests.test_autocount_write_back_primitives import DB3, _header, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

DAY = date(2026, 11, 4)
NOUN = {"QT": "Quotation", "SO": "SalesOrder", "PO": "PurchaseOrder"}
EDIT_LEAF = {"QT": "editquotationbydockey", "SO": "editsalesorderbydockey", "PO": "editpurchaseorderbydockey"}
CANCEL_LEAF = {k: f"cancel{v.lower()}bydocno" for k, v in NOUN.items()}
BYDOCNO_LEAF = {k: f"{v.lower()}bydocno" for k, v in NOUN.items()}
WB_DIR = Path(__file__).resolve().parents[1] / "modules" / "autocount" / "write_back"
REPO = Path(__file__).resolve().parents[2]
LAST_ROW_MSG = "This item has been transferred to Purchase Order, you are not allow to delete it!"


# ---- helpers ------------------------------------------------------------------------------

def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def methods(h) -> List[str]:
    return [c.method for c in h.vendor.writes()]


def by_day_gets(h) -> List[Any]:
    return [c for c in h.vendor.gets() if c.leaf.endswith("bydocdate")]


def by_no_gets(h) -> List[Any]:
    return [c for c in h.vendor.gets() if c.leaf.endswith("bydocno")]


def detail(call, dtl_key) -> Dict[str, Any]:
    return next(r for r in call.body["Details"] if r["DtlKey"] == dtl_key)


def new_rows(call) -> List[Dict[str, Any]]:
    return [r for r in call.body["Details"] if r["DtlKey"] == 0]


def d_rows(call) -> List[Dict[str, Any]]:
    return [r for r in call.body["Details"] if r.get("FullTransferOption") == "D"]


def row(vendor, kind, doc_key, dtl_key):
    return next((r for r in vendor.rows(kind, doc_key) if r["DtlKey"] == dtl_key), None)


def seed_plain(h, kind, doc_key, rows=None, **header):
    doc = h.seed_doc(kind, doc_key, rows or [_line("A", 10, 5.0), _line("B", 4, 6.0, "BR1")], **header)
    return doc, [r["DtlKey"] for r in doc["Details"]]


@pytest.fixture
def world(h):
    return World(h)


@pytest.fixture
def gw(h, db):
    return Gw(h, db)  # the NEW shipped capability table: no flag is flipped here


def call_args(h, kind, doc_key, **over):
    return h.args(kind, doc_key=doc_key, doc_date=DAY, **over)


# ============================== AC-61-01 cancel request =====================================

@pytest.mark.parametrize("kind", ["QT", "SO", "PO"])
def test_ac_61_01_cancel_request_is_delete_with_encoded_query_and_no_body(kind):
    vendor = FakeAutoCountVendor()
    docno = "A/B 1&x=2#?"
    vendor.seed(kind, new_doc(kind, 4001, docno, "P", [{}]))
    client = AutoCountWriteClient(DB3, transport=vendor.transport)
    resp = client.delete_query(f"/Cancel{NOUN[kind]}bydocno", {"DocNo": docno})
    assert resp.ok, resp.body
    call = vendor.calls[-1]
    assert call.method == "DELETE"
    assert call.path == f"/api/db3/Cancel{NOUN[kind]}bydocno"  # the path is not changed by the DocNo
    assert call.body is None  # no request body at all
    assert call.query == {"DocNo": docno}  # exactly one parameter, value intact
    query = call.raw_target.split("?", 1)[1]
    assert call.raw_target.count("?") == 1 and "&" not in query and "#" not in query
    assert query.count("=") == 1  # the "=" inside the value is encoded
    assert vendor.find(kind, 4001)["Cancelled"] == "T"


def test_ac_61_01_a_question_mark_in_the_path_is_still_refused_everywhere_else():
    vendor = FakeAutoCountVendor()
    client = AutoCountWriteClient(DB3, transport=vendor.transport)
    for call in (lambda: client.put("/x?y=1", {}), lambda: client.post("/x?y=1", {}),
                 lambda: client.delete("/x?y=1", {})):
        with pytest.raises(ValueError):
            call()
    with pytest.raises(ValueError):  # the dedicated door takes no query inside its path either
        client.delete_query("/CancelQuotationbydocno?DocNo=1", {"DocNo": "1"})
    assert vendor.calls == []


def test_ac_61_01_allowlist_guard_runs_before_the_cancel_request(monkeypatch):
    from modules.autocount.write_back import client as client_mod

    vendor = FakeAutoCountVendor()
    client = AutoCountWriteClient(DB3, transport=vendor.transport)

    class Stop(Exception):
        pass

    def deny(_url):
        raise Stop()

    monkeypatch.setattr(client_mod, "assert_write_allowed", deny)
    with pytest.raises(Stop):
        client.delete_query("/CancelQuotationbydocno", {"DocNo": "QT-1"})
    assert vendor.calls == []


# ============================== AC-61-02 single document read ================================

def test_ac_61_02_by_doc_no_paths_are_the_exact_vendor_spelling():
    from modules.autocount.write_back.doc_kinds import KINDS

    assert KINDS["QT"].by_doc_no_path == "/Quotationbydocno"
    assert KINDS["SO"].by_doc_no_path == "/SalesOrderbydocno"
    assert KINDS["PO"].by_doc_no_path == "/PurchaseOrderbydocno"
    assert KINDS["SPO"].by_doc_no_path == "/PurchaseOrderbydocno"
    assert all("Quotaton" not in k.by_doc_no_path for k in KINDS.values())


@pytest.mark.parametrize("kind", ["QT", "SO", "PO"])
def test_ac_61_02_get_by_doc_no_requests_the_bydocno_door(kind):
    vendor = FakeAutoCountVendor()
    vendor.seed(kind, new_doc(kind, 4002, "X-4002", "P", [{}]))
    reader = AutoCountDocReader(DB3, transport=vendor.transport)
    doc = reader.get_by_doc_no(kind, "X-4002")
    assert doc["DocKey"] == 4002
    call = vendor.calls[-1]
    assert call.method == "GET" and call.path == f"/api/db3/{NOUN[kind]}bydocno" and call.query == {"DocNo": "X-4002"}


def test_ac_61_02_an_empty_list_is_doc_not_found():
    vendor = FakeAutoCountVendor()
    reader = AutoCountDocReader(DB3, transport=vendor.transport)
    with pytest.raises(DocReadError) as ei:
        reader.get_by_doc_no("SO", "NOPE-1")
    assert ei.value.code == "DOC_NOT_FOUND"


def test_ac_61_02_a_doc_with_another_dockey_is_never_the_read_back(h):
    _doc, keys = seed_plain(h, "SO", 5001)
    h.vendor.find("SO", 5001)["DocKey"] = 777  # bydocno SO-5001 now answers DocKey 777, not 5001
    res = h.edit("SO", 5001, {"Remark1": "x"})
    assert res.outcome == "refused" and res.error_code in ("DOC_KIND_MISMATCH", "DOC_NOT_FOUND"), res
    assert h.vendor.writes() == []


# ============================== AC-61-03 reads use bydocno ===================================

def test_ac_61_03_edit_and_add_line_never_touch_the_by_date_list(h):
    seed_plain(h, "SO", 5001)
    res = h.edit("SO", 5001, {"Remark1": "hello"})
    assert res.outcome == "done", res.error_code
    res = h.service().add_line(**h.args("SO", doc_key=5001, line=_line("C", 1, 3.0)))
    assert res.outcome == "done", res.error_code
    assert by_day_gets(h) == []
    assert by_no_gets(h)


def test_ac_61_03_unlink_operation_never_touches_the_by_date_list(h, world):
    res = h.run("unlink_row", world.params["unlink_row"])
    assert res.outcome == "done", res.error_code
    assert by_day_gets(h) == []
    assert by_no_gets(h)


@pytest.mark.parametrize("failure", ["status", "timeout"])
def test_ac_61_03_a_failing_bydocno_falls_back_to_the_day_list(h, failure):
    seed_plain(h, "SO", 5001)
    if failure == "status":
        h.vendor.fail_next("GET", "salesorderbydocno", 500, "boom")
    else:
        h.vendor.timeout_next("GET", "salesorderbydocno")
    res = h.edit("SO", 5001, {"Remark1": "hello"})
    assert res.outcome == "done", res.error_code
    assert by_day_gets(h)  # the fallback read happened
    assert h.vendor.find("SO", 5001)["Remark1"] == "hello"


# ============================== AC-61-04 new row key from bydocno ============================

def test_ac_61_04_add_line_new_dtl_key_is_the_key_present_after_and_absent_before(h):
    _doc, keys = seed_plain(h, "PO", 5002)
    res = h.service().add_line(**h.args("PO", doc_key=5002, line=_line("C", 1, 3.0)))
    assert res.outcome == "done", res.error_code
    after = {r["DtlKey"] for r in h.vendor.rows("PO", 5002)}
    assert {res.new_dtl_key} == after - set(keys)
    assert by_day_gets(h) == []


def test_ac_61_04_replace_returns_the_new_key_from_the_bydocno_read(h, world):
    res = h.run("unlink_row", world.params["unlink_row"])
    assert res.outcome == "done", res.error_code
    (old, new), = res.replaced_lines
    assert old == world.p_linked
    assert row(h.vendor, "PO", 7001, new) is not None and row(h.vendor, "PO", 7001, old) is None
    assert new not in {world.p_free, world.p_linked, world.p_spo, world.p_other}


# ============================== AC-61-10 / 16 the replace builder ============================

def test_ac_61_10_build_row_replace_is_old_row_deleted_plus_new_row_key_zero():
    from modules.autocount.write_back import payloads

    doc = new_doc("PO", 6001, "PO-6001", "C", [
        {"ItemCode": "A", "Qty": 4.0, "UnitPrice": 5.0, "Location": "BR1", "FromSODtlKey": 900}])
    old = doc["Details"][0]
    plain = {"ItemCode": "A", "UOM": "UNIT", "Qty": 4, "UnitPrice": 5.0, "Location": "BR1",
             "Description": "A", "DeliveryDate": "2026-12-01T00:00:00"}
    req = payloads.build_row_replace("PO", doc, old, plain)
    assert req.method == "PUT" and req.path == "/EditPurchaseOrderbydockey"
    assert req.body["DocKey"] == 6001
    first, second = req.body["Details"]
    assert first["DtlKey"] == old["DtlKey"] and first["FullTransferOption"] == "D"
    assert first["ItemCode"] == "A" and first["Qty"] == 4 and first["UnitPrice"] == 5.0
    assert second["DtlKey"] == 0 and second["FullTransferOption"] == " "
    assert second["FullTransferFromDocList"] == ""
    assert not second.get("FromDocType") and not second.get("FromDocDtlKey")  # only when linking
    linked = payloads.build_row_replace(
        "PO", doc, old, dict(plain, FromDocType="SO", FromDocNo="SO-1", FromDocDtlKey=901))
    new = linked.body["Details"][1]
    assert (new["FromDocType"], new["FromDocNo"], new["FromDocDtlKey"]) == ("SO", "SO-1", 901)
    assert new["FullTransferOption"] == " " and linked.body["Details"][0]["FullTransferOption"] == "D"


@pytest.mark.parametrize("kind", ["QT", "SO", "PO"])
def test_ac_61_16_every_row_ss_sends_is_a_normal_row_unless_it_is_a_d_row(h, kind):
    res = h.service().create_doc(**h.args(kind, header=_header(kind), lines=[_line(), _line("ITEM-2", 3, 7.0)]))
    assert res.outcome == "done", res.error_code
    doc_key = res.doc_key
    res = h.service().edit_doc(**h.args(kind, doc_key=doc_key, doc_date=DAY, header_changes={},
                                        line_changes=[{"DtlKey": h.vendor.rows(kind, doc_key)[0]["DtlKey"], "Qty": 5}]))
    assert res.outcome == "done", res.error_code
    res = h.service().add_line(**h.args(kind, doc_key=doc_key, doc_date=DAY, line=_line("C", 1, 3.0)))
    assert res.outcome == "done", res.error_code
    sent = [r for c in h.vendor.writes() for r in c.body["Details"]]
    assert len(sent) >= 4
    for r in sent:
        assert r.get("FullTransferOption") == " ", (kind, r)
        assert r.get("FullTransferFromDocList") == "", (kind, r)


def test_ac_61_16_replace_rows_are_normal_except_the_d_row(h, world):
    res = h.run("relink_row", world.params["relink_row"])
    assert res.outcome == "done", res.error_code
    for call in puts(h):
        for r in call.body["Details"]:
            if r.get("FullTransferOption") != "D":
                assert r.get("FullTransferOption") == " " and r.get("FullTransferFromDocList") == "", r


# ============================== AC-61-11 PO unlink ===========================================

def _assert_unlinked_in_one_put(h, world, old_values):
    assert methods(h) == ["PUT"], [(c.method, c.leaf) for c in h.vendor.writes()]
    put = puts(h)[0]
    assert put.leaf == "editpurchaseorderbydockey"
    gone, new = d_rows(put), new_rows(put)
    assert len(put.body["Details"]) == 2 and len(gone) == 1 and len(new) == 1
    assert gone[0]["DtlKey"] == world.p_linked and gone[0]["FullTransferOption"] == "D"
    fresh = new[0]
    for field in ("ItemCode", "Qty", "UnitPrice", "UOM", "Location", "DeliveryDate"):
        assert fresh[field] == old_values[field], field
    assert fresh["FullTransferOption"] == " " and not fresh.get("FromDocType") and not fresh.get("FromDocDtlKey")
    rows = h.vendor.rows("PO", 7001)
    assert row(h.vendor, "PO", 7001, world.p_linked) is None
    added = [r for r in rows if r["DtlKey"] not in (world.p_free, world.p_spo, world.p_other)]
    assert len(added) == 1 and added[0]["FromSODtlKey"] == 0 and len(rows) == 4
    assert {f: added[0][f] for f in ("ItemCode", "Qty", "UnitPrice", "UOM", "Location")} == {
        f: old_values[f] for f in ("ItemCode", "Qty", "UnitPrice", "UOM", "Location")}
    return added[0]


def test_ac_61_11_unlink_operation_is_exactly_one_put_and_no_delete(h, world):
    old = dict(row(h.vendor, "PO", 7001, world.p_linked))
    res = h.run("unlink_row", world.params["unlink_row"])
    assert res.outcome == "done", res.error_code
    added = _assert_unlinked_in_one_put(h, world, old)
    assert res.replaced_lines == [(world.p_linked, added["DtlKey"])]
    assert "DELETE" not in [c.method for c in h.vendor.calls]


def test_ac_61_11_unlink_route_is_exactly_one_put_and_answers_done_with_the_new_key(client, h, gw, world):
    old = dict(row(h.vendor, "PO", 7001, world.p_linked))
    r = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr(),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done" and r.json().get("errorCode") is None
    added = _assert_unlinked_in_one_put(h, world, old)
    assert r.json()["replacedLines"] == [{"oldDtlKey": world.p_linked, "newDtlKey": added["DtlKey"]}]


def test_ac_61_11_unlink_is_the_service_without_operations_too_never_a_blank_link_put(h, world):
    from modules.autocount.write_back.service import WriteBackService

    svc = WriteBackService(h.db, **h.factories())
    res = svc.unlink(tenant_id=h.company.tenant_id, company_id=h.company.id, po_doc_key=7001,
                     po_dtl_key=world.p_linked, key_id="k1")
    assert res.outcome != "refused" or res.error_code != "VENDOR_UNSUPPORTED", res
    for call in puts(h):  # no PUT that edits the linked row in place with blanked link fields
        assert any(r.get("FullTransferOption") == "D" for r in call.body["Details"]) or not any(
            r["DtlKey"] == world.p_linked for r in call.body["Details"])


# ============================== AC-61-12 whole-row link ======================================

LINKED_NEW = ("FromDocType", "FromDocNo", "FromDocDtlKey")


def test_ac_61_12_link_row_operation_is_one_replace_put_plus_a_move_put(h, world):
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done", (res.error_code, res.warnings)
    assert "DELETE" not in [c.method for c in h.vendor.calls]
    first = puts(h)[0]
    assert len(first.body["Details"]) == 2
    gone, = d_rows(first)
    fresh, = new_rows(first)
    assert gone["DtlKey"] == world.p_free
    assert (fresh["FromDocType"], fresh["FromDocNo"], fresh["FromDocDtlKey"]) == ("SO", "SO-7002", world.so_a)
    (old, new), = res.replaced_lines
    assert old == world.p_free and row(h.vendor, "PO", 7001, old) is None
    stored = row(h.vendor, "PO", 7001, new)
    assert stored["FromSODtlKey"] == world.so_a
    # the vendor forced HQ and cleared the date: ONE more PUT on the new row restores the date
    assert len(puts(h)) == 2
    move = puts(h)[1]
    assert [r["DtlKey"] for r in move.body["Details"]] == [new]
    assert str(move.body["Details"][0]["DeliveryDate"])[:10] == "2026-12-01"
    assert str(stored["DeliveryDate"])[:10] == "2026-12-01"
    assert stored["FromSODtlKey"] == world.so_a  # the link survived the move


def test_ac_61_12_link_of_a_row_already_at_hq_without_a_date_is_a_single_put(h):
    world = World(h)
    free = row(h.vendor, "PO", 7001, world.p_free)  # already where the vendor puts a linked row
    free["Location"], free["DeliveryDate"], free["UnitPrice"] = "HQ", "0001-01-01T00:00:00", 0.0
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done", res.error_code
    assert methods(h) == ["PUT"] and not res.warnings


def test_ac_61_12_move_failure_keeps_the_link_and_warns_location_not_moved(h, world):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "no move", after=1)
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done" and "LOCATION_NOT_MOVED" in res.warnings
    (_old, new), = res.replaced_lines
    assert row(h.vendor, "PO", 7001, new)["FromSODtlKey"] == world.so_a  # linked, at HQ
    assert row(h.vendor, "PO", 7001, new)["Location"] == "HQ"


def test_ac_61_12_whole_row_link_route_is_no_longer_vendor_unsupported(client, h, gw, world):
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr(), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_free,
        "soDocKey": 7002, "soDtlKey": world.so_a, "qty": 4})
    assert r.status_code == 200, r.text
    assert r.json().get("errorCode") != "VENDOR_UNSUPPORTED" and r.json()["outcome"] == "done"
    assert "DELETE" not in [c.method for c in h.vendor.calls]
    assert row(h.vendor, "PO", 7001, world.p_free) is None


def test_ac_61_12_service_whole_row_link_without_operations_is_not_vendor_unsupported(h, world):
    from modules.autocount.write_back.service import WriteBackService

    svc = WriteBackService(h.db, **h.factories())
    res = svc.link(tenant_id=h.company.tenant_id, company_id=h.company.id, po_doc_key=7001,
                   po_dtl_key=world.p_free, so_doc_key=7002, so_dtl_key=world.so_a, qty=Decimal(4), key_id="k1")
    assert res.error_code != "VENDOR_UNSUPPORTED", res


# ============================== AC-61-13 relink ==============================================

def test_ac_61_13_relink_is_one_replace_put_and_a_move_no_delete_no_add(h, world):
    res = h.run("relink_row", world.params["relink_row"])
    assert res.outcome == "done", (res.error_code, res.warnings)
    assert "DELETE" not in [c.method for c in h.vendor.calls]
    first = puts(h)[0]
    assert len(first.body["Details"]) == 2
    gone, = d_rows(first)
    fresh, = new_rows(first)
    assert gone["DtlKey"] == world.p_linked
    assert (fresh["FromDocType"], fresh["FromDocDtlKey"]) == ("SO", world.so_b)
    (old, new), = res.replaced_lines
    assert old == world.p_linked and row(h.vendor, "PO", 7001, new)["FromSODtlKey"] == world.so_b
    assert len(puts(h)) <= 2  # the replace, then at most the move
    if len(puts(h)) == 2:
        assert [r["DtlKey"] for r in puts(h)[1].body["Details"]] == [new]


def test_ac_61_13_relink_route(client, h, gw, world):
    r = client.post(f"{PREFIX}/po-links/relink", headers=gw.hdr(), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked,
        "soDocKey": 7002, "soDtlKey": world.so_b})
    assert r.status_code == 200, r.text
    assert r.json()["replacedLines"] and "DELETE" not in [c.method for c in h.vendor.calls]


# ============================== AC-61-14 split link ==========================================

def test_ac_61_14_split_link_is_one_put_cut_row_plus_new_linked_row_then_the_move(h, world):
    params = dict(po_doc_key=7001, po_dtl_key=world.p_free, so_doc_key=7002, so_dtl_key=world.so_a, qty=2)
    res = h.run("split_link", params)
    assert res.outcome == "done", (res.error_code, res.warnings)
    assert "DELETE" not in [c.method for c in h.vendor.calls]
    first = puts(h)[0]
    cut, fresh = detail(first, world.p_free), new_rows(first)[0]
    assert cut.get("FullTransferOption") != "D" and float(cut["Qty"]) == 2
    assert float(fresh["Qty"]) == 2 and (fresh["FromDocType"], fresh["FromDocDtlKey"]) == ("SO", world.so_a)
    assert len(first.body["Details"]) == 2
    rows = h.vendor.rows("PO", 7001)
    assert len(rows) == 5 and row(h.vendor, "PO", 7001, world.p_free)["Qty"] == 2
    linked = [r for r in rows if r["DtlKey"] not in (world.p_free, world.p_linked, world.p_spo, world.p_other)]
    assert len(linked) == 1 and linked[0]["FromSODtlKey"] == world.so_a
    assert str(linked[0]["DeliveryDate"])[:10] == "2026-12-01"  # the move restored what the vendor cleared


# ============================== AC-61-15 atomic refusal ======================================

@pytest.mark.parametrize("op", ["unlink_row", "link_row", "relink_row"])
def test_ac_61_15_a_500_on_the_replace_put_is_vendor_refused_with_nothing_applied(h, world, op):
    h.vendor.invalid_items = {"ITEM-A"}  # the NEW row is refused, so the whole PUT changes nothing
    before = [dict(r) for r in h.vendor.rows("PO", 7001)]
    res = h.run(op, world.params[op])
    assert res.outcome == "vendor_error" and res.error_code == "VENDOR_REFUSED", (res.outcome, res.error_code)
    assert "Item code does not exist" in res.message
    assert res.replaced_lines == []
    assert len(puts(h)) == 1  # no move PUT, no recovery PUT
    assert "DELETE" not in [c.method for c in h.vendor.calls]
    assert [dict(r) for r in h.vendor.rows("PO", 7001)] == before


# ============================== AC-61-20 delete line =========================================

@pytest.mark.parametrize("kind", ["QT", "SO", "PO"])
def test_ac_61_20_delete_line_is_one_put_with_the_row_marked_d(h, kind):
    _doc, keys = seed_plain(h, kind, 5100)
    other_before = dict(row(h.vendor, kind, 5100, keys[1]))
    res = h.service().delete_line(**call_args(h, kind, 5100, dtl_key=keys[0]))
    assert res.outcome == "done", res.error_code
    assert methods(h) == ["PUT"]  # no DELETE request
    put = puts(h)[0]
    assert put.leaf == EDIT_LEAF[kind]
    assert [(r["DtlKey"], r["FullTransferOption"]) for r in put.body["Details"]] == [(keys[0], "D")]
    assert [r["DtlKey"] for r in h.vendor.rows(kind, 5100)] == [keys[1]]
    assert row(h.vendor, kind, 5100, keys[1]) == other_before


def test_ac_61_20_row_not_gone_after_the_put_is_line_not_deleted(h):
    _doc, keys = seed_plain(h, "SO", 5100)
    h.vendor.ignored_fields = {"FullTransferOption"}  # the vendor answers 200 and keeps the row
    original_edit = h.vendor._edit

    def keep(kind, body):  # a vendor that answers 200 but did not delete
        stripped = dict(body, Details=[])
        return original_edit(kind, stripped)

    h.vendor._edit = keep
    res = h.service().delete_line(**call_args(h, "SO", 5100, dtl_key=keys[0]))
    assert res.outcome == "mismatch" and res.error_code == "LINE_NOT_DELETED", res


# ============================== AC-61-21 vendor refusal / receipt guard ======================

def test_ac_61_21_so_row_transferred_to_a_po_maps_to_row_has_transfers(h):
    _doc, keys = seed_plain(h, "SO", 5100)
    # the PO is NOT staged, so only AutoCount knows: its UnableToDeleteTransferredItem answer
    h.seed_doc("PO", 5101, [_line("A", 4, 5.0, FromSODtlKey=keys[0], FromDocType="SO", FromDocDtlKey=keys[0])],
               stage=False)
    res = h.service().delete_line(**call_args(h, "SO", 5100, dtl_key=keys[0]))
    assert res.error_code == "ROW_HAS_TRANSFERS" and res.outcome != "done", res
    assert len(h.vendor.writes()) == 1
    assert len(h.vendor.rows("SO", 5100)) == 2  # nothing changed


def test_ac_61_21_qt_row_transferred_to_an_so_maps_to_row_has_transfers(h):
    _doc, keys = seed_plain(h, "QT", 5200)
    h.seed_doc("SO", 5201, [_line("A", 4, 5.0, FromDocType="QT", FromDocNo="QT-5200", FromDocDtlKey=keys[0])],
               stage=False)
    res = h.service().delete_line(**call_args(h, "QT", 5200, dtl_key=keys[0]))
    assert res.error_code == "ROW_HAS_TRANSFERS" and res.outcome != "done", res
    assert len(h.vendor.rows("QT", 5200)) == 2


def test_ac_61_21_any_other_vendor_500_stays_vendor_refused_or_error(h):
    _doc, keys = seed_plain(h, "PO", 5300)
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, json.dumps({"ExceptionMessage": "Disk on fire"}))
    res = h.service().delete_line(**call_args(h, "PO", 5300, dtl_key=keys[0]))
    assert res.error_code == "VENDOR_REFUSED" and "Disk on fire" in res.message


def test_ac_61_21_received_guard_still_refuses_before_any_write(h, world):
    res = h.run("unlink_row", world.params["unlink_row"], receipt_reader=lambda kind, doc, r: Decimal(4))
    assert res.outcome == "refused" and res.error_code == "ROW_RECEIVED"
    assert h.vendor.writes() == []


# ============================== AC-61-22 last line (owner ruling R1: never blocked) ==========

@pytest.mark.parametrize("kind", ["QT", "SO", "PO"])
def test_ac_61_22_removing_the_last_row_is_one_put_with_the_row_marked_d_and_done(h, kind):
    _doc, keys = seed_plain(h, kind, 5400, rows=[_line("A", 10, 5.0)])
    res = h.service().delete_line(**call_args(h, kind, 5400, dtl_key=keys[0]))
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert methods(h) == ["PUT"]
    put = puts(h)[0]
    assert put.leaf == EDIT_LEAF[kind]
    assert [(r["DtlKey"], r["FullTransferOption"]) for r in put.body["Details"]] == [(keys[0], "D")]
    assert h.vendor.rows(kind, 5400) == []  # the read-back has no rows


def test_ac_61_22_the_gateway_passes_the_last_row_delete_through(client, h, gw):
    _doc, keys = seed_plain(h, "SO", 5400, rows=[_line("A", 10, 5.0)])
    r = client.post(f"{PREFIX}/documents/sales-orders/5400/lines/{keys[0]}/delete", headers=gw.hdr(),
                    json={"companyCode": "SRT"})
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done" and h.vendor.rows("SO", 5400) == []


def test_ac_61_22_no_row_last_line_code_exists_anywhere():
    contract = REPO / "documentation" / "plans" / "sprint-5" / "57-autocount-write-qtso-contract.md"
    assert "ROW_LAST_LINE" not in contract.read_text("utf-8")
    module_dir = REPO / "service_backend" / "modules" / "autocount"
    hits = [str(p) for p in module_dir.rglob("*.py") if "ROW_LAST_LINE" in p.read_text("utf-8")]
    assert hits == []


# ============================== AC-61-30 / 31 cancel =========================================

def seed_confirmed_create(h, kind, doc):
    """The confirmed create action SS keeps for a document it made (its read-back carries
    the DocNo): how production knows a QT's DocNo, a QT is never staged."""
    from modules.autocount.models import AcWriteAction

    h.db.add(AcWriteAction(tenant_id=h.company.tenant_id, company_id=h.company.id, action="create_doc",
                           doc_type=kind, doc_key=doc["DocKey"], outcome="done", after_json=doc))
    h.db.commit()


@pytest.mark.parametrize("kind", ["QT", "SO", "PO"])
def test_ac_61_30_cancel_is_the_delete_request_and_reads_back_cancelled(h, kind):
    doc, _keys = seed_plain(h, kind, 5500)
    seed_confirmed_create(h, kind, doc)
    res = h.service().cancel_doc(**call_args(h, kind, 5500))
    assert res.outcome == "done", (res.error_code, res.message)
    assert methods(h) == ["DELETE"]  # no PUT with a header Cancelled
    call = h.vendor.writes()[0]
    assert call.leaf == CANCEL_LEAF[kind] and call.query == {"DocNo": f"{kind}-5500"} and call.body is None
    assert res.document["Cancelled"] == "T"
    assert h.vendor.find(kind, 5500)["Cancelled"] == "T"
    assert by_no_gets(h) and by_day_gets(h) == []


def test_ac_61_30_cancel_of_a_doc_ss_never_saw_learns_its_doc_no_from_the_day_list(h):
    """No staged copy and no confirmed action: the DocNo is unknown, so the before-read is
    the day list (AC-61-03 fallback); the DELETE then carries the DocNo it found."""
    seed_plain(h, "QT", 5550)
    res = h.service().cancel_doc(**call_args(h, "QT", 5550))
    assert res.outcome == "done", (res.error_code, res.message)
    assert by_day_gets(h) and by_day_gets(h)[0].query == {"DocDate": "20261104"}
    assert methods(h) == ["DELETE"] and h.vendor.writes()[0].query == {"DocNo": "QT-5550"}
    assert h.vendor.find("QT", 5550)["Cancelled"] == "T"


def test_ac_61_30_a_200_that_changed_nothing_is_cancel_ignored(h):
    seed_plain(h, "SO", 5500)
    h.vendor.cancel_ignored = True
    res = h.service().cancel_doc(**call_args(h, "SO", 5500))
    assert res.outcome == "mismatch" and res.error_code == "CANCEL_IGNORED", res


def test_ac_61_31_transferred_qt_maps_to_doc_has_transfers(h):
    seed_plain(h, "QT", 5600)
    h.seed_doc("SO", 5601, [_line("A", 4, 5.0, FromDocType="QT", FromDocNo="QT-5600", FromDocDtlKey=1)], stage=False)
    res = h.service().cancel_doc(**call_args(h, "QT", 5600))
    assert res.error_code == "DOC_HAS_TRANSFERS" and res.outcome != "done", res
    assert h.vendor.find("QT", 5600)["Cancelled"] == "F"


def test_ac_61_31_transferred_so_maps_to_doc_has_transfers(h):
    _doc, keys = seed_plain(h, "SO", 5700)
    h.seed_doc("PO", 5701, [_line("A", 4, 5.0, FromSODtlKey=keys[0], FromDocType="SO", FromDocDtlKey=keys[0])],
               stage=False)
    res = h.service().cancel_doc(**call_args(h, "SO", 5700))
    assert res.error_code == "DOC_HAS_TRANSFERS" and res.outcome != "done", res
    assert h.vendor.find("SO", 5700)["Cancelled"] == "F"


def test_ac_61_31_void_answer_maps_to_doc_cancelled(h):
    seed_plain(h, "PO", 5800)
    h.vendor.fail_next("DELETE", CANCEL_LEAF["PO"], 400, json.dumps({
        "Message": "Unable to (Cancel Document) for this document, due to current document status (Void)."}))
    res = h.service().cancel_doc(**call_args(h, "PO", 5800))
    assert res.error_code == "DOC_CANCELLED", res


@pytest.mark.parametrize("status,body", [(400, {"Message": "Some other reason."}),
                                         (500, {"ExceptionMessage": "Some other reason."})])
def test_ac_61_31_any_other_failure_is_vendor_refused_with_the_vendor_text(h, status, body):
    seed_plain(h, "SO", 5900)
    h.vendor.fail_next("DELETE", CANCEL_LEAF["SO"], status, json.dumps(body))
    res = h.service().cancel_doc(**call_args(h, "SO", 5900))
    assert res.error_code == "VENDOR_REFUSED" and "Some other reason." in res.message, res
    assert h.vendor.find("SO", 5900)["Cancelled"] == "F"


# ============================== AC-61-32 gateway cancel ======================================

@pytest.mark.parametrize("kind", ["QT", "SO", "PO"])
def test_ac_61_32_gateway_cancel_answers_done(client, h, gw, kind):
    seed_plain(h, kind, 6100)
    r = client.post(f"{PREFIX}/documents/{SLUG[kind]}/6100/cancel", headers=gw.hdr(),
                    json={"companyCode": "SRT", "docDate": "2026-11-04"})
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done" and r.json()["document"]["Cancelled"] == "T"
    assert methods(h) == ["DELETE"]


def test_ac_61_32_gateway_cancel_of_an_spo_stays_vendor_unsupported_with_no_request(client, h, gw):
    h.seed_doc("SPO", 6200, [_line("A", 4, 5.0)])
    h.vendor.calls.clear()
    r = client.post(f"{PREFIX}/documents/{SLUG['SPO']}/6200/cancel", headers=gw.hdr(),
                    json={"companyCode": "SRT", "docDate": "2026-11-04"})
    assert r.status_code == 409 and code(r) == "VENDOR_UNSUPPORTED", r.text
    assert h.vendor.calls == []


def test_ac_61_32_gateway_delete_line_answers_done_for_qt_so_po(client, h, gw):
    for kind, key in (("QT", 6300), ("SO", 6301), ("PO", 6302)):
        _doc, keys = seed_plain(h, kind, key)
        r = client.post(f"{PREFIX}/documents/{SLUG[kind]}/{key}/lines/{keys[0]}/delete", headers=gw.hdr(f"k-{kind}"),
                        json={"companyCode": "SRT", "docDate": "2026-11-04"})
        assert r.status_code == 200, (kind, r.text)
        assert [x["DtlKey"] for x in h.vendor.rows(kind, key)] == [keys[1]]
    assert "DELETE" not in methods(h)


# ============================== AC-61-40 capability table ====================================

def test_ac_61_40_capability_table_on_off():
    from modules.autocount.write_back import capabilities as caps

    for kind in ("QT", "SO", "PO"):
        for primitive in ("delete_line", "cancel_doc"):
            assert caps.capable(kind, primitive) is True, (kind, primitive)
        assert caps.capable(kind, "delete_doc") is False
    for primitive in ("create_doc", "add_line", "delete_line", "delete_doc", "cancel_doc"):
        assert caps.capable("SPO", primitive) is False, primitive
    assert caps.capable("SPO", "edit_doc") is True
    assert not hasattr(caps, "ZERO_QTY_EMULATION")


def test_ac_61_40_write_capabilities_report_follows_the_table(client, h, gw):
    r = client.get(f"{PREFIX}/write-capabilities?companyCode=SRT", headers=_hdr(gw.plain))
    assert r.status_code == 200, r.text
    short = {v: k for k, v in SLUG.items()}
    caps = {(i["op"], short[i["kind"]]): i for i in r.json()["capabilities"]}
    for key in (("unlink_row", "PO"), ("link_row", "PO"), ("relink_row", "PO"),
                ("delete_line", "QT"), ("delete_line", "SO"), ("delete_line", "PO"),
                ("cancel_doc", "QT"), ("cancel_doc", "SO"), ("cancel_doc", "PO")):
        assert caps[key]["enabled"] is True and caps[key]["reasonCode"] is None, key
    for key in (("spo_link_row", "SPO"), ("spo_unlink_row", "SPO"), ("spo_relink_row", "SPO"),
                ("delete_line", "SPO"), ("cancel_doc", "SPO"), ("create_doc", "SPO"), ("add_line", "SPO")):
        assert caps[key]["enabled"] is False and caps[key]["reasonCode"] == "VENDOR_UNSUPPORTED", key
    assert caps[("edit_doc", "SPO")]["enabled"] is True
    for kind in ("QT", "SO", "PO", "SPO"):
        assert caps.get(("delete_doc", kind), {"enabled": False})["enabled"] is False


def test_ac_61_40_spo_unlink_route_stays_vendor_unsupported_with_no_request(client, h, gw, world):
    h.vendor.calls.clear()
    r = client.post(f"{PREFIX}/spo-links/unlink", headers=gw.hdr(),
                    json={"companyCode": "SRT", "spoDocKey": 7003, "spoDtlKey": world.s_linked})
    assert r.status_code == 409 and code(r) == "VENDOR_UNSUPPORTED", r.text
    assert h.vendor.writes() == []


# ============================== AC-61-41 no placeholder delete doors =========================

@pytest.mark.parametrize("kind", ["QT", "SO", "PO", "SPO"])
def test_ac_61_41_delete_doc_is_vendor_unsupported_and_sends_nothing(h, kind):
    seed_plain(h, kind, 6400)
    h.vendor.calls.clear()
    res = h.service().delete_doc(**call_args(h, kind, 6400))
    assert res.outcome == "refused" and res.error_code == "VENDOR_UNSUPPORTED", res
    assert h.vendor.calls == []


def test_ac_61_41_no_placeholder_delete_path_is_left_in_the_write_layer():
    offenders = []
    for path in sorted(WB_DIR.glob("*.py")):
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            if re.search(r"/Delete[A-Za-z]*|Delete\w*bydtlkey|Delete\w*bydockey", line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == []


def test_ac_61_41_unlink_and_cancel_and_delete_builders_of_the_old_shapes_are_gone():
    from modules.autocount.write_back import payloads

    assert not hasattr(payloads, "build_delete_doc")
    assert not hasattr(payloads, "build_unlink")  # the blank-link PUT never lands (db3 ignored it)
    assert not hasattr(payloads, "build_spo_unlink")
    assert hasattr(payloads, "build_row_replace")


# ============================== round 3: review round 1 findings ===============================

def _row_matches_old(stored, old, *, location=None):
    assert float(stored["UnitPrice"]) == float(old["UnitPrice"]), stored["UnitPrice"]
    assert str(stored["DeliveryDate"])[:10] == str(old["DeliveryDate"])[:10], stored["DeliveryDate"]
    if location is not None:
        assert stored["Location"] == location


def test_r3_fake_vendor_resets_a_new_linked_po_row_price_to_zero_and_a_later_edit_can_set_it(h, world):
    res = h.service().add_line(**h.args("PO", doc_key=7001, line=_line(
        "ITEM-A", 1, 9.0, "BR1", FromDocType="SO", FromDocNo="SO-7002", FromDocDtlKey=world.so_a)))
    assert res.outcome in ("done", "mismatch"), res.error_code
    added = [r for r in h.vendor.rows("PO", 7001)
             if r["DtlKey"] not in (world.p_free, world.p_linked, world.p_spo, world.p_other)][0]
    assert added["UnitPrice"] == 0.0 and added["Location"] == "HQ" and str(added["DeliveryDate"]).startswith("0001")
    assert added["FromSODtlKey"] == world.so_a and added["FromDocType"] == ""
    h.vendor._edit("PO", {"DocKey": 7001, "Details": [{"DtlKey": added["DtlKey"], "UnitPrice": 9.0,
                                                       "Location": "BR1", "DeliveryDate": "2026-12-01T00:00:00"}]})
    again = row(h.vendor, "PO", 7001, added["DtlKey"])
    assert (again["UnitPrice"], again["Location"], str(again["DeliveryDate"])[:10]) == (9.0, "BR1", "2026-12-01")


def test_r3_link_row_ends_done_with_the_old_rows_price_and_date_in_exactly_two_puts(h, world):
    old = dict(row(h.vendor, "PO", 7001, world.p_free))
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert not res.warnings and len(puts(h)) == 2 and "DELETE" not in methods(h)
    (_o, new), = res.replaced_lines
    stored = row(h.vendor, "PO", 7001, new)
    _row_matches_old(stored, old)
    assert stored["FromSODtlKey"] == world.so_a
    assert float(puts(h)[1].body["Details"][0]["UnitPrice"]) == float(old["UnitPrice"])


def test_r3_link_row_moves_to_the_so_rows_location_when_it_differs(h):
    world = World(h, so_loc="BRW-AM")
    old = dict(row(h.vendor, "PO", 7001, world.p_free))
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done" and len(puts(h)) == 2, (res.outcome, res.error_code)
    (_o, new), = res.replaced_lines
    _row_matches_old(row(h.vendor, "PO", 7001, new), old, location="BRW-AM")


def test_r3_relink_row_ends_done_with_the_old_rows_price_and_date_in_exactly_two_puts(h, world):
    old = dict(row(h.vendor, "PO", 7001, world.p_linked))
    res = h.run("relink_row", world.params["relink_row"])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert not res.warnings and len(puts(h)) == 2
    (_o, new), = res.replaced_lines
    stored = row(h.vendor, "PO", 7001, new)
    _row_matches_old(stored, old)
    assert stored["FromSODtlKey"] == world.so_b


def test_r3_gateway_link_and_relink_end_done_not_recovered(client, h, gw, world):
    old_link = dict(row(h.vendor, "PO", 7001, world.p_free))
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr(), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_free,
        "soDocKey": 7002, "soDtlKey": world.so_a, "qty": 4})
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert len(puts(h)) == 2
    new = r.json()["replacedLines"][0][1]
    _row_matches_old(row(h.vendor, "PO", 7001, new), old_link)
    h.vendor.calls.clear()
    old_re = dict(row(h.vendor, "PO", 7001, world.p_linked))
    r = client.post(f"{PREFIX}/po-links/relink", headers=gw.hdr("k2"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked,
        "soDocKey": 7002, "soDtlKey": world.so_b})
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert len(puts(h)) == 2
    _row_matches_old(row(h.vendor, "PO", 7001, r.json()["replacedLines"][0][1]), old_re)


@pytest.mark.parametrize("op", ["link_row", "relink_row"])
def test_r3_a_failed_move_put_is_done_with_both_warnings_and_no_third_put(h, world, op):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "no move", after=1)
    res = h.run(op, world.params[op])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert "LOCATION_NOT_MOVED" in res.warnings and "ROW_VALUES_NOT_KEPT" in res.warnings
    assert len(puts(h)) == 2  # the replace and the failed move: no recovery, no retry
    (_o, new), = res.replaced_lines
    assert row(h.vendor, "PO", 7001, new)["FromSODtlKey"] in (world.so_a, world.so_b)  # the link is kept


def test_r3_old_row_at_hq_without_a_date_but_with_a_price_still_gets_the_move_put(h):
    world = World(h)
    free = row(h.vendor, "PO", 7001, world.p_free)
    free["Location"], free["DeliveryDate"] = "HQ", "0001-01-01T00:00:00"  # UnitPrice stays 5.0
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(puts(h)) == 2
    (_o, new), = res.replaced_lines
    assert float(row(h.vendor, "PO", 7001, new)["UnitPrice"]) == 5.0


# ---- AC-61-20: ROW_RECEIVED / ROW_ON_SPO before any request on a PO delete_line ----------------

def test_r3_po_delete_line_on_a_received_row_is_row_received_with_zero_writes(h, world):
    row(h.vendor, "PO", 7001, world.p_free)["TransferedQty"] = 4  # the GET shows a full receipt
    res = h.service().delete_line(**h.args("PO", doc_key=7001, dtl_key=world.p_free))
    assert res.outcome == "refused" and res.error_code == "ROW_RECEIVED", (res.outcome, res.error_code)
    assert h.vendor.writes() == []


def test_r3_po_delete_line_control_nothing_received_is_deleted(h, world):
    row(h.vendor, "PO", 7001, world.p_free)["TransferedQty"] = 0
    res = h.service().delete_line(**h.args("PO", doc_key=7001, dtl_key=world.p_free))
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert methods(h) == ["PUT"]


def test_r3_po_delete_line_on_a_row_an_spo_points_at_is_row_on_spo_with_zero_writes(h, world):
    res = h.service().delete_line(**h.args("PO", doc_key=7001, dtl_key=world.p_spo))
    assert res.outcome == "refused" and res.error_code == "ROW_ON_SPO", (res.outcome, res.error_code)
    assert h.vendor.writes() == []
    assert row(h.vendor, "PO", 7001, world.p_spo) is not None


# ---- replace PUT timeout ----------------------------------------------------------------------

@pytest.mark.parametrize("op", ["unlink_row", "link_row", "relink_row"])
def test_r3_replace_put_timeout_is_pending_sent_once_and_never_moved(h, world, op):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    res = h.run(op, world.params[op])
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    sent_puts = [c for c in h.vendor.calls if c.method == "PUT"]
    assert len(sent_puts) == 1  # exactly once: no retry, no move PUT
    assert "DELETE" not in [c.method for c in h.vendor.calls]


# ---- AC-61-16: FullTransferFromDocList "" on relocate and the split restore PUT ----------------------

def _all_rows_blank_list(h):
    rows = [r for c in puts(h) for r in c.body["Details"] if r.get("FullTransferOption") != "D"]
    assert rows
    for r in rows:
        assert "FullTransferFromDocList" in r and r["FullTransferFromDocList"] == "", r


def test_r3_relocate_put_rows_carry_a_blank_full_transfer_from_doc_list(h, world):
    from modules.autocount.write_back.service import WriteBackService

    row(h.vendor, "PO", 7001, world.p_linked)["Location"] = "BR1"  # SO row sits at HQ
    svc = WriteBackService(h.db, **h.factories())
    res = svc.relocate(tenant_id=h.company.tenant_id, company_id=h.company.id, po_doc_key=7001,
                       po_dtl_key=world.p_linked, key_id="k1")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(puts(h)) == 1
    _all_rows_blank_list(h)


def test_r3_split_link_restore_put_rows_carry_a_blank_full_transfer_from_doc_list(h, world):
    res = h.run("split_link", dict(po_doc_key=7001, po_dtl_key=world.p_free, so_doc_key=7002,
                                   so_dtl_key=world.so_a, qty=2))
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(puts(h)) == 2  # the split, then the restore of the fields the vendor reset
    _all_rows_blank_list(h)
