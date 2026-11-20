"""Plan 62 review round 2 (RED where noted): neutral regression tests.

(a) an unknown outcome is never released; (b) every batch route outcome carries ``links`` / ``freeLine``;
(c) the over-link index survives a cancelled delete intent and the backfill ignores delete intents;
(d) a pending unlink merge is only settled as landed when its quantities prove it;
(e) an operation settled as confirmed-not-landed by ``resume`` is released on a resend.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from typing import Any, List
from unittest import mock

import pytest

from app.main import app  # noqa: F401
from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import ENTITY_PURCHASE_ORDER
from modules.autocount.models import STAGED, STAGED_OP_DELETE, AcStagedRecord
from modules.autocount.write_back.primitives import PrimitiveResult
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code
from tests.test_autocount_write_back_link_batch import Rig, ROUTE
from tests.test_autocount_write_back_operations import KEY_ID, OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import DBNAME
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def replace_puts(h) -> List[Any]:
    return [c for c in puts(h) if any(r.get("FullTransferOption") == "D" for r in c.body["Details"])]


# ============================== (a) an unknown outcome is never released ========================

def test_r2a_operation_with_a_bare_vendor_failure_replays_the_stored_answer(h, monkeypatch):
    from modules.autocount.write_back import operations as ops_mod

    world = World(h)

    def fail(self, *a, **k):
        raise ops_mod._Done("vendor_error", "VENDOR_ERROR", "bare 5xx")

    monkeypatch.setattr(ops_mod.OperationService, "_steps_run", fail)
    first = h.run("link_row", world.params["link_row"], key="u-1")
    assert first.outcome == "vendor_error" and first.error_code == "VENDOR_ERROR"
    monkeypatch.undo()
    calls = len(h.vendor.calls)
    again = h.run("link_row", world.params["link_row"], key="u-1")
    assert again.outcome == "vendor_error" and again.error_code == "VENDOR_ERROR"
    assert again.operation_id == first.operation_id
    assert len(h.vendor.calls) == calls and h.vendor.writes() == []  # no blind re-PUT


def test_r2a_primitive_with_a_bare_vendor_failure_replays_the_stored_answer(h):
    ops = h.ops()
    calls: List[int] = []

    def call():
        calls.append(1)
        return PrimitiveResult(None, "vendor_error", "VENDOR_ERROR", "bare 5xx")

    args = dict(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=KEY_ID, idempotency_key="u-2",
                name="edit_doc", kind="PO", doc_key=7001, params={"a": 1}, call=call)
    first = ops.run_primitive(**args)
    again = ops.run_primitive(**args)
    assert first["outcome"] == again["outcome"] == "vendor_error" and again["errorCode"] == "VENDOR_ERROR"
    assert len(calls) == 1


# ============================== (b) batch answer wire ===========================================

@pytest.fixture
def rig(h):
    return Rig(h)


@pytest.fixture
def gw(h, db, rig):
    return Gw(h, db)


def assert_empty_batch_fields(r):
    body = r.json()
    assert "links" in body and body["links"] == [], body
    assert "freeLine" in body and body["freeLine"] is None, body


def test_r2b_refused_pre_check_carries_empty_links_and_a_null_free_line(client, h, gw, rig):
    h.vendor.find("SO", 7005)["Details"][0]["Qty"] = 2
    r = client.post(ROUTE, json=rig.body([(7005, rig.s5[0], 3)]), headers=gw.hdr("w-1"))
    assert r.status_code in (409, 422) and code(r) == "ALL_LINKS_SKIPPED"  # owner rule: the only line was skipped
    assert_empty_batch_fields(r)


def test_r2b_vendor_error_carries_empty_links_and_a_null_free_line(client, h, gw, rig):
    h.vendor.invalid_items = {"ITEM-A"}
    r = client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("w-2"))
    assert r.status_code == 502 and r.json()["outcome"] == "vendor_error"
    assert_empty_batch_fields(r)


def test_r2b_pending_carries_empty_links_and_a_null_free_line(client, h, gw, rig):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    r = client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("w-3"))
    assert r.status_code == 202 and r.json()["outcome"] == "pending_verification"
    assert_empty_batch_fields(r)


def test_r2b_idempotency_conflict_carries_empty_links_and_a_null_free_line(client, h, gw, rig):
    assert client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("w-4")).status_code == 200
    r = client.post(ROUTE, json=rig.body([(7005, rig.s5[0], 1)]), headers=gw.hdr("w-4"))
    assert code(r) == "IDEMPOTENCY_CONFLICT"
    assert_empty_batch_fields(r)


def test_r2b_a_replayed_pending_batch_carries_empty_links_and_a_null_free_line(client, h, gw, rig):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("w-5"))
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")  # the resend's PUT times out again
    r = client.post(ROUTE, json=rig.body(rig.three()), headers=gw.hdr("w-5"))
    assert r.json()["outcome"] in ("pending_verification", "needs_attention", "recovered", "done"), r.text
    assert "links" in r.json() and "freeLine" in r.json()


# ============================== (c) the index and a cancelled delete intent =====================

def _stage_po(h, ref, raw, op="upsert"):
    from modules.autocount.repositories.autocount_repository import StagedRecordRepository

    row = AcStagedRecord(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type=ENTITY_PURCHASE_ORDER,
                         job_id="sync-job", source_ref=ref, doc_no=None, raw_json=raw, status=STAGED, op=op)
    StagedRecordRepository(h.db).add(row)
    h.db.commit()
    return row


def _index(h, ref):
    from modules.autocount.models import AcPoSoLink

    h.db.expire_all()
    return sorted((r.so_dtl_key, Decimal(r.qty)) for r in h.db.query(AcPoSoLink).filter_by(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_source_ref=ref))


def test_r2c_a_cancelled_delete_intent_brings_the_pos_index_rows_back(h):
    from modules.autocount.repositories.autocount_repository import StagedRecordRepository
    from modules.autocount.write_back.link_index import refresh_po_links

    ref = f"{DBNAME}:8801"
    raw = {"DocKey": 8801, "_lines": [{"DtlKey": 1, "FromSODtlKey": 555, "Qty": 3}]}
    _stage_po(h, ref, raw)
    refresh_po_links(h.db, DEFAULT_TENANT_ID, h.company.id, ref)
    h.db.commit()
    assert _index(h, ref) == [(555, Decimal(3))]
    _stage_po(h, ref, None, op=STAGED_OP_DELETE)  # the delete intent wipes the rows (control)
    refresh_po_links(h.db, DEFAULT_TENANT_ID, h.company.id, ref, deleted=True)
    h.db.commit()
    assert _index(h, ref) == []
    # the PO reappears unchanged: the intent is cancelled without any new copy being staged
    StagedRecordRepository(h.db).discard_stale_deletes(DEFAULT_TENANT_ID, h.company.id, ENTITY_PURCHASE_ORDER, [ref])
    h.db.commit()
    assert _index(h, ref) == [(555, Decimal(3))]
    assert h.service()._so_linked_qty(h.company, 555) == Decimal(3)


def test_r2c_the_backfill_reads_the_newest_non_delete_copy(monkeypatch):
    """The migration's select must not let a CANCELLED (discarded) delete intent hide the PO's last real copy,
    and must not drop live delete intents by a blanket filter either (round 4 rule: newest non-discarded row,
    skipped when it is a live delete). The statement is captured and compiled for PostgreSQL."""
    path = next((Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic" / "versions").glob("0045_*.py"))
    spec = importlib.util.spec_from_file_location("mig_0045_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen: List[Any] = []

    class Rows(list):
        def yield_per(self, n):
            return iter(self)

    class Bind:
        class dialect:
            name = "postgresql"

        def execute(self, stmt, *a, **k):
            seen.append(stmt)
            return Rows()

    fake_op = mock.MagicMock()
    fake_op.get_bind.return_value = Bind()
    monkeypatch.setattr(mod, "op", fake_op)
    mod.upgrade()
    from sqlalchemy.dialects import postgresql

    selects = [s for s in seen if hasattr(s, "whereclause")]
    assert selects, "the backfill ran no select"
    sql = str(selects[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()
    where = sql.split("where", 1)[1]
    assert "discarded" in where, sql
    assert "order by" in sql and "created_at desc" in sql, sql


# ============================== (d) pending unlink merge reconcile ==============================

@pytest.fixture
def mworld(h):
    h.delete_on()
    w = World(h)
    h.vendor.find("PO", 7001)["Details"][1]["UnitPrice"] = 5.0  # the linked row matches the free rows: a merge
    return w


def pend_merge(h, w, key="mg-1"):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    res = h.run("unlink_row", w.params["unlink_row"], key=key)
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    assert len(puts(h)) == 1
    return res


def qty_of(h, key):
    row = next((r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == key), None)
    return None if row is None else Decimal(str(row["Qty"]))


def test_r2d_merge_pending_and_landed_is_done_with_no_second_put(h, mworld):
    pend_merge(h, mworld)
    h.vendor._edit("PO", puts(h)[0].body)  # linked row gone, free row 4 + 4
    assert qty_of(h, mworld.p_free) == Decimal(8)
    res = h.run("unlink_row", mworld.params["unlink_row"], key="mg-1")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(puts(h)) == 1
    assert res.replaced_lines == [(mworld.p_linked, mworld.p_free)]


def test_r2d_merge_pending_and_nothing_landed_sends_one_fresh_put(h, mworld):
    pend_merge(h, mworld)
    res = h.run("unlink_row", mworld.params["unlink_row"], key="mg-1")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(puts(h)) == 2 and qty_of(h, mworld.p_free) == Decimal(8)


def test_r2d_merge_pending_with_the_linked_row_deleted_by_hand_needs_attention(h, mworld):
    pend_merge(h, mworld)
    po = h.vendor.find("PO", 7001)
    po["Details"] = [r for r in po["Details"] if r["DtlKey"] != mworld.p_linked]  # gone, free row untouched (4)
    res = h.run("unlink_row", mworld.params["unlink_row"], key="mg-1")
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert len(puts(h)) == 1


def test_r2d_merge_pending_with_the_free_row_changed_otherwise_needs_attention(h, mworld):
    pend_merge(h, mworld)
    h.vendor._edit("PO", puts(h)[0].body)  # landed ...
    next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == mworld.p_free)["Qty"] = 9  # ... then edited
    res = h.run("unlink_row", mworld.params["unlink_row"], key="mg-1")
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert len(puts(h)) == 1


# ============================== (e) resume-settled not-applied is released ======================

def test_r2e_an_operation_resume_settled_as_not_applied_is_released_on_a_resend(h):
    w = World(h)
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = h.run("unlink_row", w.params["unlink_row"], key="rs-1")
    assert first.outcome == "pending_verification"
    settled = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=first.operation_id)
    assert settled.outcome == "recovered" and settled.error_code == "OPERATION_NOT_APPLIED", (
        settled.outcome, settled.error_code)
    again = h.run("unlink_row", w.params["unlink_row"], key="rs-1")
    assert again.outcome == "done", (again.outcome, again.error_code)
    assert again.operation_id != first.operation_id
    assert len(replace_puts(h)) == 2  # the resend ran fresh
