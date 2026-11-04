"""Plan 57 S3 (RED): the primitive service, AC-57-03, 10..19 (flow side) and 73.

Contract under test: ``modules.autocount.write_back.primitives.PrimitiveService``
(plan 57 sections 5.2 / 5.4). Documents are wire-shaped dicts (PascalCase, as the
hapi wrapper speaks). Result fields: action_id, outcome (done | refused | mismatch |
pending_verification | vendor_error), error_code, warnings, doc_key, doc_no,
new_dtl_key, document. The vendor is ``FakeAutoCountVendor`` (no network).
"""

from __future__ import annotations

import copy
import json
from datetime import date
from types import MappingProxyType
from typing import Any, Dict, List, Optional

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.models import (
    STAGED,
    AcCompany,
    AcStagedRecord,
    AcWriteAction,
)
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back.reader import AutoCountDocReader
from tests.autocount_write_back_fake_vendor import FakeAutoCountVendor, new_doc
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

DB3 = "https://ac.example.test/api/db3"
DBNAME = "AED_TEST"
SECRETS = {"appId": "app-secret-1", "password": "pw-secret-9"}
ALL_KINDS = ["QT", "SO", "PO", "SPO"]


def _service_cls():
    from modules.autocount.write_back.primitives import PrimitiveService

    return PrimitiveService


def _line(item="ITEM-1", qty=2, price=10.0, location="HQ", **over) -> Dict[str, Any]:
    row = {"ItemCode": item, "UOM": "UNIT", "Qty": qty, "UnitPrice": price, "Location": location,
           "Description": item, "DeliveryDate": "2026-11-04T00:00:00"}
    row.update(over)
    return row


def _header(kind="SO", **over) -> Dict[str, Any]:
    party = "CreditorCode" if kind in ("PO", "SPO") else "DebtorCode"
    head = {party: "PARTY-1", "DocDate": "2026-11-04T00:00:00", "DisplayTerm": "C.B.D.",
            "CurrencyCode": "MYR", "CurrencyRate": 1.0, "Description": "test doc"}
    head.update(over)
    return head


