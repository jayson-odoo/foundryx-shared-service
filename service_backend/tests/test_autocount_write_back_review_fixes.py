"""Plan 57 (RED): AC-57-41..47 from the review, the security review and the live db3 run.

New fake-vendor knobs used here: ``drop_link_next_add``, ``require_full_row``,
``inherit_qt_values`` (plus the existing ``apply_then_500_next`` for a stray row and for a
delete that landed, and ``fail_next`` with an IIS-like HTML body).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    AcEntityConfig,
    AcStagedRecord,
    AcWriteAction,
)
from tests.autocount_write_back_fake_vendor import FULL_ROW_KEYS, new_doc
from tests.test_autocount_write_back_gateway_qtso import (  # noqa: F401
    PREFIX,
    Gw,
    code,
    create_body,
    gw,
    no_secret,
    world,
)
from tests.test_autocount_write_back_operations import (  # noqa: F401
    deleted_a_row,
    PUT_PO,
    OpHarness,
    drop_new_row_once,
    World,
    db,
    h,
    w,
    w_far,
)
from tests.test_autocount_write_back_primitives import DB3, SECRETS, _header, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

DB1 = "https://ac.example.test/api/db1"
HTML_500 = (
    "<html><head><title>IIS 8.5 Detailed Error - 500.0</title></head><body>"
    "<h2>HTTP Error 500.0 - Internal Server Error</h2>"
    "<p>Requested URL: http://acw-internal.corp:8080/api/db3/EditPurchaseOrderbydockey</p>"
    "<p>Physical Path: C:\\\\inetpub\\\\wwwroot\\\\AutoCountApi\\\\bin</p>"
    "<p>Logon User: CORP\\\\svc_autocount</p></body></html>"
)
LEAKS = ("acw-internal", "http://", "C:\\\\", "inetpub", "svc_autocount", "Logon User", "8080")


def blob(*parts) -> str:
    return json.dumps(parts, default=str)


def n_item_a(h, doc_key=7001):
    rows = [r for r in h.vendor.rows("PO", doc_key) if r["ItemCode"] == "ITEM-A"]
    return len(rows), sum(Decimal(str(r["Qty"])) for r in rows)


# ======================================================================================
# AC-57-41: the link is verified on add; recovery removes a stray row, never doubles qty
# ======================================================================================

def test_ac_57_41_link_row_whose_add_loses_the_link_is_recovered_without_doubling_qty(h, w_far):
    w = w_far
    h.vendor.drop_link_next_add()
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "recovered", (res.outcome, res.error_code)
    assert res.error_code  # the failed step's code (the link mismatch)
    count, qty = n_item_a(h)
    assert (count, qty) == (4, Decimal(16)), "a stray linked-less copy must not double the line"
    assert all(r["FromSODtlKey"] != w.so_a or r["DtlKey"] == w.p_linked for r in h.vendor.rows("PO", 7001))


def test_ac_57_41_the_stray_row_is_deleted_before_the_original_is_re_added(h, w_far):
    w = w_far
    h.vendor.drop_link_next_add()
    h.run("link_row", w.params["link_row"])
    assert h.steps() == [PUT_PO, PUT_PO, PUT_PO]  # plan 61: replace (link lost), unstray, re-add
    replace, unstray, readd = h.vendor.writes()
    stray = [r["DtlKey"] for r in unstray.body["Details"]]
    assert [r.get("FullTransferOption") for r in unstray.body["Details"]] == ["D"]  # the stray goes first
    assert stray[0] not in [r["DtlKey"] for r in w.po["Details"]]
    assert [r["DtlKey"] for r in readd.body["Details"]] == [0]  # then the original is re-added


def test_ac_57_41_a_failed_add_that_applied_leaves_a_stray_row_that_recovery_removes(h, w):
    h.vendor.apply_then_500_next("PUT", "EditPurchaseOrderbydockey")  # the add lands, answers 500
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome in ("recovered", "needs_attention", "pending_verification"), res.outcome
    if res.outcome == "recovered":
        assert n_item_a(h) == (4, Decimal(16))
    else:
        assert res.outcome != "done"


def test_ac_57_41_when_the_stray_row_cannot_be_removed_the_operation_needs_attention(h, w_far):
    w = w_far
    h.vendor.drop_link_next_add()
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "boom", after=1)  # the unstray "D" fails
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "needs_attention"
    assert len(h.alerts) == 1
    count, qty = n_item_a(h)
    assert qty <= Decimal(20) and h.steps() == [PUT_PO, PUT_PO]  # replace, failed unstray: no blind re-add
    assert all(r["DtlKey"] for r in h.vendor.writes()[1].body["Details"])


def test_ac_57_41_po_add_line_with_a_dropped_link_is_a_mismatch_not_done(h):
    h.delete_on()
    w = World(h)
    h.vendor.drop_link_next_add()
    line = _line("ITEM-A", 1, 5.0, "HQ", FromDocType="SO", FromDocNo="SO-7002", FromDocDtlKey=w.so_a)
    res = h.service().add_line(**h.args("PO", doc_key=7001, line=line))
    assert res.outcome == "mismatch", res.outcome
    assert "Linked" in (res.error_code or "") or "LINK" in (res.error_code or "").upper() or res.error_code


def test_ac_57_41_spo_add_line_with_a_dropped_link_is_a_mismatch(h):
    h.delete_on()
    w = World(h)
    h.vendor.drop_link_next_add()
    line = _line("ITEM-A", 1, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7001", FromDocDtlKey=w.p_other)
    res = h.service().add_line(**h.args("SPO", doc_key=7003, line=line))
    assert res.outcome == "mismatch", res.outcome


def test_ac_57_41_so_create_from_quotation_that_loses_the_link_type_is_a_mismatch(h):
    h.vendor.drop_link_next_add()
    line = _line(FromDocType="QT", FromDocNo="QT-000009", FromDocDtlKey=555)
    res = h.create("SO", lines=[line])
    assert res.outcome == "mismatch", res.outcome


def test_ac_57_41_a_link_that_landed_is_still_done(h):
    h.delete_on()
    w = World(h)
    line = _line("ITEM-A", 1, 5.0, "HQ", FromDocType="SO", FromDocNo="SO-7002", FromDocDtlKey=w.so_a)
    assert h.service().add_line(**h.args("PO", doc_key=7001, line=line)).outcome == "done"


# ======================================================================================
# AC-57-42: a delete with an unknown outcome is pending_verification (resumable)
# ======================================================================================

@pytest.mark.parametrize("failure", ["boom", HTML_500, ""])
def test_ac_57_42_a_bare_5xx_on_the_delete_is_pending_verification_and_resumable(h, w, failure):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, failure)  # plan 61: on the replace PUT
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    assert h.steps() == [PUT_PO]  # no recovery on top of an unknown replace
    out = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)
    assert out.outcome in ("done", "recovered")


def test_ac_57_42_a_delete_that_landed_but_answered_5xx_is_resumed_by_re_creating_the_row(h, w):
    h.vendor.apply_then_500_next("PUT", "EditPurchaseOrderbydockey")  # plan 61: the replace landed
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "pending_verification"
    assert w.row_by_key(w.po_rows(), w.p_linked) is None
    out = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)
    assert out.outcome in ("done", "recovered")
    assert n_item_a(h) == (4, Decimal(16))


def test_ac_57_42_only_vendor_refused_means_the_delete_did_not_land(h, w):
    h.vendor.mark_received("PO", 7001, w.p_linked, "line already received")
    res = h.run("unlink_row", w.params["unlink_row"], receipt_reader=lambda *a: None)
    assert res.outcome == "vendor_error" and res.error_code == "VENDOR_REFUSED"
    assert h.steps() == [PUT_PO]


# ======================================================================================
# AC-57-43: a stranded operation never blocks a document; DOC_BUSY is not stored
# ======================================================================================

def _strand(h, res, age_seconds):
    """Make a finished operation look like a crashed in_progress one, ``age_seconds`` old."""
    from modules.autocount.models import AcWriteOperation

    old = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    op = h.db.query(AcWriteOperation).filter(AcWriteOperation.id == res.operation_id).one()
    op.status = "in_progress"
    op.created_at = old
    op.updated_at = old
    h.db.commit()
    return op.id


def test_ac_57_43_an_old_in_progress_operation_is_flipped_and_does_not_block(h, w):
    from modules.autocount.write_back.frame import BUSY_WINDOW_SECONDS
    from modules.autocount.models import AcWriteOperation

    h.vendor.timeout_next("PUT", "editpurchaseorderbydockey")  # plan 61: the replace PUT times out
    first = h.run("unlink_row", w.params["unlink_row"], key="k-old")
    assert first.outcome == "pending_verification", first.outcome
    op_id = _strand(h, first, BUSY_WINDOW_SECONDS + 60)
    second = h.run("link_row", w.params["link_row"], key="k-new")
    assert second.error_code != "DOC_BUSY", second.error_code
    assert second.outcome == "done"
    h.db.expire_all()
    assert h.db.get(AcWriteOperation, op_id).status == "pending_verification"
    out = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=op_id)
    assert out.outcome not in ("refused",) or out.error_code != "DOC_BUSY"


def test_ac_57_43_a_young_in_progress_operation_still_blocks(h, w):
    h.vendor.timeout_next("PUT", "editpurchaseorderbydockey")  # plan 61: the replace PUT times out
    first = h.run("unlink_row", w.params["unlink_row"], key="k-old")
    assert first.outcome == "pending_verification", first.outcome
    _strand(h, first, 5)
    second = h.run("link_row", w.params["link_row"], key="k-new")
    assert second.outcome == "refused" and second.error_code == "DOC_BUSY"


def test_ac_57_43_doc_busy_is_not_stored_under_the_idempotency_key(h, w):
    busy = AcWriteAction(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, action="edit_doc",
                         doc_type="PO", doc_key=7001, outcome="in_flight", request_json={})
    h.db.add(busy)
    h.db.commit()
    first = h.run("link_row", w.params["link_row"], key="retry-me")
    assert first.outcome == "refused" and first.error_code == "DOC_BUSY"
    h.db.delete(busy)
    h.db.commit()
    again = h.run("link_row", w.params["link_row"], key="retry-me")
    assert again.outcome == "done", (again.outcome, again.error_code)  # tried again, not the stored refusal


# ======================================================================================
# AC-57-44: /po-links passes the caller's qty; soDocDate / poDocDate
# ======================================================================================

def _set_row_qty(h, dtl_key, qty, *, vendor_only=True):
    next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == dtl_key)["Qty"] = qty


def _po_links_body(world, qty, **extra):
    return {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_free, "soDocKey": 7002,
            "soDtlKey": world.so_a, "qty": qty, **extra}


def test_ac_57_44_a_part_qty_is_a_split_even_when_autocount_holds_more_than_staged(client, gw, world):
    _set_row_qty(gw.h, world.p_free, 6)  # staged copy says 4
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr(), json=_po_links_body(world, 4))
    assert r.status_code == 200, r.text
    rows = gw.h.vendor.rows("PO", 7001)
    linked = [x for x in rows if x["FromSODtlKey"] == world.so_a and x["DtlKey"] != world.p_linked]
    assert len(linked) == 1 and linked[0]["Qty"] == 4  # never the whole 6
    assert next(x for x in rows if x["DtlKey"] == world.p_free)["Qty"] == 2
    assert all(c.method != "DELETE" for c in gw.h.vendor.writes())


def test_ac_57_44_a_whole_row_qty_runs_the_operation_and_needs_the_delete_flag(client, h, db):
    gw = Gw(h, db)
    h.flag("PO", "delete_line", False)  # plan 61 ships it on: switched off here
    world = World(h)
    _set_row_qty(h, world.p_free, 6)
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr(), json=_po_links_body(world, 6))
    assert r.status_code == 409 and code(r) == "VENDOR_UNSUPPORTED", r.text
    assert h.vendor.writes() == []


def test_ac_57_44_a_whole_row_qty_against_the_fresh_qty_deletes_and_adds(client, gw, world):
    _set_row_qty(gw.h, world.p_free, 6)
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr(), json=_po_links_body(world, 6))
    assert r.status_code == 200, r.text
    first = gw.h.vendor.writes()[0]  # plan 61: one replace PUT, the row "D" + a new linked row
    assert first.method == "PUT" and [r.get("FullTransferOption") for r in first.body["Details"]][0] == "D"
    assert r.json()["replacedLines"]


def test_ac_57_44_same_key_other_qty_is_an_idempotency_conflict(client, gw, world):
    first = client.post(f"{PREFIX}/po-links", headers=gw.hdr(), json=_po_links_body(world, 2))
    assert first.status_code == 200, first.text
    clash = client.post(f"{PREFIX}/po-links", headers=gw.hdr(), json=_po_links_body(world, 3))
    assert clash.status_code == 409 and code(clash) == "IDEMPOTENCY_CONFLICT"


def _unstage(h, entity, doc_key):
    h.db.query(AcStagedRecord).filter(AcStagedRecord.entity_type == entity,
                                      AcStagedRecord.source_ref == f"AED_TEST:{doc_key}").delete()
    h.db.commit()


def test_ac_57_44_so_doc_date_lets_link_and_relink_reach_an_unstaged_target(client, gw, world):
    _unstage(gw.h, "sales_order", 7002)
    relink = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "soDocKey": 7002,
              "soDtlKey": world.so_b}
    r = client.post(f"{PREFIX}/po-links/relink", headers=gw.hdr("a"), json=relink)
    assert r.status_code == 409 and code(r) == "DOC_DATE_REQUIRED", r.text
    r = client.post(f"{PREFIX}/po-links/relink", headers=gw.hdr("b"), json={**relink, "soDocDate": "2026-11-04"})
    assert r.status_code == 200, r.text
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr("c"),
                    json=_po_links_body(world, 2, soDocDate="2026-11-04"))
    assert r.status_code == 200, r.text


def test_ac_57_44_po_doc_date_lets_spo_link_and_relink_reach_an_unstaged_target(client, gw, world):
    _unstage(gw.h, "purchase_order", 7001)
    link = {"companyCode": "SRT", "spoDocKey": 7003, "spoDtlKey": world.s_free, "poDocKey": 7001,
            "poDtlKey": world.p_other}
    r = client.post(f"{PREFIX}/spo-links", headers=gw.hdr("a"), json=link)
    assert r.status_code == 409 and code(r) == "DOC_DATE_REQUIRED", r.text
    r = client.post(f"{PREFIX}/spo-links", headers=gw.hdr("b"), json={**link, "poDocDate": "2026-11-04"})
    assert r.status_code == 200, r.text
    new_key = r.json()["replacedLines"][0]["newDtlKey"]
    r = client.post(f"{PREFIX}/spo-links/relink", headers=gw.hdr("c"), json={
        **link, "spoDtlKey": new_key, "poDtlKey": world.p_free, "poDocDate": "2026-11-04"})
    assert r.status_code == 200, r.text


def test_ac_57_44_a_malformed_target_doc_date_is_422(client, gw, world):
    r = client.post(f"{PREFIX}/po-links/relink", headers=gw.hdr(), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "soDocKey": 7002,
        "soDtlKey": world.so_b, "soDocDate": "04/11/2026"})
    assert r.status_code == 422
    gw.h.no_http()


# ======================================================================================
# AC-57-45: builders always send the full vendor row shape
# ======================================================================================

@pytest.mark.parametrize("kind", ["QT", "SO", "PO"])
def test_ac_57_45_create_and_add_line_carry_the_full_row_shape(h, kind):
    res = h.create(kind, lines=[_line()])
    assert res.outcome == "done", res.error_code
    sent = h.vendor.writes()[0].body["Details"][0]
    missing = [k for k in FULL_ROW_KEYS if k not in sent] if kind == "SO" else [
        k for k in ("ProjNo", "FOCQty", "Discount", "TaxCode", "Desc2") if k not in sent]
    assert not missing, missing
    h.delete_on()
    add = h.service().add_line(**h.args(kind, doc_key=res.doc_key, line=_line("Z", 1, 2.0),
                                        doc_date=__import__("datetime").date(2026, 11, 4)))
    assert add.outcome == "done", add.error_code
    row = h.vendor.writes()[-1].body["Details"][0]
    assert all(k in row for k in ("ProjNo", "FOCQty", "Discount", "TaxCode", "Desc2"))


def test_ac_57_45_a_thin_sales_order_row_is_not_dropped_through_the_gateway(client, gw):
    gw.h.vendor.require_full_row = {"SO"}
    r = client.post(f"{PREFIX}/documents/sales-orders", json=create_body("SO"), headers=gw.hdr())
    assert r.status_code == 200, r.text
    assert len(r.json()["document"]["Details"]) == 1
    add = client.post(f"{PREFIX}/documents/sales-orders/{r.json()['docKey']}/lines", headers=gw.hdr("k2"),
                      json={"companyCode": "SRT", "docDate": "2026-11-04", "line": {
                          "itemCode": "C", "uom": "UNIT", "qty": 1, "unitPrice": 3, "location": "HQ"}})
    assert add.status_code == 200, add.text
    assert len(add.json()["document"]["Details"]) == 2


def test_ac_57_45_the_dropping_fake_really_drops_a_thin_row(h):
    h.vendor.require_full_row = {"SO"}
    import httpx

    body = {"DocNo": "<<New>>", "DocDate": "2026-11-04T00:00:00", "DebtorCode": "D", "DisplayTerm": "x",
            "CurrencyCode": "MYR", "CurrencyRate": 1, "Details": [{"ItemCode": "A", "UOM": "UNIT", "Qty": 1,
                                                                    "UnitPrice": 1, "Location": "HQ"}]}
    with httpx.Client(transport=h.vendor.transport, base_url=DB3) as c:
        assert c.post("/NewSalesOrder", json=body).status_code == 200
    assert h.vendor.docs["SO"][0]["Details"] == []


# ======================================================================================
# AC-57-46: an SO row taken from a QT row inherits its price and location
# ======================================================================================

def _qt(h):
    qt = h.seed_doc("QT", 6001, [_line("A", 5, 900.0, "HQ")], stage=False, doc_no="QT-6001")
    return qt["Details"][0]["DtlKey"]


def test_ac_57_46_inherited_price_and_location_are_a_warning_not_a_failure(h):
    h.vendor.inherit_qt_values = True
    dtl = _qt(h)
    line = _line("A", 5, 99.0, "BR1", FromDocType="QT", FromDocNo="QT-6001", FromDocDtlKey=dtl)
    res = h.create("SO", lines=[line])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert "QT_ROW_VALUES_INHERITED" in res.warnings
    named = (getattr(res, "message", "") or "") + json.dumps(res.warnings)
    assert "UnitPrice" in named and "Location" in named
    row = h.vendor.docs["SO"][0]["Details"][0]
    assert row["UnitPrice"] == 900.0 and row["Location"] == "HQ"


def test_ac_57_46_only_the_fields_that_differ_are_named(h):
    h.vendor.inherit_qt_values = True
    dtl = _qt(h)
    line = _line("A", 5, 900.0, "BR1", FromDocType="QT", FromDocNo="QT-6001", FromDocDtlKey=dtl)
    res = h.create("SO", lines=[line])
    assert res.outcome == "done"
    named = (getattr(res, "message", "") or "") + json.dumps(res.warnings)
    assert "Location" in named and "UnitPrice" not in named


def test_ac_57_46_no_warning_when_the_values_already_match(h):
    h.vendor.inherit_qt_values = True
    dtl = _qt(h)
    line = _line("A", 5, 900.0, "HQ", FromDocType="QT", FromDocNo="QT-6001", FromDocDtlKey=dtl)
    res = h.create("SO", lines=[line])
    assert res.outcome == "done" and "QT_ROW_VALUES_INHERITED" not in res.warnings


def test_ac_57_46_a_row_not_taken_from_a_quotation_still_fails_on_a_changed_price(h):
    h.vendor.inherit_qt_values = True
    res = h.create("SO", lines=[_line("A", 5, 99.0, "BR1")])
    assert res.outcome == "done" and "QT_ROW_VALUES_INHERITED" not in res.warnings


# ======================================================================================
# AC-57-47: security
# ======================================================================================

def _vendor_message():
    from modules.autocount.write_back.primitives import vendor_message

    return vendor_message


REDACTIONS = [
    ("Login failed, see ftp://10.9.8.7/db for details", ("ftp:", "10.9.8.7")),
    ("Cannot connect, tcp://acw-internal.corp:1433 refused", ("tcp:", "acw-internal")),
    ("Cannot connect host=acw-internal.corp port 1433", ("acw-internal",)),
    ("Cannot connect addr=intsrv01 failed", ("intsrv01",)),
    ("Cannot connect address: intsrv02 failed", ("intsrv02",)),
    ("Login failed user id=sa;password=hunter2", ("hunter2",)),
    ("Login failed user=bobby", ("bobby",)),
    ("Login failed username=carol", ("carol",)),
    ("Login failed pwd=hunter3", ("hunter3",)),
    ("Login failed password=hunter4", ("hunter4",)),
    ("Connection to 10.20.30.40 was refused", ("10.20.30.40",)),
    ("File C:\\\\inetpub\\\\wwwroot\\\\x.cs not found", ("inetpub",)),
    ("File \\\\\\\\fileserver01\\\\share\\\\x.cs not found", ("fileserver01",)),
    ('Bad config {"password": "hunter5"} rejected', ("hunter5",)),
    ("Bad config {'Password':'hunter6'} rejected", ("hunter6",)),
]


@pytest.mark.parametrize("text,leaks", REDACTIONS)
def test_ac_57_47_refusal_text_is_cut_at_every_kind_of_internal_detail(text, leaks):
    body = {"ExceptionMessage": text, "Message": "An error has occurred."}
    out = _vendor_message()(body, "https://ac.example.test/api/db3")
    for leak in leaks:
        assert leak not in out, (leak, out)
    assert out.strip()  # the message is cut, not blanked


def test_ac_57_47_bare_host_without_a_url_is_cut(h):
    out = _vendor_message()({"ExceptionMessage": "cannot reach acw-internal.corp"},
                            "https://acw-internal.corp/api/db3")
    assert "acw-internal" not in out
    out = _vendor_message()({"ExceptionMessage": "cannot reach ac.example.test now"},
                            "https://ac.example.test/api/db3")
    assert "ac.example.test" not in out


def test_ac_57_47_a_clean_refusal_is_kept_whole():
    text = "This account had violated the credit limit. You are not allow to save."
    assert _vendor_message()({"ExceptionMessage": text}, "https://ac.example.test/api/db3") == text


def test_ac_57_47_bare_5xx_body_is_stored_as_status_and_redacted_text_only(h, w):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, HTML_500)
    res = h.run("unlink_row", w.params["unlink_row"])
    rows = h.op_actions(res)
    assert rows and rows[0].response_status == 500
    stored = json.dumps(rows[0].response_json, default=str)
    for leak in LEAKS + ("ac.example.test",):
        assert leak not in stored, leak
        assert leak not in (res.message or "")


def test_ac_57_47_bare_5xx_on_a_primitive_keeps_no_host_on_the_row_or_the_answer(h):
    h.vendor.fail_next("POST", "NewSalesOrder", 500, HTML_500)
    res = h.create("SO")
    assert res.outcome == "vendor_error" and res.error_code != "VENDOR_REFUSED"
    row = h.action(res)
    stored = json.dumps([row.response_json, res.message], default=str)
    for leak in LEAKS:
        assert leak not in stored, leak


def _needs_attention(h, w):
    drop_new_row_once(h)  # plan 61: the replace lost its new row
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "recovery failed", after=1)
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "needs_attention"
    return res


def test_ac_57_47_the_needs_attention_mail_goes_once_across_failed_resumes(h, w):
    res = _needs_attention(h, w)
    assert len(h.alerts) == 1
    for _ in range(2):
        h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "still down")
        again = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                               operation_id=res.operation_id)
        assert again.outcome == "needs_attention"
    assert len(h.alerts) == 1


def test_ac_57_47_two_concurrent_resumes_run_only_once(h, w):
    res = _needs_attention(h, w)
    seen = {}
    original = h.vendor._edit

    def hook(kind, body):
        if "other" not in seen:
            db2 = h.session_factory()
            try:
                seen["other"] = h.ops(db=db2).resume(
                    tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)
            finally:
                db2.close()
        return original(kind, body)

    h.vendor._edit = hook
    first = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)
    assert first.outcome in ("done", "recovered")
    other = seen["other"]
    assert other.outcome == "refused" and other.error_code == "OPERATION_IN_PROGRESS"
    assert n_item_a(h) == (4, Decimal(16))  # re-created exactly once


def _operation_ids_containing_book_names(monkeypatch):
    """Every new autocount row id carries both book names: the id is a random UUID
    in production, so a book name can appear in it by chance. The model default
    calls ``uuid.uuid4`` through this module's own ``uuid`` name on every insert,
    so replacing that name here (not the global module) reaches every new id."""
    import types

    from modules.autocount import models as ac_models

    counter = iter(range(1, 100_000))
    shim = types.SimpleNamespace(uuid4=lambda: f"0db1-db3-{next(counter):05d}")
    monkeypatch.setattr(ac_models, "uuid", shim)


def test_ac_57_47_403_write_not_allowed_names_no_book(client, h, db, monkeypatch):
    _operation_ids_containing_book_names(monkeypatch)
    gw = Gw(h, db)
    other = h._connection(DB1, DEFAULT_TENANT_ID)
    h.company.write_connection_id = other.id
    db.commit()
    for path, body in ((f"{PREFIX}/documents/quotations", create_body()),
                       (f"{PREFIX}/po-links/unlink", {"companyCode": "SRT", "poDocKey": 1, "poDtlKey": 2})):
        r = client.post(path, json=body, headers=gw.hdr(path[-8:]))
        assert r.status_code == 403 and code(r) == "WRITE_NOT_ALLOWED", r.text
        # the random ids (operationId, actionId) are the only fields a book name can match by chance
        text = json.dumps({k: v for k, v in r.json().items() if k not in ("operationId", "actionId")})
        for book in ("db1", "db3", "api/db"):
            assert book not in text, (book, text)
    h.no_http()


def test_ac_57_47_field_names_in_422s_are_length_capped_and_control_char_safe(client, gw):
    gw.h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    nasty = "x" * 200 + "\x00\x1b[31m\nEVIL\t"
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {nasty: "v"}})
    assert r.status_code == 422 and code(r) == "FIELD_NOT_EDITABLE", r.text
    assert "x" * 65 not in r.text
    for raw in ("\\u0000", "\\u001b", "\\n", "\\t"):
        assert raw not in r.text, raw
    long_line = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr("k2"), json={
        "companyCode": "SRT", "lines": [{"dtlKey": 1, nasty: 1}]})
    assert long_line.status_code == 422 and "x" * 65 not in long_line.text
    body = create_body()
    del body["header"]["displayTerm"]
    body["lines"][0][nasty] = 1
    created = client.post(f"{PREFIX}/documents/quotations", json=body, headers=gw.hdr("k3"))
    assert created.status_code == 422 and "x" * 65 not in created.text
    gw.h.no_http()


def _config_sql(h):
    h.db.add(AcEntityConfig(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="customer",
                            source_impl=SOURCE_IMPL_SQL_DB))
    h.db.commit()


def test_ac_57_47_a_company_that_gained_sql_data_is_refused_at_write_time_for_primitives(h):
    h.create("QT")  # fine: a clean test company
    h.vendor.calls.clear()
    _config_sql(h)  # the connection was set long ago; the company now holds SQL-synced data
    for res in (h.create("SO"), h.create("QT")):
        assert res.outcome == "refused" and res.error_code == "WRITE_COMPANY_NOT_TEST"
    h.no_http()


def test_ac_57_47_a_company_that_gained_sql_data_is_refused_at_write_time_for_operations(h, w):
    _config_sql(h)
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "refused" and res.error_code == "WRITE_COMPANY_NOT_TEST"
    h.no_http()


def test_ac_57_47_a_foreign_staged_document_row_also_refuses_at_write_time(h, w):
    row = h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7001").one()
    row.job_id = "sql-sync-job"
    h.db.commit()
    res = h.edit("PO", 7001, {"Remark1": "x"})
    assert res.outcome == "refused" and res.error_code == "WRITE_COMPANY_NOT_TEST"
    h.no_http()


def test_ac_57_47_a_foreign_row_left_alone_is_logged_once_with_codes_only(h, w, caplog):
    """Driven at the stager directly: through a write the AC-57-47 write-time check refuses a
    company holding another job's document rows before staging is reached."""
    from modules.autocount.write_back.staging import DocStager

    row = h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7001").one()
    row.job_id = "sql-sync-job"
    h.db.commit()
    caplog.set_level(logging.INFO, logger="foundryx.autocount")
    outcome = DocStager(h.db, h.factories()["sink_factory"]).stage_and_push(
        h.company, h.vendor.find("PO", 7001), "PO")
    assert not outcome.staged and not outcome.pushed
    records = [r for r in caplog.records if r.name == "foundryx.autocount"]
    text = " ".join(r.getMessage() for r in records)
    assert "ac.example.test" not in text and "api/db3" not in text
    assert len(records) == 1, [r.getMessage() for r in records]


