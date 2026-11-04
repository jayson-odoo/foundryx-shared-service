"""Plan 57 (RED): AC-57-22 write connection only on a test company; staging never
overwrites another job's rows.

(a) ``set_write_connection`` (staged rows count only for purchase_order / shipping_order / sales_order;
masters of any job never block) refuses ``WRITE_COMPANY_NOT_TEST`` (company unchanged) when the
company has ANY ``ac_entity_config`` with ``source_impl == "sql_db"`` or ANY
``ac_staged_record`` whose ``job_id`` is not ``STAGING_JOB_ID``; the CLI prints
``error: WRITE_COMPANY_NOT_TEST`` and returns 2.
(b) ``DocStager`` never touches a newest ``{db}:{DocKey}`` row whose ``job_id`` is not
``STAGING_JOB_ID`` (raw_json, canonical_json, status, pushed_at, doc_no unchanged, nothing
pushed) while the write still answers ``done`` from the read-back. Rows created by write-back
keep plan 55 behaviour (restaged and pushed). Holds for the plan 55 service and the new
primitives / operations.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any, Dict

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import SOURCE_IMPL_SQL_DB, STAGED, AcEntityConfig, AcStagedRecord
from modules.autocount.write_back.service import WriteBackService, WriteConnectionError, set_write_connection
from modules.autocount.write_back.staging import STAGING_JOB_ID
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import DB3, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

SYNC_JOB = "sql-sync-job"


def test_the_write_back_job_id_is_the_stable_constant():
    assert STAGING_JOB_ID == "write-back"


# ---- (a) set_write_connection ------------------------------------------------------------------------

@pytest.fixture
def fresh(h):
    h.company.write_connection_id = None
    h.db.commit()
    return h


def _set(h):
    conn = h._connection(DB3, DEFAULT_TENANT_ID)
    return conn, lambda: set_write_connection(
        h.db, tenant_id=h.company.tenant_id, company_id=h.company.id, connection_id=conn.id)


def _config(h, entity="customer", impl=SOURCE_IMPL_SQL_DB, company_id=None, tenant_id=DEFAULT_TENANT_ID):
    h.db.add(AcEntityConfig(tenant_id=tenant_id, company_id=company_id or h.company.id,
                            entity_type=entity, source_impl=impl))
    h.db.commit()


def _row(h, job_id, ref="AED_TEST:1", company_id=None, tenant_id=DEFAULT_TENANT_ID, entity="customer"):
    h.db.add(AcStagedRecord(tenant_id=tenant_id, company_id=company_id or h.company.id, entity_type=entity,
                            job_id=job_id, source_ref=ref, doc_no="x", raw_json={}, status=STAGED))
    h.db.commit()


def _refused(h, call):
    with pytest.raises(WriteConnectionError) as exc:
        call()
    assert exc.value.code == "WRITE_COMPANY_NOT_TEST"
    h.db.expire_all()
    h.db.refresh(h.company)
    assert h.company.write_connection_id is None


@pytest.mark.parametrize("entity", ["customer", "purchase_order", "sales_order", "product"])
def test_ac_57_22_any_sql_db_entity_config_refuses(fresh, entity):
    _config(fresh, entity)
    _conn, call = _set(fresh)
    _refused(fresh, call)


@pytest.mark.parametrize("entity", ["purchase_order", "shipping_order", "sales_order"])
def test_ac_57_22_a_staged_document_row_of_another_job_refuses(fresh, entity):
    _row(fresh, SYNC_JOB, entity=entity)
    _conn, call = _set(fresh)
    _refused(fresh, call)


@pytest.mark.parametrize("entity", ["product", "customer", "supplier", "warehouse", "item_class"])
def test_ac_57_22_staged_masters_of_another_job_do_not_block(fresh, entity):
    _row(fresh, SYNC_JOB, ref=f"AED_TEST:M-{entity}", entity=entity)  # an HTTP master task's row
    conn, call = _set(fresh)
    call()
    fresh.db.expire_all()
    fresh.db.refresh(fresh.company)
    assert fresh.company.write_connection_id == conn.id


def test_ac_57_22_clean_company_gets_the_connection(fresh):
    conn, call = _set(fresh)
    call()
    fresh.db.expire_all()
    fresh.db.refresh(fresh.company)
    assert fresh.company.write_connection_id == conn.id


def test_ac_57_22_write_back_staged_rows_and_http_configs_do_not_block(fresh):
    _row(fresh, STAGING_JOB_ID, ref="AED_TEST:2")
    _row(fresh, STAGING_JOB_ID, ref="AED_TEST:3", entity="purchase_order")
    _config(fresh, "customer", "autocount_read")
    conn, call = _set(fresh)
    call()
    fresh.db.expire_all()
    fresh.db.refresh(fresh.company)
    assert fresh.company.write_connection_id == conn.id


def test_ac_57_22_only_this_companys_data_counts(fresh):
    from modules.autocount.models import AcCompany

    other = AcCompany(tenant_id=DEFAULT_TENANT_ID, connection_id=fresh.conn.id, database_name="AED_OTHER",
                      company_name="o", name="o", is_active=True, sink_impl="logging")
    fresh.db.add(other)
    fresh.db.commit()
    _config(fresh, "customer", company_id=other.id)
    _row(fresh, SYNC_JOB, company_id=other.id)
    conn, call = _set(fresh)
    call()
    fresh.db.refresh(fresh.company)
    assert fresh.company.write_connection_id == conn.id


def test_ac_57_22_refusal_wins_over_a_bad_connection_but_checks_nothing_else_first(fresh):
    _config(fresh, "customer")
    with pytest.raises(WriteConnectionError) as exc:
        set_write_connection(fresh.db, tenant_id=fresh.company.tenant_id, company_id=fresh.company.id,
                             connection_id=fresh._connection(DB3, DEFAULT_TENANT_ID).id)
    assert exc.value.code == "WRITE_COMPANY_NOT_TEST"


def _cli(fresh, monkeypatch, capsys, session_factory):
    import app.database as database
    from app.models.tenant import Tenant
    from modules.autocount.write_back import admin

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    slug = fresh.db.get(Tenant, DEFAULT_TENANT_ID).slug
    conn = fresh._connection(DB3, DEFAULT_TENANT_ID)
    code = admin.main(["set-write-connection", "--tenant-slug", slug, "--company-id", fresh.company.id,
                       "--connection-id", conn.id])
    return code, capsys.readouterr().out, conn


def test_ac_57_22_cli_prints_the_code_and_returns_2(fresh, monkeypatch, capsys, session_factory):
    _config(fresh, "customer")
    code, out, _conn = _cli(fresh, monkeypatch, capsys, session_factory)
    assert code == 2 and out.strip() == "error: WRITE_COMPANY_NOT_TEST"
    fresh.db.expire_all()
    fresh.db.refresh(fresh.company)
    assert fresh.company.write_connection_id is None


def test_ac_57_22_cli_still_sets_a_clean_company(fresh, monkeypatch, capsys, session_factory):
    code, out, conn = _cli(fresh, monkeypatch, capsys, session_factory)
    assert code == 0 and out.strip() == "ok"
    fresh.db.expire_all()
    fresh.db.refresh(fresh.company)
    assert fresh.company.write_connection_id == conn.id


# ---- (b) staging never overwrites another job's row ----------------------------------------------------------

FIELDS = ("raw_json", "canonical_json", "status", "pushed_at", "doc_no", "job_id", "error", "diff_json")


def _snap(row: AcStagedRecord) -> Dict[str, Any]:
    return {f: copy.deepcopy(getattr(row, f)) for f in FIELDS}


def _newest(h, entity, doc_key):
    h.db.expire_all()
    return (h.db.query(AcStagedRecord)
            .filter(AcStagedRecord.company_id == h.company.id, AcStagedRecord.entity_type == entity,
                    AcStagedRecord.source_ref == f"AED_TEST:{doc_key}")
            .order_by(AcStagedRecord.created_at.desc()).first())


def _foreign_po(h, canonical=True):
    """PO 7001 staged by ANOTHER job (a SQL sync), as the world's staged row."""
    h.delete_on()
    w = World(h)
    row = _newest(h, "purchase_order", 7001)
    row.job_id = SYNC_JOB
    if canonical:
        row.canonical_json = {"sourceRef": "AED_TEST:7001", "lines": [
            {"source_ref": f"AED_TEST:7001:{w.p_free}", "qty_received": 0}]}
    h.db.commit()
    return w