class Harness:
    def __init__(self, db, session_factory, monkeypatch):
        self.db = db
        self.session_factory = session_factory
        self.monkeypatch = monkeypatch
        self.vendor = FakeAutoCountVendor()
        self.sink_calls: List[Any] = []
        self.factory_urls: List[str] = []
        self.conn = self._connection(DB3, DEFAULT_TENANT_ID)
        self.company = AcCompany(
            tenant_id=DEFAULT_TENANT_ID, connection_id=self.conn.id, database_name=DBNAME,
            company_name="AED Co", name=DBNAME, is_active=True, sink_impl="logging",
            write_connection_id=self.conn.id,
        )
        db.add(self.company)
        db.commit()

    def _connection(self, base_url: str, tenant_id: str) -> Connection:
        conn = Connection(
            tenant_id=tenant_id, provider="autocount", type="erp", name=f"AC {base_url}",
            config_json={"baseUrl": base_url, "userId": "ADMIN"},
            credentials_json=encrypt_secret(SECRETS), is_active=True,
        )
        self.db.add(conn)
        self.db.commit()
        return conn

    # ---- document seeding: vendor side + staged copy (the service reads DocDate from it)
    def seed_doc(self, kind: str, doc_key: int, rows: List[Dict[str, Any]], *, stage: bool = True,
                 doc_no: Optional[str] = None, **header: Any) -> Dict[str, Any]:
        party = "PARTY-1"
        doc = new_doc(kind, doc_key, doc_no or f"{kind}-{doc_key}", party, rows, **header)
        self.vendor.seed(kind, doc)
        if stage and kind != "QT":
            self.stage(kind, doc)
        return doc

    def stage(self, kind: str, doc: Dict[str, Any], job_id: str = "write-back") -> AcStagedRecord:
        """Stage ``doc`` as a row created by ``job_id`` (default = the write-back job, so the
        plan 57 staging guard treats it as ours; pass another job for a SQL-sync row)."""
        entity = {"SO": "sales_order", "PO": "purchase_order", "SPO": "shipping_order"}[kind]
        raw = {k: v for k, v in doc.items() if k != "Details"}
        raw["_lines"] = copy.deepcopy(doc["Details"])
        row = AcStagedRecord(
            tenant_id=DEFAULT_TENANT_ID, company_id=self.company.id, entity_type=entity,
            job_id=job_id, source_ref=f"{DBNAME}:{doc['DocKey']}", doc_no=doc["DocNo"],
            raw_json=raw, canonical_json={"sourceRef": f"{DBNAME}:{doc['DocKey']}"}, status=STAGED,
        )
        self.db.add(row)
        self.db.commit()
        return row

    # ---- service
    def factories(self) -> Dict[str, Any]:
        def client_factory(base_url: str):
            self.factory_urls.append(base_url)
            return AutoCountWriteClient(base_url, transport=self.vendor.transport)

        def reader_factory(base_url: str):
            return AutoCountDocReader(base_url, transport=self.vendor.transport)

        outer = self

        def sink_factory(*args, **kwargs):
            class _Sink:
                name = "fake"

                def write(self, record, *, request_id=""):
                    outer.sink_calls.append(record)

                def push(self, *a, **kw):
                    outer.sink_calls.append((a, kw))

            return _Sink()

        return dict(client_factory=client_factory, reader_factory=reader_factory, sink_factory=sink_factory)

    def service(self):
        return _service_cls()(self.db, **self.factories())

    def args(self, kind: str, **over) -> Dict[str, Any]:
        base = {"tenant_id": DEFAULT_TENANT_ID, "company_id": self.company.id, "kind": kind}
        base.update(over)
        return base

    def create(self, kind="SO", header=None, lines=None, **over):
        return self.service().create_doc(
            **self.args(kind, header=header if header is not None else _header(kind),
                        lines=lines if lines is not None else [_line(), _line("ITEM-2", 3, 7.0, "BR1")], **over))

    def edit(self, kind, doc_key, header_changes=None, line_changes=None, **over):
        return self.service().edit_doc(
            **self.args(kind, doc_key=doc_key, header_changes=header_changes or {},
                        line_changes=line_changes or [], **over))

    def flag(self, kind: str, primitive: str, value: bool = True) -> None:
        from modules.autocount.write_back import capabilities

        table = dict(capabilities.CAPABILITIES)
        table[(kind, primitive)] = value
        self.monkeypatch.setattr(capabilities, "CAPABILITIES", MappingProxyType(table), raising=True)

    def action(self, result) -> AcWriteAction:
        self.db.expire_all()
        return self.db.query(AcWriteAction).filter(AcWriteAction.id == result.action_id).one()

    def staged_count(self, entity: str) -> int:
        self.db.expire_all()
        return self.db.query(AcStagedRecord).filter(
            AcStagedRecord.company_id == self.company.id, AcStagedRecord.entity_type == entity).count()

    def no_http(self):
        assert self.vendor.calls == [], [(c.method, c.leaf) for c in self.vendor.calls]


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def h(db, session_factory, monkeypatch):
    return Harness(db, session_factory, monkeypatch)


# ---- AC-57-03: capability flags, refused before any HTTP ---------------------------

@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize("primitive", ["delete_line", "delete_doc", "cancel_doc"])
def test_ac_57_03_shipped_off_primitives_refused_without_http(h, kind, primitive):
    svc = h.service()
    common = h.args(kind, doc_key=12345)
    if primitive == "delete_line":
        res = svc.delete_line(**common, dtl_key=1)
    elif primitive == "delete_doc":
        res = svc.delete_doc(**common)
    else:
        res = svc.cancel_doc(**common)
    assert res.outcome == "refused" and res.error_code == "VENDOR_UNSUPPORTED"
    h.no_http()
    row = h.action(res)
    assert row.outcome == "refused" and row.error_code == "VENDOR_UNSUPPORTED"


