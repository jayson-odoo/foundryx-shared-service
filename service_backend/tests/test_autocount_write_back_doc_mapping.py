"""Plan 55 S4: wrapper document mapping + post-write push (AC-55-25, 30, 31).

Mapping tests call ``map_wrapper_document`` directly. Push tests drive the
real ``WriteBackService`` over the S3 fake wrapper. A company pushes after a
confirmed write UNLESS it has an entity config for that doc's entity type with
``source_impl`` ``sql_db`` (no config at all = push: the write connection is
then the only PO source).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.masters import (
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT,
    ENTITY_SUPPLIER,
    ENTITY_WAREHOUSE,
)
from modules.autocount.mapping import flat_source_ref
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    STAGED,
    STAGED_PUSHED,
    AcEntityConfig,
    AcStagedRecord,
)
from modules.autocount.sinks import WriteResult
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back.doc_mapping import map_wrapper_document
from modules.autocount.write_back.reader import AutoCountDocReader
from modules.autocount.write_back.service import WriteBackService
from tests.test_autocount_write_back_service import DBNAME, Harness, _load

PO_DOC_KEY = 12008


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


def _master(value: str, key_col: str, entity: str) -> str:
    return flat_source_ref(
        {key_col: value}, database_name=DBNAME, key_columns=[key_col], entity_type=entity
    )


def _so_doc() -> Dict[str, Any]:
    doc = _load("so_SO389293.json")
    doc.update(DebtorCode="300-C001", DebtorName="Example Customer", Cancelled="F")
    return doc


def _spo_doc() -> Dict[str, Any]:
    return _load("spo_db1_sample.json")


def _src_po_for_spo() -> Dict[str, Any]:
    spo = _spo_doc()
    rows = []
    for r in spo["Details"]:
        rows.append({
            "DtlKey": r["FromDocDtlKey"], "ItemCode": r["ItemCode"], "Location": r["Location"],
            "Qty": 26.0, "UOM": "UNIT", "UserUOM": "UNIT", "FromDocType": "", "FromDocNo": "",
            "FromDocDtlKey": 0, "FromSODtlKey": 0, "FromSODocList": "", "UnitPrice": 1.0,
        })
    po = _load("po_202602_S0007.json")
    po = {k: v for k, v in po.items() if k != "Details"}
    po.update(DocKey=45981200, DocNo="202610-S0024", Details=rows)
    return po


def _line(rec, dtl_key: int):
    return next(l for l in rec.lines if l.source_ref.endswith(f":{dtl_key}"))


def _map(h, doc, **kw):
    return map_wrapper_document(
        h.db, tenant_id=DEFAULT_TENANT_ID, company=h.company, doc=doc, **kw
    )


# ---- entity type + identity -------------------------------------------------

def test_ac_55_30_po_maps_to_purchase_order_with_identity(h):
    entity, rec = _map(h, _load("po_202602_S0007.json"))
    assert entity == "purchase_order"
    assert rec.source_ref == f"{DBNAME}:{PO_DOC_KEY}"
    assert rec.po_number == "202602-S0007"
    assert rec.supplier_ref == _master("400-N004", "AccNo", ENTITY_SUPPLIER)
    line = _line(rec, 12017)
    assert line.source_ref == f"{DBNAME}:{PO_DOC_KEY}:12017"
    assert line.product_ref == _master("SRTKT38SS", "ItemCode", ENTITY_PRODUCT)
    assert line.warehouse_ref == _master("HQ", "Location", ENTITY_WAREHOUSE)


def test_ac_55_30_spo_header_shipping_po_t_maps_to_shipping_order(h):
    entity, rec = _map(h, _spo_doc())
    assert entity == "shipping_order"
    assert rec.source_ref == f"{DBNAME}:46178924"
    assert rec.spo_number == "SPO-2026/11-0001"


def test_ac_55_30_so_maps_to_sales_order_with_customer_ref(h):
    entity, rec = _map(h, _so_doc())
    assert entity == "sales_order"
    assert rec.source_ref == f"{DBNAME}:11988"
    assert rec.so_number == "SO389293"
    assert rec.customer_ref == _master("300-C001", "AccNo", ENTITY_CUSTOMER)
    line = _line(rec, 11989)
    assert line.product_ref == _master("SRTKT38SS", "ItemCode", ENTITY_PRODUCT)
    assert line.warehouse_ref == _master("BRW-AM", "Location", ENTITY_WAREHOUSE)
    # blank-item zero-qty spacer rows (11991, 11994) are skipped, as the SQL path's WHERE does
    assert len(rec.lines) == 6


def test_ac_55_30_explicit_kind_overrides_detection(h):
    so = _so_doc()
    so.pop("DebtorCode")
    entity, _rec = _map(h, so, kind="SO")
    assert entity == "sales_order"


def test_ac_55_30_qty_is_decimal_exact(h):
    po = _load("po_202602_S0007.json")
    for r in po["Details"]:
        if r["DtlKey"] == 12017:
            r["Qty"] = 3.3
    _entity, rec = _map(h, po)
    q = _line(rec, 12017).qty_ordered
    assert isinstance(q, Decimal) and q == Decimal("3.3")


def test_ac_55_30_cancelled_doc_maps_to_cancelled_status(h):
    po = _load("po_202602_S0007.json")
    po["Cancelled"] = "T"
    _entity, rec = _map(h, po)
    assert rec.status == "cancelled"


# ---- AC-55-31 link resolution --------------------------------------------------

def test_ac_55_31_po_row_resolves_so_line_ref_through_staged_so(h):
    _entity, rec = _map(h, _load("po_202602_S0007.json"))
    line = _line(rec, 12011)  # FromSODtlKey 11990, FromSODocList SO389293, SO DocKey 11988
    assert line.from_so_line_ref == f"{DBNAME}:11988:11990"
    assert line.from_so_numbers == ["SO389293"]
    unlinked = _line(rec, 12017)
    assert unlinked.from_so_line_ref is None
    assert not unlinked.from_so_numbers


def test_ac_55_31_unstaged_so_keeps_numbers_drops_ref_no_exception(h):
    h.db.query(AcStagedRecord).filter(AcStagedRecord.entity_type == "sales_order").delete()
    h.db.commit()
    _entity, rec = _map(h, _load("po_202602_S0007.json"))
    line = _line(rec, 12011)
    assert line.from_so_line_ref is None
    assert line.from_so_numbers == ["SO389293"]


def test_ac_55_31_spo_row_resolves_po_line_ref_through_staged_po(h):
    h._stage("purchase_order", _src_po_for_spo())
    _entity, rec = _map(h, _spo_doc())
    line = _line(rec, 46179075)
    assert line.from_po_line_ref == f"{DBNAME}:45981200:45981239"
    assert line.from_po_number == "202610-S0024"
    other = _line(rec, 46179077)
    assert other.from_po_line_ref == f"{DBNAME}:45981200:45981240"


def test_ac_55_31_unresolved_spo_po_ref_keeps_number(h):
    _entity, rec = _map(h, _spo_doc())  # no source PO staged
    line = _line(rec, 46179075)
    assert line.from_po_line_ref is None
    assert line.from_po_number == "202610-S0024"


# ---- post-write push (AC-55-25) --------------------------------------------------

def _add_config(h, source_impl):
    h.db.add(AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="purchase_order",
        source_impl=source_impl, etl_status="active", delivery_mode="push", source_config={},
    ))
    h.db.commit()


def _service(h, sink):
    return WriteBackService(
        h.db,
        client_factory=lambda url: AutoCountWriteClient(url, transport=h.ac.write_transport),
        reader_factory=lambda url: AutoCountDocReader(url, transport=h.ac.read_transport),
        sink_factory=lambda *a, **k: sink,
    )


class _Sink:
    name = "fake"

    def __init__(self, mode="ok"):
        self.mode = mode
        self.records: List[Any] = []

    def write(self, record, *, request_id=""):
        self.records.append(record)
        if self.mode == "raise":
            raise RuntimeError("sink down")
        if self.mode == "reject":
            return WriteResult(ok=False, sink="fake", message="no", outcome="failed")
        return WriteResult(ok=True, sink="fake", delivered=True, outcome="delivered")


def _link(h, svc):
    return svc.link(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=PO_DOC_KEY,
        po_dtl_key=12017, so_doc_key=11988, so_dtl_key=11989, qty=Decimal(10),
    )


def test_ac_55_25_done_maps_and_pushes_once_and_marks_pushed(h):
    sink = _Sink()
    res = _link(h, _service(h, sink))
    assert res.outcome == "done", res.error_code
    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec.source_ref == f"{DBNAME}:{PO_DOC_KEY}"
    assert any(l.qty_ordered == Decimal(10) and l.warehouse_ref == _master("BRW-AM", "Location", ENTITY_WAREHOUSE) for l in rec.lines)
    row = h.staged_po()
    assert row.status == STAGED_PUSHED
    assert row.canonical_json is not None


def test_ac_55_25_mapping_failure_still_done_row_stays_staged_no_push(h):
    h.ac.docs["purchaseorderbydocdate"][0]["Details"][0]["ItemCode"] = ""  # row 12009 has qty 1
    sink = _Sink()
    res = _link(h, _service(h, sink))
    assert res.outcome == "done", res.error_code
    assert sink.records == []
    assert h.staged_po().status == STAGED


@pytest.mark.parametrize("mode", ["raise", "reject"])
def test_ac_55_25_sink_failure_still_done_row_stays_staged(h, mode):
    sink = _Sink(mode)
    res = _link(h, _service(h, sink))
    assert res.outcome == "done", res.error_code
    assert h.staged_po().status == STAGED


def test_ac_55_25_sql_db_company_gets_no_wrapper_mapping_and_no_push(h):
    _add_config(h, SOURCE_IMPL_SQL_DB)
    sink = _Sink()
    res = _link(h, _service(h, sink))
    assert res.outcome == "done", res.error_code
    assert sink.records == []
    row = h.staged_po()
    assert row.status == STAGED
    assert row.canonical_json is None


def test_ac_55_25_company_without_entity_config_pushes(h):
    sink = _Sink()
    res = _link(h, _service(h, sink))
    assert res.outcome == "done"
    assert len(sink.records) == 1
    assert h.staged_po().status == STAGED_PUSHED


def test_ac_55_25_sql_config_on_another_entity_does_not_block_po_push(h):
    h.db.add(AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="sales_order",
        source_impl=SOURCE_IMPL_SQL_DB, etl_status="active", delivery_mode="push", source_config={},
    ))
    h.db.commit()
    sink = _Sink()
    res = _link(h, _service(h, sink))
    assert res.outcome == "done"
    assert len(sink.records) == 1
