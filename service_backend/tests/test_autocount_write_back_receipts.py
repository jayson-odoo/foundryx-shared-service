"""Plan 57 (RED): received / delivered qty comes from the SQL sync, and write-back never
wipes SQL staging (AC-57-33, owner note: the quantities already exist at PO and SO line level).

Default receipt reader order (``OperationService`` with no ``receipt_reader``, and the
primitive delete guard for SO rows):
  1. the fresh GET row's ``TransferedQty`` when present;
  2. else, when the company's entity config for that document type has
     ``source_impl == "sql_db"``, the staged canonical line's ``qty_received`` (PO / SPO) or
     ``qty_delivered`` (SO), found by line ``source_ref`` ``{db}:{DocKey}:{DtlKey}`` on the
     newest staged row of ``{db}:{DocKey}``;
  3. else unknown: the operation proceeds with warning ``TRANSFER_STATE_UNKNOWN`` and
     AutoCount decides.
Staging: a confirmed write-back on a document whose entity source is ``sql_db`` leaves the
SQL-staged row's ``canonical_json`` (and its lines' qty) untouched; an HTTP-sourced
document keeps plan 55 behaviour (restaged and pushed).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import SOURCE_IMPL_SQL_DB, AcEntityConfig, AcStagedRecord
from tests.test_autocount_write_back_operations import (  # noqa: F401
    DEL_PO,
    PUT_PO,
    OpHarness,
    World,
    db,
    h,
)
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401
from tests.write_back_live_books import live_books_open  # noqa: F401

pytestmark = pytest.mark.usefixtures("live_books_open")

ENTITY = {"PO": "purchase_order", "SPO": "shipping_order", "SO": "sales_order"}
QTY_FIELD = {"purchase_order": "qty_received", "shipping_order": "qty_received", "sales_order": "qty_delivered"}


def set_source(h: OpHarness, entity: str, impl: str) -> None:
    h.db.add(AcEntityConfig(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type=entity,
                            source_impl=impl))
    h.db.commit()


def staged(h: OpHarness, entity: str, doc_key: int) -> AcStagedRecord:
    h.db.expire_all()
    return (h.db.query(AcStagedRecord)
            .filter(AcStagedRecord.company_id == h.company.id, AcStagedRecord.entity_type == entity,
                    AcStagedRecord.source_ref == f"AED_TEST:{doc_key}").one())


def seed_canonical(h: OpHarness, entity: str, doc_key: int, qty_by_dtl: Dict[int, Any]) -> Dict[str, Any]:
    """Give the staged row the canonical_json a SQL sync leaves: lines with the qty."""
    row = staged(h, entity, doc_key)
    canonical = {"sourceRef": f"AED_TEST:{doc_key}", "lines": [
        {"source_ref": f"AED_TEST:{doc_key}:{dtl}", QTY_FIELD[entity]: qty} for dtl, qty in qty_by_dtl.items()]}
    row.canonical_json = canonical
    h.db.commit()
    return copy.deepcopy(canonical)


def sql_world(h: OpHarness, received: Optional[Any], *, so_qty=50, po_qty=35, source=SOURCE_IMPL_SQL_DB,
              **kw) -> World:
    h.delete_on()
    w = World(h, po_over={"Qty": po_qty}, so_qty=so_qty, **kw)
    if source:
        set_source(h, "purchase_order", source)
    if received is not None:
        seed_canonical(h, "purchase_order", 7001, {w.p_free: received, w.p_linked: 0})
    return w


def run_link(h: OpHarness, w: World, **kw):
    return h.run("link_row", w.params["link_row"], receipt_reader="default", **kw)


# ---- (1) the default reader ---------------------------------------------------------------------

def test_ac_57_33_sql_staged_zero_received_proceeds_without_warning_on_the_delete_path(h):
    w = sql_world(h, 0)
    res = run_link(h, w)
    assert res.outcome == "done", res.error_code
    assert "TRANSFER_STATE_UNKNOWN" not in res.warnings
    assert DEL_PO in h.steps()


def test_ac_57_33_sql_staged_partial_receipt_cuts_and_adds_the_remainder_without_delete(h):
    w = sql_world(h, 20)
    res = run_link(h, w)
    assert res.outcome == "done", res.error_code
    assert "TRANSFER_STATE_UNKNOWN" not in res.warnings
    assert DEL_PO not in h.steps() and h.steps()[:2] == [PUT_PO, PUT_PO]
    cut, add = h.vendor.writes()[:2]
    assert cut.body["Details"][0]["DtlKey"] == w.p_free and cut.body["Details"][0]["Qty"] == 20
    assert add.body["Details"][0]["Qty"] == 15 and add.body["Details"][0]["FromDocDtlKey"] == w.so_a
    assert w.row_by_key(w.po_rows(), w.p_free)["Qty"] == 20


def test_ac_57_33_sql_staged_full_receipt_is_row_received_with_no_write(h):
    w = sql_world(h, 35)
    res = run_link(h, w)
    assert res.outcome == "refused" and res.error_code == "ROW_RECEIVED"
    assert h.vendor.writes() == []


def test_ac_57_33_sql_source_without_a_staged_line_is_unknown_with_warning(h):
    w = sql_world(h, None)  # entity is sql_db, the staged canonical has no such line
    res = run_link(h, w)
    assert res.outcome == "done" and "TRANSFER_STATE_UNKNOWN" in res.warnings
    assert DEL_PO in h.steps()


def test_ac_57_33_sql_staged_line_with_a_null_qty_is_unknown(h):
    w = sql_world(h, None)
    seed_canonical(h, "purchase_order", 7001, {w.p_free: None})
    res = run_link(h, w)
    assert res.outcome == "done" and "TRANSFER_STATE_UNKNOWN" in res.warnings


@pytest.mark.parametrize("source", ["autocount_read", None])
def test_ac_57_33_http_sourced_company_is_unknown_even_if_canonical_lines_exist(h, source):
    w = sql_world(h, 35, source=source)  # a decoy full receipt that must be ignored
    res = run_link(h, w)
    assert res.outcome == "done" and "TRANSFER_STATE_UNKNOWN" in res.warnings
    assert DEL_PO in h.steps()


def test_ac_57_33_the_get_rows_transfered_qty_beats_the_sql_staging(h):
    w = sql_world(h, 35, po_qty=35)
    row = next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == w.p_free)
    row["TransferedQty"] = 0  # AutoCount says nothing received; SQL staging says all
    res = run_link(h, w)
    assert res.outcome == "done" and "TRANSFER_STATE_UNKNOWN" not in res.warnings
    assert DEL_PO in h.steps()


def test_ac_57_33_a_full_get_transfered_qty_beats_a_zero_in_sql_staging(h):
    w = sql_world(h, 0, po_qty=35)
    next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == w.p_free)["TransferedQty"] = 35
    res = run_link(h, w)
    assert res.outcome == "refused" and res.error_code == "ROW_RECEIVED"
    assert h.vendor.writes() == []


def test_ac_57_33_staged_line_is_matched_by_dtlkey_not_by_position(h):
    w = sql_world(h, None)
    seed_canonical(h, "purchase_order", 7001, {w.p_linked: 35, w.p_other: 35, w.p_free: 0})
    res = run_link(h, w)
    assert res.outcome == "done" and "TRANSFER_STATE_UNKNOWN" not in res.warnings


def test_ac_57_33_newest_staged_row_of_the_document_is_the_one_read(h):
    w = sql_world(h, 35)
    stale = staged(h, "purchase_order", 7001)
    newer = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="purchase_order", job_id="job-2",
        source_ref="AED_TEST:7001", doc_no=stale.doc_no, raw_json=stale.raw_json, status="staged",
        canonical_json={"sourceRef": "AED_TEST:7001", "lines": [
            {"source_ref": f"AED_TEST:7001:{w.p_free}", "qty_received": 0}]})
    h.db.add(newer)
    h.db.commit()
    stale.created_at = stale.created_at.replace(year=2020)
    h.db.commit()
    res = run_link(h, w)
    assert res.outcome == "done" and "TRANSFER_STATE_UNKNOWN" not in res.warnings


def test_ac_57_33_other_tenants_or_companys_staging_is_never_read(h):
    w = sql_world(h, None)
    other = AcStagedRecord(
        tenant_id="other-tenant-id", company_id=h.company.id, entity_type="purchase_order", job_id="j",
        source_ref="AED_TEST:7001", doc_no="x", raw_json={}, status="staged",
        canonical_json={"lines": [{"source_ref": f"AED_TEST:7001:{w.p_free}", "qty_received": 35}]})
    h.db.add(other)
    h.db.commit()
    res = run_link(h, w)
    assert res.outcome == "done" and "TRANSFER_STATE_UNKNOWN" in res.warnings


def test_ac_57_33_spo_rows_read_the_shipping_order_staging(h):
    h.delete_on()
    w = World(h)
    set_source(h, "shipping_order", SOURCE_IMPL_SQL_DB)
    seed_canonical(h, "shipping_order", 7003, {w.s_linked: 4})  # fully received SPO row (qty 4)
    res = h.run("spo_unlink_row", w.params["spo_unlink_row"], receipt_reader="default")
    assert res.outcome == "refused" and res.error_code == "ROW_RECEIVED"
    assert h.vendor.writes() == []


def test_ac_57_33_so_line_delete_with_sql_qty_delivered_is_row_received(h):
    h.flag("SO", "delete_line", True)
    doc = h.seed_doc("SO", 5001, [_line("A", 10, 5.0), _line("B", 4, 6.0, "BR1")])
    keys = [r["DtlKey"] for r in doc["Details"]]
    set_source(h, "sales_order", SOURCE_IMPL_SQL_DB)
    seed_canonical(h, "sales_order", 5001, {keys[0]: 3, keys[1]: 0})
    res = h.service().delete_line(**h.args("SO", doc_key=5001, dtl_key=keys[0]))
    assert res.outcome == "refused" and res.error_code == "ROW_RECEIVED"
    assert h.vendor.writes() == []
    ok = h.service().delete_line(**h.args("SO", doc_key=5001, dtl_key=keys[1]))
    assert ok.outcome == "done", ok.error_code


def test_ac_57_33_so_line_delete_for_an_http_sourced_company_is_left_to_autocount(h):
    h.flag("SO", "delete_line", True)
    doc = h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    key = doc["Details"][0]["DtlKey"]
    seed_canonical(h, "sales_order", 5001, {key: 3})  # no sql_db config: ignored
    res = h.service().delete_line(**h.args("SO", doc_key=5001, dtl_key=key))
    assert res.outcome == "done", res.error_code


# ---- (2) staging never wipes the SQL sync ------------------------------------------------------------

def test_ac_57_33_operation_on_a_sql_sourced_po_leaves_the_staged_canonical_untouched(h):
    w = sql_world(h, 0)
    before = staged(h, "purchase_order", 7001).canonical_json
    res = run_link(h, w)
    assert res.outcome == "done", res.error_code
    after = staged(h, "purchase_order", 7001)
    assert after.canonical_json == before
    line = next(l for l in after.canonical_json["lines"] if l["source_ref"].endswith(f":{w.p_linked}"))
    assert line["qty_received"] == 0


def test_ac_57_33_primitive_edit_on_a_sql_sourced_so_leaves_qty_delivered(h):
    doc = h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    key = doc["Details"][0]["DtlKey"]
    set_source(h, "sales_order", SOURCE_IMPL_SQL_DB)
    before = seed_canonical(h, "sales_order", 5001, {key: 7})
    res = h.edit("SO", 5001, {"Remark1": "x"})
    assert res.outcome == "done", res.error_code
    after = staged(h, "sales_order", 5001)
    assert after.canonical_json == before and after.canonical_json["lines"][0]["qty_delivered"] == 7


def test_ac_57_33_add_line_on_a_sql_sourced_po_leaves_the_staged_canonical_untouched(h):
    w = sql_world(h, 5)
    before = staged(h, "purchase_order", 7001).canonical_json
    res = h.service().add_line(**h.args("PO", doc_key=7001, line=_line("C", 1, 3.0)))
    assert res.outcome == "done", res.error_code
    assert staged(h, "purchase_order", 7001).canonical_json == before
    assert w  # world kept alive


def test_ac_57_33_http_sourced_document_keeps_plan_55_staging_restaged_and_pushed(h):
    h.delete_on()
    doc = h.seed_doc("PO", 7001, [_line("A", 4, 5.0)])
    seed_canonical(h, "purchase_order", 7001, {doc["Details"][0]["DtlKey"]: 1})
    res = h.edit("PO", 7001, {"Remark1": "restaged"})
    assert res.outcome == "done", res.error_code
    row = staged(h, "purchase_order", 7001)
    assert row.raw_json["Remark1"] == "restaged"
    assert row.canonical_json is not None and row.canonical_json != {"sourceRef": "AED_TEST:7001"}
    assert row.status == "pushed" or row.pushed_at is not None
    assert h.sink_calls, "an HTTP-sourced write-back read-back goes out through the sink"
