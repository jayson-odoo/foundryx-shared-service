"""Plan 62 round 5 pins: (a) the guard's pending count leaves out the PO being written;
(b) the 0045 backfill picks the same row the runtime does (``newest()``): a discarded UPSERT still counts,
a discarded DELETE intent does not hide the copy, a live delete intent removes the PO.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest
import sqlalchemy as sa

from app.main import app  # noqa: F401
from modules.autocount.models import AcWriteOperation
from modules.autocount.write_back.frame import BUSY_WINDOW_SECONDS
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


# ============================== (a) the PO being written is left out of the pending count =======

def test_r5b_a_pending_link_of_the_same_po_is_not_counted_twice(h):
    h.delete_on()
    so = h.seed_doc("SO", 7010, [_line("ITEM-A", 5, 5.0, "HQ")])
    s = so["Details"][0]["DtlKey"]
    po = h.seed_doc("PO", 7011, [_line("ITEM-A", 3, 5.0, "BR1"), _line("ITEM-A", 2, 5.0, "BR1")])
    r1, r2 = [r["DtlKey"] for r in po["Details"]]
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = h.run("link_row", dict(doc_key=7011, dtl_key=r1, so_doc_key=7010, so_dtl_key=s), key="pa-1")
    assert first.outcome == "pending_verification", (first.outcome, first.error_code)
    sent = next(c for c in h.vendor.writes() if c.method == "PUT")
    h.vendor._edit("PO", sent.body)  # it had landed after all: the fresh PO read already shows 3 linked to S
    old = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS + 60)
    h.db.query(AcWriteOperation).filter_by(idempotency_key="pa-1").update({"created_at": old, "updated_at": old})
    h.db.commit()  # past the busy window
    new_r2 = next(r["DtlKey"] for r in h.vendor.rows("PO", 7011) if r["Qty"] == 2 and not r.get("FromSODtlKey"))
    # S: 5 outstanding = 3 (already on PO 7011) + 2 (this link). Counting the pending 3 again would make it 8.
    second = h.run("link_row", dict(doc_key=7011, dtl_key=new_r2, so_doc_key=7010, so_dtl_key=s), key="pa-2")
    assert second.outcome == "done", (second.outcome, second.error_code)


# ============================== (b) the backfill picks the row the runtime does ==================

def _migration():
    path = next((Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic" / "versions").glob("0045_*.py"))
    spec = importlib.util.spec_from_file_location("mig_0045_probe5b", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _raw(qty):
    return {"DocKey": 1, "_lines": [{"DtlKey": 5, "FromSODtlKey": 77, "Qty": qty}]}


def _backfill(monkeypatch, rows: List[Dict[str, Any]]):
    """Run the migration's backfill against real rows: the statement's own WHERE and ORDER BY are executed on
    SQLite (DISTINCT ON is applied by hand: the first row per PO), the rows go through the migration's loop."""
    mod = _migration()
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS app_autocount")
        conn.exec_driver_sql(
            "CREATE TABLE app_autocount.ac_staged_record (id TEXT, tenant_id TEXT, company_id TEXT, "
            "entity_type TEXT, source_ref TEXT, op TEXT, status TEXT, raw_json TEXT, created_at TIMESTAMP)")
        base = datetime(2026, 11, 1, 10, 0, 0)
        for i, r in enumerate(rows):
            conn.exec_driver_sql(
                "INSERT INTO app_autocount.ac_staged_record VALUES (?,?,?,?,?,?,?,?,?)",
                (f"id{i:03d}", "t", "c", "purchase_order", r["ref"], r["op"], r["status"],
                 json.dumps(r["raw"]) if r["raw"] is not None else None,
                 (base + timedelta(minutes=r["age"])).strftime("%Y-%m-%d %H:%M:%S.%f")))
        inserted: List[Dict[str, Any]] = []

        class Bind:
            class dialect:
                name = "postgresql"

            def execute(self, stmt, *a, **k):
                if a:
                    inserted.extend(a[0])
                    return None
                cols = list(stmt.selected_columns)
                run = sa.select(*cols).where(stmt.whereclause).order_by(*stmt._order_by_clauses)
                seen, out = set(), []
                for row in conn.execute(run):
                    key = (row[0], row[1], row[2])
                    if key not in seen:  # DISTINCT ON (tenant, company, source_ref)
                        seen.add(key)
                        out.append(tuple(row))

                class Rows(list):
                    def yield_per(self, n):
                        return iter(self)

                return Rows(out)

        fake_op = mock.MagicMock()
        fake_op.get_bind.return_value = Bind()
        monkeypatch.setattr(mod, "op", fake_op)
        mod.upgrade()
    return inserted


def _by_ref(inserted):
    out: Dict[str, int] = {}
    for r in inserted:
        out[r["po_source_ref"]] = out.get(r["po_source_ref"], 0) + int(r["qty"])
    return out


def test_r5b_the_backfill_follows_the_runtime_choice_of_row(monkeypatch):
    rows = [
        # A: the newest copy is a DISCARDED upsert: it still counts (as newest() reads it)
        dict(ref="A", op="upsert", status="STAGED", raw=_raw(1), age=1),
        dict(ref="A", op="upsert", status="DISCARDED", raw=_raw(3), age=2),
        # B: a live delete intent is the newest row: really deleted, no rows
        dict(ref="B", op="upsert", status="STAGED", raw=_raw(4), age=1),
        dict(ref="B", op="delete", status="PUSHED", raw=None, age=2),
        # C: a DISCARDED delete intent is ignored, the newest real copy wins
        dict(ref="C", op="upsert", status="STAGED", raw=_raw(5), age=1),
        dict(ref="C", op="delete", status="DISCARDED", raw=None, age=2),
        # D: a live (staged) delete intent
        dict(ref="D", op="upsert", status="PUSHED", raw=_raw(6), age=1),
        dict(ref="D", op="delete", status="STAGED", raw=None, age=2),
    ]
    assert _by_ref(_backfill(monkeypatch, rows)) == {"A": 3, "C": 5}
