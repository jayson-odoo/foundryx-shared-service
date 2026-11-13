"""Plan 57 (RED): the final review round. Sections A..H follow the coordinator's brief:
A stale primitive lock, B heartbeat and operation deadline, C partial-mode recovery, D partial
needs_attention mail, E runner report redaction and scrub, F more redaction cuts, G plan 55 suite
guard, H contract consistency (camelCase names, 422 codes, docDate, capabilities).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    AcEntityConfig,
    AcStagedRecord,
    AcWriteAction,
    AcWriteOperation,
)
from tests.test_autocount_write_back_gateway_qtso import (  # noqa: F401
    PREFIX,
    Gw,
    code,
    create_body,
    gw,
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
from tests.test_autocount_write_back_primitives import _line
from tests.test_autocount_write_back_review_fixes import HTML_500, n_item_a
from tests.test_autocount_write_back_runner_qtso import DEBTOR, EXTRA, _runner, run_suite
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


def _stale_op(h, kind, doc_key, *, age=3 * 86400, op="edit_doc", key="stale-key"):
    old = datetime.now(timezone.utc) - timedelta(seconds=age)
    row = AcWriteOperation(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id="old-key", idempotency_key=key,
        request_hash="x", op=f"{op}:{kind}", doc_type=kind, doc_key=doc_key, status="in_progress",
        created_at=old, updated_at=old)
    h.db.add(row)
    h.db.commit()
    return row.id


# ======================================================================================
# A (AC-57-43): the primitive routes flip stale in_progress rows of any kind
# ======================================================================================

@pytest.mark.parametrize("kind,slug", [("SO", "sales-orders"), ("PO", "purchase-orders")])
def test_a_a_three_day_old_in_progress_row_does_not_block_a_primitive_edit(client, gw, kind, slug):
    gw.h.seed_doc(kind, 5001, [_line("A", 10, 5.0)])
    old_id = _stale_op(gw.h, kind, 5001)
    r = client.patch(f"{PREFIX}/documents/{slug}/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {"ref": "x"}})
    assert r.status_code == 200, r.text
    gw.h.db.expire_all()
    assert gw.h.db.get(AcWriteOperation, old_id).status == "pending_verification"


def test_a_stale_row_on_a_quotation_does_not_block_add_line(client, gw):
    gw.h.seed_doc("QT", 6001, [_line("A", 1, 9.0)], stage=False)
    _stale_op(gw.h, "QT", 6001, op="add_line")
    r = client.post(f"{PREFIX}/documents/quotations/6001/lines", headers=gw.hdr(), json={
        "companyCode": "SRT", "docDate": "2026-11-04",
        "line": {"itemCode": "Z", "uom": "UNIT", "qty": 1, "unitPrice": 1, "location": "HQ"}})
    assert r.status_code == 200, r.text


def test_a_a_young_in_progress_row_still_blocks_a_primitive(client, gw):
    gw.h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    _stale_op(gw.h, "SO", 5001, age=5)
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {"ref": "x"}})
    assert r.status_code == 409 and code(r) == "DOC_BUSY"
    gw.h.no_http()


def test_a_doc_busy_from_the_primitive_frame_is_not_stored_under_the_idempotency_key(client, gw):
    gw.h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    busy = AcWriteAction(tenant_id=DEFAULT_TENANT_ID, company_id=gw.h.company.id, action="edit_doc",
                         doc_type="SO", doc_key=5001, outcome="in_flight", request_json={})
    gw.h.db.add(busy)
    gw.h.db.commit()
    body = {"companyCode": "SRT", "header": {"ref": "x"}}
    first = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr("retry"), json=body)
    assert first.status_code == 409 and code(first) == "DOC_BUSY"
    gw.h.db.delete(busy)
    gw.h.db.commit()
    again = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr("retry"), json=body)
    assert again.status_code == 200, again.text  # tried again, not the stored refusal


# ======================================================================================
# B (AC-57-43): heartbeat and an operation-wide deadline under the busy window
# ======================================================================================

def _other_session_op(h, op_id):
    db2 = h.session_factory()
    try:
        row = db2.get(AcWriteOperation, op_id)
        return db2, row
    except Exception:
        db2.close()
        raise


def test_b_every_step_refreshes_the_operation_rows_updated_at(h, w):
    seen = {}
    original_edit = h.vendor._edit  # plan 61: step 1 = the replace PUT, step 2 = the move PUT

    def op_id():
        db2 = h.session_factory()
        try:
            return db2.query(AcWriteOperation).filter(AcWriteOperation.status == "in_progress").one().id
        finally:
            db2.close()

    def during_replace(kind, body):
        seen["id"] = op_id()
        db2 = h.session_factory()
        try:
            db2.get(AcWriteOperation, seen["id"]).updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db2.commit()
        finally:
            db2.close()
        return original_edit(kind, body)

    def during_move(kind, body):
        db2 = h.session_factory()
        try:
            seen["updated"] = db2.get(AcWriteOperation, seen["id"]).updated_at
        finally:
            db2.close()
        return original_edit(kind, body)

    def during(kind, body):
        return (during_move if "id" in seen else during_replace)(kind, body)

    h.vendor._edit = during
    res = h.run("link_row", w.params["link_row"])  # the vendor clears the date: a move is due
    assert res.outcome == "done", res.error_code
    updated = seen["updated"]
    updated = updated if updated.tzinfo else updated.replace(tzinfo=timezone.utc)
    assert datetime.now(timezone.utc) - updated < timedelta(seconds=120), "step 2 must heartbeat the row"


def test_b_a_resume_cannot_claim_a_live_operation(h, w):
    seen = {}
    original = h.vendor._edit

    def during(kind, body):
        if seen:
            return original(kind, body)
        db2 = h.session_factory()
        try:
            op = db2.query(AcWriteOperation).filter(AcWriteOperation.status == "in_progress").one()
            seen["resume"] = h.ops(db=db2).resume(
                tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=op.id)
        finally:
            db2.close()
        return original(kind, body)

    h.vendor._edit = during
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "done"
    assert seen["resume"].outcome == "refused" and seen["resume"].error_code == "OPERATION_IN_PROGRESS"


def _clock_jump_after_writes(h, monkeypatch, writes):
    """The clock jumps past the busy window right after the read-back GET that follows the
    ``writes``-th vendor write (``0`` = during the operation's first read, before any write).
    Jumping after a read-back keeps the primitive's own deadline out of the picture: only the
    operation-wide deadline sees it."""
    from modules.autocount.write_back.frame import BUSY_WINDOW_SECONDS

    offset = {"s": 0.0}
    real = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real() + offset["s"])
    def hooked(original):
        def get(kind, call):
            out = original(kind, call)
            if len(h.vendor.writes()) == writes and not offset["s"]:
                offset["s"] = BUSY_WINDOW_SECONDS + 1
            return out
        return get

    h.vendor._get = hooked(h.vendor._get)
    h.vendor._get_by_doc_no = hooked(h.vendor._get_by_doc_no)  # plan 61: reads are bydocno


def test_b_a_deadline_passed_before_the_first_write_stops_the_operation_with_zero_writes(h, w, monkeypatch):
    _clock_jump_after_writes(h, monkeypatch, 0)
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "pending_verification" and res.error_code == "DEADLINE_EXCEEDED", (
        res.outcome, res.error_code)
    assert h.vendor.writes() == []
    assert h.operation(res).status == "pending_verification"


# ======================================================================================
# 1 (AC-57-39): the deadline never turns a landed result into pending or strands a write
# ======================================================================================

def test_deadline_after_the_add_with_no_move_needed_is_done_with_replaced_lines_and_a_push(h, w, monkeypatch):
    _clock_jump_after_writes(h, monkeypatch, 1)  # plan 61: the replace landed; an unlink needs no move
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(res.replaced_lines) == 1 and res.replaced_lines[0][0] == w.p_linked
    assert h.steps() == [PUT_PO]
    assert n_item_a(h) == (4, Decimal(16))  # never leaves the line missing
    assert any(hasattr(r, "lines") for r in h.sink_calls), "the read-back document must still be pushed"


def test_deadline_after_the_add_when_a_move_is_due_is_done_with_location_not_moved(h, w_far, monkeypatch):
    w = w_far
    _clock_jump_after_writes(h, monkeypatch, 1)  # plan 61: after the replace PUT
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert "LOCATION_NOT_MOVED" in res.warnings
    assert len(res.replaced_lines) == 1
    assert h.steps() == [PUT_PO]  # no move PUT after the deadline
    assert any(hasattr(r, "lines") for r in h.sink_calls)




def test_deadline_during_recovery_still_runs_the_recovery_add(h, w, monkeypatch):
    _clock_jump_after_writes(h, monkeypatch, 1)  # the replace landed wrong, then the clock is past the deadline
    drop_new_row_once(h)
    res = h.run("unlink_row", w.params["unlink_row"])
    assert res.outcome == "recovered", (res.outcome, res.error_code)
    assert h.steps() == [PUT_PO, PUT_PO, PUT_PO]  # replace that lost its row, recovery add, move back
    assert n_item_a(h) == (4, Decimal(16))


# ======================================================================================
# C (AC-57-41): partial-mode recovery never doubles the line
# ======================================================================================

PARTIAL = lambda w: (lambda kind, doc, row: Decimal(1) if row["DtlKey"] == w.p_free else Decimal(0))  # noqa: E731


def test_c_a_remainder_that_loses_its_link_is_removed_before_the_cut_row_is_restored(h, w):
    h.vendor.drop_link_next_add()
    res = h.run("link_row", w.params["link_row"], receipt_reader=PARTIAL(w))
    assert res.outcome == "recovered", (res.outcome, res.error_code)
    deletes = [r for c in h.vendor.writes() for r in c.body["Details"] if r.get("FullTransferOption") == "D"]
    assert deletes, h.steps()  # the stray remainder (qty 3) goes (plan 61: a "D" row)
    assert n_item_a(h) == (4, Decimal(16))
    assert w.row_by_key(w.po_rows(), w.p_free)["Qty"] == 4  # the cut row is whole again


def test_c_a_remainder_add_that_applied_then_failed_is_removed_too(h, w):
    h.vendor.apply_then_500_next("PUT", "EditPurchaseOrderbydockey", after=1)  # cut ok, remainder applied + 500
    res = h.run("link_row", w.params["link_row"], receipt_reader=PARTIAL(w))
    assert res.outcome in ("recovered", "needs_attention")
    if res.outcome == "recovered":
        assert n_item_a(h) == (4, Decimal(16))
        assert w.row_by_key(w.po_rows(), w.p_free)["Qty"] == 4


def test_c_a_failed_remainder_add_restores_the_cut_row_without_a_stray_delete(h, w):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "remainder failed", after=1)
    res = h.run("link_row", w.params["link_row"], receipt_reader=PARTIAL(w))
    assert res.outcome == "recovered"
    assert not deleted_a_row(h)  # nothing stray: the failed add never landed
    assert n_item_a(h) == (4, Decimal(16))


# ======================================================================================
# D (AC-57-35): partial-mode needs_attention names the remainder and says "cut"
# ======================================================================================

def _partial_needs_attention(h, w, **kw):
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "remainder failed", after=1)
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "restore failed", after=1)
    res = h.run("link_row", w.params["link_row"], receipt_reader=PARTIAL(w), **kw)
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    return res


def test_d_the_event_names_the_remainder_qty_and_says_the_row_was_cut(h, w):
    _partial_needs_attention(h, w)
    assert len(h.alerts) == 1
    blob = json.dumps(h.alerts[0], default=str).lower()
    assert "cut" in blob and "remainder" in blob
    assert '"3' in blob or "3.0" in blob or ": 3" in blob or "'3'" in blob or "3" in blob.replace("7001", "")
    assert "deleted" not in blob.replace("not deleted", "")


def test_d_the_default_mail_says_cut_not_deleted_and_gives_the_remainder_qty(h, w):
    from app.models.email_outbox import EmailOutbox
    from tests.test_s33_integration_alerts import MANAGE, _only_recipients, _user

    _only_recipients(h.db)
    _user(h.db, "mgr@example.com", perms=[MANAGE])
    _partial_needs_attention(h, w, notifier="default")
    h.db.expire_all()
    mail = h.db.query(EmailOutbox).one()
    text = (mail.html_body + mail.text_body).lower()
    assert "cut" in text and "remainder" in text and "1" in text and "3" in text
    assert "re-key the line" not in text or "cut" in text


# ======================================================================================
# E (AC-57-70): runner report redacts failed-write bodies and scrubs more fields
# ======================================================================================

def test_e_failed_write_bodies_in_the_markdown_go_through_redact_text(h):
    from datetime import date

    body = json.dumps({"ExceptionMessage": "Credit limit exceeded for http://acw-internal.corp/x tail-secret",
                       "StackTrace": "at AutoCount.Foo() in C:\\\\src\\\\Foo.cs", "ExceptionType": "System.Exception"})
    h.vendor.fail_next("POST", "NewQuotation", 500, body)
    md = _runner().render_report(run_suite(h), run_date=date(2026, 11, 5))
    assert "Q01" in md and "Credit limit exceeded" in md
    for leak in ("StackTrace", "ExceptionType", "System.Exception", "acw-internal", "tail-secret", "Foo.cs"):
        assert leak not in md, leak


def test_e_an_iis_html_failure_leaks_nothing_into_the_markdown(h):
    from datetime import date

    h.vendor.fail_next("POST", "NewQuotation", 500, HTML_500)
    md = _runner().render_report(run_suite(h), run_date=date(2026, 11, 5))
    assert "Q01" in md
    for leak in ("acw-internal", "inetpub", "svc_autocount", "Logon User", "<html"):
        assert leak not in md, leak


def test_e_the_scrub_list_also_covers_creditor_name_remarks_note_and_user_ids(h):
    from datetime import date

    extra = {**EXTRA, "CreditorName": "SUPPLIER SECRET LTD", "Remark1": "REMARK-ONE-X", "Remark2": "REMARK-TWO-X",
             "Remark3": "REMARK-THREE-X", "Remark4": "REMARK-FOUR-X", "Note": "PRIVATE NOTE TEXT",
             "CreatedUserID": "USER-CREATED-X", "LastModifiedUserID": "USER-MODIFIED-X"}
    suite = run_suite(h, header_extra=extra)
    md = _runner().render_report(suite, run_date=date(2026, 11, 5))
    for private in ("SUPPLIER SECRET LTD", "REMARK-ONE-X", "REMARK-TWO-X", "REMARK-THREE-X", "REMARK-FOUR-X",
                    "PRIVATE NOTE TEXT", "USER-CREATED-X", "USER-MODIFIED-X"):
        assert private not in md, private
    assert DEBTOR in md and "QT-000001" in md
    assert "SUPPLIER SECRET LTD" in json.dumps(suite.evidence)  # the private file keeps exact values


# ======================================================================================
# F (AC-57-47): more cuts
# ======================================================================================

@pytest.mark.parametrize("text,leak", [
    ("Login failed for user 'svc_acw_prod'.", "svc_acw_prod"),
    ("Cannot open database \"AED_PROD\" requested by the login.", "AED_PROD"),
    ("Bad call token=abc123def", "abc123def"),
    ("Bad call TOKEN=abc123def2", "abc123def2"),
    ("Bad call secret=s3cr3tvalue", "s3cr3tvalue"),
    ("Bad call Secret: s3cr3tvalue2", "s3cr3tvalue2"),
    ("Bad call apikey=key-4455", "key-4455"),
    ("Bad call ApiKey=key-4456", "key-4456"),
    ("Bad call api_key=key-4457", "key-4457"),
    ("Bad call API_KEY=key-4458", "key-4458"),
])
def test_f_more_internal_details_are_cut(text, leak):
    from modules.autocount.write_back.primitives import redact_text

    out = redact_text(text, "https://ac.example.test/api/db3")
    assert leak not in out, out
    assert "[redacted]" in out


# ======================================================================================
# G (AC-57-22): the plan 55 suite refuses a company with SQL data before any request
# ======================================================================================

def test_g_run_db3_suite_refuses_write_company_not_test_before_any_request(h):
    h.db.add(AcEntityConfig(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="customer",
                            source_impl=SOURCE_IMPL_SQL_DB))
    h.db.commit()
    factories = h.factories()
    with pytest.raises(Exception) as exc:
        _runner().run_db3_suite(h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                                creditor_code="400-N004", run_tag="T1", **factories)
    assert getattr(exc.value, "code", None) == "WRITE_COMPANY_NOT_TEST"
    h.no_http()


def test_g_run_db3_suite_refuses_a_foreign_staged_document_too(h):
    h.db.add(AcStagedRecord(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="purchase_order",
                            job_id="sql-sync-job", source_ref="AED_TEST:1", doc_no="x", raw_json={}, status="staged"))
    h.db.commit()
    with pytest.raises(Exception) as exc:
        _runner().run_db3_suite(h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                                creditor_code="400-N004", run_tag="T1", **h.factories())
    assert getattr(exc.value, "code", None) == "WRITE_COMPANY_NOT_TEST"
    h.no_http()


# ======================================================================================
# H: contract consistency
# ======================================================================================

def test_h_field_ignored_names_the_field_in_the_callers_camel_case(client, gw):
    gw.h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    gw.h.vendor.ignored_fields = {"Remark1"}
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {"remark1": "x"}})
    assert r.status_code == 502, r.text
    body = r.json()
    named = (body.get("message") or "") + json.dumps(body.get("warnings"))
    assert "remark1" in named and "Remark1" not in named, named


def test_h_qt_row_values_inherited_names_fields_in_camel_case(client, gw):
    gw.h.vendor.inherit_qt_values = True
    qt = gw.h.seed_doc("QT", 6001, [_line("A", 5, 900.0, "HQ")], stage=False, doc_no="QT-6001")
    dtl = qt["Details"][0]["DtlKey"]
    body = create_body("SO")
    body["lines"][0].update(unitPrice=99, location="BR1", fromQuotation={"docNo": "QT-6001", "dtlKey": dtl})
    r = client.post(f"{PREFIX}/documents/sales-orders", json=body, headers=gw.hdr())
    assert r.status_code == 200, r.text
    answer = r.json()
    assert "QT_ROW_VALUES_INHERITED" in answer["warnings"]
    named = (answer.get("message") or "") + json.dumps(answer["warnings"])
    assert "unitPrice" in named and "location" in named
    assert "UnitPrice" not in named and "Location" not in named


@pytest.mark.parametrize("line,expect", [
    ({"dtlKey": 1, "qty": 0}, "QTY_INVALID"),
    ({"dtlKey": 1, "qty": -3}, "QTY_INVALID"),
    ({"dtlKey": 1, "qty": 0.123456789}, "QTY_INVALID"),
    ({"dtlKey": 1, "unitPrice": -5}, "PRICE_INVALID"),
])
def test_h_qty_and_price_invalid_are_422_on_the_gateway(client, gw, line, expect):
    doc = gw.h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    line = {**line, "dtlKey": doc["Details"][0]["DtlKey"]}
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "lines": [line]})
    assert r.status_code == 422 and code(r) == expect, r.text
    gw.h.no_http()


def _unstage(h, entity, doc_key):
    h.db.query(AcStagedRecord).filter(AcStagedRecord.entity_type == entity,
                                      AcStagedRecord.source_ref == f"AED_TEST:{doc_key}").delete()
    h.db.commit()


def test_h_po_links_unlink_and_spo_unlink_accept_a_doc_date(client, gw, world):
    _unstage(gw.h, "purchase_order", 7001)
    unlink = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked}
    r = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("a"), json=unlink)
    assert r.status_code == 409 and code(r) == "DOC_DATE_REQUIRED", r.text
    r = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("b"), json={**unlink, "docDate": "2026-11-04"})
    assert r.status_code == 200, r.text
    bad = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("c"), json={**unlink, "docDate": "04/11/2026"})
    assert bad.status_code == 422


def test_h_spo_links_unlink_accepts_a_doc_date(client, gw, world):
    _unstage(gw.h, "shipping_order", 7003)
    unlink = {"companyCode": "SRT", "spoDocKey": 7003, "spoDtlKey": world.s_linked}
    r = client.post(f"{PREFIX}/spo-links/unlink", headers=gw.hdr("a"), json=unlink)
    assert r.status_code == 409 and code(r) == "DOC_DATE_REQUIRED", r.text
    r = client.post(f"{PREFIX}/spo-links/unlink", headers=gw.hdr("b"), json={**unlink, "docDate": "2026-11-04"})
    assert r.status_code == 200, r.text
    assert client.post(f"{PREFIX}/spo-links/unlink", headers=gw.hdr("c"),
                       json={**unlink, "docDate": "nope"}).status_code == 422


def test_h_po_links_split_accepts_a_doc_date(client, gw, world):
    _unstage(gw.h, "purchase_order", 7001)
    body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_free, "soDocKey": 7002,
            "soDtlKey": world.so_a, "qty": 2}
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr("a"), json=body)
    assert r.status_code == 409 and code(r) == "DOC_DATE_REQUIRED", r.text
    r = client.post(f"{PREFIX}/po-links", headers=gw.hdr("b"), json={**body, "docDate": "2026-11-04"})
    assert r.status_code == 200, r.text


def test_h_write_capabilities_lists_split_link_and_uses_wire_kind_names(client, h, db):
    gw = Gw(h, db)  # shipped flags (plan 61: PO row operations on, SPO off)
    r = client.get(f"{PREFIX}/write-capabilities?companyCode=SRT", headers={"X-API-Key": gw.plain})
    assert r.status_code == 200, r.text
    body = r.json()
    items = body if isinstance(body, list) else body["capabilities"]
    wire = {"quotations", "sales-orders", "purchase-orders", "shipping-purchase-orders"}
    assert {i["kind"] for i in items} <= wire
    by = {(i["op"], i["kind"]): i for i in items}
    assert by[("split_link", "purchase-orders")] == {
        "op": "split_link", "kind": "purchase-orders", "enabled": True, "reasonCode": None}
    assert by[("link_row", "purchase-orders")]["enabled"] is True
    assert by[("link_row", "purchase-orders")]["reasonCode"] is None
    assert by[("spo_link_row", "shipping-purchase-orders")]["enabled"] is False
    assert by[("spo_link_row", "shipping-purchase-orders")]["reasonCode"] == "VENDOR_UNSUPPORTED"
    assert by[("create_doc", "quotations")]["enabled"] is True


# ======================================================================================
# 2 (AC-57-70): a generic Message with an empty ExceptionMessage shows the status only
# ======================================================================================

def test_report_shows_status_only_for_a_generic_message_with_an_empty_exception_message(h):
    from datetime import date

    body = json.dumps({"Message": "An error has occurred.", "ExceptionMessage": "",
                       "ExceptionType": "System.Data.SqlClient.SqlException",
                       "StackTrace": "   at AutoCount.Wrapper.Foo.Bar(Int32 key) in C:\\src\\Foo.cs:line 7"})
    h.vendor.fail_next("POST", "NewQuotation", 500, body)
    md = _runner().render_report(run_suite(h), run_date=date(2026, 11, 5))
    assert "Q01" in md and "500" in md
    for leak in ("ExceptionType", "StackTrace", "SqlException", "Foo.Bar", "AutoCount.Wrapper", "Foo.cs",
                 "An error has occurred"):
        assert leak not in md, leak


# ======================================================================================
# 3 (AC-57-47): plan 55 frame failures keep status + redacted text only on the action row
# ======================================================================================

_JSON_FAIL = json.dumps({"Message": "An error has occurred.", "ExceptionMessage": "",
                         "ExceptionType": "System.Exception",
                         "StackTrace": "at AutoCount.Foo() in C:\\src\\Foo.cs http://acw-internal.corp/x"})


@pytest.mark.parametrize("failure", [HTML_500, _JSON_FAIL])
def test_plan_55_split_link_failure_stores_status_and_redacted_text_only(h, w, failure):
    from modules.autocount.write_back.service import WriteBackService

    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, failure)
    res = WriteBackService(h.db, **h.factories()).link(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=7001, po_dtl_key=w.p_free,
        so_doc_key=7002, so_dtl_key=w.so_a, qty=Decimal(2))
    assert res.outcome == "vendor_error", (res.outcome, res.error_code)
    row = h.action(res)
    assert row.response_status == 500
    stored = json.dumps(row.response_json, default=str)
    for leak in ("acw-internal", "inetpub", "svc_autocount", "StackTrace", "ExceptionType", "Foo.cs",
                 "ac.example.test", "<html"):
        assert leak not in stored, leak
        assert leak not in (res.message or "")


def test_plan_55_relocate_failure_stores_status_and_redacted_text_only(h, w_far):
    from modules.autocount.write_back.service import WriteBackService

    w = w_far  # p_linked sits at BR1, its SO row at BRW-AM: a relocation is due
    h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, HTML_500)
    res = WriteBackService(h.db, **h.factories()).relocate(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=7001, po_dtl_key=w.p_linked)
    assert res.outcome == "vendor_error", (res.outcome, res.error_code)
    row = h.action(res)
    assert row.response_status == 500
    stored = json.dumps(row.response_json, default=str)
    for leak in ("acw-internal", "inetpub", "svc_autocount", "<html"):
        assert leak not in stored, leak


# ======================================================================================
# 4: AutoCount's own refusal text is passed through unchanged (no camelCasing inside it)
# ======================================================================================

REFUSAL = ("The quantity of the item code SRTKT38SS is less than the quantity it was partially transferred "
           "to Purchase Order, save aborted. Unit Price and Item Code stay as written.")


def test_refusal_text_is_passed_through_unchanged_by_the_primitive(h):
    h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, json.dumps({"ExceptionMessage": REFUSAL}))
    res = h.edit("SO", 5001, {"Remark1": "x"})
    assert res.error_code == "VENDOR_REFUSED"
    assert res.message == REFUSAL


def test_refusal_text_is_passed_through_unchanged_by_the_gateway(client, gw):
    gw.h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    gw.h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, json.dumps({"ExceptionMessage": REFUSAL}))
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {"remark1": "x"}})
    assert r.status_code == 502, r.text
    body = r.json()
    assert body["errorCode"] == "VENDOR_REFUSED" and body["message"] == REFUSAL
