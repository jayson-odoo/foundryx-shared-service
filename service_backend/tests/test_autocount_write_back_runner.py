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
from typing import Any, Dict, List, Optional

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

DB3 = "https://ac.example.test/api/db3"
DB1 = "https://ac.example.test/api/db1"
DBNAME = "AED_RUN"
SECRETS = {"appId": "app-secret-run", "password": "pw-secret-run"}
CASE_IDS = [f"C{n:02d}" for n in range(1, 13)]
CREDITOR = "400-N004"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


class Wrapper:
    def __init__(self, db, *, ignore_shipping_po: bool = False):
        self.db = db
        self.ignore_shipping_po = ignore_shipping_po
        self.requests: List[str] = []  # "METHOD full-url"
        self.violations: List[str] = []
        so = _load("so_SO389293.json")
        so.update(DebtorCode="300-C001", DebtorName="Example Customer", Cancelled="F", LastModified="2026-01-26T10:00:00.00")
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
        for r in body["Details"]:
            row = {**_load("po_202602_S0007.json")["Details"][0], **r, "DtlKey": self.next_dtl, "DocKey": doc["DocKey"]}
            row.setdefault("FromDocType", "")
            self.next_dtl += 1
            self._derive(row)
            rows.append(row)
        doc["Details"] = rows
        self._touch(doc)
        self.pos.append(doc)
        return httpx.Response(200, json={"DocKey": doc["DocKey"], "DocNo": doc["DocNo"]})

    def _edit(self, body):
        doc = next((d for d in self.pos if d["DocKey"] == body["DocKey"]), None)
        if doc is None:
            return httpx.Response(404, text="no doc")
        for r in body["Details"]:
            if r["DtlKey"] == 0:
                row = {**doc["Details"][0], **r, "DtlKey": self.next_dtl, "DocKey": doc["DocKey"]}
                self.next_dtl += 1
                doc["Details"].append(row)
            else:
                row = next(x for x in doc["Details"] if x["DtlKey"] == r["DtlKey"])
                row.update(r)
            self._derive(row)
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


