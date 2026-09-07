"""Line fingerprint sweep (lane feat/line-fingerprint-sweep, contract A).

Prod finding: SO419208 (DocKey 45672056) had a delivery transfer after our
initial staging. AutoCount updates ``SODTL.TransferedQty`` WITHOUT bumping
``SO.LastModified``, the SODTL ``Last*Modified`` stamps are NULL and the ESB
login cannot read DO/DODTL, so an incremental run (``LastModified > :since``)
never sees the change and the CRM copy stays stale until the daily reconcile.

Contract pinned here (red before the coder):

A1. ``DocumentPreset.fingerprint_query`` per preset (SO text exact; PO/SPO
    over PODTL/PO with the header OUTER APPLY's own cuts), stored per task in
    ``source_config["fingerprintQuery"]`` with the same stored-vs-preset rules
    as ``query``: the picker substitutes ``{database}``, the validator keeps
    it, a backfill (``backfill_document_fingerprint_queries``: module Alembic
    0017 + ``update_tenant``) sets it when absent, never overwrites a
    customised one, WARNING naming the config id.
A2. ``ac_doc_fingerprint(tenant_id, company_id, entity_type, source_ref,
    fingerprint, seen_at)`` PK on the first four (model ``AcDocFingerprint``),
    module Alembic 0017 (<= 32 chars, single head, Postgres-guarded) which
    also adds ``ac_watermark.last_fingerprint_sweep_at``. ``fingerprint`` =
    sha of the ordered aggregate values as strings
    (``sql_source.hashing.document_fingerprint``).
A3. INCREMENTAL runs only (never reconcile, never the initial load): when
    ``now - last_fingerprint_sweep_at >= settings.autocount_fingerprint_sweep_minutes``
    (default 15, floor 1) the source runs the fingerprint query once, the
    header fetch adds ``DocKey IN (changed keys)`` (chunked at 500,
    ``FINGERPRINT_KEY_CHUNK``) to ``LastModified > :since``; the first sweep
    SEEDS fingerprints for known-hash documents without fetching them; staged
    documents get their fingerprint updated; a fingerprint-query error fails
    only the sweep (WARNING, run continues, ``last_fingerprint_sweep_at`` not
    advanced).
A4. Tenant scoping on every fingerprint row; a vanished document's
    fingerprint is removed by the reconcile pass.
A5. End to end on the SQL rig (below).
"""
from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool

import modules.autocount as autocount_module
from app.config import Settings, settings
from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, JOB_NEEDS_REVIEW
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
)
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.mapping import SCOPE_HEADER, SCOPE_LINE
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    SOURCE_IMPL_SQL_DB,
    STAGED_OP_DELETE,
    STAGED_OP_UPSERT,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcRowHash,
    AcStagedRecord,
    AcSyncRun,
    AcWatermark,
)
from modules.autocount.presets import (
    DOCUMENT_PRESETS,
    PO_PRESET,
    SO_PRESET,
    SPO_PRESET,
    list_mapping_presets,
)
from modules.autocount.services.etl_service import validate_source_config
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sync import AUTOCOUNT_SYNC

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"
PREVIOUS_REVISION = "0016_autocount_spo_container"
HELPER_NAME = "backfill_document_fingerprint_queries"

SO_FINGERPRINT_QUERY = (
    "SELECT d.DocKey AS DocKey, COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
    "SUM(d.TransferedQty) AS TransferedSum, MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.SODTL AS d JOIN {database}.dbo.SO AS h ON h.DocKey = d.DocKey "
    "WHERE h.DocDate >= :from_date AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL "
    "GROUP BY d.DocKey"
)

FINISHED = (JOB_DONE, JOB_NEEDS_REVIEW)


def _model():
    from modules.autocount import models

    model = getattr(models, "AcDocFingerprint", None)
    if model is None:
        pytest.fail("modules.autocount.models has no `AcDocFingerprint` model yet")
    return model