@pytest.mark.parametrize("primitive", ["create_doc", "add_line"])
def test_ac_57_03_spo_create_and_add_line_refused_without_http(h, primitive):
    svc = h.service()
    if primitive == "create_doc":
        res = svc.create_doc(**h.args("SPO", header=_header("SPO"), lines=[_line()]))
    else:
        res = svc.add_line(**h.args("SPO", doc_key=12345, line=_line()))
    assert res.outcome == "refused" and res.error_code == "VENDOR_UNSUPPORTED"
    h.no_http()
    assert h.action(res).outcome == "refused"


def test_ac_57_03_flag_is_read_at_call_time(h):
    h.flag("QT", "create_doc", False)
    res = h.create("QT")
    assert res.outcome == "refused" and res.error_code == "VENDOR_UNSUPPORTED"
    h.no_http()
    h.flag("QT", "create_doc", True)
    assert h.create("QT").outcome == "done"


# ---- AC-57-10: create preconditions (no HTTP) ---------------------------------------

@pytest.mark.parametrize("missing", ["DebtorCode", "DocDate", "DisplayTerm", "CurrencyCode", "CurrencyRate"])
def test_ac_57_10_header_field_missing_is_field_required_naming_it(h, missing):
    head = _header("QT")
    head.pop(missing)
    res = h.create("QT", header=head)
    assert res.outcome == "refused" and res.error_code == "FIELD_REQUIRED"
    assert missing in json.dumps(h.action(res).response_json or "") + str(getattr(res, "message", "")) + str(res.warnings)
    h.no_http()


def test_ac_57_10_po_needs_creditor_code(h):
    head = _header("PO")
    head.pop("CreditorCode")
    res = h.create("PO", header=head)
    assert res.outcome == "refused" and res.error_code == "FIELD_REQUIRED"
    h.no_http()


def test_ac_57_10_no_lines_and_bad_line_fields_refused(h):
    assert h.create("SO", lines=[]).error_code == "FIELD_REQUIRED"
    for bad in ({"Qty": 0}, {"UnitPrice": -1}, {"Location": ""}, {"ItemCode": ""}, {"UOM": ""}):
        res = h.create("SO", lines=[_line(**bad)])
        assert res.outcome == "refused" and res.error_code == "FIELD_REQUIRED", bad
    h.no_http()


def test_ac_57_10_date_before_1753_never_sent(h):
    res = h.create("SO", lines=[_line(DeliveryDate="0001-01-01T00:00:00")])
    sent = [c.body for c in h.vendor.writes()]
    assert all("0001-01-01" not in json.dumps(b) for b in sent)
    assert res.outcome in ("done", "refused")


# ---- AC-57-12 / 13: create QT / SO / PO, answer parsing, read-back --------------------

def test_ac_57_12_create_qt_full_flow(h):
    res = h.create("QT")
    assert res.outcome == "done", res.error_code
    assert res.doc_no == "QT-000001" and isinstance(res.doc_key, int)
    assert [c.method for c in h.vendor.writes()] == ["POST"]
    post = h.vendor.writes()[0]
    assert post.leaf == "newquotation" and post.body["DocNo"] == "<<New>>"
    last = h.vendor.calls[-1]
    assert last.method == "GET" and last.leaf == "quotationbydocdate" and last.query["DocDate"] == "20261104"
    assert len(res.document["Details"]) == 2 and all(r["DtlKey"] for r in res.document["Details"])
    stored = h.vendor.find("QT", res.doc_key)
    assert stored["DebtorCode"] == "PARTY-1" and len(stored["Details"]) == 2


def test_ac_57_12_create_so_and_po_use_their_doors(h):
    so = h.create("SO")
    po = h.create("PO")
    assert so.outcome == "done" and po.outcome == "done", (so.error_code, po.error_code)
    assert [c.leaf for c in h.vendor.writes()] == ["newsalesorder", "newpurchaseorder"]
    assert h.vendor.writes()[1].body["CreditorCode"] == "PARTY-1"
    assert so.doc_no == "SO-000001" and po.doc_no == "PO-000001"


