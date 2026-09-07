"""SPO ``container_number`` from AutoCount ``PO.Ref`` (lane feat/spo-container-number).

Red tests written BEFORE the coder, to exactly this contract:

1. ``presets._PO_HEADER_QUERY`` selects ``h.Ref AS Ref`` (no UDF columns in
   the generic query - per-company UDF routing is a backlog follow-up).
2. ``CanonicalShippingOrder.container_number: Optional[str]`` (max 100),
   sourced from ``Ref``; sent to Sorento ONLY at contract major >= 2 (the
   same gate as the existing ``FALLBACK_FIELDS``): a v1 payload omits it, a
   v2 payload carries it when present and OMITS it when None (addendum
   section 11: absent = leave alone, null = clear). ``CanonicalPurchaseOrder``
   gets NO such field; a PO payload never carries it at any version.
3. ``SPO_PRESET.header`` gains ``PresetField("Ref", "container_number",
   "string")`` (not required); ``PO_PRESET.header`` does not.
4. Backfill for EXISTING tasks (module Alembic 0016 + the same helper on the
   ``update_tenant`` path, both schema-tolerant), for every stored
   ``shipping_order`` entity config: (a) add an enabled ``Ref ->
   container_number`` header mapping row when absent; (b) when the stored
   header query is byte-identical to the OLD preset text (with the company's
   own database name substituted - that is how the "Use preset" picker hands
   it out) replace it with the NEW preset text and put ``Ref`` into
   ``result_columns`` (the compared set derives from it, so without that the
   new column never enters the row hash); a customised query is left alone
   and a WARNING naming the config id is logged.

   Stored-vs-referenced finding: the header query is STORED per task in
   ``AcEntityConfig.source_config["query"]`` (``EtlService`` ``clean``
   dict); ``DocumentPreset.header_query`` is read ONLY by
   ``list_mapping_presets`` (the picker) with ``{database}`` substituted.
   Nothing references the preset at run time, so an existing task keeps
   the old text until the backfill rewrites it.
5. Re-offer: a document whose ONLY change is a newly selected ``Ref`` value
   is re-staged as an update on the next run and its canonical carries the
   container number.
6. Addendum section 3 documents ``container_number``; the backlog carries
   the ``PO.UDF_ShipOrder`` routing follow-up.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import re

import pytest
import sqlalchemy as sa
from annotated_types import MaxLen
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool

import modules.autocount as autocount_module
from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, JOB_NEEDS_REVIEW
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SHIPPING_ORDER,
    CanonicalPurchaseOrder,
    CanonicalShippingOrder,
    CanonicalShippingOrderLine,
)
from modules.autocount.mapping import SCOPE_HEADER, SCOPE_LINE, profile_for
from modules.autocount.models import (
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    SOURCE_IMPL_SQL_DB,
    STAGED_OP_UPSERT,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcStagedRecord,
    AcSyncRun,
)
from modules.autocount.presets import PO_PRESET, SPO_PRESET, PresetField, _PO_HEADER_QUERY
from modules.autocount.sinks_sorento import SorentoSink
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sync import AUTOCOUNT_SYNC

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"
REPO_ROOT = MODULE_ROOT.parents[2]
ADDENDUM = (
    REPO_ROOT / "documentation" / "plans" / "sprint-5"
    / "02-autocount-document-mapping-sorento-addendum.md"
)
BACKLOG = REPO_ROOT / "documentation" / "backlogs" / "backlog.md"

HELPER_NAME = "backfill_shipping_order_container_number"
PREVIOUS_REVISION = "0015_autocount_run_requests"

# The generic PO/SPO header query EXACTLY as shipped before this lane (frozen
# here on purpose: the backfill's byte-identity check is against THIS text,
# with `{database}` substituted the way the picker does it).
OLD_PO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, s.AutoKey AS CreditorAutoKey, "
    "h.PurchaseAgent AS SalesAgent, h.DocDate AS DocDate, "
    "CAST(l.FirstDeliveryDate AS date) AS ExpectedDate, h.Cancelled AS Cancelled, "
    "h.CreditorCode AS CreditorCode, h.CreditorName AS CreditorName, "
    "h.CurrencyCode AS CurrencyCode, h.LastModified AS LastModified, "
    "l.LineCount AS LineCount, l.QtySum AS QtySum, l.TransferedSum AS TransferedSum, "
    "l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey "
    "FROM {database}.dbo.PO AS h "
    "LEFT JOIN {database}.dbo.Creditor AS s ON s.AccNo = h.CreditorCode "
    "OUTER APPLY ("
    "SELECT MIN(d.DeliveryDate) AS FirstDeliveryDate, COUNT(*) AS LineCount, "
    "SUM(d.Qty) AS QtySum, SUM(d.TransferedQty) AS TransferedSum, "
    "SUM(d.SubTotal) AS SubTotalSum, MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.PODTL AS d "
    "WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
    ") AS l"
)


def _backfill():
    from modules.autocount import backfill

    helper = getattr(backfill, HELPER_NAME, None)
    if helper is None:
        pytest.fail(f"modules.autocount.backfill has no `{HELPER_NAME}` helper yet")
    return helper


# ── 1 + 3: the preset registry ─────────────────────────────────────────────


def test_po_header_query_selects_ref_and_no_udf_column():
    assert "h.Ref AS Ref" in _PO_HEADER_QUERY, _PO_HEADER_QUERY
    assert "UDF" not in _PO_HEADER_QUERY, (
        "the generic query must not select a per-company UDF column - "
        "that routing is the backlog follow-up"
    )
    # Both document presets keep sharing the one generic PO header query.
    assert SPO_PRESET.header_query == _PO_HEADER_QUERY
    assert PO_PRESET.header_query == _PO_HEADER_QUERY


def test_spo_preset_header_maps_ref_to_container_number_not_required():
    rows = [field for field in SPO_PRESET.header if field.source_path == "Ref"]
    assert rows == [PresetField("Ref", "container_number", "string")], (
        f"SPO_PRESET.header rows sourced from Ref: {rows}"
    )
    assert rows[0].required is False
    assert rows[0].formula is None


def test_po_preset_header_maps_neither_ref_nor_container_number():
    sources = {field.source_path for field in PO_PRESET.header}
    targets = {field.canonical_field for field in PO_PRESET.header}
    assert "Ref" not in sources, sorted(sources)
    assert "container_number" not in targets, sorted(targets)


# ── 2: the canonical shape + the contract gate ─────────────────────────────


def test_shipping_order_declares_container_number_optional_str_max_100():
    field = CanonicalShippingOrder.model_fields.get("container_number")
    assert field is not None, "CanonicalShippingOrder has no `container_number` field"
    assert field.default is None
    assert any(isinstance(m, MaxLen) and m.max_length == 100 for m in field.metadata), (
        f"container_number must carry max_length=100 - metadata {field.metadata}"
    )
    assert CanonicalShippingOrder(
        source_ref="k", spo_number="SPO-1", status="open", container_number="MSKU1234567"
    ).container_number == "MSKU1234567"
    with pytest.raises(ValidationError):
        CanonicalShippingOrder(
            source_ref="k", spo_number="SPO-1", status="open", container_number="C" * 101
        )


def test_purchase_order_has_no_container_number_field():
    assert "container_number" not in CanonicalPurchaseOrder.model_fields
    assert "container_number" not in profile_for(ENTITY_PURCHASE_ORDER).record_fields()


def test_mapping_profile_offers_container_number_as_a_shipping_order_header_target():
    assert "container_number" in profile_for(ENTITY_SHIPPING_ORDER).record_fields()


def _spo(**overrides) -> CanonicalShippingOrder:
    fields = dict(
        source_ref="AED:PO:77", spo_number="SPO-00077", status="open",
        supplier_code="400-J001", container_number="MSKU1234567",
        lines=[
            CanonicalShippingOrderLine(
                source_ref="AED:PO:77:1", product_ref="AED:ITEM:1", qty_ordered=1,
            )
        ],
    )
    fields.update(overrides)
    return CanonicalShippingOrder(**fields)


def test_v1_payload_omits_container_number_even_when_set():
    payload = _spo().sink_payload(contract_version=1)
    assert "container_number" not in payload, sorted(payload)
    # The existing v1 shape is untouched.
    assert payload["spo_number"] == "SPO-00077"
    assert "supplier_code" not in payload


def test_v2_payload_carries_container_number_when_present():
    payload = _spo().sink_payload(contract_version=2)
    assert payload.get("container_number") == "MSKU1234567", sorted(payload)
    # Same gate as the existing fallback fields - they still travel too.
    assert payload["supplier_code"] == "400-J001"


def test_v2_payload_omits_container_number_when_none():
    """Addendum section 11 (2.1 semantics): absent = leave Sorento's value
    alone, ``null`` = clear it. A document with no ``Ref`` must therefore NOT
    send ``"container_number": null``."""
    payload = _spo(container_number=None).sink_payload(contract_version=2)
    assert "container_number" not in payload, sorted(payload)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_purchase_order_payload_never_carries_container_number(version):
    po = CanonicalPurchaseOrder(
        source_ref="AED:PO:5", po_number="PO-00005", status="open", supplier_code="400-J001",
        **{"container_number": "MSKU1234567"},
    )
    payload = po.sink_payload(contract_version=version)
    assert "container_number" not in payload, sorted(payload)


@pytest.mark.parametrize(
    "version, expected", [(1, False), (2, True), (3, True)],
)
def test_sorento_sink_projects_container_number_through_the_contract_gate(version, expected):
    """The sink's own projection (``_to_records`` -> ``sink_payload``) is the
    wire; the gate is the connection's stored contract major, never Sorento's
    advertised version."""
    sink = SorentoSink(
        base_url="http://x", api_key="sk_test", entity_type=ENTITY_SHIPPING_ORDER,
        company_code="AED", contract_version=version,
    )
    records = sink._to_records([_spo()])
    assert len(records) == 1
    assert ("container_number" in records[0]) is expected, sorted(records[0])
    if expected:
        assert records[0]["container_number"] == "MSKU1234567"


# ── 4: backfill for existing tasks ─────────────────────────────────────────


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


def _document_config(
    db, company: AcCompany, entity_type: str, *, query: str, result_columns=None,
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=entity_type,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x",
        "query": query,
        "lineQuery": "SELECT d.DtlKey AS DtlKey FROM PODTL AS d WHERE d.DocKey = :doc_key",
        "keyColumns": ["DocKey"],
        "watermarkColumn": "LastModified",
        "comparedColumns": [],
        "fromDate": "2026-01-01",
        "docDateColumn": "DocDate",
        "filterFormula": 'startswith(upper(trim(DocNo)), "SPO-")',
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileAt": "02:00",
    }
    config.result_columns = list(
        result_columns or ["DocKey", "DocNo", "Cancelled", "DocDate", "LastModified"]
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _ref_rows(db, company_id: str, entity_type: str = ENTITY_SHIPPING_ORDER):
    return (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == entity_type,
            AcFieldMapping.scope == SCOPE_HEADER,
            AcFieldMapping.source_path == "Ref",
        )
        .all()
    )


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_backfill_adds_an_enabled_ref_row_to_every_shipping_order_task_across_tenants(db):
    helper = _backfill()
    company_a = _api_company(db, database="AED_A")
    company_b = _api_company(db, database="AED_B", tenant_id="tenant-b")
    spo_a = _document_config(
        db, company_a, ENTITY_SHIPPING_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_A"),
    )
    spo_b = _document_config(
        db, company_b, ENTITY_SHIPPING_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_B"),
    )
    po_a = _document_config(
        db, company_a, ENTITY_PURCHASE_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_A"),
    )
    assert spo_a.id and spo_b.id and po_a.id
    db.expire_all()

    touched = helper(db, schema=None)
    assert touched >= 2, f"helper reported {touched} rows touched"
    db.expire_all()

    for company in (company_a, company_b):
        rows = _ref_rows(db, company.id)
        assert len(rows) == 1, f"{company.database_name}: {len(rows)} Ref rows"
        row = rows[0]
        assert row.tenant_id == company.tenant_id
        assert row.canonical_field == "container_number"
        assert row.transform == "string"
        assert row.is_enabled is True
        assert row.is_required is False
        assert row.formula is None

    assert _ref_rows(db, company_a.id, ENTITY_PURCHASE_ORDER) == [], (
        "a purchase_order task must never get the Ref -> container_number row"
    )

    # Idempotent: a second pass adds nothing.
    db.expire_all()
    helper(db, schema=None)
    db.expire_all()
    assert len(_ref_rows(db, company_a.id)) == 1
    assert len(_ref_rows(db, company_b.id)) == 1


def test_backfill_leaves_an_existing_ref_row_alone(db):
    helper = _backfill()
    company = _api_company(db, database="AED_HAS")
    _document_config(
        db, company, ENTITY_SHIPPING_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_HAS"),
    )
    existing = AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SHIPPING_ORDER,
        scope=SCOPE_HEADER, source_path="Ref", canonical_field="container_number",
        transform="string", formula='upper(trim(Ref))', is_enabled=False, is_required=False,
    )
    db.add(existing)
    db.commit()
    existing_id = existing.id
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    rows = _ref_rows(db, company.id)
    assert [row.id for row in rows] == [existing_id], "the operator's own row was duplicated"
    assert rows[0].is_enabled is False, "the operator's disabled row was flipped"
    assert rows[0].formula == "upper(trim(Ref))"


def test_backfill_replaces_a_byte_identical_old_preset_query_with_the_new_text(db):
    helper = _backfill()
    company = _api_company(db, database="AED_OLD")
    config = _document_config(
        db, company, ENTITY_SHIPPING_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_OLD"),
    )
    before = dict(config.source_config)
    config_id = config.id
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    expected = _PO_HEADER_QUERY.replace("{database}", "AED_OLD")
    assert "h.Ref AS Ref" in after.source_config["query"], after.source_config["query"]
    assert after.source_config["query"] == expected
    assert "{database}" not in after.source_config["query"]
    # Only the query moved - every other stored key is byte-identical.
    for key, value in before.items():
        if key != "query":
            assert after.source_config.get(key) == value, key
    # The compared set derives from result_columns (minus keys); Ref must be
    # in it or the new column never enters the row hash.
    assert "Ref" in (after.result_columns or []), after.result_columns
    assert after.result_columns[:5] == ["DocKey", "DocNo", "Cancelled", "DocDate", "LastModified"]


def test_backfill_leaves_a_customised_query_alone_and_warns_naming_the_config_id(db, caplog):
    helper = _backfill()
    company = _api_company(db, database="AED_CUSTOM")
    customised = (
        OLD_PO_HEADER_QUERY.replace("{database}", "AED_CUSTOM")
        + " WHERE h.DocDate >= '2025-01-01'"
    )
    config = _document_config(
        db, company, ENTITY_SHIPPING_ORDER, query=customised,
    )
    config_id = config.id
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == customised, "a customised query was overwritten"
    assert "Ref" not in (after.result_columns or [])
    warnings = [
        record for record in caplog.records
        if record.levelno >= logging.WARNING and config_id in record.getMessage()
    ]
    assert warnings, (
        "no WARNING names the customised config id "
        f"{config_id}; warnings seen: {[r.getMessage() for r in caplog.records]}"
    )
    # (a) is independent of (b): the mapping row still lands.
    assert len(_ref_rows(db, company.id)) == 1


def test_backfill_ignores_a_query_that_matches_another_companys_database(db):
    """Byte identity is against the OWN company's database name - a query
    pasted from a sibling company's picker is a customisation, not the
    preset."""
    helper = _backfill()
    company = _api_company(db, database="AED_MINE")
    config = _document_config(
        db, company, ENTITY_SHIPPING_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_OTHER"),
    )
    config_id = config.id
    stored = config.source_config["query"]
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    assert db.get(AcEntityConfig, config_id).source_config["query"] == stored


def test_backfill_is_a_no_op_on_a_schema_that_predates_its_tables():
    """Runs at ANY module stamp (0016 and ``update_tenant`` both call it), so
    a bind without ``ac_field_mapping`` / without ``source_config`` must be a
    clean 0, never an UndefinedColumn / OperationalError."""
    helper = _backfill()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE ac_entity_config (id TEXT PRIMARY KEY, tenant_id TEXT, "
            "company_id TEXT, entity_type TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO ac_entity_config VALUES ('cfg-1', 't', 'c', 'shipping_order')"
        )
    with engine.begin() as conn:
        assert helper(conn, schema=None) == 0

    bare = sa.create_engine("sqlite://")
    with bare.begin() as conn:
        assert helper(conn, schema=None) == 0


def test_update_tenant_runs_the_container_number_backfill(db):
    """The App Store update path (an already-installed tenant moving past the
    version that ships this lane) delivers both halves without Alembic."""
    from modules.autocount.bootstrap import update_tenant

    company = _api_company(db, database="AED_UPD")
    config = _document_config(
        db, company, ENTITY_SHIPPING_ORDER,
        query=OLD_PO_HEADER_QUERY.replace("{database}", "AED_UPD"),
    )
    config_id = config.id
    db.expire_all()

    update_tenant(db, DEFAULT_TENANT_ID, "0.6.0")
    db.commit()
    db.expire_all()

    rows = _ref_rows(db, company.id)
    assert len(rows) == 1 and rows[0].canonical_field == "container_number"
    assert rows[0].is_enabled is True
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _PO_HEADER_QUERY.replace("{database}", "AED_UPD")
    assert "Ref" in (after.result_columns or [])


def test_manifest_version_is_bumped_past_0_6_0():
    """``update_tenant`` only runs when the manifest version moves - without
    the bump an already-installed tenant never receives the backfill."""
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    version = tuple(int(part) for part in manifest["version"].split("."))
    assert version > (0, 6, 0), f"manifest still at {manifest['version']}"


def test_revision_0016_chains_onto_0015_and_calls_the_helper():
    candidates = sorted(VERSIONS_DIR.glob("0016_*.py"))
    assert candidates, "no 0016_* module revision under modules/autocount/alembic/versions"
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    assert revision and len(revision.group(1)) <= 32, "revision id missing or > 32 chars"
    spec = importlib.util.spec_from_file_location("_ac_rev_0016", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS_REVISION
    assert HELPER_NAME in text, f"{path.name} does not call {HELPER_NAME}"
    # No sibling revision may also claim 0015 as its parent (single head).
    for other in VERSIONS_DIR.glob("*.py"):
        if other == path:
            continue
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', other.read_text(), re.M)
        assert not (down and down.group(1) == PREVIOUS_REVISION), (
            f"{other.name} also chains onto {PREVIOUS_REVISION}"
        )


# ── 5: re-offer - a newly selected Ref re-stages the document ───────────────


def _spo_rig(session_factory):
    """A self-contained SPO document task on a SQLite source. The header table
    starts WITHOUT a ref column, exactly like a task saved before this lane."""
    db = session_factory()
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE po_header (doc_key TEXT PRIMARY KEY, doc_no TEXT, "
            "status TEXT, doc_date TEXT, last_modified TEXT)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE po_line (dtl_key TEXT PRIMARY KEY, doc_key TEXT, "
            "item_code TEXT, qty_ordered TEXT)"
        )
        for row in [
            ("D001", "SPO-00001", "open", "2026-08-01", "2026-08-01 09:00:00"),
            ("D002", "SPO-00002", "open", "2026-08-02", "2026-08-02 09:00:00"),
        ]:
            conn.exec_driver_sql("INSERT INTO po_header VALUES (?, ?, ?, ?, ?)", row)
        for row in [("D001-1", "D001", "ITEM-A", "10"), ("D002-1", "D002", "ITEM-B", "5")]:
            conn.exec_driver_sql("INSERT INTO po_line VALUES (?, ?, ?, ?)", row)

    company = _api_company(db, database="AED_SPO")
    conn_row = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="erp", name="Source DB",
        config_json={"dbType": "postgresql", "host": "db.example.com", "port": "5432",
                     "database": "AED_SPO", "username": "readonly"},
        credentials_json=encrypt_secret({"password": "S3cret!Pa55"}), is_active=True,
    )
    db.add(conn_row)
    db.commit()
    db.refresh(conn_row)
    RUNTIME.put_engine(conn_row.id, engine)

    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SHIPPING_ORDER,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": conn_row.id,
        "query": "SELECT doc_key, doc_no, status, doc_date, last_modified FROM po_header",
        "lineQuery": "SELECT dtl_key, item_code, qty_ordered FROM po_line WHERE doc_key = :doc_key",
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
    db.add(config)
    db.commit()
    db.refresh(config)

    def seed(scope, source_path, canonical_field, transform, *, required=False):
        db.add(AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
            entity_type=ENTITY_SHIPPING_ORDER, scope=scope, source_path=source_path,
            canonical_field=canonical_field, transform=transform,
            is_required=required, is_enabled=True,
        ))

    seed(SCOPE_HEADER, "doc_no", "spo_number", "string", required=True)
    seed(SCOPE_HEADER, "status", "status", "string", required=True)
    seed(SCOPE_LINE, "dtl_key", "source_ref", "string", required=True)
    seed(SCOPE_LINE, "item_code", "product_ref", "ref_product", required=True)
    seed(SCOPE_LINE, "qty_ordered", "qty_ordered", "decimal", required=True)
    db.commit()
    return db, company, config, engine, seed


def _run(db, company, mode):
    job = JobService(db).create_and_enqueue(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_SHIPPING_ORDER, "mode": mode},
    )
    db.refresh(job)
    return job


def _staged_for(db, job_id):
    return {
        record.source_ref: record
        for record in db.query(AcStagedRecord).filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.job_id == job_id,
        )
    }


def test_a_document_whose_only_change_is_a_newly_selected_ref_is_restaged_as_an_update(
    session_factory,
):
    db, company, config, engine, seed = _spo_rig(session_factory)
    try:
        job1 = _run(db, company, RUN_MODE_MANUAL)
        assert job1.status in (JOB_DONE, JOB_NEEDS_REVIEW), (job1.status, job1.error, job1.logs_json)
        first = _staged_for(db, job1.id)
        assert len(first) == 2, sorted(first)
        assert all(
            (r.canonical_json or {}).get("container_number") is None for r in first.values()
        ), "no document carries a container number before Ref is selected"

        # The operator's next save (or the backfill) selects Ref; the source
        # gains the column and exactly one document carries a value. Nothing
        # else about either document changes - not even last_modified.
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE po_header ADD COLUMN ref TEXT")
            conn.exec_driver_sql("UPDATE po_header SET ref = 'MSKU1234567' WHERE doc_key = 'D001'")
        config.source_config = {
            **config.source_config,
            "query": (
                "SELECT doc_key, doc_no, status, doc_date, last_modified, ref AS Ref "
                "FROM po_header"
            ),
        }
        config.result_columns = [*config.result_columns, "Ref"]
        seed(SCOPE_HEADER, "Ref", "container_number", "string")
        db.commit()

        job2 = _run(db, company, RUN_MODE_RECONCILE)
        assert job2.status in (JOB_DONE, JOB_NEEDS_REVIEW), (job2.status, job2.error, job2.logs_json)
        run2 = db.query(AcSyncRun).filter(AcSyncRun.job_id == job2.id).one()
        second = _staged_for(db, job2.id)
        changed = [ref for ref in second if ref.endswith("D001")]
        assert changed, (
            f"D001 was not re-staged - run2 scanned={run2.rows_scanned} "
            f"updated={run2.updated_count} staged={sorted(second)}"
        )
        record = second[changed[0]]
        assert record.op == STAGED_OP_UPSERT
        assert record.canonical_json.get("container_number") == "MSKU1234567", record.canonical_json
        assert record.canonical_json.get("spo_number") == "SPO-00001"
        assert run2.updated_count >= 1
        assert run2.added_count == 0
    finally:
        db.close()
        RUNTIME.dispose_all()


# ── 6: the cross-repo contract + the backlog follow-up ─────────────────────


def _section(text: str, heading_prefix: str) -> str:
    start = text.index(heading_prefix)
    rest = text[start + len(heading_prefix):]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def test_addendum_section_3_documents_container_number_from_po_ref():
    text = ADDENDUM.read_text()
    section = _section(text, "## 3. Shipping orders as an ingest entity")
    assert "container_number" in section, "addendum section 3 does not mention container_number"
    line = next(
        (ln for ln in section.splitlines() if "container_number" in ln), ""
    )
    assert "Ref" in line, line
    assert "2.1" in line, line
    assert "purchase_orders" not in line or "shipping_orders" in line, line


def test_backlog_carries_the_udf_shiporder_routing_follow_up():
    text = BACKLOG.read_text()
    assert "UDF_ShipOrder" in text, "no backlog entry for the PO.UDF_ShipOrder routing follow-up"
    row = next(ln for ln in text.splitlines() if "UDF_ShipOrder" in ln)
    assert re.search(r"BL-SS-\d+", row), row