def test_ac_57_22_primitive_edit_answers_from_the_read_back_and_leaves_a_foreign_row_alone(h):
    _foreign_po(h)
    before = _snap(_newest(h, "purchase_order", 7001))
    res = h.edit("PO", 7001, {"Remark1": "from write-back"})
    assert res.outcome == "done", res.error_code
    assert res.document["Remark1"] == "from write-back"
    assert _snap(_newest(h, "purchase_order", 7001)) == before
    assert h.sink_calls == []


def test_ac_57_22_primitive_add_line_leaves_a_foreign_row_alone(h):
    _foreign_po(h)
    before = _snap(_newest(h, "purchase_order", 7001))
    res = h.service().add_line(**h.args("PO", doc_key=7001, line=_line("C", 1, 3.0)))
    assert res.outcome == "done", res.error_code
    assert _snap(_newest(h, "purchase_order", 7001)) == before and h.sink_calls == []


def test_ac_57_22_operation_leaves_foreign_rows_alone_and_still_answers_done(h):
    w = _foreign_po(h)
    before = _snap(_newest(h, "purchase_order", 7001))
    res = h.run("link_row", w.params["link_row"])
    assert res.outcome == "done", res.error_code
    assert res.document is not None and len(res.document["Details"]) == 4
    assert _snap(_newest(h, "purchase_order", 7001)) == before
    assert h.sink_calls == []