def test_ac_57_13_explicit_docno_is_sent_as_given(h):
    res = h.create("SO", header=_header("SO", DocNo="FXT-SO-9"))
    assert res.outcome == "done" and res.doc_no == "FXT-SO-9"
    assert h.vendor.writes()[0].body["DocNo"] == "FXT-SO-9"


def test_ac_57_13_auto_docno_off_is_docno_required(h):
    from modules.autocount.write_back import capabilities

    h.monkeypatch.setattr(capabilities, "AUTO_DOCNO", False, raising=False)
    res = h.create("SO")
    assert res.outcome == "refused" and res.error_code == "DOCNO_REQUIRED"
    h.no_http()


def test_ac_57_12_rows_dropped_is_mismatch_never_done(h):
    h.vendor.drop_rows_next_create()
    res = h.create("SO")
    assert res.outcome == "mismatch" and res.error_code == "ROWS_DROPPED"
    assert h.action(res).outcome == "mismatch"


def test_ac_57_12_unparseable_2xx_answer_falls_back_to_docno_when_sent(h):
    v = h.vendor
    original = v._create

    def odd(kind, body):
        resp = original(kind, body)
        import httpx

        return httpx.Response(200, text="OK")

    v._create = odd
    res = h.create("SO", header=_header("SO", DocNo="FXT-SO-7"))
    assert res.outcome == "done" and res.doc_no == "FXT-SO-7"
    res2 = h.create("SO")  # DocNo unknown and unparseable answer
    assert res2.outcome == "pending_verification"


def test_ac_57_11_so_from_qt_warns_link_unconfirmed_not_failed(h):
    line = _line(FromDocType="QT", FromDocNo="QT-000009", FromDocDtlKey=555)
    res = h.create("SO", lines=[line])
    assert res.outcome == "done", res.error_code
    assert "QT_ROW_LINK_UNCONFIRMED" in res.warnings
    assert h.vendor.writes()[0].body["Details"][0]["FromDocDtlKey"] == 555


def test_ac_57_12_create_vendor_500_is_vendor_error(h):
    h.vendor.fail_next("POST", "NewSalesOrder", 500, "boom")
    res = h.create("SO")
    assert res.outcome == "vendor_error"
    assert h.action(res).response_status == 500


# ---- AC-57-14: edit ---------------------------------------------------------------------

def _so(h, rows=None, **hdr):
    doc = h.seed_doc("SO", 5001, rows or [_line("A", 10, 5.0), _line("B", 4, 6.0, "BR1")], **hdr)
    return doc, [r["DtlKey"] for r in doc["Details"]]


def test_ac_57_14_edit_applied_reads_back_and_sends_only_changed_rows(h):
    _doc, keys = _so(h)
    res = h.edit("SO", 5001, {"Remark1": "hello"}, [{"DtlKey": keys[0], "Qty": 8}])
    assert res.outcome == "done", res.error_code
    put = h.vendor.writes()[0]
    assert put.method == "PUT" and put.leaf == "editsalesorderbydockey"
    assert [r["DtlKey"] for r in put.body["Details"]] == [keys[0]]
    assert put.body["DisplayTerm"] == "C.B.D." and put.body["Remark1"] == "hello"  # full header
    rows = h.vendor.rows("SO", 5001)
    assert rows[0]["Qty"] == 8 and rows[1]["Qty"] == 4
    assert res.document["Remark1"] == "hello"


def test_ac_57_14_ignored_header_field_is_mismatch_naming_the_field(h):
    _so(h)
    h.vendor.ignored_fields = {"Remark1"}
    res = h.edit("SO", 5001, {"Remark1": "hello"})
    assert res.outcome == "mismatch"
    assert "Remark1" in str(res.error_code) + str(getattr(res, "message", "")) + str(res.warnings)


def test_ac_57_14_header_field_outside_allowlist_refused_without_write(h):
    _so(h)
    res = h.edit("SO", 5001, {"DebtorCode": "OTHER"})
    assert res.outcome == "refused"
    assert h.vendor.writes() == []


