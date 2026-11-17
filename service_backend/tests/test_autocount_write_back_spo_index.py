"""Lane AUTOCOUNT-STRANDED-OPS, C.d: the write guards look SPO rows up through an index, never by loading
every staged SPO into the request.

Prod 17 Nov: an unlink's guards loaded every staged shipping order (20k+ docs, 35 MB raw) once for the row
and again per merge candidate; the gunicorn worker hit its timeout and was killed before the snapshot commit.
Here the work of one unlink is bounded: it must not grow with the number of staged SPOs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import SOURCE_IMPL_SQL_DB, AcEntityConfig, AcSpoPoLink, AcStagedRecord
from tests.test_autocount_write_back_operations import (  # noqa: F401
    OpHarness,
    db,
    h,
)
from tests.test_autocount_write_back_primitives import DBNAME, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401
from tests.write_back_live_books import live_books_open  # noqa: F401

pytestmark = pytest.mark.usefixtures("live_books_open")  # a sql_db receipt source makes the book "live"

NOISE_SPOS = 200


def _po_with_candidates(h: OpHarness):
    """SO 8002 (one row) + PO 8001: row 0 linked to it, rows 1..5 free and merge-equal to row 0. SPOs point at
    rows 1..4 (so the merge walks every candidate), row 5 is the merge target."""
    h.delete_on()
    so = h.seed_doc("SO", 8002, [_line("ITEM-A", 10, 5.0, "BR1")])
    so_dtl = so["Details"][0]["DtlKey"]
    base = dict(Discount="", TaxCode="SR", DeliveryDate="2026-12-01T00:00:00", Description="d")
    link = dict(FromDocType="SO", FromDocNo="SO-8002", FromDocDtlKey=so_dtl, FromSODtlKey=so_dtl)
    po = h.seed_doc("PO", 8001, [_line("ITEM-A", 4, 5.0, "BR1", **base, **link)]
                    + [_line("ITEM-A", 1, 5.0, "BR1", **base) for _ in range(5)])
    keys = [r["DtlKey"] for r in po["Details"]]
    for n, cand in enumerate(keys[1:5]):
        h.seed_doc("SPO", 8100 + n, [_line("ITEM-A", 1, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-8001",
                                           FromDocDtlKey=cand)])
    for n in range(NOISE_SPOS):  # the rest of the book: SPOs that point at other POs' rows
        h.seed_doc("SPO", 9000 + n, [_line("ITEM-A", 1, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-1",
                                           FromDocDtlKey=900000 + n)])
    # receipts come from the staged copies (sql_db source), so the merge reads the staged PO too
    h.db.add(AcEntityConfig(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="purchase_order",
                            source_impl=SOURCE_IMPL_SQL_DB))
    h.db.commit()
    return keys


class _Counter:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.loaded = 0
        self.staged_selects = 0

    def __enter__(self):
        event.listen(AcStagedRecord, "load", self._load)
        event.listen(self.engine, "before_cursor_execute", self._sql)
        return self

    def __exit__(self, *exc):
        event.remove(AcStagedRecord, "load", self._load)
        event.remove(self.engine, "before_cursor_execute", self._sql)

    def _load(self, target, context) -> None:
        self.loaded += 1

    def _sql(self, conn, cursor, statement, params, context, executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT") and "ac_staged_record" in statement:
            self.staged_selects += 1


def test_unlink_guards_do_bounded_work_whatever_the_number_of_staged_spos(h):
    keys = _po_with_candidates(h)
    with _Counter(h.db.get_bind()) as seen:
        res = h.run("unlink_row", dict(doc_key=8001, dtl_key=keys[0]), receipt_reader="default")
    assert res.outcome == "done", (res.outcome, res.error_code)
    # merged into row 5: rows 1..4 were skipped because SPO rows point at them (the index answered)
    assert h.operation(res).snapshot_json["mergeInto"] == keys[5]
    # bounded: a handful of staged reads (the PO's own copy, the read-back staging), never one per SPO
    assert seen.loaded <= 10, seen.loaded
    assert seen.staged_selects <= 10, seen.staged_selects


def test_row_on_spo_comes_from_the_index(h):
    keys = _po_with_candidates(h)
    res = h.run("unlink_row", dict(doc_key=8001, dtl_key=keys[1]), key="on-spo")
    assert (res.outcome, res.error_code) == ("refused", "ROW_ON_SPO")  # an SPO row points at row 1
    res = h.run("unlink_row", dict(doc_key=8001, dtl_key=keys[5]), key="free")
    assert (res.outcome, res.error_code) == ("refused", "ROW_NOT_LINKED")  # row 5: no SPO, just not linked
    assert h.vendor.writes() == []


def _restage(h, doc, minutes):
    """Stage a newer copy of ``doc`` (``minutes`` later), then refresh the index like a staging write."""
    from modules.autocount.write_back.link_index import refresh_spo_links

    row = h.stage("SPO", doc)
    row.created_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    h.db.flush()
    refresh_spo_links(h.db, DEFAULT_TENANT_ID, h.company.id, row.source_ref)
    h.db.commit()


def _index(h, ref):
    h.db.expire_all()
    return sorted((r.po_dtl_key, Decimal(r.qty)) for r in h.db.query(AcSpoPoLink).filter_by(
        company_id=h.company.id, spo_source_ref=ref))


def test_the_index_follows_the_newest_copy_and_drops_cancelled_and_deleted_spos(h):
    from modules.autocount.write_back.link_index import refresh_links

    spo = h.seed_doc("SPO", 8200, [_line("ITEM-A", 3, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-1",
                                         FromDocDtlKey=111)])
    ref = f"{DBNAME}:8200"
    assert _index(h, ref) == [(111, Decimal(3))]
    moved = dict(spo, Details=[dict(spo["Details"][0], FromDocDtlKey=222, Qty=2)])
    _restage(h, moved, 1)  # a newer copy: the old pointer is gone
    assert _index(h, ref) == [(222, Decimal(2))]
    _restage(h, dict(moved, Cancelled="T"), 2)
    assert _index(h, ref) == []
    _restage(h, moved, 3)
    assert _index(h, ref) == [(222, Decimal(2))]
    refresh_links(h.db, DEFAULT_TENANT_ID, h.company.id, "shipping_order", ref, deleted=True)
    assert _index(h, ref) == []


def test_index_is_tenant_and_company_scoped(h):
    from modules.autocount.write_back.repository import SpoPoLinkRepository

    h.seed_doc("SPO", 8300, [_line("ITEM-A", 1, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-1",
                                   FromDocDtlKey=333)])
    repo = SpoPoLinkRepository(h.db)
    assert repo.spo_doc_no(DEFAULT_TENANT_ID, h.company.id, 333) == "SPO-8300"
    assert repo.spo_doc_no("other-tenant", h.company.id, 333) is None
    assert repo.spo_doc_no(DEFAULT_TENANT_ID, "other-company", 333) is None
    assert repo.linked_qty(DEFAULT_TENANT_ID, h.company.id, 333) == Decimal(1)
    assert repo.linked_qty(DEFAULT_TENANT_ID, h.company.id, 333, except_ref=f"{DBNAME}:8300") == Decimal(0)


def test_migration_backfill_rows_match_the_runtime_writer():
    """The 0047 backfill builds the same rows as ``link_index.spo_links_of`` (module Alembic does not run
    under conftest, so the function is pinned directly)."""
    import importlib.util
    from pathlib import Path

    from modules.autocount.write_back.link_index import spo_links_of

    path = (Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic" / "versions"
            / "0047_autocount_spo_po_link.py")
    spec = importlib.util.spec_from_file_location("m0047", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raw = {"DocNo": "SPO-1", "_lines": [
        {"DtlKey": 1, "FromDocDtlKey": 10, "Qty": 2},
        {"DtlKey": 2, "FromDocDtlKey": 0, "Qty": 5},
        {"DtlKey": 3, "FromDocDtlKey": "11", "Qty": None},
        "junk",
    ]}
    rows = mod.rows_of("t", "c", "DB:1", None, raw)
    assert [(r["spo_dtl_key"], r["po_dtl_key"], r["qty"]) for r in rows] == spo_links_of(raw)
    assert {r["spo_doc_no"] for r in rows} == {"SPO-1"}
    assert mod.rows_of("t", "c", "DB:1", None, dict(raw, Cancelled="T")) == []


# ---- SO-row index (0048): the unlink snapshot's SO number + the relocate's SO location ------------------------

NOISE_SOS = 2 * NOISE_SPOS  # owner: size the SO side at twice the SPO side


def test_unlink_of_a_row_read_back_without_from_doc_no_finds_the_so_through_the_index(h):
    h.delete_on()
    so = h.seed_doc("SO", 8402, [_line("ITEM-A", 10, 5.0, "BR1")])
    so_dtl = so["Details"][0]["DtlKey"]
    for n in range(NOISE_SOS):  # the rest of the book
        h.seed_doc("SO", 20000 + n, [_line("ITEM-B", 1, 5.0, "BR1")])
    # the vendor reads the linked row back WITHOUT FromDocNo (AutoCount quirk): the snapshot must look it up
    link = dict(FromDocType="SO", FromDocNo="", FromDocDtlKey=so_dtl, FromSODtlKey=so_dtl)
    po = h.seed_doc("PO", 8401, [_line("ITEM-A", 4, 5.5, "BR1", **link)])
    with _Counter(h.db.get_bind()) as seen:
        res = h.run("unlink_row", dict(doc_key=8401, dtl_key=po["Details"][0]["DtlKey"]), key="so-idx")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert h.operation(res).snapshot_json["oldLink"] == {"FromDocType": "SO", "FromDocNo": "SO-8402",
                                                          "FromDocDtlKey": so_dtl}
    assert seen.loaded <= 10, seen.loaded  # never one load per staged SO


def _so_index(h, ref):
    from modules.autocount.models import AcSoRowIndex

    h.db.expire_all()
    return sorted((r.so_dtl_key, r.location, r.ambiguous) for r in h.db.query(AcSoRowIndex).filter_by(
        company_id=h.company.id, so_source_ref=ref))


def test_so_index_marks_equally_new_disagreeing_copies_ambiguous_and_follows_the_newest(h):
    from modules.autocount.write_back.link_index import refresh_links

    so = h.seed_doc("SO", 8500, [_line("ITEM-A", 1, 5.0, "BR1")])
    ref, key = f"{DBNAME}:8500", so["Details"][0]["DtlKey"]
    assert _so_index(h, ref) == [(key, "BR1", False)]
    newest = h.db.query(AcStagedRecord).filter_by(company_id=h.company.id, source_ref=ref).one()
    moment = datetime.now(timezone.utc).replace(microsecond=0)
    newest.created_at = moment
    twin = h.stage("SO", dict(so, Details=[dict(so["Details"][0], Location="BR2")]))
    twin.created_at = moment  # equally new, disagreeing
    h.db.flush()
    refresh_links(h.db, DEFAULT_TENANT_ID, h.company.id, "sales_order", ref)
    h.db.commit()
    assert _so_index(h, ref) == [(key, None, True)]
    later = h.stage("SO", dict(so, Details=[dict(so["Details"][0], Location="BR3")]))
    later.created_at = moment + timedelta(minutes=5)
    h.db.flush()
    refresh_links(h.db, DEFAULT_TENANT_ID, h.company.id, "sales_order", ref)
    h.db.commit()
    assert _so_index(h, ref) == [(key, "BR3", False)]


def test_a_rolled_back_sync_job_rebuilds_the_indexes_from_what_survives(h):
    """Review fix: ``discard_for_job`` hard-deletes a guard-tripped job's staged rows; the indexes built from
    them are rebuilt, never left pointing at a gone copy."""
    from modules.autocount.repositories import StagedRecordRepository
    from modules.autocount.write_back.link_index import refresh_links

    spo = h.seed_doc("SPO", 8600, [_line("ITEM-A", 1, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-1",
                                         FromDocDtlKey=601)])
    ref = f"{DBNAME}:8600"
    newer = h.stage("SPO", dict(spo, Details=[dict(spo["Details"][0], FromDocDtlKey=602)]), job_id="sync-job")
    newer.created_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    h.db.flush()
    refresh_links(h.db, DEFAULT_TENANT_ID, h.company.id, "shipping_order", ref)
    h.db.commit()
    assert [k for k, _q in _index(h, ref)] == [602]
    StagedRecordRepository(h.db).discard_for_job(DEFAULT_TENANT_ID, h.company.id, "sync-job")
    h.db.commit()
    assert [k for k, _q in _index(h, ref)] == [601]  # back to the copy that survived


def test_migration_0048_backfill_rows_match_the_runtime_writer():
    import importlib.util
    from pathlib import Path

    from modules.autocount.write_back.link_index import so_rows_of

    path = (Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic" / "versions"
            / "0048_autocount_so_row_index.py")
    spec = importlib.util.spec_from_file_location("m0048", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    copies = [{"DocNo": "SO-1", "_lines": [{"DtlKey": 1, "Location": "A"}, {"DtlKey": 2, "Location": "B"}, "x"]},
              {"DocNo": "SO-1", "_lines": [{"DtlKey": 1, "Location": "A"}, {"DtlKey": 2, "Location": "C"}]}]
    rows = mod.rows_of("t", "c", "DB:1", None, None, copies)
    assert sorted((r["so_dtl_key"], r["location"], r["ambiguous"]) for r in rows) == sorted(so_rows_of(copies))
    assert {r["so_doc_no"] for r in rows} == {"SO-1"}
