"""Plan 62 review round 4 (RED): neutral regression tests.

(1) the index backfill and delete intents; (3) a needs-attention reconcile sends the notice;
(4) the "owned by another create" check is bounded in time. (2) is in test_autocount_write_back_create_lookup.py.
"""

from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List
from unittest import mock

import pytest
from sqlalchemy.dialects import postgresql

from app.main import app  # noqa: F401
from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteOperation
from tests.test_autocount_write_back_create_lookup import URL, body, first_attempt_landed, posts
from tests.test_autocount_write_back_gateway_qtso import Gw
from tests.test_autocount_write_back_link_batch import Rig
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


# ============================== (1) backfill and delete intents =================================

def _load_migration():
    path = next((Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic" / "versions").glob("0045_*.py"))
    spec = importlib.util.spec_from_file_location("mig_0045_probe4", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Rows(list):
    def yield_per(self, n):
        return iter(self)


def _run_backfill(monkeypatch, rows_by_column):
    """Run ``upgrade()`` on a fake Postgres bind; ``rows_by_column`` = dicts keyed by the select's column
    names, handed back in the select's own column order. Returns (select statement, inserted rows)."""
    mod = _load_migration()
    seen: List[Any] = []
    inserted: List[Any] = []

    class Bind:
        class dialect:
            name = "postgresql"

        def execute(self, stmt, *a, **k):
            if hasattr(stmt, "whereclause") and not hasattr(stmt, "table"):
                seen.append(stmt)
                names = [c.name for c in stmt.selected_columns]
                return _Rows(tuple(r.get(n) for n in names) for r in rows_by_column)
            if a:
                inserted.extend(a[0])
            return _Rows()

    fake_op = mock.MagicMock()
    fake_op.get_bind.return_value = Bind()
    monkeypatch.setattr(mod, "op", fake_op)
    mod.upgrade()
    return seen[0], inserted


def _row(op, raw, status="STAGED", ref="AED_TEST:1"):
    return {"tenant_id": "t", "company_id": "c", "source_ref": ref, "op": op, "raw_json": raw, "status": status}


RAW = {"DocKey": 1, "_lines": [{"DtlKey": 5, "FromSODtlKey": 77, "Qty": 3}]}


def test_r4_1_the_selection_excludes_discarded_rows_only_not_every_delete(monkeypatch):
    stmt, _ = _run_backfill(monkeypatch, [])
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    where = sql.lower().split("where", 1)[1]
    assert "discarded" in where, sql  # a cancelled intent is out of the picture ...
    assert not re.search(r"\.op\s*(!=|<>)\s*'delete'", where), sql  # ... a live one is not filtered away


def test_r4_1_a_po_whose_newest_row_is_a_live_delete_intent_gets_no_rows(monkeypatch):
    _stmt, inserted = _run_backfill(monkeypatch, [_row("delete", None)])
    assert inserted == []


def test_r4_1_a_po_whose_newest_remaining_row_is_a_copy_gets_its_rows(monkeypatch):
    _stmt, inserted = _run_backfill(monkeypatch, [_row("upsert", RAW)])
    assert [(r["so_dtl_key"], int(r["qty"])) for r in inserted] == [(77, 3)]


# ============================== (3) needs attention sends the notice ============================

def test_r4_3_a_batch_reconcile_that_needs_attention_sends_the_notice(h):
    rig = Rig(h)
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = h.run("link_batch", rig.params(rig.three()), key="na-1")
    assert first.outcome == "pending_verification"
    row = next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == rig.w.p_free)
    row["Qty"] = 3  # the old row was cut by someone else; none of the batch's rows exist
    res = h.run("link_batch", rig.params(rig.three()), key="na-1")
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert len(h.alerts) == 1


def test_r4_3_a_merge_reconcile_that_needs_attention_sends_the_notice(h):
    h.delete_on()
    w = World(h)
    h.vendor.find("PO", 7001)["Details"][1]["UnitPrice"] = 5.0  # the linked row matches a free row: a merge
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = h.run("unlink_row", w.params["unlink_row"], key="na-2")
    assert first.outcome == "pending_verification"
    po = h.vendor.find("PO", 7001)
    po["Details"] = [r for r in po["Details"] if r["DtlKey"] != w.p_linked]  # deleted by hand, free row untouched
    res = h.run("unlink_row", w.params["unlink_row"], key="na-2")
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert len(h.alerts) == 1


# ============================== (4) the ownership check is bounded in time ======================

@pytest.fixture
def gw(h, db):
    h.vendor.stamp_created = True
    h.delete_on()
    return Gw(h, db)


def test_r4_4_an_old_done_create_does_not_own_a_document_inside_the_window(client, h, gw, db):
    first_attempt_landed(client, h, gw, "bd-1", body())
    landed = h.vendor.docs["PO"][0]
    db.add(AcWriteOperation(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=None, idempotency_key="old-done",
        request_hash="x", op="create_doc:PO", doc_type="PO", status="done",
        result_json={"outcome": "done", "docKey": landed["DocKey"], "docNo": landed["DocNo"]},
        created_at=datetime.now(timezone.utc) - timedelta(days=60),
    ))
    db.commit()
    r = client.post(URL, json=body(), headers=gw.hdr("bd-1"))
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert r.json()["docNo"] == landed["DocNo"]
    assert len(posts(h)) == 1  # the 60 day old row was outside the window and never counted