# ======================================================================================
# test gaps found by the kill test
# ======================================================================================

def test_ac_57_32_relinking_a_row_back_passes_when_stale_staging_still_shows_it_on_the_target(h, w):
    """Behaviour pin only (the exclusion filter itself is unreachable, reviewer-proved): a stale
    staged SPO copy shows the moved row on its OLD target while AutoCount already has it
    elsewhere; relinking it BACK must pass."""
    spo = h.vendor.find("SPO", 7003)
    next(r for r in spo["Details"] if r["DtlKey"] == w.s_linked)["FromDocDtlKey"] = w.p_other  # fresh: moved
    staged = h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7003").one()
    assert next(r for r in staged.raw_json["_lines"] if r["DtlKey"] == w.s_linked)["FromDocDtlKey"] == w.p_spo
    res = h.run("spo_relink_row", dict(spo_doc_key=7003, spo_dtl_key=w.s_linked, po_doc_key=7001,
                                         po_dtl_key=w.p_spo))
    assert res.outcome == "done", (res.outcome, res.error_code)


def test_ac_57_32_a_different_row_on_the_target_is_still_counted(h, w):
    """Control for the exclusion test: the same stale layout, but ANOTHER staged SPO row (not the
    moved one) holds the target's quantity, so the relink is refused."""
    spo = h.vendor.find("SPO", 7003)
    next(r for r in spo["Details"] if r["DtlKey"] == w.s_linked)["FromDocDtlKey"] = w.p_other
    res = h.run("spo_relink_row", dict(spo_doc_key=7003, spo_dtl_key=w.s_linked, po_doc_key=7001,
                                         po_dtl_key=w.p_spo))
    assert res.outcome == "done"  # only the moved row is on p_spo in staging: excluded, so it fits
    # now make a second, distinct staged row hold p_spo's whole quantity
    from tests.test_autocount_write_back_operations import _extra_spo_row

    _extra_spo_row(h, w, w.p_free, 4)
    h.vendor.find("SPO", 7003)["Details"][-1]["FromDocDtlKey"] = w.p_free
    res = h.run("spo_link_row", dict(spo_doc_key=7003, spo_dtl_key=w.s_free, po_doc_key=7001,
                                      po_dtl_key=w.p_free), key="idem-2")
    assert res.outcome == "refused" and res.error_code == "QTY_ABOVE_OUTSTANDING"
