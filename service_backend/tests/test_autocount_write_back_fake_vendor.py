"""Self-test of the plan 57 fake vendor helper (it must itself behave like db3)."""

from __future__ import annotations

import httpx
import pytest

from tests.autocount_write_back_fake_vendor import FakeAutoCountVendor, new_doc

BASE = "https://ac.example.test/api/db3"


def _create_body(party="DEBTOR-1", **over):
    body = {
        "DocNo": "<<New>>", "DocDate": "2026-11-04T00:00:00", "DebtorCode": party,
        "DisplayTerm": "C.B.D.", "CurrencyCode": "MYR", "CurrencyRate": 1.0,
        "Details": [
            {"ItemCode": "A", "Location": "HQ", "UOM": "UNIT", "Qty": 2, "UnitPrice": 5.0},
            {"ItemCode": "B", "Location": "BR1", "UOM": "UNIT", "Qty": 3, "UnitPrice": 7.0},
        ],
    }
    body.update(over)
    return body


@pytest.fixture
def v():
    return FakeAutoCountVendor()


@pytest.fixture
def http(v):
    with httpx.Client(transport=v.transport, base_url=BASE) as client:
        yield client


def test_create_new_docno_answer_and_get(v, http):
    r = http.post("/NewQuotation", json=_create_body())
    assert r.status_code == 200
    assert r.text.startswith("DocNo=QT-000001 ,DocKey=") and r.text.endswith("... Created Successful.")
    got = http.get("/quotationbydocdate", params={"DocDate": "20261104"}).json()
    assert len(got) == 1 and len(got[0]["Details"]) == 2
    assert http.get("/quotationbydocdate", params={"DocDate": "20261105"}).json() == []


def test_create_missing_docno_or_displayterm_is_500(v, http):
    assert http.post("/NewSalesOrder", json=_create_body(DocNo="")).status_code == 500
    assert http.post("/NewSalesOrder", json=_create_body(DisplayTerm="")).status_code == 500
    assert v.docs["SO"] == []


def test_edit_keeps_omitted_rows_adds_dtlkey0_and_accepts_qty_zero(v, http):
    doc = v.seed("SO", new_doc("SO", 100, "SO-1", "D", [{"ItemCode": "A"}, {"ItemCode": "B"}]))
    first = doc["Details"][0]["DtlKey"]
    body = {"DocKey": 100, "Remark1": "x", "Cancelled": "T", "Details": [
        {"DtlKey": first, "Qty": 0}, {"DtlKey": 0, "ItemCode": "C", "Qty": 4, "UOM": "UNIT", "UnitPrice": 1.0, "Location": "HQ"}]}
    r = http.put("/EditSalesOrderbydockey", json=body)
    assert r.status_code == 200 and r.text.endswith("... Done Edit.")
    stored = v.find("SO", 100)
    assert stored["Remark1"] == "x" and stored["Cancelled"] == "F"
    assert len(stored["Details"]) == 3 and stored["Details"][0]["Qty"] == 0


def test_edit_ignores_link_on_existing_row_and_forces_hq_on_new_linked_row(v, http):
    v.seed("PO", new_doc("PO", 200, "PO-1", "C", [{"ItemCode": "A", "Location": "BR1"}]))
    existing = v.rows("PO", 200)[0]["DtlKey"]
    http.put("/EditPurchaseOrderbydockey", json={"DocKey": 200, "Details": [
        {"DtlKey": existing, "FromDocType": "SO", "FromDocDtlKey": 777},
        {"DtlKey": 0, "ItemCode": "A", "Location": "BR1", "Qty": 1, "UOM": "UNIT", "UnitPrice": 1.0,
         "FromDocType": "SO", "FromDocDtlKey": 777}]})
    rows = v.rows("PO", 200)
    assert rows[0]["FromSODtlKey"] == 0 and rows[0]["Location"] == "BR1"
    assert rows[1]["FromSODtlKey"] == 777 and rows[1]["Location"] == "HQ"


def test_so_create_from_qt_reads_back_dtlkey_zero(v, http):
    body = _create_body()
    body["Details"][0].update({"FromDocType": "QT", "FromDocNo": "QT-000009", "FromDocDtlKey": 555})
    http.post("/NewSalesOrder", json=body)
    row = v.docs["SO"][0]["Details"][0]
    assert row["FromDocType"] == "QT" and row["FromDocNo"] == "QT-000009" and row["FromDocDtlKey"] == 0


def test_delete_shapes_and_call_log(v, http):
    v.seed("QT", new_doc("QT", 300, "QT-1", "D", [{}, {}]))
    gone = v.rows("QT", 300)[0]["DtlKey"]
    r = http.request("DELETE", "/DeleteQuotationDetailbydtlkey", json={"DocKey": 300, "DtlKey": gone})
    assert r.status_code == 200 and len(v.rows("QT", 300)) == 1
    assert http.request("DELETE", "/DeleteQuotationbydockey", json={"DocKey": 300}).status_code == 200
    assert v.docs["QT"] == []
    assert [(c.method, c.leaf) for c in v.calls] == [
        ("DELETE", "deletequotationdetailbydtlkey"), ("DELETE", "deletequotationbydockey")]


def test_failure_injection_is_consumed_once(v, http):
    v.fail_next("POST", "NewQuotation", 503, "down")
    assert http.post("/NewQuotation", json=_create_body()).status_code == 503
    assert v.docs["QT"] == []
    assert http.post("/NewQuotation", json=_create_body()).status_code == 200
    v.timeout_next("POST", "NewQuotation")
    with pytest.raises(httpx.ReadTimeout):
        http.post("/NewQuotation", json=_create_body())
    v.apply_then_500_next("POST", "NewQuotation")
    assert http.post("/NewQuotation", json=_create_body()).status_code == 500
    assert len(v.docs["QT"]) == 2  # first success + the applied-but-500 one
    v.drop_rows_next_create()
    http.post("/NewQuotation", json=_create_body())
    assert len(v.docs["QT"][-1]["Details"]) == 1