def test_ac_57_14_edit_on_qt_uses_quotation_door(h):
    doc = h.seed_doc("QT", 6001, [_line("A", 1, 9.0)])
    res = h.edit("QT", 6001, {"Remark2": "x"}, [{"DtlKey": doc["Details"][0]["DtlKey"], "Qty": 3}],
                 doc_date=date(2026, 11, 4))  # AC-57-20: a QT has no staged copy
    assert res.outcome == "done", res.error_code
    assert h.vendor.writes()[0].leaf == "editquotationbydockey"


# ---- AC-57-15: add line --------------------------------------------------------------------

def test_ac_57_15_add_line_returns_new_dtl_key(h):
    _so(h)
    res = h.service().add_line(**h.args("SO", doc_key=5001, line=_line("C", 1, 3.0)))
    assert res.outcome == "done", res.error_code
    rows = h.vendor.rows("SO", 5001)
    assert len(rows) == 3 and res.new_dtl_key == rows[-1]["DtlKey"]
    put = h.vendor.writes()[0]
    assert [r["DtlKey"] for r in put.body["Details"]] == [0]


# ---- AC-57-16: delete line (flag on) -----------------------------------------------------------

def test_ac_57_16_delete_line_removes_row_and_leaves_others(h):
    _doc, keys = _so(h)
    h.flag("SO", "delete_line", True)
    before_other = copy.deepcopy(h.vendor.rows("SO", 5001)[1])
    res = h.service().delete_line(**h.args("SO", doc_key=5001, dtl_key=keys[0]))
    assert res.outcome == "done", res.error_code
    call = h.vendor.writes()[0]
    assert call.method == "DELETE" and call.leaf == "deletesalesorderdetailbydtlkey"
    assert call.body == {"DocKey": 5001, "DtlKey": keys[0]}
    rows = h.vendor.rows("SO", 5001)
    assert [r["DtlKey"] for r in rows] == [keys[1]] and rows[0] == before_other


# ---- AC-57-17: cancel (flag on) -----------------------------------------------------------------

def test_ac_57_17_cancel_applied_when_vendor_honours_it(h):
    _so(h)
    h.flag("SO", "cancel_doc", True)
    h.vendor.docs["SO"][0]["Cancelled"] = "F"
    original = h.vendor._edit

    def honour(kind, body):
        resp = original(kind, body)
        if body.get("Cancelled") == "T":
            h.vendor.find(kind, body["DocKey"])["Cancelled"] = "T"
        return resp

    h.vendor._edit = honour
    res = h.service().cancel_doc(**h.args("SO", doc_key=5001))
    assert res.outcome == "done", res.error_code
    assert h.vendor.writes()[0].body["Cancelled"] == "T"


def test_ac_57_17_cancel_ignored_by_vendor_is_mismatch(h):
    _so(h)
    h.flag("SO", "cancel_doc", True)
    res = h.service().cancel_doc(**h.args("SO", doc_key=5001))  # db3 ignores Cancelled
    assert res.outcome == "mismatch"


# ---- AC-57-18: refusals before any write ----------------------------------------------------------------

def test_ac_57_18_doc_stale(h):
    _so(h)
    res = h.edit("SO", 5001, {"Remark1": "x"}, expected_last_modified="1999-01-01T00:00:00.00")
    assert res.outcome == "refused" and res.error_code == "DOC_STALE"
    assert h.vendor.writes() == []


def test_ac_57_18_doc_busy(h):
    _so(h)
    h.db.add(AcWriteAction(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, action="edit_doc",
                           doc_type="SO", doc_key=5001, outcome="in_flight", request_json={}))
    h.db.commit()
    res = h.edit("SO", 5001, {"Remark1": "x"})
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY"
    h.no_http()


@pytest.mark.parametrize("op", ["edit", "add", "delete", "cancel"])
def test_ac_57_18_cancelled_document_is_doc_cancelled(h, op):
    _doc, keys = _so(h, Cancelled="T")
    for prim in ("delete_line", "cancel_doc"):
        h.flag("SO", prim, True)
    svc = h.service()
    common = h.args("SO", doc_key=5001)
    if op == "edit":
        res = svc.edit_doc(**common, header_changes={"Remark1": "x"}, line_changes=[])
    elif op == "add":
        res = svc.add_line(**common, line=_line())
    elif op == "delete":
        res = svc.delete_line(**common, dtl_key=keys[0])
    else:
        res = svc.cancel_doc(**common)
    assert res.outcome == "refused" and res.error_code == "DOC_CANCELLED"
    assert h.vendor.writes() == []