def _run(db, s, tag="T1"):
    def client_factory(url):
        s.bases.append(url)
        return AutoCountWriteClient(url, transport=s.wrapper.transport)

    return run_db3_suite(
        db, tenant_id=DEFAULT_TENANT_ID, company_id=s.company.id, creditor_code=CREDITOR,
        run_tag=tag, client_factory=client_factory,
        reader_factory=lambda url: AutoCountDocReader(url, transport=s.wrapper.transport),
        sink_factory=lambda *a, **k: s.sink,
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


def test_ac_55_50_c03_split_link_steps_and_server_state(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C03")
    assert c.status == "PASS" and c.action_id
    put = next(st for st in c.steps if st.method == "PUT")
    assert put.path == "/EditPurchaseOrderbydockey" and put.status_code == 200
    assert put.request_json["Details"] and put.before_rows and put.after_rows
    row = db.get(AcWriteAction, c.action_id)
    assert row.action == "link" and row.outcome == "done"
    test_po = s.wrapper.po("FXT-T1-1")
    # quantity is conserved across split + relocation
    assert sum(r["Qty"] for r in test_po["Details"]) == 60
    after = {(r["Qty"], r["Location"], r.get("FromSODtlKey")) for r in put.after_rows}
    assert (40, "HQ", 0) in after
    assert (10, "BRW-AM", 11989) in after
    # final server state: C04's link on row 11992 stands; C11 unlinked the split-off row
    by_so = {r["FromSODtlKey"] for r in test_po["Details"]}
    assert 11992 in by_so
    assert 11989 not in by_so
    split_off = [r for r in test_po["Details"] if r["Qty"] == 10 and r["Location"] == "BRW-AM"]
    assert any(r["FromSODtlKey"] == 0 for r in split_off)


def test_ac_55_50_c04_same_qty_location_move_adds_no_row(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C04")
    assert c.status == "PASS"
    assert len(s.wrapper.po("FXT-T1-1")["Details"]) == 3  # 2 created + 1 split, none from C04
    put = next(st for st in c.steps if st.method == "PUT")
    assert [r["DtlKey"] for r in put.request_json["Details"] if r["DtlKey"] == 0] == []


@pytest.mark.parametrize("cid,code", [("C05", "QTY_ABOVE_OUTSTANDING"), ("C06", "QTY_ABOVE_FREE"), ("C09", "DOC_STALE")])
def test_ac_55_50_refusal_cases_name_the_code_and_send_no_put(db, cid, code):
    s = _setup(db)
    c = _case(_run(db, s), cid)
    assert c.status == "PASS"
    assert code in c.observed
    assert not [st for st in c.steps if st.method == "PUT"]


def test_ac_55_50_c07_c08_unlink_then_relink_real_row(db):
    s = _setup(db)
    res = _run(db, s)
    assert _case(res, "C07").status == "PASS" and _case(res, "C08").status == "PASS"
    row = next(r for r in s.wrapper.po("202602-S0007")["Details"] if r["DtlKey"] == 12013)
    assert row["FromSODtlKey"] == 11993
    assert _case(res, "C07").action_id and _case(res, "C08").action_id


def test_ac_55_50_c10_creates_spo_and_sees_row_on_spo(db):
    s = _setup(db)
    res = _run(db, s, tag="T1")
    c = _case(res, "C10")
    assert c.status == "PASS" and "ROW_ON_SPO" in c.observed
    post = next(st for st in c.steps if st.method == "POST")
    assert post.path == "/NewPurchaseOrder"
    assert post.request_json["ShippingPO"] == "T" and post.request_json["DocNo"] == "FXT-T1-S1"
    row = post.request_json["Details"][0]
    assert row["FromDocType"] == "PO" and row["FromDocNo"] == "FXT-T1-1" and row["FromDocDtlKey"]


def test_ac_55_50_c11_spo_unlink_then_po_unlink_done(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C11")
    assert c.status == "PASS" and c.action_id
    spo = s.wrapper.po("FXT-T1-S1")
    assert spo["Details"][0]["FromDocType"] == "" and spo["Details"][0]["FromDocDtlKey"] == 0
    actions = {a.action for a in db.query(AcWriteAction).all()}
    assert {"link", "unlink", "spo_unlink"} <= actions


def test_ac_55_50_c12_guard_makes_zero_requests(db):
    s = _setup(db)
    res = _run(db, s)
    c = _case(res, "C12")
    assert c.status == "PASS" and "WRITE_NOT_ALLOWED" in c.observed
    assert not [st for st in c.steps if st.method in ("PUT", "POST")]
    assert not [r for r in s.wrapper.requests if "/api/db1" in r]


# ---- vendor ignores ShippingPO ------------------------------------------------------

def test_ac_55_50_vendor_ignoring_shipping_po_fails_c10_and_skips_c11(db):
    s = _setup(db, ignore_shipping_po=True)
    res = _run(db, s)  # must not crash
    st = _statuses(res)
    for cid in CASE_IDS[:9]:
        assert st[cid][0] == "PASS", (cid, st[cid])
    assert st["C10"][0] == "FAIL" and "ShippingPO" in st["C10"][1]
    assert st["C11"][0] == "SKIPPED" and "C10" in st["C11"][1]


# ---- runner guard ------------------------------------------------------------------

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
    assert "FXT-T1-1" in md and "202602-S0007" in md
    assert "QTY_ABOVE_OUTSTANDING" in md and "ROW_ON_SPO" in md


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
    s = _setup(db, ignore_shipping_po=True)
    md = render_report(_run(db, s), run_date=date(2026, 11, 5))
    c10 = re.search(r"^#+ .*C10.*?(?=^#+ .*C11)", md, re.M | re.S).group(0)
    assert "FAIL" in c10 and "ShippingPO" in c10
    c11 = md[md.index(re.search(r"^#+ .*C11", md, re.M).group(0)):]
    assert "SKIPPED" in c11.split("C12")[0]