def _helper():
    from modules.autocount import backfill

    helper = getattr(backfill, HELPER_NAME, None)
    if helper is None:
        pytest.fail(f"modules.autocount.backfill has no `{HELPER_NAME}` helper yet")
    return helper


# ── A1: the preset registry + storage rules ────────────────────────────────


def test_so_preset_carries_the_documented_fingerprint_query():
    assert getattr(SO_PRESET, "fingerprint_query", None) == SO_FINGERPRINT_QUERY


@pytest.mark.parametrize("preset, label", [(PO_PRESET, "PO"), (SPO_PRESET, "SPO")])
def test_po_and_spo_presets_fingerprint_podtl_with_the_header_cuts(preset, label):
    query = getattr(preset, "fingerprint_query", None)
    assert query, f"{label}_PRESET has no fingerprint_query"
    assert "{database}.dbo.PODTL AS d" in query, query
    assert "{database}.dbo.PO AS h ON h.DocKey = d.DocKey" in query, query
    for alias in ("d.DocKey AS DocKey", "COUNT(*) AS LineCount", "SUM(d.Qty) AS QtySum",
                  "SUM(d.TransferedQty) AS TransferedSum", "MAX(d.DtlKey) AS MaxDtlKey"):
        assert alias in query, f"{label}: missing {alias}"
    # The same cuts the header's OUTER APPLY makes - a pseudo-line or an
    # ItemCode-NULL line must not move the fingerprint either.
    assert "d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL" in query, query
    assert "h.DocDate >= :from_date" in query, query
    assert query.rstrip().endswith("GROUP BY d.DocKey"), query
    assert "SODTL" not in query


def test_every_document_preset_has_a_fingerprint_query_and_the_picker_substitutes_it():
    for entity_type, preset in DOCUMENT_PRESETS.items():
        assert getattr(preset, "fingerprint_query", None), entity_type
        [offer] = list_mapping_presets(entity_type, "AED_X")
        assert "fingerprintQuery" in offer, sorted(offer)
        assert offer["fingerprintQuery"] == preset.fingerprint_query.replace("{database}", "AED_X")
        assert "{database}" not in offer["fingerprintQuery"]


_HEADER_COLUMNS = {"DocKey": "string", "DocNo": "string", "Status": "string", "DocDate": "datetime"}
_LINE_COLUMNS = {"DtlKey": "string", "ItemCode": "string"}


