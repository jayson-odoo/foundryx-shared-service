"""Plan 55 S6: db3 runner + AutoCount test report (AC-55-42, 50, 51, 04).

A stateful fake wrapper emulates GET by day, POST /NewPurchaseOrder (fresh
DocKey / DtlKey, ShippingPO, From* read-back) and PUT /EditPurchaseOrderbydockey.
One MockTransport serves every method; every request is logged with its full URL.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.models import AcCompany, AcWriteAction
from modules.autocount.sinks import WriteResult
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back.reader import AutoCountDocReader
from modules.autocount.write_back.runner import render_report, run_db3_suite
from tests.test_autocount_write_back_service import _load
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

DB3 = "https://ac.example.test/api/db3"
DB1 = "https://ac.example.test/api/db1"
DBNAME = "AED_RUN"
SECRETS = {"appId": "app-secret-run", "password": "pw-secret-run"}
CASE_IDS = [f"C{n:02d}" for n in range(0, 13)]
DEBTOR = "300-S057"
CREDITOR = "400-N004"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


_DATE = re.compile(r"^(\d{4})-\d{2}-\d{2}T")


def _has_ancient_date(node) -> bool:
    if isinstance(node, dict):
        return any(_has_ancient_date(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_ancient_date(v) for v in node)
    m = _DATE.match(node) if isinstance(node, str) else None
    return bool(m and int(m.group(1)) < 1753)


HEADER_KEYS = {
    "DocKey", "DocNo", "DocDate", "CreditorCode", "CreditorName", "Ref", "Description",
    "DisplayTerm", "PurchaseAgent", "InvAddr1", "InvAddr2", "InvAddr3", "InvAddr4",
    "Phone1", "Fax1", "Attention", "BranchCode", "DeliverAddr1", "DeliverAddr2",
    "DeliverAddr3", "DeliverAddr4", "DeliverPhone1", "DeliverFax1", "DeliverContact",
    "CurrencyCode", "CurrencyRate", "Remark1", "Remark2", "Remark3", "Remark4",
    "RefDocNo", "ShipVia", "ShipInfo", "InclusiveTax",
}
POST_ROW_FIELDS = {
    "ItemCode", "Location", "Description", "ProjNo", "UOM", "UserUOM", "Qty", "FOCQty",
    "UnitPrice", "Discount", "TaxCode", "DeliveryDate", "Desc2", "FromDocType", "FromDocNo",
    "FromDocDtlKey", "FullTransferOption", "FullTransferFromDocList",
}


class Wrapper:
    def __init__(self, db, *, ignore_shipping_po: bool = False, drop_rows: bool = False, drop_so_rows: bool = False):
        self.db = db
        self.ignore_shipping_po = ignore_shipping_po
        self.drop_rows = drop_rows  # vendor answers 200 but saves no PO rows
        self.drop_so_rows = drop_so_rows  # same for a created SO
        self.bodies: List[Dict[str, Any]] = []
        self.requests: List[str] = []  # "METHOD full-url"
        self.violations: List[str] = []
        so = _load("so_SO389293.json")
        so.update(
            DebtorCode=DEBTOR, DebtorName="Example Customer", Cancelled="F", LastModified="2026-01-26T10:00:00.00",
            Ref="", Description="SALES ORDER", DisplayTerm="C.O.D.", SalesAgent="AGENT",
            InvAddr1="1 Example Road", InvAddr2="", InvAddr3="", InvAddr4="", Phone1="000", Fax1="",
            Attention="Example Contact", BranchCode="", DeliverAddr1="1 Example Road", DeliverAddr2="",
            DeliverAddr3="", DeliverAddr4="", DeliverPhone1="000", DeliverFax1="", DeliverContact="",
            CurrencyCode="MYR", CurrencyRate=1.0, Remark1="", Remark2="", Remark3="", Remark4="",
            RefDocNo="", ShipVia="", ShipInfo="", InclusiveTax="F", YourPODate="0001-01-01T00:00:00",
        )
        self.sos: List[Dict[str, Any]] = [so]
        self.pos: List[Dict[str, Any]] = [_load("po_202602_S0007.json")]
        self.next_doc = 50000
        self.next_dtl = 60000
        self.stamp = 0
        self.transport = httpx.MockTransport(self._handle)

    # -- helpers
    def _touch(self, doc):
        self.stamp += 1
        doc["LastModified"] = f"2026-11-05T09:00:{self.stamp:02d}.00"

    def _derive(self, row):
        row["FromSODtlKey"] = row.get("FromDocDtlKey", 0) if row.get("FromDocType") == "SO" else 0
        row["FromSODocList"] = row.get("FromDocNo", "") if row.get("FromDocType") == "SO" else ""

    def po(self, doc_no: str) -> Dict[str, Any]:
        return next(d for d in self.pos if d["DocNo"] == doc_no)

    # -- transport
    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.method} {request.url}")
        if self.db.in_transaction():
            self.violations.append(f"{request.method} {request.url.path}: transaction open")
        name = request.url.path.rsplit("/", 1)[-1].lower()
        if request.method == "GET":
            docs = self.pos if name.startswith("purchaseorder") else self.sos
            return httpx.Response(200, json=copy.deepcopy(docs))
        body = json.loads(request.content)
        self.bodies.append(body)
        if _has_ancient_date(body):  # vendor behaviour (plan 55 live run, C07)
            return httpx.Response(500, json={"ExceptionMessage": "SqlDateTime overflow. Must be between 1/1/1753 12:00:00 AM and 12/31/9999 11:59:59 PM."})
        if request.method == "POST" and name == "newsalesorder":
            return self._new_so(body)
        if request.method == "POST" and name == "newpurchaseorder":
            return self._new(body)
        if request.method == "PUT" and name == "editpurchaseorderbydockey":
            return self._edit(body)
        return httpx.Response(404, text="unknown")

    def _new(self, body):
        tmpl = {k: v for k, v in _load("po_202602_S0007.json").items() if k != "Details"}
        doc = {**tmpl, **{k: v for k, v in body.items() if k != "Details"}}
        doc.update(DocKey=self.next_doc, Cancelled="F", CreditorName="Example Supplier Ltd")
        self.next_doc += 1
        doc.setdefault("DocDate", "2026-11-05T00:00:00")
        doc["ShippingPO"] = "F" if self.ignore_shipping_po else body.get("ShippingPO", "F")
        rows = []
        incomplete = any(not r.get("UOM") or r.get("UnitPrice") is None or not r.get("DeliveryDate") for r in body["Details"])
        for r in ([] if (incomplete or self.drop_rows) else body["Details"]):
            row = {**_load("po_202602_S0007.json")["Details"][0], **r, "DtlKey": self.next_dtl, "DocKey": doc["DocKey"]}
            row.setdefault("FromDocType", "")
            self.next_dtl += 1
            self._derive(row)
            rows.append(row)
        doc["Details"] = rows
        self._touch(doc)
        self.pos.append(doc)
        return httpx.Response(200, json={"DocKey": doc["DocKey"], "DocNo": doc["DocNo"]})

    def so(self, doc_no: str) -> Dict[str, Any]:
        return next(d for d in self.sos if d["DocNo"] == doc_no)

    def _new_so(self, body):
        """POST /NewSalesOrder: fresh DocKey / DtlKeys; a row missing UOM, UnitPrice or
        DeliveryDate is silently dropped (200 with no rows), as for a PO."""
        tmpl = {k: v for k, v in self.sos[0].items() if k != "Details"}
        doc = {**tmpl, **{k: v for k, v in body.items() if k != "Details"}}
        doc.update(DocKey=self.next_doc, Cancelled="F", DebtorName="Example Customer")
        self.next_doc += 1
        incomplete = any(not r.get("UOM") or r.get("UnitPrice") is None or not r.get("DeliveryDate") for r in body["Details"])
        rows = []
        for r in ([] if (incomplete or self.drop_so_rows) else body["Details"]):
            rows.append({**r, "DtlKey": self.next_dtl, "DocKey": doc["DocKey"]})
            self.next_dtl += 1
        doc["Details"] = rows
        self._touch(doc)
        self.sos.append(doc)
        return httpx.Response(200, json={"DocKey": doc["DocKey"], "DocNo": doc["DocNo"]})

    def _edit(self, body):
        """db3 reality: a NEW row linked to an SO is forced to HQ and reads back
        FromDocType "" with an empty DeliveryDate; editing an EXISTING row changes
        its location but never its link."""
        doc = next((d for d in self.pos if d["DocKey"] == body["DocKey"]), None)
        if doc is None:
            return httpx.Response(404, text="no doc")
        for r in body["Details"]:
            linked_sent = r.get("FromDocType") == "SO"
            if r["DtlKey"] == 0:
                row = {**doc["Details"][0], **r, "DtlKey": self.next_dtl, "DocKey": doc["DocKey"]}
                self.next_dtl += 1
                row["FromSODtlKey"] = r["FromDocDtlKey"] if linked_sent else 0
                row["FromSODocList"] = r.get("FromDocNo", "") if linked_sent else ""
                row["FromDocType"], row["FromDocNo"], row["FromDocDtlKey"] = "", "", 0
                if linked_sent:
                    row["DeliveryDate"] = "0001-01-01T00:00:00"
                    row["Location"] = "HQ"
                doc["Details"].append(row)
            else:
                row = next(x for x in doc["Details"] if x["DtlKey"] == r["DtlKey"])
                row.update({k: v for k, v in r.items() if not k.startswith("From")})
        self._touch(doc)
        return httpx.Response(200, json={"DocKey": doc["DocKey"]})


class Sink:
    name = "fake"

    def __init__(self):
        self.records: List[Any] = []

    def write(self, record, *, request_id=""):
        self.records.append(record)
        return WriteResult(ok=True, sink="fake", delivered=True, outcome="delivered")


def _setup(db, *, base_url=DB3, **wrapper_kw):
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="AC",
        config_json={"baseUrl": base_url, "userId": "ADMIN"},
        credentials_json=encrypt_secret(SECRETS), is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DBNAME,
        company_name=DBNAME, name=DBNAME, is_active=True, sink_impl="logging",
        write_connection_id=conn.id,
    )
    db.add(company)
    db.commit()
    return SimpleNamespace(company=company, wrapper=Wrapper(db, **wrapper_kw), sink=Sink(), bases=[])


def _run(db, s, tag="T1", **kw):
    def client_factory(url):
        s.bases.append(url)
        return AutoCountWriteClient(url, transport=s.wrapper.transport)

    return run_db3_suite(
        db, tenant_id=DEFAULT_TENANT_ID, company_id=s.company.id, creditor_code=CREDITOR,
        run_tag=tag, client_factory=client_factory,
        reader_factory=lambda url: AutoCountDocReader(url, transport=s.wrapper.transport),
        sink_factory=lambda *a, **k: s.sink, **kw,
    )


def _case(result, cid):
    return next(c for c in result.cases if c.case_id == cid)


def _statuses(result):
    return {c.case_id: (c.status, c.observed) for c in result.cases}


# ---- AC-55-50: full pass --------------------------------------------------------

def test_ac_55_50_full_suite_passes_in_order_against_the_fake(db):
    s = _setup(db)
    res = _run(db, s)
    assert [c.case_id for c in res.cases] == CASE_IDS
    bad = {k: v for k, v in _statuses(res).items() if v[0] != "PASS"}
    assert bad == {}, bad
    assert s.wrapper.violations == []


def test_ac_55_50_c01_creates_the_test_po(db):
    s = _setup(db)
    res = _run(db, s, tag="AB12")
    step = next(st for st in _case(res, "C01").steps if st.method == "POST")
    assert step.path == "/NewPurchaseOrder"
    body = step.request_json
    assert body["DocNo"] == "FXT-AB12-1" and body["CreditorCode"] == CREDITOR
    rows = body["Details"]
    assert [(r["ItemCode"], r["Qty"], r["Location"]) for r in rows] == [("SRTKT38SS", 50, "HQ"), ("SRTKT38SS", 10, "HQ")]
    assert s.wrapper.po("FXT-AB12-1")["ShippingPO"] == "F"


def test_ac_55_50_c02_pulls_so_before_po(db):
    s = _setup(db)
    res = _run(db, s)
    assert _case(res, "C02").status == "PASS"
    gets = [r for r in s.wrapper.requests if r.startswith("GET")]
    first_po = next(i for i, r in enumerate(gets) if "purchaseorder" in r.lower())
    assert all("salesorder" in r.lower() for r in gets[:first_po])
    assert first_po > 0


def _so_keys(s, tag="T1"):
    """DtlKeys of the test SO the suite created in C00 (row 1 = 10 @BRW-AM, row 2 = 5)."""
    rows = s.wrapper.so(f"FXT-{tag}-SO")["Details"]
    return rows[0]["DtlKey"], rows[1]["DtlKey"]


def _put_count(s):
    return len([r for r in s.wrapper.requests if r.startswith("PUT")])


def _post_count(s):
    return len([r for r in s.wrapper.requests if r.startswith("POST")])


def test_ac_55_50_c03_is_a_two_write_split_ending_at_the_so_location(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C03")
    assert c.status == "PASS" and c.action_id
    puts = [st for st in c.steps if st.method == "PUT"]
    assert len(puts) == 2 and all(p.path == "/EditPurchaseOrderbydockey" and p.status_code == 200 for p in puts)
    # first write: the vendor forced the new linked row to HQ; second write moved it
    so1, so2 = _so_keys(s)
    first_after = {(r["Qty"], r["Location"], r.get("FromSODtlKey")) for r in puts[0].after_rows}
    assert (40, "HQ", 0) in first_after and (10, "HQ", so1) in first_after
    second_after = {(r["Qty"], r["Location"], r.get("FromSODtlKey")) for r in puts[1].after_rows}
    assert (10, "BRW-AM", so1) in second_after
    new_row = next(r for r in puts[0].request_json["Details"] if r["DtlKey"] == 0)
    assert (new_row["FromDocNo"], new_row["FromDocDtlKey"]) == ("FXT-T1-SO", so1)
    row = db.get(AcWriteAction, c.action_id)
    assert row.action == "link" and row.outcome == "done" and row.error_code is None


def test_ac_55_50_c04_whole_row_link_is_refused_vendor_unsupported(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C04")
    assert c.status == "PASS" and "VENDOR_UNSUPPORTED" in c.observed
    assert not [st for st in c.steps if st.method in ("PUT", "POST")]
    assert db.get(AcWriteAction, c.action_id).error_code == "VENDOR_UNSUPPORTED"
    # writes in the whole suite: C03 (2) + C08 (2), nothing from C04
    assert _put_count(s) == 4


def test_ac_55_50_c08_second_split_of_the_40_row_ends_at_brw_am(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C08")
    assert c.status == "PASS" and c.action_id
    po = s.wrapper.po("FXT-T1-1")["Details"]
    linked = {r["FromSODtlKey"]: r for r in po if r["FromSODtlKey"]}
    so1, so2 = _so_keys(s)
    assert set(linked) == {so1, so2}
    assert linked[so1]["Qty"] == 10 and linked[so1]["Location"] == "BRW-AM"
    assert linked[so2]["Qty"] == 5 and linked[so2]["Location"] == "BRW-AM"
    assert sorted(r["Qty"] for r in po if not r["FromSODtlKey"]) == [10, 35]
    assert sum(r["Qty"] for r in po) == 60


@pytest.mark.parametrize("cid,code", [("C05", "QTY_ABOVE_OUTSTANDING"), ("C06", "QTY_ABOVE_FREE"), ("C09", "DOC_STALE")])
def test_ac_55_50_refusal_cases_name_the_code_and_send_no_put(db, cid, code):
    s = _setup(db)
    c = _case(_run(db, s), cid)
    assert c.status == "PASS"
    assert code in c.observed
    assert not [st for st in c.steps if st.method == "PUT"]


def test_ac_55_50_c07_unlink_is_refused_vendor_unsupported_with_no_request(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C07")
    assert c.status == "PASS" and "VENDOR_UNSUPPORTED" in c.observed
    assert not c.steps
    row = db.get(AcWriteAction, c.action_id)
    assert row.action == "unlink" and row.outcome == "refused"
    # the real PO is untouched
    assert next(r for r in s.wrapper.po("202602-S0007")["Details"] if r["DtlKey"] == 12013)["FromSODtlKey"] == 11993


def test_ac_55_50_c10_spo_unlink_is_refused_vendor_unsupported_and_no_spo_is_created(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C10")
    assert c.status == "PASS" and "VENDOR_UNSUPPORTED" in c.observed
    assert not c.steps
    assert db.get(AcWriteAction, c.action_id).action == "spo_unlink"
    assert _post_count(s) == 2  # C00's SO create and C01's PO create
    assert not [b for b in s.wrapper.bodies if b.get("ShippingPO") == "T"]


def test_ac_55_50_c11_relocate_on_c08s_row_is_already_at_location(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C11")
    assert c.status == "PASS" and "ROW_ALREADY_AT_LOCATION" in c.observed
    assert not [st for st in c.steps if st.method in ("PUT", "POST")]
    row = db.get(AcWriteAction, c.action_id)
    assert row.action == "relocate" and row.outcome == "refused"
    assert _put_count(s) == 4


def test_ac_55_50_c12_guard_makes_zero_requests(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C12")
    assert c.status == "PASS" and "WRITE_NOT_ALLOWED" in c.observed
    assert not [st for st in c.steps if st.method in ("PUT", "POST")]
    assert not [r for r in s.wrapper.requests if "/api/db1" in r]


def test_ac_55_42_non_db3_write_connection_refuses_to_start(db):
    s = _setup(db, base_url=DB1)
    with pytest.raises(Exception) as ei:
        _run(db, s)
    assert getattr(ei.value, "code", None) == "WRITE_NOT_ALLOWED"
    assert s.wrapper.requests == []


# ---- AC-55-51 / 04: step shape + sanitised report -----------------------------------

def test_ac_55_51_step_paths_are_vendor_paths_only(db):
    s = _setup(db)
    res = _run(db, s)
    for c in res.cases:
        for st in c.steps:
            assert st.path.startswith("/") and "http" not in st.path and "example.test" not in st.path
            assert st.method in ("GET", "POST", "PUT")


def test_ac_55_51_report_has_a_section_per_case_with_evidence(db):
    s = _setup(db)
    res = _run(db, s)
    md = render_report(res, run_date=date(2026, 11, 5))
    assert md.lstrip().startswith("#")
    assert "2026-11-05" in md
    for cid in CASE_IDS:
        assert re.search(rf"^#+ .*{cid}", md, re.M), cid
    assert "PASS" in md and "/EditPurchaseOrderbydockey" in md and "/NewPurchaseOrder" in md
    assert "/NewSalesOrder" in md
    assert "FXT-T1-1" in md and "202602-S0007" in md
    assert "QTY_ABOVE_OUTSTANDING" in md and "VENDOR_UNSUPPORTED" in md


def test_ac_55_04_report_is_sanitised(db):
    s = _setup(db)
    md = render_report(_run(db, s), run_date=date(2026, 11, 5))
    assert "http" not in md.lower()
    assert "example.test" not in md
    assert "x-api-key" not in md.lower()
    for secret in SECRETS.values():
        assert secret not in md
    for leaked in ("Example Supplier", "Example Contact", "Example Customer", "Example Road"):
        assert leaked not in md
    assert not re.search(r"fxa_(live|test)_", md)
    assert not re.search(r"\b[0-9a-f]{64}\b", md)  # no sha256 hash


def test_ac_55_51_report_marks_fail_and_skipped_honestly(db):
    s = _setup(db, drop_rows=True)
    md = render_report(_run(db, s), run_date=date(2026, 11, 5))
    c01 = re.search(r"^#+ .*C01.*?(?=^#+ .*C02)", md, re.M | re.S).group(0)
    assert "FAIL" in c01 and "rows dropped" in c01
    c02 = md[md.index(re.search(r"^#+ .*C02", md, re.M).group(0)):]
    assert "SKIPPED" in c02.split("C03")[0]
    assert "http" not in md.lower() and "example.test" not in md


# ---- vendor findings (live run 2026-11-04): create body + read-back check ----------

def _create_bodies(s):
    return [b for b in s.wrapper.bodies if "DocNo" in b and "DocKey" not in b and "CreditorCode" in b]


def _assert_complete_create_body(body, *, spo=False):
    assert set(body) - {"Details", "ShippingPO"} <= HEADER_KEYS
    assert body["DisplayTerm"] == "C.O.D." and body["CurrencyCode"] == "CNY"
    assert body["CurrencyRate"] == 0.6 and body["CreditorCode"] == CREDITOR
    assert body["DocDate"] and not _has_ancient_date(body)
    assert body.get("ShippingPO") == ("T" if spo else "F")
    assert body["Details"]
    for r in body["Details"]:
        assert POST_ROW_FIELDS <= set(r), POST_ROW_FIELDS - set(r)
        assert r["UOM"] == "UNIT" and r["UserUOM"] == "UNIT"
        assert r["UnitPrice"] == 1.0
        assert r["Description"] and r["Description"].endswith("SRTKT38SS")
        assert re.match(r"^20\d\d-\d\d-\d\dT", r["DeliveryDate"])


def test_vendor_c01_create_body_is_complete_and_has_no_empty_dates(db):
    s = _setup(db)
    res = _run(db, s)
    body = _create_bodies(s)[0]
    assert body["DocNo"] == "FXT-T1-1"
    _assert_complete_create_body(body)
    assert [r["Qty"] for r in body["Details"]] == [50, 10]
    assert [r["Location"] for r in body["Details"]] == ["HQ", "HQ"]
    assert _case(res, "C01").status == "PASS"
    # C01's OWN read-back shows two rows (the PO grows later, e.g. C03's split)
    seen = [len(st.after_rows) for st in _case(res, "C01").steps if st.after_rows is not None]
    assert (seen and seen[-1] == 2) or "2 rows" in _case(res, "C01").observed


def test_vendor_c01_description_comes_from_the_so_row(db):
    s = _setup(db)
    _run(db, s)
    so_row = next(r for r in s.wrapper.sos[0]["Details"] if r["DtlKey"] == 11989)
    for r in _create_bodies(s)[0]["Details"]:
        assert r["Description"] == so_row["Description"] and r["UOM"] == so_row["UOM"]


def test_vendor_no_write_body_in_the_suite_carries_a_pre_1753_date(db):
    s = _setup(db)
    _run(db, s)
    assert s.wrapper.bodies
    assert not [b for b in s.wrapper.bodies if _has_ancient_date(b)]


def test_vendor_c01_200_with_dropped_rows_is_fail_and_dependents_skipped(db):
    s = _setup(db, drop_rows=True)
    res = _run(db, s)
    c01 = _case(res, "C01")
    assert c01.status == "FAIL" and "rows dropped" in c01.observed
    assert _case(res, "C02").status == "SKIPPED" and "C01" in _case(res, "C02").observed
    for cid in ("C03", "C04", "C08", "C10", "C11"):
        assert _case(res, cid).status == "SKIPPED", cid


# ---- the fake itself reproduces both vendor behaviours ------------------------------

def test_fake_wrapper_rejects_ancient_dates_and_drops_incomplete_rows(db):
    s = _setup(db)
    client = AutoCountWriteClient(DB3, transport=s.wrapper.transport)
    bad_date = {"DocNo": "X1", "DocDate": "0001-01-01T00:00:00", "Details": []}
    assert client.post("/NewPurchaseOrder", bad_date).status_code == 500
    thin = {"DocNo": "X2", "DocDate": "2026-11-04T00:00:00", "Details": [{"ItemCode": "A", "Qty": 1}]}
    assert client.post("/NewPurchaseOrder", thin).status_code == 200
    assert s.wrapper.po("X2")["Details"] == []


# ---- C00: the suite creates its own test SO (repeatable db3 suite) ---------------------

SO_HEADER_KEYS = {
    "DocNo", "DocDate", "DebtorCode", "DebtorName", "Ref", "Description", "DisplayTerm", "SalesAgent",
    "InvAddr1", "InvAddr2", "InvAddr3", "InvAddr4", "Phone1", "Fax1", "Attention", "BranchCode",
    "DeliverAddr1", "DeliverAddr2", "DeliverAddr3", "DeliverAddr4", "DeliverPhone1", "DeliverFax1",
    "DeliverContact", "CurrencyCode", "CurrencyRate", "Remark1", "Remark2", "Remark3", "Remark4",
    "RefDocNo", "ShipVia", "ShipInfo", "InclusiveTax",
}
SO_ROW_FIELDS = {
    "ItemCode", "Location", "Description", "YourPONo", "ProjNo", "UOM", "UserUOM", "Qty", "FOCQty",
    "UnitPrice", "Discount", "TaxCode", "DeliveryDate", "Desc2", "FromDocType", "FromDocNo",
    "FromDocDtlKey", "FullTransferOption", "FullTransferFromDocList",
}


def _so_bodies(s):
    return [b for b in s.wrapper.bodies if "DebtorCode" in b and "DocKey" not in b]


def test_c00_creates_a_test_so_with_a_complete_body(db):
    s = _setup(db)
    res = _run(db, s, tag="T1")
    c = _case(res, "C00")
    assert c.status == "PASS"
    post = next(st for st in c.steps if st.method == "POST")
    assert post.path == "/NewSalesOrder"
    body = _so_bodies(s)[0]
    assert set(body) - {"Details"} <= SO_HEADER_KEYS
    assert "YourPODate" not in body and not _has_ancient_date(body)
    assert body["DocNo"] == "FXT-T1-SO" and body["DebtorCode"] == DEBTOR
    assert re.match(r"^20\d\d-\d\d-\d\dT", body["DocDate"])
    assert body["DisplayTerm"] == "C.O.D." and body["CurrencyCode"] == "MYR"
    rows = body["Details"]
    assert [(r["ItemCode"], r["Qty"], r["Location"]) for r in rows] == [("SRTKT38SS", 10, "BRW-AM"), ("SRTKT38SS", 5, "BRW-AM")]
    for r in rows:
        assert SO_ROW_FIELDS <= set(r), SO_ROW_FIELDS - set(r)
        assert re.match(r"^20\d\d-\d\d-\d\dT", r["DeliveryDate"]) and r["UOM"] == "UNIT"
        assert r["FromDocType"] == "" and r["FromDocNo"] == "" and r["FromDocDtlKey"] == 0
        assert r["YourPONo"] == ""
    assert len(s.wrapper.so("FXT-T1-SO")["Details"]) == 2


def test_c00_header_comes_from_so389293s_read_back(db):
    s = _setup(db)
    _run(db, s)
    body = _so_bodies(s)[0]
    src = s.wrapper.so("SO389293")
    for k in ("DisplayTerm", "SalesAgent", "CurrencyCode", "CurrencyRate", "InclusiveTax"):
        assert body[k] == src[k]


def test_c00_debtor_code_defaults_and_can_be_overridden(db):
    s = _setup(db)
    _run(db, s)
    assert _so_bodies(s)[0]["DebtorCode"] == "300-S057"
    s2 = _setup(db)
    _run(db, s2, tag="T2", debtor_code="300-X999")
    assert _so_bodies(s2)[0]["DebtorCode"] == "300-X999"


def test_c00_cli_has_a_debtor_flag(capsys):
    from modules.autocount.write_back.runner import main

    with pytest.raises(SystemExit):
        main(["--help"])
    assert "--debtor" in capsys.readouterr().out


def test_c00_200_with_dropped_so_rows_is_fail_and_dependents_skipped(db):
    s = _setup(db, drop_so_rows=True)
    res = _run(db, s)
    c00 = _case(res, "C00")
    assert c00.status == "FAIL" and "rows dropped" in c00.observed
    assert _case(res, "C02").status == "SKIPPED" and "C00" in _case(res, "C02").observed
    for cid in ("C03", "C04", "C08", "C11"):
        assert _case(res, cid).status == "SKIPPED", cid
    assert not [r for r in s.wrapper.requests if r.startswith("PUT")]


def test_c02_pulls_so_before_po_and_stages_the_test_so(db):
    from modules.autocount.models import AcStagedRecord

    s = _setup(db)
    res = _run(db, s)
    assert _case(res, "C02").status == "PASS"
    so_key = s.wrapper.so("FXT-T1-SO")["DocKey"]
    db.expire_all()
    ref = f"{DBNAME}:{so_key}"
    assert db.query(AcStagedRecord).filter(
        AcStagedRecord.company_id == s.company.id, AcStagedRecord.entity_type == "sales_order",
        AcStagedRecord.source_ref == ref,
    ).count() == 1


def test_c05_over_link_targets_the_test_so_row_covered_by_c03(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C05")
    assert c.status == "PASS" and "QTY_ABOVE_OUTSTANDING" in c.observed
    assert not [st for st in c.steps if st.method == "PUT"]
    assert db.get(AcWriteAction, c.action_id).error_code == "QTY_ABOVE_OUTSTANDING"


def test_suite_is_repeatable_second_run_with_a_new_tag_passes_again(db):
    s = _setup(db)
    first = _run(db, s, tag="R1")
    second = _run(db, s, tag="R2")
    for res in (first, second):
        bad = {c.case_id: (c.status, c.observed) for c in res.cases if c.status != "PASS"}
        assert bad == {}, bad
