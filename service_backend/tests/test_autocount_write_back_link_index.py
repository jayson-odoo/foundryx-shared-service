"""Plan 62 (RED): the over-link index ``app_autocount.ac_po_so_link``, AC-62-40..42 (plan D8).

``_so_linked_qty`` (``write_back/service.py`` and ``write_back/primitives.py``) must read the
indexed rows of the OTHER POs instead of iterating every staged PO (which also double counts
history copies). New model ``AcPoSoLink`` (tenant_id, company_id, po_source_ref, po_dtl_key,
so_dtl_key, qty), rewritten from a PO's NEWEST staged copy on every PO staging write (sync +
write-back); a cancelled or deleted PO leaves no rows. The model is imported inside each
test so every test fails on its own.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import ENTITY_PURCHASE_ORDER
from modules.autocount.write_back.repository import StagedDocRepository
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import DBNAME, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

OTHER_TENANT = "tenant-other-plan62-index"
SO_KEY = 91001


def _model():
    from modules.autocount.models import AcPoSoLink

    return AcPoSoLink


def _link(h, po_ref, po_dtl, so_dtl, qty, tenant=DEFAULT_TENANT_ID, company=None):
    row = _model()(tenant_id=tenant, company_id=company or h.company.id, po_source_ref=po_ref,
                   po_dtl_key=po_dtl, so_dtl_key=so_dtl, qty=Decimal(qty))
    h.db.add(row)
    h.db.commit()
    return row


def _rows(h, ref=None):
    h.db.expire_all()
    q = h.db.query(_model()).filter_by(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id)
    if ref:
        q = q.filter_by(po_source_ref=ref)
    return q.all()


def _po_with_link(h, doc_key, so_dtl, qty, **header):
    rows = [_line("ITEM-A", qty, 5.0, "BR1", FromDocType="SO", FromDocNo="SO-1", FromDocDtlKey=so_dtl,
                  FromSODtlKey=so_dtl)]
    return h.seed_doc("PO", doc_key, rows, **header)


def _no_scan(monkeypatch):
    orig = StagedDocRepository.for_entity

    def spy(self, tenant_id, company_id, entity_type):
        if entity_type == ENTITY_PURCHASE_ORDER:
            raise AssertionError("every staged PO was iterated (for_entity) instead of the index")
        return orig(self, tenant_id, company_id, entity_type)

    monkeypatch.setattr(StagedDocRepository, "for_entity", spy)


def _svc_qty(h, fresh, so_dtl):
    from modules.autocount.write_back.service import WriteBackService

    svc = WriteBackService(h.db, **h.factories())
    return svc._so_linked_qty(h.company, fresh, so_dtl)


def _prim_qty(h, so_dtl, fresh=None):
    return h.service()._so_linked_qty(h.company, so_dtl, fresh)


# ============================== AC-62-40 the sum reads the index ================================

def test_ac_62_40_service_sum_is_fresh_rows_plus_the_index_of_other_pos(h, monkeypatch):
    other = _po_with_link(h, 8001, SO_KEY, 3)
    own = _po_with_link(h, 8002, SO_KEY, 2)
    _link(h, f"{DBNAME}:8001", other["Details"][0]["DtlKey"], SO_KEY, 3)
    _no_scan(monkeypatch)
    assert _svc_qty(h, own, SO_KEY) == Decimal(5)  # 2 (fresh, own) + 3 (index, other PO)


def test_ac_62_40_primitives_sum_is_the_index_and_never_scans_staged_pos(h, monkeypatch):
    other = _po_with_link(h, 8001, SO_KEY, 3)
    _link(h, f"{DBNAME}:8001", other["Details"][0]["DtlKey"], SO_KEY, 3)
    _no_scan(monkeypatch)
    assert _prim_qty(h, SO_KEY) == Decimal(3)


def test_ac_62_40_the_fresh_po_replaces_its_own_index_rows(h, monkeypatch):
    own = _po_with_link(h, 8002, SO_KEY, 2)
    _link(h, f"{DBNAME}:8002", own["Details"][0]["DtlKey"], SO_KEY, 9)  # stale rows of the PO being edited
    _no_scan(monkeypatch)
    assert _svc_qty(h, own, SO_KEY) == Decimal(2)
    assert _prim_qty(h, SO_KEY, own) == Decimal(2)


def test_ac_62_40_other_tenants_index_rows_never_count(h, monkeypatch):
    _link(h, f"{DBNAME}:8001", 1, SO_KEY, 7, tenant=OTHER_TENANT)
    _link(h, f"{DBNAME}:8003", 2, SO_KEY, 6, company="other-company-id")
    _no_scan(monkeypatch)
    own = _po_with_link(h, 8002, SO_KEY, 2)
    assert _svc_qty(h, own, SO_KEY) == Decimal(2)
    assert _prim_qty(h, SO_KEY) == Decimal(0)


def test_ac_62_40_double_count_regression_two_staged_copies_of_one_other_po_count_once(h):
    other = _po_with_link(h, 8001, SO_KEY, 3)  # copy 1 (seed_doc stages)
    h.stage("PO", other)                        # copy 2 = the history copy sync inserts after a push
    _link(h, f"{DBNAME}:8001", other["Details"][0]["DtlKey"], SO_KEY, 3)  # the index holds the newest copy once
    own = _po_with_link(h, 8002, SO_KEY, 0)
    assert _svc_qty(h, own, SO_KEY) == Decimal(3), "history copies were counted (6)"
    assert _prim_qty(h, SO_KEY) == Decimal(3)


# ============================== AC-62-41 staging rewrites the rows ==============================

def test_ac_62_41_write_back_staging_writes_the_pos_rows_and_replaces_them_on_a_newer_copy(h):
    world = World(h)
    linked = world.p_linked
    res = h.run("unlink_row", world.params["unlink_row"], key="k-41a")  # restages PO 7001 after the write
    assert res.outcome == "done"
    ref = f"{DBNAME}:7001"
    rows = _rows(h, ref)
    assert all(r.so_dtl_key != world.so_a for r in rows), "the unlinked row is still indexed"
    res2 = h.run("link_row", world.params["link_row"], key="k-41b")
    assert res2.outcome == "done"
    rows = _rows(h, ref)
    assert [(r.so_dtl_key, Decimal(r.qty)) for r in rows] == [(world.so_a, Decimal(4))], rows  # replaced, not appended
    assert linked not in [r.po_dtl_key for r in rows]


def test_ac_62_41_a_cancelled_po_leaves_no_rows(h):
    from datetime import date

    h.flag("PO", "cancel_doc", True)
    world = World(h)
    res = h.run("unlink_row", world.params["unlink_row"], key="k-41c")
    assert res.outcome == "done"
    _link(h, f"{DBNAME}:7001", 99, world.so_a, 4)  # a row that must disappear with the cancel
    out = h.service().cancel_doc(**h.args("PO", doc_key=7001, doc_date=date(2026, 11, 4)))
    assert out.outcome == "done", (out.outcome, out.error_code)
    assert _rows(h, f"{DBNAME}:7001") == []


def test_ac_62_41_sync_pull_writes_and_rewrites_the_pos_rows(session_factory):
    from modules.autocount.canonical.documents import ENTITY_PURCHASE_ORDER as PO
    from modules.autocount.models import RUN_MODE_MANUAL, RUN_MODE_RECONCILE
    from tests.test_autocount_line_linkage import _po_link_rig, _run_po
    from modules.autocount.sql_source.runtime import RUNTIME

    db, company, config, engine = _po_link_rig(session_factory, database="AED_P62_IDX")
    try:
        # AutoCount-shaped line columns, so the raw line carries FromSODtlKey / Qty
        cfg = dict(config.source_config)
        cfg["lineQuery"] = (
            "SELECT dtl_key, item_code, qty_ordered AS Qty, from_so_doc_key, from_so_dtl_key AS FromSODtlKey "
            "FROM po_line WHERE doc_key = :doc_key"
        )
        config.source_config = cfg
        from modules.autocount.models import AcFieldMapping

        for m in db.query(AcFieldMapping).filter_by(company_id=company.id, entity_type=PO):
            if m.source_path == "qty_ordered":
                m.source_path = "Qty"
            elif m.source_path == "from_so_dtl_key":
                m.source_path = "FromSODtlKey"
        db.commit()
        with engine.begin() as conn:  # the rig's D001-1 has an SO doc key but NO SO line key: give it a real link
            conn.exec_driver_sql("UPDATE po_line SET from_so_dtl_key = '45700101' WHERE dtl_key = 'D001-1'")
        _run_po(db, company, RUN_MODE_MANUAL)
        AcPoSoLink = _model()
        first = db.query(AcPoSoLink).filter_by(company_id=company.id).all()
        assert [(r.so_dtl_key, Decimal(r.qty)) for r in first] == [(45700101, Decimal(10))], first
        with engine.begin() as conn:
            conn.exec_driver_sql("UPDATE po_line SET from_so_dtl_key = '45700148' WHERE dtl_key = 'D001-1'")
            conn.exec_driver_sql(  # a real AutoCount edit bumps the header LastModified too
                "UPDATE po_header SET last_modified = '2026-08-05 09:00:00' WHERE doc_key = 'D001'")
        db.expire_all()
        _run_po(db, company, RUN_MODE_RECONCILE)
        rows = db.query(AcPoSoLink).filter_by(company_id=company.id).all()
        assert [(r.so_dtl_key, Decimal(r.qty)) for r in rows] == [(45700148, Decimal(10))], rows
    finally:
        db.close()
        RUNTIME.dispose_all()


# ============================== AC-62-42 migration 0045 =========================================

def test_ac_62_42_migration_0045_exists_with_a_short_revision_id():
    versions = Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic" / "versions"
    files = sorted(versions.glob("0045_*.py"))
    assert len(files) == 1, files
    text = files[0].read_text()
    rev = re.search(r'^revision(?:: str)? = "([^"]+)"', text, re.M)
    assert rev and len(rev.group(1)) <= 32, rev and rev.group(1)
    assert "0044_autocount_api_call_log" in text  # chains onto the current head
    assert "ac_po_so_link" in text