def test_ac_57_22_spo_operation_leaves_a_foreign_spo_row_alone(h):
    h.delete_on()
    w = World(h)
    row = _newest(h, "shipping_order", 7003)
    row.job_id = SYNC_JOB
    h.db.commit()
    before = _snap(_newest(h, "shipping_order", 7003))
    res = h.run("spo_relink_row", w.params["spo_relink_row"])
    assert res.outcome == "done", res.error_code
    assert _snap(_newest(h, "shipping_order", 7003)) == before and h.sink_calls == []


def test_ac_57_22_plan_55_split_link_leaves_a_foreign_row_alone(h):
    w = _foreign_po(h)
    before = _snap(_newest(h, "purchase_order", 7001))
    svc = WriteBackService(h.db, **h.factories())
    res = svc.link(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=7001,
                   po_dtl_key=w.p_free, so_doc_key=7002, so_dtl_key=w.so_a, qty=Decimal(2))
    assert res.outcome == "done", res.error_code
    assert _snap(_newest(h, "purchase_order", 7001)) == before and h.sink_calls == []


def test_ac_57_22_a_foreign_so_row_is_left_alone_when_the_so_is_edited(h):
    doc = h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    row = _newest(h, "sales_order", 5001)
    row.job_id = SYNC_JOB
    h.db.commit()
    before = _snap(_newest(h, "sales_order", 5001))
    res = h.edit("SO", 5001, {"Remark1": "x"})
    assert res.outcome == "done", res.error_code
    assert _snap(_newest(h, "sales_order", 5001)) == before and h.sink_calls == []
    assert doc


def test_ac_57_22_no_second_row_is_added_next_to_a_foreign_one(h):
    _foreign_po(h)
    count = h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7001").count()
    h.edit("PO", 7001, {"Remark1": "x"})
    assert h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7001").count() == count


def test_ac_57_22_write_back_created_rows_keep_plan_55_behaviour_restaged_and_pushed(h):
    h.delete_on()
    World(h)  # staged with job_id = the write-back job
    assert _newest(h, "purchase_order", 7001).job_id == STAGING_JOB_ID
    res = h.edit("PO", 7001, {"Remark1": "restaged"})
    assert res.outcome == "done", res.error_code
    row = _newest(h, "purchase_order", 7001)
    assert row.raw_json["Remark1"] == "restaged" and row.job_id == STAGING_JOB_ID
    assert row.canonical_json and row.pushed_at is not None
    assert h.sink_calls


def test_ac_57_22_a_document_created_by_write_back_is_staged_with_the_write_back_job(h):
    res = h.create("SO")
    assert res.outcome == "done", res.error_code
    row = _newest(h, "sales_order", res.doc_key)
    assert row is not None and row.job_id == STAGING_JOB_ID
    again = h.edit("SO", res.doc_key, {"Remark1": "second"})
    assert again.outcome == "done", again.error_code
    assert _newest(h, "sales_order", res.doc_key).raw_json["Remark1"] == "second"