def _raw_so_config(**overrides) -> Dict[str, object]:
    base = {
        "connectionId": "c1",
        "query": "SELECT DocKey, DocNo, Status, DocDate FROM SOHeader",
        "lineQuery": "SELECT DtlKey, ItemCode FROM SODetail WHERE DocKey = :doc_key",
        "keyColumns": ["DocKey"],
        "watermarkColumn": "DocDate",
        "comparedColumns": [],
        "fromDate": "2026-01-01",
        "docDateColumn": "DocDate",
        "lineKeyColumn": "DtlKey",
        "lineProductColumn": "ItemCode",
        "lineWarehouseColumn": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    base.update(overrides)
    return base


def test_validator_stores_a_document_tasks_fingerprint_query_verbatim():
    text = SO_FINGERPRINT_QUERY.replace("{database}", "AED_V")
    clean, errors = validate_source_config(
        ENTITY_SALES_ORDER, _raw_so_config(fingerprintQuery=text + " ;"),
        _HEADER_COLUMNS, line_columns=_LINE_COLUMNS,
    )
    assert errors == {}, errors
    # Same normalisation as `query`: outer whitespace + one trailing ';'.
    assert clean.get("fingerprintQuery") == text, clean.get("fingerprintQuery")


def test_validator_keeps_no_fingerprint_query_on_a_master_task():
    clean, _errors = validate_source_config(
        ENTITY_CUSTOMER,
        {"connectionId": "c1", "query": "SELECT AccNo FROM Debtor", "keyColumns": ["AccNo"],
         "watermarkColumn": None, "comparedColumns": [], "incrementalMinutes": 15,
         "reconcileMode": "dailyAt", "reconcileAt": "02:00",
         "fingerprintQuery": "SELECT 1"},
        {"AccNo": "string"},
    )
    assert clean.get("fingerprintQuery") is None


# ── A1 backfill + A2 migration ─────────────────────────────────────────────


def _api_company(db, *, database: str, tenant_id: str = DEFAULT_TENANT_ID) -> AcCompany:
    api = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name=f"AutoCount {database}",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=tenant_id, connection_id=api.id, database_name=database,
        company_name=f"{database} Sdn Bhd", name=database, is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _stored_config(db, company: AcCompany, entity_type: str, **source_overrides) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=entity_type,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    source = {
        "connectionId": "conn-x",
        "query": f"SELECT h.DocKey AS DocKey FROM {company.database_name}.dbo.SO AS h",
        "lineQuery": "SELECT d.DtlKey AS DtlKey FROM SODTL AS d WHERE d.DocKey = :doc_key",
        "keyColumns": ["DocKey"],
        "watermarkColumn": "LastModified",
        "comparedColumns": [],
        "fromDate": "2026-01-01",
        "docDateColumn": "DocDate",
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
    }
    source.update(source_overrides)
    config.source_config = source
    config.result_columns = ["DocKey"]
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_backfill_sets_the_preset_fingerprint_query_on_every_document_task_lacking_one(db):
    helper = _helper()
    company_a = _api_company(db, database="AED_FP_A")
    company_b = _api_company(db, database="AED_FP_B", tenant_id="tenant-b")
    so = _stored_config(db, company_a, ENTITY_SALES_ORDER)
    po = _stored_config(db, company_a, ENTITY_PURCHASE_ORDER)
    spo = _stored_config(db, company_b, ENTITY_SHIPPING_ORDER)
    master = _stored_config(db, company_a, ENTITY_CUSTOMER)
    ids = {so.id: (ENTITY_SALES_ORDER, "AED_FP_A"), po.id: (ENTITY_PURCHASE_ORDER, "AED_FP_A"),
           spo.id: (ENTITY_SHIPPING_ORDER, "AED_FP_B")}
    before = {cid: dict(db.get(AcEntityConfig, cid).source_config) for cid in ids}
    master_id = master.id
    db.expire_all()

    touched = helper(db, schema=None)
    assert touched == 3, touched
    db.expire_all()

    for cid, (entity_type, database) in ids.items():
        after = db.get(AcEntityConfig, cid)
        expected = DOCUMENT_PRESETS[entity_type].fingerprint_query.replace("{database}", database)
        assert after.source_config.get("fingerprintQuery") == expected, (cid, after.source_config)
        for key, value in before[cid].items():
            assert after.source_config.get(key) == value, key
    assert "fingerprintQuery" not in (db.get(AcEntityConfig, master_id).source_config or {})

    db.expire_all()
    assert helper(db, schema=None) == 0, "second pass must be a no-op"


def test_backfill_never_overwrites_a_customised_fingerprint_query_and_warns(db, caplog):
    helper = _helper()
    company = _api_company(db, database="AED_FP_C")
    custom = "SELECT d.DocKey AS DocKey, COUNT(*) AS LineCount FROM AED_FP_C.dbo.SODTL AS d GROUP BY d.DocKey"
    config = _stored_config(db, company, ENTITY_SALES_ORDER, fingerprintQuery=custom)
    config_id = config.id
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        touched = helper(db, schema=None)
    db.expire_all()

    assert touched == 0
    assert db.get(AcEntityConfig, config_id).source_config["fingerprintQuery"] == custom
    assert any(
        r.levelno >= logging.WARNING and config_id in r.getMessage() for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_backfill_is_a_no_op_on_a_schema_that_predates_its_tables():
    helper = _helper()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE ac_entity_config (id TEXT PRIMARY KEY, tenant_id TEXT, "
            "company_id TEXT, entity_type TEXT)"
        )
        conn.exec_driver_sql("INSERT INTO ac_entity_config VALUES ('cfg-1', 't', 'c', 'sales_order')")
    with engine.begin() as conn:
        assert helper(conn, schema=None) == 0
    bare = sa.create_engine("sqlite://")
    with bare.begin() as conn:
        assert helper(conn, schema=None) == 0


def test_update_tenant_runs_the_fingerprint_query_backfill(db):
    from modules.autocount.bootstrap import update_tenant

    company = _api_company(db, database="AED_FP_U")
    config = _stored_config(db, company, ENTITY_SALES_ORDER)
    config_id = config.id
    db.expire_all()

    update_tenant(db, DEFAULT_TENANT_ID, "0.6.1")
    db.commit()
    db.expire_all()

    assert db.get(AcEntityConfig, config_id).source_config.get("fingerprintQuery") == (
        SO_FINGERPRINT_QUERY.replace("{database}", "AED_FP_U")
    )


def test_manifest_version_is_bumped_past_0_6_1():
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    version = tuple(int(part) for part in manifest["version"].split("."))
    assert version > (0, 6, 1), f"manifest still at {manifest['version']}"


def test_revision_0017_adds_the_fingerprint_table_and_sweep_column_behind_a_postgres_guard():
    candidates = sorted(VERSIONS_DIR.glob("0017_*.py"))
    assert candidates, "no 0017_* module revision under modules/autocount/alembic/versions"
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    assert revision and len(revision.group(1)) <= 32, "revision id missing or > 32 chars"
    spec = importlib.util.spec_from_file_location("_ac_rev_0017", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS_REVISION
    assert "ac_doc_fingerprint" in text
    assert "last_fingerprint_sweep_at" in text
    assert "postgresql" in text, "module migrations are Postgres-guarded"
    assert HELPER_NAME in text, f"{path.name} does not run {HELPER_NAME}"
    for other in VERSIONS_DIR.glob("*.py"):
        if other == path:
            continue
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', other.read_text(), re.M)
        assert not (down and down.group(1) == PREVIOUS_REVISION), (
            f"{other.name} also chains onto {PREVIOUS_REVISION}"
        )


def test_fingerprint_model_is_keyed_by_tenant_company_entity_and_ref():
    model = _model()
    assert model.__tablename__ == "ac_doc_fingerprint"
    pk = [column.name for column in model.__table__.primary_key.columns]
    assert pk == ["tenant_id", "company_id", "entity_type", "source_ref"], pk
    columns = {column.name for column in model.__table__.columns}
    assert {"fingerprint", "seen_at"} <= columns, sorted(columns)
    assert model.__table__.c.fingerprint.nullable is False


def test_watermark_carries_last_fingerprint_sweep_at():
    assert "last_fingerprint_sweep_at" in AcWatermark.__table__.c, (
        sorted(c.name for c in AcWatermark.__table__.c)
    )


def test_document_fingerprint_is_a_sha_over_the_ordered_values_as_strings():
    from modules.autocount.sql_source import hashing

    fn = getattr(hashing, "document_fingerprint", None)
    assert fn is not None, "sql_source.hashing has no `document_fingerprint`"
    same = fn(["3", "10", "2", "77"])
    assert isinstance(same, str) and len(same) == 64 and int(same, 16) >= 0
    assert fn([3, 10, 2, 77]) == same, "values must hash AS STRINGS, whatever the driver returned"
    assert fn([Decimal("3"), Decimal("10"), Decimal("2"), 77]) == same
    assert fn(["10", "3", "2", "77"]) != same, "order is part of the fingerprint"
    assert fn(["3", "10", "2", None]) != same


def test_sweep_interval_setting_defaults_to_15_minutes_with_a_floor_of_1():
    assert getattr(settings, "autocount_fingerprint_sweep_minutes", None) == 15
    data = settings.model_dump()
    assert Settings.model_validate({**data, "autocount_fingerprint_sweep_minutes": 1}) \
        .autocount_fingerprint_sweep_minutes == 1
    with pytest.raises(ValidationError):
        Settings.model_validate({**data, "autocount_fingerprint_sweep_minutes": 0})


def test_changed_key_in_list_is_chunked_at_500():
    from modules.autocount.sql_source import source

    assert getattr(source, "FINGERPRINT_KEY_CHUNK", None) == 500


# ── A3/A4/A5: end to end on the SQL rig ────────────────────────────────────

RIG_FINGERPRINT_QUERY = (
    "SELECT d.doc_key AS DocKey, COUNT(*) AS LineCount, SUM(d.qty_ordered) AS QtySum, "
    "SUM(d.qty_delivered) AS TransferedSum, MAX(d.dtl_key) AS MaxDtlKey "
    "FROM so_line AS d JOIN so_header AS h ON h.doc_key = d.doc_key "
    "WHERE h.doc_date >= :from_date AND d.item_code IS NOT NULL AND d.qty_ordered IS NOT NULL "
    "GROUP BY d.doc_key"
)

DOCS = [
    ("D001", "SO-001", "open", "2026-08-01", "2026-08-01 09:00:00"),
    ("D002", "SO-002", "open", "2026-08-02", "2026-08-02 09:00:00"),
    ("D003", "SO-003", "open", "2026-08-03", "2026-08-03 09:00:00"),
]
LINES = [
    ("D001-1", "D001", "ITEM-A", "10", "0"),
    ("D002-1", "D002", "ITEM-B", "5", "0"),
    ("D003-1", "D003", "ITEM-C", "7", "0"),
]


class _Rig:
    def __init__(self, session_factory, *, fingerprint_query: str = RIG_FINGERPRINT_QUERY):
        self.db = session_factory()
        self.engine = sa.create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with self.engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE so_header (doc_key TEXT PRIMARY KEY, doc_no TEXT, status TEXT, "
                "doc_date TEXT, last_modified TEXT)"
            )
            conn.exec_driver_sql(
                "CREATE TABLE so_line (dtl_key TEXT PRIMARY KEY, doc_key TEXT, item_code TEXT, "
                "qty_ordered TEXT, qty_delivered TEXT)"
            )
            for row in DOCS:
                conn.exec_driver_sql("INSERT INTO so_header VALUES (?, ?, ?, ?, ?)", row)
            for row in LINES:
                conn.exec_driver_sql("INSERT INTO so_line VALUES (?, ?, ?, ?, ?)", row)

        self.statements = {"header": [], "line": [], "fingerprint": []}

        def before_cursor_execute(conn2, cursor, statement, parameters, context, executemany):
            if "GROUP BY d.doc_key" in statement:
                self.statements["fingerprint"].append((statement, parameters))
            elif "FROM so_line WHERE doc_key" in statement:
                self.statements["line"].append((statement, parameters))
            elif "so_header" in statement:
                self.statements["header"].append((statement, parameters))

        sa.event.listen(self.engine, "before_cursor_execute", before_cursor_execute)

        db = self.db
        self.company = _api_company(db, database="AED_FP_RIG")
        conn_row = Connection(
            tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="erp", name="Source DB",
            config_json={"dbType": "postgresql", "host": "db.example.com", "port": "5432",
                         "database": "AED_FP_RIG", "username": "readonly"},
            credentials_json=encrypt_secret({"password": "S3cret!Pa55"}), is_active=True,
        )
        db.add(conn_row)
        db.commit()
        db.refresh(conn_row)
        RUNTIME.put_engine(conn_row.id, self.engine)

        config = AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=self.company.id, entity_type=ENTITY_SALES_ORDER,
            source_impl=SOURCE_IMPL_SQL_DB,
        )
        config.source_config = {
            "connectionId": conn_row.id,
            "query": "SELECT doc_key, doc_no, status, doc_date, last_modified FROM so_header",
            "lineQuery": (
                "SELECT dtl_key, item_code, qty_ordered, qty_delivered FROM so_line "
                "WHERE doc_key = :doc_key"
            ),
            "fingerprintQuery": fingerprint_query,
            "keyColumns": ["doc_key"],
            "watermarkColumn": "last_modified",
            "comparedColumns": [],
            "fromDate": "2026-01-01",
            "docDateColumn": "doc_date",
            "lineKeyColumn": "dtl_key",
            "lineProductColumn": "item_code",
            "lineWarehouseColumn": None,
            "incrementalMinutes": 15,
            "reconcileMode": "dailyAt",
            "reconcileAt": "02:00",
        }
        config.result_columns = ["doc_key", "doc_no", "status", "doc_date", "last_modified"]
        config.etl_status = ETL_STATUS_ACTIVE
        db.add(config)
        db.commit()
        db.refresh(config)
        self.config = config

        def seed(scope, source_path, canonical_field, transform, *, required=False):
            db.add(AcFieldMapping(
                tenant_id=DEFAULT_TENANT_ID, company_id=self.company.id,
                entity_type=ENTITY_SALES_ORDER, scope=scope, source_path=source_path,
                canonical_field=canonical_field, transform=transform,
                is_required=required, is_enabled=True,
            ))

        seed(SCOPE_HEADER, "doc_no", "so_number", "string", required=True)
        seed(SCOPE_HEADER, "status", "status", "string", required=True)
        seed(SCOPE_LINE, "dtl_key", "source_ref", "string", required=True)
        seed(SCOPE_LINE, "item_code", "product_ref", "ref_product", required=True)
        seed(SCOPE_LINE, "qty_ordered", "qty_ordered", "decimal", required=True)
        seed(SCOPE_LINE, "qty_delivered", "qty_delivered", "decimal")
        db.commit()

    def reset_counts(self):
        for key in self.statements:
            self.statements[key].clear()

    def run(self, mode: str):
        self.reset_counts()
        job = JobService(self.db).create_and_enqueue(
            type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
            payload={"companyId": self.company.id, "entityType": ENTITY_SALES_ORDER, "mode": mode},
        )
        self.db.refresh(job)
        assert job.status in FINISHED, (job.status, job.error, job.logs_json)
        run = self.db.query(AcSyncRun).filter(AcSyncRun.job_id == job.id).one()
        return job, run

    def staged(self, job_id: str) -> Dict[str, AcStagedRecord]:
        return {
            record.source_ref.split(":")[-1]: record
            for record in self.db.query(AcStagedRecord).filter(
                AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.job_id == job_id,
            )
        }

    def hashes(self) -> Dict[str, str]:
        return {
            row.source_ref.split(":")[-1]: row.row_hash
            for row in self.db.query(AcRowHash).filter(
                AcRowHash.company_id == self.company.id, AcRowHash.entity_type == ENTITY_SALES_ORDER,
            )
        }

    def fingerprints(self) -> Dict[str, str]:
        model = _model()
        self.db.expire_all()
        return {
            row.source_ref.split(":")[-1]: row.fingerprint
            for row in self.db.query(model).filter(
                model.tenant_id == DEFAULT_TENANT_ID, model.company_id == self.company.id,
                model.entity_type == ENTITY_SALES_ORDER,
            )
        }

    def watermark(self) -> AcWatermark:
        self.db.expire_all()
        return (
            self.db.query(AcWatermark)
            .filter(AcWatermark.company_id == self.company.id, AcWatermark.entity_type == ENTITY_SALES_ORDER)
            .one()
        )

    def age_sweep(self, minutes: int):
        watermark = self.watermark()
        watermark.last_fingerprint_sweep_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        self.db.commit()

    def close(self):
        self.db.close()
        RUNTIME.dispose_all()


@pytest.fixture
def rig(session_factory):
    r = _Rig(session_factory)
    try:
        yield r
    finally:
        r.close()


def test_initial_load_and_reconcile_never_run_the_fingerprint_query(rig):
    _job, run1 = rig.run(RUN_MODE_MANUAL)
    assert run1.rows_scanned == 3
    assert rig.statements["fingerprint"] == [], "the initial load must not sweep"
    assert rig.fingerprints() == {}
    assert rig.watermark().last_fingerprint_sweep_at is None

    rig.run(RUN_MODE_RECONCILE)
    assert rig.statements["fingerprint"] == [], "a reconcile pass must not sweep"


def test_first_incremental_sweep_seeds_known_documents_without_fetching_them(rig):
    rig.run(RUN_MODE_MANUAL)
    hashes_before = rig.hashes()
    assert len(hashes_before) == 3

    job2, run2 = rig.run(RUN_MODE_INCREMENTAL)
    assert len(rig.statements["fingerprint"]) == 1, "the sweep runs the fingerprint query exactly once"
    assert set(rig.fingerprints()) == {"D001", "D002", "D003"}
    assert run2.rows_scanned == 0, "seeding must not re-fetch the known backlog"
    assert rig.statements["line"] == [], "no line fetch on a seed-only sweep"
    assert rig.staged(job2.id) == {}
    assert rig.hashes() == hashes_before
    assert rig.watermark().last_fingerprint_sweep_at is not None


def test_a_run_inside_the_sweep_interval_does_not_run_the_fingerprint_query(rig):
    rig.run(RUN_MODE_MANUAL)
    rig.run(RUN_MODE_INCREMENTAL)  # first sweep (seeds)
    swept_at = rig.watermark().last_fingerprint_sweep_at

    # A delivery lands, but the interval has not elapsed - this tick is a
    # plain watermark run.
    with rig.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE so_line SET qty_delivered = '4' WHERE dtl_key = 'D001-1'")
    job3, run3 = rig.run(RUN_MODE_INCREMENTAL)
    assert rig.statements["fingerprint"] == [], "sweep ran inside the interval"
    assert run3.rows_scanned == 0
    assert rig.staged(job3.id) == {}
    assert rig.watermark().last_fingerprint_sweep_at == swept_at


def test_a_delivery_that_leaves_the_header_untouched_is_restaged_by_the_sweep(rig):
    """SO419208: TransferedQty rises, SO.LastModified does not. The next
    incremental run past the interval must re-stage exactly that document as
    an UPDATE carrying the new qty_delivered, refresh its row hash and its
    fingerprint, and leave the two unchanged documents unfetched."""
    rig.run(RUN_MODE_MANUAL)
    rig.run(RUN_MODE_INCREMENTAL)  # first sweep (seeds)
    hashes_before = rig.hashes()
    fingerprints_before = rig.fingerprints()

    with rig.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE so_line SET qty_delivered = '4' WHERE dtl_key = 'D001-1'")
    rig.age_sweep(minutes=16)

    job4, run4 = rig.run(RUN_MODE_INCREMENTAL)
    assert len(rig.statements["fingerprint"]) == 1
    staged = rig.staged(job4.id)
    assert set(staged) == {"D001"}, sorted(staged)
    record = staged["D001"]
    assert record.op == STAGED_OP_UPSERT
    lines = record.canonical_json.get("lines") or []
    assert len(lines) == 1, record.canonical_json
    assert Decimal(str(lines[0]["qty_delivered"])) == Decimal("4"), lines[0]
    assert run4.updated_count == 1 and run4.added_count == 0
    assert len(rig.statements["line"]) == 1, "only the changed document's lines are fetched"

    # The header fetch was keyed on the changed DocKey, not a full scan.
    keyed = [
        (stmt, params) for stmt, params in rig.statements["header"]
        if " IN (" in stmt.upper() and "D001" in repr(params)
    ]
    assert keyed, [stmt for stmt, _ in rig.statements["header"]]

    hashes_after = rig.hashes()
    assert hashes_after["D001"] != hashes_before["D001"]
    assert hashes_after["D002"] == hashes_before["D002"]
    fingerprints_after = rig.fingerprints()
    assert fingerprints_after["D001"] != fingerprints_before["D001"]
    assert fingerprints_after["D002"] == fingerprints_before["D002"]
    assert fingerprints_after["D003"] == fingerprints_before["D003"]


def test_a_new_document_and_a_fingerprint_change_stage_in_the_same_incremental_run(rig):
    rig.run(RUN_MODE_MANUAL)
    rig.run(RUN_MODE_INCREMENTAL)
    with rig.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE so_line SET qty_delivered = '2' WHERE dtl_key = 'D002-1'")
        conn.exec_driver_sql(
            "INSERT INTO so_header VALUES ('D004', 'SO-004', 'open', '2026-08-04', '2026-09-01 09:00:00')"
        )
        conn.exec_driver_sql("INSERT INTO so_line VALUES ('D004-1', 'D004', 'ITEM-D', '1', '0')")
    rig.age_sweep(minutes=16)

    job, run = rig.run(RUN_MODE_INCREMENTAL)
    staged = rig.staged(job.id)
    assert set(staged) == {"D002", "D004"}, sorted(staged)
    assert run.added_count == 1 and run.updated_count == 1
    assert set(rig.fingerprints()) == {"D001", "D002", "D003", "D004"}, (
        "a document staged this run gets its fingerprint written"
    )


def test_a_fingerprint_query_error_fails_only_the_sweep(session_factory, caplog):
    rig = _Rig(session_factory, fingerprint_query="SELECT nonsense FROM missing_table GROUP BY d.doc_key")
    try:
        rig.run(RUN_MODE_MANUAL)
        with rig.engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO so_header VALUES ('D004', 'SO-004', 'open', '2026-08-04', '2026-09-01 09:00:00')"
            )
            conn.exec_driver_sql("INSERT INTO so_line VALUES ('D004-1', 'D004', 'ITEM-D', '1', '0')")
        with caplog.at_level(logging.WARNING):
            job, run = rig.run(RUN_MODE_INCREMENTAL)
        # The plain watermark path still delivered the new document.
        assert set(rig.staged(job.id)) == {"D004"}
        assert run.added_count == 1
        assert rig.fingerprints() == {}
        assert rig.watermark().last_fingerprint_sweep_at is None, (
            "a failed sweep must not be counted as done"
        )
        assert any(
            r.levelno >= logging.WARNING and "fingerprint" in r.getMessage().lower()
            for r in caplog.records
        ), [r.getMessage() for r in caplog.records]
    finally:
        rig.close()


def test_reconcile_drops_the_fingerprint_of_a_vanished_document_and_only_ours(rig):
    model = _model()
    rig.run(RUN_MODE_MANUAL)
    rig.run(RUN_MODE_INCREMENTAL)
    assert set(rig.fingerprints()) == {"D001", "D002", "D003"}
    # Another tenant's fingerprint for the SAME ref must be invisible to
    # this company's sweep and its reconcile delete.
    rig.db.add(model(
        tenant_id="tenant-b", company_id="company-b", entity_type=ENTITY_SALES_ORDER,
        source_ref="AED_FP_RIG:D003", fingerprint="f" * 64, seen_at=datetime.now(timezone.utc),
    ))
    rig.db.commit()

    with rig.engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM so_line WHERE doc_key = 'D003'")
        conn.exec_driver_sql("DELETE FROM so_header WHERE doc_key = 'D003'")
    job, _run = rig.run(RUN_MODE_RECONCILE)
    staged = rig.staged(job.id)
    assert staged.get("D003") is not None and staged["D003"].op == STAGED_OP_DELETE
    assert set(rig.fingerprints()) == {"D001", "D002"}
    foreign = rig.db.query(model).filter(model.tenant_id == "tenant-b").all()
    assert len(foreign) == 1 and foreign[0].fingerprint == "f" * 64


def test_every_fingerprint_row_is_scoped_to_the_tenant_and_company(rig):
    model = _model()
    rig.run(RUN_MODE_MANUAL)
    rig.run(RUN_MODE_INCREMENTAL)
    rows = rig.db.query(model).all()
    assert rows and all(
        (row.tenant_id, row.company_id, row.entity_type)
        == (DEFAULT_TENANT_ID, rig.company.id, ENTITY_SALES_ORDER)
        for row in rows
    )
    assert all(row.seen_at is not None for row in rows)
    assert all(isinstance(row.fingerprint, str) and len(row.fingerprint) == 64 for row in rows)
    assert len({row.fingerprint for row in rows}) == 3, "three different line sets, three fingerprints"
