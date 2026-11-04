"""Plan 55 S3: write-back service flow, action log, fetch-back (AC-55-20..28).

The AutoCount wrapper is a fake server behind two ``httpx.MockTransport``s (one
for the read client, one for the write client) so a test can assert "zero
requests on BOTH". Every handler also asserts the db session holds no open
transaction (AC-55-27) and that the in_flight action row is already committed
when the PUT arrives.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    STAGED,
    AcCompany,
    AcEntityConfig,
    AcStagedRecord,
    AcWriteAction,
)
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back.reader import AutoCountDocReader
from modules.autocount.write_back.service import WriteBackService

FIX = Path(__file__).parent / "fixtures" / "autocount_write_back"
DB3 = "https://ac.example.test/api/db3"
DB1 = "https://ac.example.test/api/db1"
DBNAME = "AED_TEST"
OTHER_TENANT = "other-tenant-id"
SECRETS = {"appId": "app-secret-1", "password": "pw-secret-9"}
PUT_PATH = "/EditPurchaseOrderbydockey"


def _load(name: str) -> Dict[str, Any]:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class FakeAutoCount:
    """Stateful fake wrapper. ``put_mode``: apply | vendor_error | timeout | ignore |
    corrupt_untouched. ``get_fail_after_put``: second GET answers 500."""

    def __init__(self, db, session_factory, doc_keys_in_flight_check: int = 12008):
        self.db = db
        self.session_factory = session_factory
        self.docs: Dict[str, List[Dict[str, Any]]] = {}
        self.put_mode = "apply"
        self.get_fail_after_put = False
        self.get_calls: List[httpx.Request] = []
        self.put_calls: List[httpx.Request] = []
        self.put_bodies: List[Dict[str, Any]] = []
        self.violations: List[str] = []
        self.in_flight_seen_at_put: List[int] = []
        self.next_dtl = 90001
        self.check_key = doc_keys_in_flight_check
        self.read_transport = httpx.MockTransport(self._on_get)
        self.write_transport = httpx.MockTransport(self._on_put)

    def serve(self, kind_path: str, doc: Dict[str, Any]) -> None:
        self.docs.setdefault(kind_path, []).append(copy.deepcopy(doc))

    def _check_txn(self, what: str) -> None:
        if self.db.in_transaction():
            self.violations.append(f"{what}: db transaction open during AutoCount call")

    def _on_get(self, request: httpx.Request) -> httpx.Response:
        self.get_calls.append(request)
        self._check_txn("GET")
        if self.get_fail_after_put and self.put_calls:
            return httpx.Response(500, text="boom")
        path = request.url.path.rsplit("/", 1)[-1].lower()
        return httpx.Response(200, json=copy.deepcopy(self.docs.get(path, [])))

    def _on_put(self, request: httpx.Request) -> httpx.Response:
        self.put_calls.append(request)
        self._check_txn("PUT")
        body = json.loads(request.content)
        self.put_bodies.append(body)
        other = self.session_factory()
        try:
            rows = (
                other.query(AcWriteAction)
                .filter(AcWriteAction.doc_key == body["DocKey"], AcWriteAction.outcome == "in_flight")
                .all()
            )
            self.in_flight_seen_at_put.append(len(rows))
        finally:
            other.close()
        if self.put_mode == "timeout":
            raise httpx.ReadTimeout("slow")
        if self.put_mode == "vendor_error":
            return httpx.Response(400, json={"Message": "vendor says no"})
        if self.put_mode != "ignore":
            self._apply(body)
        return httpx.Response(200, json={"DocKey": body["DocKey"]})

    def _apply(self, body: Dict[str, Any]) -> None:
        doc = next(d for d in self.docs["purchaseorderbydocdate"] if d["DocKey"] == body["DocKey"])
        for r in body["Details"]:
            if r["DtlKey"] == 0:
                new = {**r, "DtlKey": self.next_dtl, "FromSODtlKey": 0, "FromSODocList": ""}
                self.next_dtl += 1
                doc["Details"].append(new)
                target = new
            else:
                target = next(x for x in doc["Details"] if x["DtlKey"] == r["DtlKey"])
                target.update(r)
            target["FromSODtlKey"] = r["FromDocDtlKey"] if r["FromDocType"] == "SO" else 0
        if self.put_mode == "corrupt_untouched":
            touched = {r["DtlKey"] for r in body["Details"]}
            victim = next(x for x in doc["Details"] if x["DtlKey"] not in touched and x["FromSODtlKey"])
            victim["Location"] = "ELSEWHERE"
        doc["LastModified"] = "2026-11-05T09:00:00.00"


class Harness:
    def __init__(self, db, session_factory):
        self.db = db
        self.session_factory = session_factory
        self.ac = FakeAutoCount(db, session_factory)
        self.ac.serve("purchaseorderbydocdate", _load("po_202602_S0007.json"))
        self.ac.serve("salesorderbydocdate", _load("so_SO389293.json"))
        self.sink_calls: List[Any] = []
        self.factory_urls: List[str] = []
        self.conn = self._connection(DB3, DEFAULT_TENANT_ID)
        self.company = self._company(DEFAULT_TENANT_ID, self.conn.id)
        self.stage_po()
        self.stage_so()

    # ---- seeding -------------------------------------------------------
    def _connection(self, base_url: str, tenant_id: str) -> Connection:
        conn = Connection(
            tenant_id=tenant_id, provider="autocount", type="erp", name=f"AC {base_url}",
            config_json={"baseUrl": base_url, "userId": "ADMIN"},
            credentials_json=encrypt_secret(SECRETS), is_active=True,
        )
        self.db.add(conn)
        self.db.commit()
        return conn

    def _company(self, tenant_id: str, write_conn_id: Optional[str], database: str = DBNAME) -> AcCompany:
        company = AcCompany(
            tenant_id=tenant_id, connection_id=self.conn.id if hasattr(self, "conn") else "x",
            database_name=database, company_name=f"{database} Co", name=database,
            is_active=True, sink_impl="logging", write_connection_id=write_conn_id,
        )
        self.db.add(company)
        self.db.commit()
        return company

    def _stage(self, entity: str, doc: Dict[str, Any], tenant_id: str = DEFAULT_TENANT_ID,
               company_id: Optional[str] = None) -> AcStagedRecord:
        raw = {k: v for k, v in doc.items() if k != "Details"}
        raw["_lines"] = copy.deepcopy(doc["Details"])
        row = AcStagedRecord(
            tenant_id=tenant_id, company_id=company_id or self.company.id, entity_type=entity,
            job_id="job-1", source_ref=f"{DBNAME}:{doc['DocKey']}", doc_no=doc["DocNo"],
            raw_json=raw, canonical_json={"sourceRef": f"{DBNAME}:{doc['DocKey']}"}, status=STAGED,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def stage_po(self):
        return self._stage("purchase_order", _load("po_202602_S0007.json"))

    def stage_so(self):
        return self._stage("sales_order", _load("so_SO389293.json"))

    def stage_spo_pointing_at(self, po_dtl_key: int):
        spo = _load("spo_db1_sample.json")
        spo["Details"][0]["FromDocType"] = "PO"
        spo["Details"][0]["FromDocDtlKey"] = po_dtl_key
        return self._stage("shipping_order", spo), spo

    # ---- service -------------------------------------------------------
    def service(self) -> WriteBackService:
        def client_factory(base_url: str):
            self.factory_urls.append(base_url)
            return AutoCountWriteClient(base_url, transport=self.ac.write_transport)

        def reader_factory(base_url: str):
            return AutoCountDocReader(base_url, transport=self.ac.read_transport)

        def sink_factory(*args, **kwargs):
            outer = self

            class _Sink:
                name = "fake"

                def write(self, record, *, request_id=""):
                    outer.sink_calls.append(record)
                    return None

                def push(self, *a, **kw):
                    outer.sink_calls.append((a, kw))

            return _Sink()

        return WriteBackService(
            self.db, client_factory=client_factory, reader_factory=reader_factory,
            sink_factory=sink_factory,
        )

    def link_split(self, **over):
        args = dict(
            tenant_id=DEFAULT_TENANT_ID, company_id=self.company.id, po_doc_key=12008,
            po_dtl_key=12017, so_doc_key=11988, so_dtl_key=11989, qty=Decimal(10),
        )
        args.update(over)
        return self.service().link(**args)

    def action(self, result) -> AcWriteAction:
        self.db.expire_all()
        return self.db.query(AcWriteAction).filter(AcWriteAction.id == result.action_id).one()

    def staged_po(self) -> AcStagedRecord:
        self.db.expire_all()
        return (
            self.db.query(AcStagedRecord)
            .filter(AcStagedRecord.company_id == self.company.id,
                    AcStagedRecord.entity_type == "purchase_order",
                    AcStagedRecord.source_ref == f"{DBNAME}:12008")
            .one()
        )

    def no_http(self):
        assert self.ac.get_calls == [] and self.ac.put_calls == []

    def clean(self):
        assert self.ac.violations == []


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def h(db, session_factory):
    return Harness(db, session_factory)


# ---- steps 1-3: connection / company / book ---------------------------------

def test_ac_55_45_write_disabled_when_no_write_connection(h):
    h.company.write_connection_id = None
    h.db.commit()
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "WRITE_DISABLED"
    h.no_http()


def test_ac_55_45_company_of_another_tenant_is_write_disabled(h):
    other_conn = h._connection(DB3, OTHER_TENANT)
    other_company = h._company(OTHER_TENANT, other_conn.id, database="OTHER_DB")
    res = h.link_split(company_id=other_company.id)
    assert res.outcome == "refused" and res.error_code == "WRITE_DISABLED"
    h.no_http()


def test_ac_55_45_other_tenants_connection_is_never_used(h):
    other_conn = h._connection(DB3, OTHER_TENANT)
    h.company.write_connection_id = other_conn.id
    h.db.commit()
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "WRITE_DISABLED"
    assert h.factory_urls == []
    h.no_http()


def test_ac_55_02_non_db3_book_refused_zero_requests_and_recorded(h):
    db1 = h._connection(DB1, DEFAULT_TENANT_ID)
    h.company.write_connection_id = db1.id
    h.db.commit()
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "WRITE_NOT_ALLOWED"
    h.no_http()
    row = h.action(res)
    assert row.outcome == "refused" and row.error_code == "WRITE_NOT_ALLOWED"
    assert row.action == "link" and row.doc_key == 12008 and row.tenant_id == DEFAULT_TENANT_ID


# ---- step 4: busy -----------------------------------------------------------

def _seed_in_flight(h, doc_key: int) -> AcWriteAction:
    row = AcWriteAction(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, action="link", doc_type="PO",
        doc_key=doc_key, dtl_key=12017, outcome="in_flight", request_json={},
    )
    h.db.add(row)
    h.db.commit()
    return row


def test_ac_55_26_open_action_same_doc_is_doc_busy(h):
    _seed_in_flight(h, 12008)
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY"
    h.no_http()


def test_ac_55_26_open_action_other_doc_does_not_block(h):
    _seed_in_flight(h, 99999)
    res = h.link_split()
    assert res.outcome == "done", res.error_code


# ---- step 5: staged date ------------------------------------------------------

def test_ac_55_20_unstaged_doc_is_doc_unknown(h):
    res = h.link_split(po_doc_key=77777)
    assert res.outcome == "refused" and res.error_code == "DOC_UNKNOWN"
    h.no_http()


def test_ac_55_20_get_uses_staged_docdate(h):
    h.link_split()
    queries = {str(r.url.params.get("DocDate")) for r in h.ac.get_calls}
    assert "20260204" in queries  # PO DocDate 2026-02-04
    assert "20260126" in queries  # SO DocDate
    assert all(r.method == "GET" for r in h.ac.get_calls)


# ---- step 6: stale ------------------------------------------------------------

def test_ac_55_21_stale_document_refused_no_put(h):
    res = h.link_split(expected_last_modified="2020-01-01T00:00:00.00")
    assert res.outcome == "refused" and res.error_code == "DOC_STALE"
    assert h.ac.put_calls == []


def test_ac_55_21_matching_last_modified_proceeds(h):
    lm = h.ac.docs["purchaseorderbydocdate"][0]["LastModified"]
    res = h.link_split(expected_last_modified=lm)
    assert res.outcome == "done", res.error_code


# ---- step 7: payload refusals --------------------------------------------------

def test_ac_55_13_item_mismatch_surfaces_refused_no_put(h):
    res = h.link_split(po_dtl_key=12009)  # SRTKS7090 row vs SRTKT38SS SO row 11989
    assert res.outcome == "refused" and res.error_code == "ITEM_MISMATCH"
    assert h.ac.put_calls == []
    assert h.action(res).outcome == "refused"


def test_ac_55_13_already_linked_surfaces_refused(h):
    res = h.link_split(po_dtl_key=12011, so_dtl_key=11990, qty=Decimal(1))
    assert res.outcome == "refused" and res.error_code == "ROW_ALREADY_LINKED"
    assert h.ac.put_calls == []


def test_ac_55_13_so_row_already_covered_by_staged_po_rows(h):
    # SO row 11996 qty 9 is covered 9/9 by staged PO row 12015 (FromSODtlKey 11996)
    res = h.link_split(po_dtl_key=12009, so_dtl_key=11996, qty=Decimal(1))
    assert res.outcome == "refused" and res.error_code == "QTY_ABOVE_OUTSTANDING"
    assert h.ac.put_calls == []


def test_ac_55_15_spo_row_pointing_at_po_row_blocks_link(h):
    h.stage_spo_pointing_at(12017)
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "ROW_ON_SPO"
    assert h.ac.put_calls == []


def test_ac_55_15_spo_blocks_unlink(h):
    h.stage_spo_pointing_at(12013)
    res = h.service().unlink(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=12008, po_dtl_key=12013
    )
    assert res.outcome == "refused" and res.error_code == "ROW_ON_SPO"
    assert h.ac.put_calls == []


# ---- step 8: PUT shape + vendor error -----------------------------------------

def test_ac_55_20_put_goes_to_edit_endpoint_with_s2_body(h):
    from modules.autocount.write_back.payloads import build_link

    po = h.ac.docs["purchaseorderbydocdate"][0]
    so = h.ac.docs["salesorderbydocdate"][0]
    expected = build_link(copy.deepcopy(po), 12017, so, 11989, Decimal(10))
    res = h.link_split()
    assert res.outcome == "done", res.error_code
    assert len(h.ac.put_calls) == 1
    assert h.ac.put_calls[0].method == "PUT"
    assert h.ac.put_calls[0].url.path.endswith(PUT_PATH)
    assert h.ac.put_bodies[0] == json.loads(json.dumps(expected))
    h.clean()


def test_ac_55_24_vendor_error_recorded_and_staged_unchanged(h):
    before = copy.deepcopy(h.staged_po().raw_json)
    h.ac.put_mode = "vendor_error"
    res = h.link_split()
    assert res.outcome == "vendor_error"
    row = h.action(res)
    assert row.outcome == "vendor_error" and row.response_status == 400
    assert "vendor says no" in json.dumps(row.response_json)
    assert h.staged_po().raw_json == before
    assert h.sink_calls == []


# ---- step 9: timeout ------------------------------------------------------------

def test_ac_55_05_timeout_is_pending_verification_and_never_retried(h):
    h.ac.put_mode = "timeout"
    res = h.link_split()
    assert res.outcome == "pending_verification"
    assert res.outcome != "done"
    assert len(h.ac.put_calls) == 1
    assert h.action(res).outcome == "pending_verification"
    assert h.sink_calls == []


def test_ac_55_23_readback_failure_is_pending_not_done(h):
    h.ac.get_fail_after_put = True
    before = copy.deepcopy(h.staged_po().raw_json)
    res = h.link_split()
    assert res.outcome == "pending_verification"
    assert len(h.ac.put_calls) == 1
    assert h.staged_po().raw_json == before
    assert h.sink_calls == []


# ---- step 10: fetch-back verification ---------------------------------------------

def test_ac_55_22_untouched_row_changed_is_mismatch(h):
    h.ac.put_mode = "corrupt_untouched"
    res = h.link_split()
    assert res.outcome == "mismatch"
    row = h.action(res)
    assert row.outcome == "mismatch"
    assert row.request_json == h.ac.put_bodies[0]
    assert row.after_json is not None
    assert "ELSEWHERE" in json.dumps(row.after_json)
    assert h.sink_calls == []


def test_ac_55_22_put_accepted_but_intended_state_missing_is_mismatch(h):
    h.ac.put_mode = "ignore"
    res = h.link_split()
    assert res.outcome == "mismatch"
    assert h.sink_calls == []


# ---- step 11: done ----------------------------------------------------------------

def test_ac_55_22_link_split_done_and_readback_rows(h):
    res = h.link_split()
    assert res.outcome == "done" and res.error_code is None
    doc = res.document
    rows = {r["DtlKey"]: r for r in doc["Details"]}
    assert Decimal(str(rows[12017]["Qty"])) == 40 and rows[12017]["Location"] == "HQ"
    new = [r for r in doc["Details"] if r["DtlKey"] not in (12009, 12011, 12013, 12015, 12017)]
    assert len(new) == 1
    assert Decimal(str(new[0]["Qty"])) == 10 and new[0]["Location"] == "BRW-AM"
    assert new[0]["FromSODtlKey"] == 11989
    for k in (12011, 12013, 12015):
        assert rows[k]["FromSODtlKey"] in (11990, 11993, 11996)


def test_ac_55_20_done_stores_only_the_second_get(h):
    res = h.link_split()
    assert res.outcome == "done"
    raw = h.staged_po().raw_json
    server = h.ac.docs["purchaseorderbydocdate"][0]
    expected = {k: v for k, v in server.items() if k != "Details"}
    expected["_lines"] = server["Details"]
    assert raw == json.loads(json.dumps(expected))
    assert len(h.ac.get_calls) >= 3  # PO + SO before, PO after


def _make_po_sql_sourced(h):
    h.db.add(AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="purchase_order",
        source_impl=SOURCE_IMPL_SQL_DB, etl_status="active", delivery_mode="push", source_config={},
    ))
    h.db.commit()


def _assert_staged_readback_queued_for_remap(h, res):
    # SQL-sourced PO: wrapper push skipped; push pinned in S4
    row = h.staged_po()
    server = h.ac.docs["purchaseorderbydocdate"][0]
    expected = {k: v for k, v in server.items() if k != "Details"}
    expected["_lines"] = server["Details"]
    assert row.raw_json == json.loads(json.dumps(expected))
    assert row.canonical_json is None
    assert row.status == STAGED
    assert len(h.sink_calls) == 0


def test_ac_55_25_done_stages_readback_for_remap(h):
    _make_po_sql_sourced(h)
    res = h.link_split()
    assert res.outcome == "done"
    _assert_staged_readback_queued_for_remap(h, res)


def test_ac_55_12_unlink_done(h):
    _make_po_sql_sourced(h)
    res = h.service().unlink(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=12008, po_dtl_key=12013
    )
    assert res.outcome == "done", res.error_code
    body = h.ac.put_bodies[0]
    assert [r["DtlKey"] for r in body["Details"]] == [12013]
    rows = {r["DtlKey"]: r for r in res.document["Details"]}
    assert rows[12013]["FromSODtlKey"] == 0
    assert rows[12013]["FromDocType"] == ""
    assert Decimal(str(rows[12013]["Qty"])) == 10 and rows[12013]["Location"] == "HQ"
    assert rows[12011]["FromSODtlKey"] == 11990
    _assert_staged_readback_queued_for_remap(h, res)
    assert h.action(res).action == "unlink"


def test_ac_55_15_spo_unlink_done(h):
    spo = _load("spo_db1_sample.json")
    spo["Details"][0]["FromDocType"] = "PO"
    spo["Details"][0]["FromDocDtlKey"] = 12013
    h.stage_spo_pointing_at(12013)
    h.ac.serve("purchaseorderbydocdate", spo)
    # the fake applies edits against the SPO doc too; link fields cleared by the body
    dtl = spo["Details"][0]["DtlKey"]
    original_apply = h.ac._apply

    def apply(body):
        for d in h.ac.docs["purchaseorderbydocdate"]:
            if d["DocKey"] == body["DocKey"]:
                for r in body["Details"]:
                    next(x for x in d["Details"] if x["DtlKey"] == r["DtlKey"]).update(r)
                d["LastModified"] = "2026-11-05T09:00:00.00"
                return
        original_apply(body)

    h.ac._apply = apply
    res = h.service().spo_unlink(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, spo_doc_key=spo["DocKey"], spo_dtl_key=dtl
    )
    assert res.outcome == "done", res.error_code
    row = h.action(res)
    assert row.action == "spo_unlink" and row.doc_type == "SPO" and row.doc_key == spo["DocKey"]


# ---- step 12-13: transactions + record ---------------------------------------------

def test_ac_55_27_no_transaction_open_and_in_flight_committed_before_put(h):
    res = h.link_split()
    assert res.outcome == "done"
    assert h.ac.violations == []
    assert h.ac.in_flight_seen_at_put == [1]
    assert len(h.ac.get_calls) >= 1 and len(h.ac.put_calls) == 1


def test_ac_55_27_no_transaction_open_on_timeout_path(h):
    h.ac.put_mode = "timeout"
    h.link_split()
    assert h.ac.violations == []
    assert h.ac.in_flight_seen_at_put == [1]


def test_ac_55_28_action_row_fields_and_request_equals_body_sent(h):
    res = h.link_split()
    row = h.action(res)
    assert row.tenant_id == DEFAULT_TENANT_ID and row.company_id == h.company.id
    assert row.action == "link" and row.doc_type == "PO"
    assert row.doc_key == 12008 and row.dtl_key == 12017
    assert row.outcome == "done" and row.error_code is None
    assert row.request_json == h.ac.put_bodies[0]
    assert row.response_status == 200
    assert row.before_json and row.after_json
    assert row.created_at is not None and row.updated_at is not None
    assert row.key_id is None


def test_ac_55_28_key_id_is_recorded(h):
    res = h.link_split(key_id="key-123")
    assert h.action(res).key_id == "key-123"


def test_ac_55_04_no_credential_in_the_action_row(h):
    res = h.link_split()
    row = h.action(res)
    dump = json.dumps(
        {c.name: getattr(row, c.name) for c in AcWriteAction.__table__.columns}, default=str
    )
    for secret in SECRETS.values():
        assert secret not in dump
    assert "password" not in dump.lower()
    refused = h.action(h.link_split(po_dtl_key=12009))
    dump2 = json.dumps(
        {c.name: getattr(refused, c.name) for c in AcWriteAction.__table__.columns}, default=str
    )
    for secret in SECRETS.values():
        assert secret not in dump2


def test_ac_55_28_actions_are_tenant_scoped_rows(h):
    res = h.link_split()
    rows = h.db.query(AcWriteAction).filter(AcWriteAction.tenant_id == OTHER_TENANT).all()
    assert rows == []
    assert h.action(res).tenant_id == DEFAULT_TENANT_ID


# ---- reader contract (S3 interface) --------------------------------------------------

def _reader(handler):
    return AutoCountDocReader(DB3, transport=httpx.MockTransport(handler))


def test_ac_55_20_reader_gets_by_docdate_and_filters_on_dockey():
    seen: List[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[{"DocKey": 1, "DocNo": "A"}, {"DocKey": 2, "DocNo": "B"}])

    doc = _reader(handler).get_document("PO", 2, date(2026, 2, 4))
    assert doc["DocNo"] == "B"
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/api/db3/purchaseorderbydocdate"
    assert seen[0].url.params["DocDate"] == "20260204"


def test_ac_55_20_reader_so_path_and_errors():
    from modules.autocount.write_back.reader import DocReadError

    seen: List[httpx.Request] = []

    def ok(request):
        seen.append(request)
        return httpx.Response(200, json=[{"DocKey": 1}])

    _reader(ok).get_document("SO", 1, date(2026, 1, 26))
    assert seen[0].url.path == "/api/db3/salesorderbydocdate"

    def run(handler):
        with pytest.raises(DocReadError) as ei:
            _reader(handler).get_document("PO", 1, date(2026, 2, 4))
        return ei.value.code

    assert run(lambda r: httpx.Response(200, json=[{"DocKey": 9}])) == "DOC_NOT_FOUND"
    assert run(lambda r: httpx.Response(200, json=[{"DocKey": 1}, {"DocKey": 1}])) == "DOC_AMBIGUOUS"
    assert run(lambda r: httpx.Response(500, text="x")) == "READ_FAILED"
    assert run(lambda r: httpx.Response(200, text="not json")) == "READ_FAILED"