def test_ac_57_18_row_not_found(h):
    _so(h)
    res = h.edit("SO", 5001, {}, [{"DtlKey": 999999, "Qty": 1}])
    assert res.outcome == "refused" and res.error_code == "ROW_NOT_FOUND"
    assert h.vendor.writes() == []


def test_ac_57_18_so_qty_below_transferred_refused(h):
    _doc, keys = _so(h, rows=[_line("A", 10, 5.0)])
    po = h.seed_doc("PO", 5002, [_line("A", 6, 5.0, FromSODtlKey=keys[0], FromDocType="SO", FromDocDtlKey=keys[0])])
    assert po["Details"][0]["FromSODtlKey"] == keys[0]
    res = h.edit("SO", 5001, {}, [{"DtlKey": keys[0], "Qty": 4}])
    assert res.outcome == "refused" and res.error_code == "QTY_BELOW_TRANSFERRED"
    assert h.vendor.writes() == []
    ok = h.edit("SO", 5001, {}, [{"DtlKey": keys[0], "Qty": 6}])
    assert ok.outcome == "done", ok.error_code


# ---- AC-57-05: no retry; vendor errors ----------------------------------------------------------------------

def test_ac_57_05_timeout_is_pending_verification_and_never_retried(h):
    _so(h)
    h.vendor.timeout_next("PUT", "EditSalesOrderbydockey")
    res = h.edit("SO", 5001, {"Remark1": "x"})
    assert res.outcome == "pending_verification"
    assert len([c for c in h.vendor.writes()]) == 1
    row = h.action(res)
    assert row.outcome == "pending_verification"


def test_ac_57_05_vendor_500_is_vendor_error_no_retry(h):
    _so(h)
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, "kaput")
    res = h.edit("SO", 5001, {"Remark1": "x"})
    assert res.outcome == "vendor_error"
    assert len(h.vendor.writes()) == 1


# ---- AC-57-19: exact recording, no host --------------------------------------------------------------------------

def test_ac_57_19_action_row_records_exact_call_without_host(h):
    _doc, keys = _so(h)
    res = h.edit("SO", 5001, {"Remark1": "rec"}, [{"DtlKey": keys[0], "Qty": 7}])
    assert res.outcome == "done"
    row = h.action(res)
    sent = h.vendor.writes()[0]
    assert row.request_method == "PUT" and row.request_path == "/EditSalesOrderbydockey"
    assert row.request_json == sent.body
    assert row.response_status == 200 and "Done Edit" in json.dumps(row.response_json)
    assert row.before_json["Details"][0]["Qty"] == 10 and row.after_json["Details"][0]["Qty"] == 7
    blob = json.dumps(
        [row.request_method, row.request_path, row.request_json, row.response_status,
         row.response_json, row.before_json, row.after_json, row.error_code], default=str)
    for secret in ("ac.example.test", "api/db3", SECRETS["appId"], SECRETS["password"]):
        assert secret not in blob
    assert "ac.example.test" not in json.dumps(res.document, default=str)


def test_ac_57_19_create_row_has_post_method_and_path(h):
    res = h.create("QT")
    row = h.action(res)
    assert (row.request_method, row.request_path) == ("POST", "/NewQuotation")
    assert row.doc_type == "QT" and row.doc_key == res.doc_key


# ---- AC-57-52 / 50: sink -------------------------------------------------------------------------------------------

def test_ac_57_52_qt_is_answered_not_staged_or_pushed(h):
    res = h.create("QT")
    assert res.outcome == "done"
    assert h.sink_calls == []
    assert h.db.query(AcStagedRecord).filter(AcStagedRecord.company_id == h.company.id).count() == 0


