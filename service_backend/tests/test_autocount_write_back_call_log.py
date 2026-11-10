"""Plan 61 (RED): the AutoCount API call log, AC-61-60..64 (owner ruling R3, plan section 4.8).

One ``ac_api_call_log`` row per HTTP call the write layer makes (writes, read-backs, bydocno,
day-list fallback, debtor term, cancel), written on its own short session so it survives a
rollback, never storing a secret or the base URL host. The model ``AcApiCallLog`` is imported
inside each test, so each test fails on its own while the seam does not exist.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteAction
from tests.test_autocount_write_back_gateway import _hdr
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw
from tests.test_autocount_write_back_operations import (  # noqa: F401
    OpHarness,
    World,
    db,
    h,
)
from tests.test_autocount_write_back_primitives import _header, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

from datetime import date

DAY = date(2026, 11, 4)
BASE_PATH = "/api/db3"
COLUMNS = {
    "id", "tenant_id", "company_id", "created_at", "actor", "request_id", "operation_id", "action_id", "book",
    "method", "path", "doc_type", "doc_no", "doc_key", "request_json", "response_status", "response_body",
    "response_truncated", "duration_ms", "outcome", "error_code",
}
CAP = 32768


def model():
    from modules.autocount import models

    return getattr(models, "AcApiCallLog")


def logs(h) -> List[Any]:
    cls = model()
    session = h.session_factory()
    try:
        rows = session.query(cls).order_by(cls.created_at, cls.id).all()
        session.expunge_all()
        return rows
    finally:
        session.close()


def sent(h) -> List[tuple]:
    """(method, vendor path incl. encoded query) of every request the fake vendor saw."""
    return [(c.method, c.raw_target[len(BASE_PATH):]) for c in h.vendor.calls]


def logged(h) -> List[tuple]:
    return [(r.method, r.path) for r in logs(h) if r.outcome != "guard_refused"]


def assert_one_row_per_call(h) -> None:
    assert sorted(logged(h)) == sorted(sent(h)), (logged(h), sent(h))


def seed_so(h, key=5001, rows=None, **hdr):
    doc = h.seed_doc("SO", key, rows or [_line("A", 10, 5.0), _line("B", 4, 6.0, "BR1")], **hdr)
    return doc, [r["DtlKey"] for r in doc["Details"]]


@pytest.fixture
def world(h):
    return World(h)


@pytest.fixture
def gw(h, db):
    return Gw(h, db)


# ============================== AC-61-60 one row per call ====================================

def test_ac_61_60_the_table_has_exactly_the_planned_columns():
    cls = model()
    assert cls.__table__.name == "ac_api_call_log"
    assert cls.__table__.schema == "app_autocount"
    assert {c.name for c in cls.__table__.columns} == COLUMNS


def test_ac_61_60_post_create_is_logged_with_its_body(h):
    res = h.create("QT")
    assert res.outcome == "done", res.error_code
    assert_one_row_per_call(h)
    post = next(r for r in logs(h) if r.method == "POST")
    assert post.path == "/NewQuotation" and post.response_status == 200 and post.outcome == "ok"
    assert post.request_json == h.vendor.writes()[0].body


def test_ac_61_60_put_edit_and_its_bydocno_reads_are_logged(h):
    seed_so(h)
    res = h.edit("SO", 5001, {"Remark1": "hello"})
    assert res.outcome == "done", res.error_code
    assert_one_row_per_call(h)
    rows = logs(h)
    put = next(r for r in rows if r.method == "PUT")
    assert put.path == "/EditSalesOrderbydockey" and put.request_json == h.vendor.writes()[0].body
    gets = [r for r in rows if r.method == "GET"]
    assert gets and all(r.path.startswith("/SalesOrderbydocno?") and r.request_json is None for r in gets)
    assert all(r.response_status == 200 and r.outcome == "ok" for r in gets)


def test_ac_61_60_the_replace_put_is_logged(h, world):
    res = h.run("unlink_row", world.params["unlink_row"])
    assert res.outcome == "done", res.error_code
    assert_one_row_per_call(h)
    put_rows = [r for r in logs(h) if r.method == "PUT"]
    assert len(put_rows) == 1
    assert [d["FullTransferOption"] for d in put_rows[0].request_json["Details"]] == ["D", " "]


def test_ac_61_60_a_link_logs_the_replace_put_and_the_move_put_with_their_reads(h, world):
    res = h.run("link_row", world.params["link_row"])
    assert res.outcome == "done", (res.error_code, res.warnings)
    assert_one_row_per_call(h)
    rows = logs(h)
    assert len([r for r in rows if r.method == "PUT"]) == 2
    assert len([r for r in rows if r.method == "GET"]) >= 2


def test_ac_61_60_cancel_is_logged_with_the_encoded_query_and_no_request_body(h):
    docno = "A/B 1&x=2#?"
    seed_so(h, 5500, doc_no=docno)
    res = h.service().cancel_doc(**h.args("SO", doc_key=5500, doc_date=DAY))
    assert res.outcome == "done", (res.error_code, res.message)
    assert_one_row_per_call(h)
    cancel = next(r for r in logs(h) if r.method == "DELETE")
    assert cancel.path.startswith("/CancelSalesOrderbydocno?DocNo=")
    assert "%2F" in cancel.path and "&" not in cancel.path and "#" not in cancel.path
    assert cancel.request_json is None and cancel.response_status == 200
    assert cancel.doc_no == docno and cancel.doc_key == 5500 and cancel.doc_type == "SO"


def test_ac_61_60_a_failing_bydocno_then_the_day_list_fallback_are_both_logged(h):
    seed_so(h)
    h.vendor.fail_next("GET", "salesorderbydocno", 500, "boom")
    res = h.edit("SO", 5001, {"Remark1": "hello"})
    assert res.outcome == "done", res.error_code
    assert_one_row_per_call(h)
    rows = [r for r in logs(h) if r.method == "GET"]
    failed = [r for r in rows if r.path.startswith("/SalesOrderbydocno") and r.outcome == "http_error"]
    assert len(failed) == 1 and failed[0].response_status == 500 and "boom" in failed[0].response_body
    assert [r for r in rows if r.path.startswith("/salesorderbydocdate") and r.outcome == "ok"]


def test_ac_61_60_the_debtor_term_read_is_logged(h):
    h.vendor.debtors = [{"AccNo": "PARTY-1", "DisplayTerm": "30 DAYS"}]
    header = _header("QT")
    header.pop("DisplayTerm")
    res = h.create("QT", header=header)
    assert res.outcome == "done", res.error_code
    assert_one_row_per_call(h)
    debtor = [r for r in logs(h) if r.path.startswith("/debtorbypage")]
    assert len(debtor) == 1 and debtor[0].method == "GET" and debtor[0].outcome == "ok"


# ============================== AC-61-61 row fields ==========================================

def test_ac_61_61_gateway_call_fields_with_x_request_id(client, h, gw):
    seed_so(h)
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr("idem-1", **{"X-Request-ID": "req-abc"}),
                     json={"companyCode": "SRT", "header": {"ref": "x"}})
    assert r.status_code == 200, r.text
    assert_one_row_per_call(h)
    rows = logs(h)
    assert rows
    for row in rows:
        assert row.tenant_id == DEFAULT_TENANT_ID and row.company_id == h.company.id
        assert row.actor == gw.key.id and row.request_id == "req-abc"
        assert row.book == "db3"
        assert "://" not in row.path and "ac.example.test" not in row.path and row.path.startswith("/")
        assert row.created_at is not None and isinstance(row.duration_ms, int) and row.duration_ms >= 0
    put = next(x for x in rows if x.method == "PUT")
    h.db.expire_all()
    action = h.db.query(AcWriteAction).one()
    assert put.action_id == action.id
    assert (put.doc_type, put.doc_no, put.doc_key) == ("SO", "SO-5001", 5001)


def test_ac_61_61_request_id_falls_back_to_the_idempotency_key(client, h, gw):
    seed_so(h)
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr("idem-77"),
                     json={"companyCode": "SRT", "header": {"ref": "x"}})
    assert r.status_code == 200, r.text
    rows = logs(h)
    assert rows and all(x.request_id == "idem-77" for x in rows)


def test_ac_61_61_operation_rows_carry_the_operation_id(client, h, gw, world):
    r = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr(),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 200, r.text
    puts = [x for x in logs(h) if x.method == "PUT"]
    assert len(puts) == 1 and puts[0].operation_id == r.json()["operationId"]
    assert puts[0].action_id is not None


def test_ac_61_61_a_call_without_a_key_has_actor_system(h):
    seed_so(h)
    assert h.edit("SO", 5001, {"Remark1": "hello"}).outcome == "done"
    rows = logs(h)
    assert rows and all(x.actor == "system" for x in rows)


def test_ac_61_61_get_and_delete_have_no_request_json_and_post_put_have_one(h):
    seed_so(h)
    h.edit("SO", 5001, {"Remark1": "hello"})
    h.service().cancel_doc(**h.args("SO", doc_key=5001, doc_date=DAY))
    for row in logs(h):
        if row.method in ("GET", "DELETE"):
            assert row.request_json is None, (row.method, row.path)
        else:
            assert isinstance(row.request_json, dict)


# ============================== AC-61-62 failed calls ========================================

def test_ac_61_62_vendor_500_is_http_error_with_the_body_kept(h):
    seed_so(h)
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, json.dumps({"ExceptionMessage": "Credit limit hit"}))
    h.edit("SO", 5001, {"Remark1": "hello"})
    row = next(r for r in logs(h) if r.method == "PUT")
    assert row.outcome == "http_error" and row.response_status == 500 and "Credit limit hit" in row.response_body
    assert row.request_json is not None


def test_ac_61_62_timeout_is_logged_with_no_status(h):
    seed_so(h)
    h.vendor.timeout_next("PUT", "EditSalesOrderbydockey")
    h.edit("SO", 5001, {"Remark1": "hello"})
    row = next(r for r in logs(h) if r.method == "PUT")
    assert row.outcome == "timeout" and row.response_status is None and row.error_code == "WRITE_TIMEOUT"


def test_ac_61_62_connect_error_is_logged(h, monkeypatch):
    seed_so(h)
    real = h.vendor.transport.handle_request

    def refuse_writes(request):
        if request.method == "PUT":
            raise httpx.ConnectError("no route")
        return real(request)

    monkeypatch.setattr(h.vendor.transport, "handle_request", refuse_writes)
    h.edit("SO", 5001, {"Remark1": "hello"})
    row = next(r for r in logs(h) if r.method == "PUT")
    assert row.outcome == "connect_error" and row.response_status is None and row.error_code == "WRITE_CONNECT"


def test_ac_61_62_allowlist_refusal_is_guard_refused_and_nothing_is_sent(h):
    seed_so(h)
    factories = h.factories()
    make_client = factories["client_factory"]

    def wrong_book(base_url):
        client = make_client(base_url)
        client.base_url = "https://ac.example.test/api/db1"  # swapped after construction: re-run guard refuses
        return client

    factories["client_factory"] = wrong_book
    from tests.test_autocount_write_back_primitives import _service_cls

    _service_cls()(h.db, **factories).edit_doc(**h.args("SO", doc_key=5001, header_changes={"Remark1": "x"},
                                                       line_changes=[]))
    assert h.vendor.writes() == []
    refused = [r for r in logs(h) if r.outcome == "guard_refused"]
    assert len(refused) == 1 and refused[0].method == "PUT" and refused[0].response_status is None


# ============================== AC-61-61 truncation ==========================================

def test_ac_61_61_response_body_is_cut_at_32kb_and_flagged(h):
    seed_so(h)
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, "x" * (CAP + 5000))
    h.edit("SO", 5001, {"Remark1": "hello"})
    row = next(r for r in logs(h) if r.method == "PUT")
    assert len(row.response_body) == CAP and row.response_truncated is True


def test_ac_61_61_a_short_body_is_stored_whole_and_not_flagged(h):
    seed_so(h)
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, "x" * CAP)
    h.edit("SO", 5001, {"Remark1": "hello"})
    row = next(r for r in logs(h) if r.method == "PUT")
    assert len(row.response_body) == CAP and row.response_truncated is False
    get = next(r for r in logs(h) if r.method == "GET")
    assert get.response_truncated is False


# ============================== AC-61-63 durability ==========================================

def test_ac_61_63_rows_survive_a_rollback_of_the_business_transaction(h, monkeypatch):
    from modules.autocount.write_back import payloads

    seed_so(h)

    def boom(*args, **kwargs):
        raise RuntimeError("verify blew up after the call")

    monkeypatch.setattr(payloads, "verify_edit", boom)
    h.edit("SO", 5001, {"Remark1": "hello"})  # the service rolls the session back and answers INTERNAL_ERROR
    h.db.rollback()
    put = [r for r in logs(h) if r.method == "PUT"]
    assert len(put) == 1 and put[0].outcome == "ok"
    assert_one_row_per_call(h)


def test_ac_61_63_a_broken_log_writer_never_fails_the_call(h, monkeypatch):
    seed_so(h)
    cls = model()

    def broken(self, *args, **kwargs):
        raise RuntimeError("log table down")

    monkeypatch.setattr(cls, "__init__", broken)
    res = h.edit("SO", 5001, {"Remark1": "hello"})
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert h.vendor.find("SO", 5001)["Remark1"] == "hello"
    assert len(h.vendor.writes()) == 1


# ============================== AC-61-64 no secrets ==========================================

def test_ac_61_64_no_column_of_any_row_holds_a_secret_or_the_host(client, h, gw, world):
    r = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr(**{"X-Request-ID": "req-sec"}),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 200, r.text
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, "Authorization: Bearer abc; X-API-Key: zzz")
    client.post(f"{PREFIX}/po-links/relink", headers=gw.hdr("k2"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_free, "soDocKey": 7002, "soDtlKey": world.so_b})
    rows = logs(h)
    assert len(rows) >= 4
    cls = model()
    needles = ["ac.example.test", "Authorization", "X-API-Key", gw.plain, "app-secret-1", "pw-secret-9"]
    for row in rows:
        for column in cls.__table__.columns:
            value = getattr(row, column.name)
            text = json.dumps(value, default=str) if isinstance(value, (dict, list)) else str(value)
            for needle in needles:
                if column.name == "response_body" and row.outcome == "http_error" and needle in (
                        "Authorization", "X-API-Key"):
                    continue  # the vendor's own error text is stored as it came, never our headers
                assert needle not in text, (column.name, needle)


# ============================== round 3: review round 1 findings ===============================

HOST = "ac.example.test"


def test_r3_a_vendor_error_body_is_stored_without_the_host_stack_traces_or_paths(h):
    seed_so(h)
    body = {
        "Message": f"Call to https://{HOST}/api/db3/EditSalesOrderbydockey failed on {HOST}",
        "ExceptionMessage": f"Credit limit hit for debtor D1 at {HOST}",
        "ExceptionType": "AutoCount.Invoicing.CreditLimitException",
        "StackTrace": "   at AutoCount.Foo() in C:\\src\\AutoCount\\Foo.cs:line 12",
        "InnerException": {"Message": f"inner {HOST}", "StackTrace": "   at X() in C:\\src\\Inner.cs:line 3"},
    }
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, json.dumps(body))
    h.edit("SO", 5001, {"Remark1": "hello"})
    row = next(r for r in logs(h) if r.method == "PUT")
    stored = row.response_body
    assert row.outcome == "http_error" and row.response_status == 500
    assert HOST not in stored and "StackTrace" not in stored and "C:\\" not in stored
    assert "Credit limit hit for debtor D1" in stored  # the vendor's message text is kept, minus the host


def test_r3_a_2xx_get_body_is_stored_as_is(h):
    seed_so(h)
    h.edit("SO", 5001, {"Remark1": "hello"})
    first = next(r for r in logs(h) if r.method == "GET")
    stored = json.loads(first.response_body)
    assert stored[0]["DocNo"] == "SO-5001" and len(stored[0]["Details"]) == 2
    assert "[redacted]" not in first.response_body


def test_r3_the_32kb_cap_counts_utf8_bytes(h):
    seed_so(h)
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, "\u20ac" * 20000)  # 3 bytes each, 60000 bytes
    h.edit("SO", 5001, {"Remark1": "hello"})
    row = next(r for r in logs(h) if r.method == "PUT")
    assert len(row.response_body.encode("utf-8")) <= CAP
    assert row.response_truncated is True


def test_r3_split_link_operation_rows_carry_the_operation_id(h, world):
    res = h.run("split_link", dict(po_doc_key=7001, po_dtl_key=world.p_free, so_doc_key=7002,
                                   so_dtl_key=world.so_a, qty=2))
    assert res.outcome == "done", (res.outcome, res.error_code)
    put_rows = [r for r in logs(h) if r.method == "PUT"]
    assert len(put_rows) == 2
    assert all(r.operation_id == res.operation_id for r in put_rows), [r.operation_id for r in put_rows]