@pytest.mark.parametrize("kind,entity", [("SO", "sales_order"), ("PO", "purchase_order")])
def test_ac_57_50_so_and_po_create_is_staged_for_the_sink(h, kind, entity):
    res = h.create(kind)
    assert res.outcome == "done"
    assert h.staged_count(entity) == 1


# ---- AC-57-73: schema surface (the migration itself is checked on Postgres by the lane) --------------------------

def test_ac_57_73_new_columns_are_nullable_and_operation_model_exists():
    from modules.autocount import models

    cols = AcWriteAction.__table__.c
    for name in ("operation_id", "step", "request_method", "request_path"):
        assert name in cols and cols[name].nullable, name
    op = models.AcWriteOperation.__table__.c
    for name in ("id", "tenant_id", "company_id", "key_id", "idempotency_key", "request_hash", "op",
                 "doc_type", "doc_key", "dtl_key", "status", "error_code", "snapshot_json",
                 "steps_json", "result_json", "created_at", "updated_at"):
        assert name in op, name


# ---- VENDOR_REFUSED: AutoCount's own refusal text (owner ruling 4 Nov) ----------------------------------------

CREDIT = "This account had violated the credit limit. You are not allow to save."
TRANSFERRED = ("Quantity cannot be less than the quantity it was partially transferred to Purchase "
               "Order, save aborted.")


def _refusal_body(message: str, **extra) -> str:
    return json.dumps({"Message": "An error has occurred.", "ExceptionMessage": message,
                       "ExceptionType": "System.Exception",
                       "StackTrace": "   at AutoCount.Foo.Bar() in C:\\src\\Foo.cs:line 12", **extra})


def _assert_clean(res):
    text = res.message or ""
    for bad in ("StackTrace", "ExceptionType", "System.Exception", "Foo.cs", "ac.example.test", "api/db3"):
        assert bad not in text, bad


def test_vendor_refused_on_create_carries_the_autocount_message(h):
    h.vendor.fail_next("POST", "NewSalesOrder", 500, _refusal_body(CREDIT))
    res = h.create("SO")
    assert res.outcome == "vendor_error" and res.error_code == "VENDOR_REFUSED"
    assert CREDIT in res.message
    _assert_clean(res)
    assert [c.method for c in h.vendor.writes()] == ["POST"] and h.vendor.docs["SO"] == []


def test_vendor_refused_on_edit_carries_the_autocount_message(h):
    _so(h)
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, _refusal_body(TRANSFERRED))
    res = h.edit("SO", 5001, {"Remark1": "x"})
    assert res.outcome == "vendor_error" and res.error_code == "VENDOR_REFUSED"
    assert TRANSFERRED in res.message
    _assert_clean(res)
    assert len(h.vendor.writes()) == 1


def test_vendor_refused_message_is_sanitised_of_hosts_and_secrets(h):
    nasty = f"Cannot reach https://ac.example.test/api/db3/NewSalesOrder with {SECRETS['password']}"
    h.vendor.fail_next("POST", "NewSalesOrder", 500, _refusal_body(nasty))
    res = h.create("SO")
    assert res.error_code == "VENDOR_REFUSED"
    _assert_clean(res)
    assert SECRETS["password"] not in (res.message or "")


@pytest.mark.parametrize("body", ["boom", "", json.dumps({"Message": "An error has occurred."}),
                                  json.dumps({"ExceptionMessage": ""})])
def test_a_bare_5xx_without_a_message_stays_a_plain_vendor_error(h, body):
    _so(h)
    h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, body)
    res = h.edit("SO", 5001, {"Remark1": "x"})
    assert res.outcome == "vendor_error" and res.error_code != "VENDOR_REFUSED"


def test_vendor_refused_message_is_recorded_on_the_action_row_without_a_host(h):
    h.vendor.fail_next("POST", "NewSalesOrder", 500, _refusal_body(CREDIT))
    res = h.create("SO")
    row = h.action(res)
    assert row.error_code == "VENDOR_REFUSED" and row.response_status == 500
    assert "ac.example.test" not in json.dumps(row.response_json, default=str)
