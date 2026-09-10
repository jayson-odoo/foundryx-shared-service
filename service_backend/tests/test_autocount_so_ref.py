"""AutoCount SO `Ref` on the Sorento feed (sprint-5/07, lane sprint-5/07-autocount-so-ref-repush).

RED tests written BEFORE the coder, from the UAC
(`documentation/plans/sprint-5/07-autocount-so-ref-repush-acceptance-criteria.md`)
Groups A (AC-07-01..06) and B (AC-07-07..12), modelled on
`test_autocount_spo_container_number.py` (the same `Ref` -> new-field shape,
one entity earlier) and `test_autocount_line_linkage_backfill.py` (the
existing-task backfill idiom). AC-07-06/AC-07-12 are `[T]` (docs / live
replay) - not testable here, out of scope for this file.

Where the target symbol does not exist yet (`backfill.backfill_sales_order_ref`),
the test imports it LOCALLY via a `pytest.fail`-guarded helper so a missing
name fails only the tests that need it (never the whole module's collection).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import pathlib
import re

import pytest
import sqlalchemy as sa
from annotated_types import MaxLen
from pydantic import ValidationError

import modules.autocount as autocount_module
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    CanonicalPurchaseOrder,
    CanonicalSalesOrder,
    CanonicalShippingOrder,
)
from modules.autocount.mapping import (
    SCOPE_HEADER,
    SCOPE_LINE,
    MappingEngine,
    MappingRow,
    build_mapping_rows_for_run,
    flat_profile,
)
from modules.autocount.mapping_catalog import (
    SORENTO_FIELDS,
    accepted_field_names,
)
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.presets import (
    PO_PRESET,
    SO_PRESET,
    SPO_PRESET,
    PresetField,
    _PO_HEADER_QUERY,
    _SO_FINGERPRINT_QUERY,
    _SO_HEADER_QUERY,
    _SO_LINE_QUERY,
    list_mapping_presets,
)

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"

HELPER_NAME = "backfill_sales_order_ref"
PREVIOUS_REVISION = "0018_autocount_line_linkage"

# ── the OLD SO header query, pinned VERBATIM (0016/0018 precedent) ──────────
#
# Copied byte-for-byte from `presets.py`'s CURRENT `_SO_HEADER_QUERY` at the
# moment this lane starts. Once the coder edits the preset to add `h.Ref AS
# Ref`, THIS constant stays the OLD text forever - the backfill's
# byte-identity check (AC-07-08) is against exactly this, independent of any
# later preset edit.
_OLD_SO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, c.AutoKey AS DebtorAutoKey, "
    "h.SalesAgent AS SalesAgent, h.DocDate AS DocDate, "
    "h.UDF_DelDate AS RequestedDeliveryDate, h.Note AS Note, "
    "h.Cancelled AS Cancelled, h.DebtorCode AS DebtorCode, "
    "h.DebtorName AS DebtorName, h.LastModified AS LastModified, "
    "l.LineCount AS LineCount, l.QtySum AS QtySum, l.TransferedSum AS TransferedSum, "
    "l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey "
    "FROM {database}.dbo.SO AS h "
    "LEFT JOIN {database}.dbo.Debtor AS c ON c.AccNo = h.DebtorCode "
    "OUTER APPLY ("
    "SELECT COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum, "
    "SUM(d.TransferedQty) AS TransferedSum, SUM(d.SubTotal) AS SubTotalSum, "
    "MAX(d.DtlKey) AS MaxDtlKey "
    "FROM {database}.dbo.SODTL AS d "
    "WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
    ") AS l"
)
# The NEW text per plan section 2.1: "one new select item" right after
# `h.Note AS Note,`. Derived by substitution (never hand-retyped) so this
# constant can never itself drift from the OLD one above.
_NEW_SO_HEADER_QUERY = _OLD_SO_HEADER_QUERY.replace(
    "h.Note AS Note, ", "h.Note AS Note, h.Ref AS Ref, ", 1
)
assert _NEW_SO_HEADER_QUERY != _OLD_SO_HEADER_QUERY, "the substitution above did not fire"


def _fp(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


# Byte-unchanged siblings (AC-07-01) - pinned by fingerprint (computed against
# the CURRENT, pre-lane values) rather than a second giant literal, so an
# accidental edit to any of these while the coder is touching `_SO_HEADER_
# QUERY` fails loudly here instead of silently reaching a live PO/SPO task.
_PO_HEADER_QUERY_FINGERPRINT = (
    "828e327359a159b0931f4923e7d8a55de5e422c0250c69730f1be68db939e04a"
)
_SO_LINE_QUERY_FINGERPRINT = (
    "46935582aaa88d6c5e8b5d7cc2de4283cca994af227e05fe45e7a037d6a7bbb2"
)
_SO_FINGERPRINT_QUERY_FINGERPRINT = (
    "e54b9cb32c3483c7649a5cf1a6665144d7580f2d5a97893e9b6ed7b1b286750f"
)
_PO_PRESET_FINGERPRINT = (
    "00ec63627403c3dcd4237fa483fe93c1e2423ddc0eea2972ee9e5653d4e8ecde"
)
_SPO_PRESET_FINGERPRINT = (
    "60312b8f728464663dfa837234c305383f825ead7b19a23a71a477e7eebe72d3"
)


def _backfill():
    from modules.autocount import backfill

    helper = getattr(backfill, HELPER_NAME, None)
    if helper is None:
        pytest.fail(f"modules.autocount.backfill has no `{HELPER_NAME}` helper yet")
    return helper


# ═════════════════════════ Group A - preset, canonical, wire ════════════════


# ── AC-07-01 ─────────────────────────────────────────────────────────────────


def test_so_header_query_selects_ref_after_note():
    assert "h.Ref AS Ref" in _SO_HEADER_QUERY, _SO_HEADER_QUERY
    assert _SO_HEADER_QUERY == _NEW_SO_HEADER_QUERY, (
        "presets._SO_HEADER_QUERY must select `h.Ref AS Ref` right after "
        "`h.Note AS Note` and be otherwise byte-identical to the OLD text"
    )


def test_so_preset_header_carries_a_ref_field_not_required():
    rows = [field for field in SO_PRESET.header if field.source_path == "Ref"]
    assert rows == [PresetField("Ref", "ref", "string")], (
        f"SO_PRESET.header rows sourced from Ref: {rows}"
    )
    assert rows[0].required is False
    assert rows[0].formula is None


def test_list_mapping_presets_headerquery_carries_ref_for_sales_order():
    payload = list_mapping_presets(ENTITY_SALES_ORDER, "AED_TEST")
    assert payload, "no preset registered for sales_order"
    assert "h.Ref AS Ref" in payload[0]["headerQuery"], payload[0]["headerQuery"]


def test_po_spo_and_so_line_fingerprint_queries_are_byte_unchanged():
    assert _fp(_PO_HEADER_QUERY) == _PO_HEADER_QUERY_FINGERPRINT, (
        "_PO_HEADER_QUERY changed - this lane touches SO only"
    )
    assert _fp(_SO_LINE_QUERY) == _SO_LINE_QUERY_FINGERPRINT, (
        "_SO_LINE_QUERY changed - this lane touches the SO HEADER query only"
    )
    assert _fp(_SO_FINGERPRINT_QUERY) == _SO_FINGERPRINT_QUERY_FINGERPRINT, (
        "_SO_FINGERPRINT_QUERY changed - this lane touches the SO HEADER query only"
    )
    assert _fp(PO_PRESET) == _PO_PRESET_FINGERPRINT, "PO_PRESET changed"
    assert _fp(SPO_PRESET) == _SPO_PRESET_FINGERPRINT, "SPO_PRESET changed"


# ── AC-07-02 ─────────────────────────────────────────────────────────────────


def test_canonical_sales_order_declares_ref_optional_str_max_255():
    field = CanonicalSalesOrder.model_fields.get("ref")
    assert field is not None, "CanonicalSalesOrder has no `ref` field"
    assert field.default is None
    assert any(isinstance(m, MaxLen) and m.max_length == 255 for m in field.metadata), (
        f"ref must carry max_length=255 - metadata {field.metadata}"
    )
    assert CanonicalSalesOrder(
        source_ref="k", so_number="SO-1", status="open", ref="THE MET KL"
    ).ref == "THE MET KL"
    with pytest.raises(ValidationError):
        CanonicalSalesOrder(source_ref="k", so_number="SO-1", status="open", ref="R" * 256)


def test_ref_is_in_fallback_fields_and_omit_when_empty_fields():
    assert "ref" in CanonicalSalesOrder.FALLBACK_FIELDS, CanonicalSalesOrder.FALLBACK_FIELDS
    omit = getattr(CanonicalSalesOrder, "OMIT_WHEN_EMPTY_FIELDS", None)
    if omit is None:
        pytest.fail("CanonicalSalesOrder has no OMIT_WHEN_EMPTY_FIELDS")
    assert "ref" in omit, omit


def _so(**overrides) -> CanonicalSalesOrder:
    fields = dict(source_ref="AED:SO:1", so_number="SO-00001", status="open", ref="THE MET KL")
    fields.update(overrides)
    return CanonicalSalesOrder(**fields)


def test_v1_payload_never_carries_ref():
    payload = _so().sink_payload(contract_version=1)
    assert "ref" not in payload, sorted(payload)


def test_v2_payload_carries_ref_when_set():
    payload = _so().sink_payload(contract_version=2)
    assert payload.get("ref") == "THE MET KL", sorted(payload)


@pytest.mark.parametrize("value", [None, ""])
def test_v2_payload_omits_ref_when_empty(value):
    payload = _so(ref=value).sink_payload(contract_version=2)
    assert "ref" not in payload, sorted(payload)


# ── AC-07-03 ─────────────────────────────────────────────────────────────────


def test_purchase_order_and_shipping_order_have_no_ref_field():
    assert "ref" not in CanonicalPurchaseOrder.model_fields
    assert "ref" not in CanonicalShippingOrder.model_fields


@pytest.mark.parametrize("version", [1, 2, 3])
def test_purchase_order_payload_never_carries_ref(version):
    po = CanonicalPurchaseOrder(
        source_ref="AED:PO:5", po_number="PO-00005", status="open", supplier_code="400-J001",
    )
    assert "ref" not in po.sink_payload(contract_version=version)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_shipping_order_payload_never_carries_ref(version):
    spo = CanonicalShippingOrder(
        source_ref="AED:PO:7", spo_number="SPO-00007", status="open", supplier_code="400-J001",
    )
    assert "ref" not in spo.sink_payload(contract_version=version)


# ── AC-07-04 ─────────────────────────────────────────────────────────────────


def test_mapping_catalog_accepts_ref_for_sales_order_only():
    assert "ref" in accepted_field_names(ENTITY_SALES_ORDER), SORENTO_FIELDS[ENTITY_SALES_ORDER]
    assert "ref" not in accepted_field_names(ENTITY_PURCHASE_ORDER), (
        SORENTO_FIELDS[ENTITY_PURCHASE_ORDER]
    )
    assert "ref" not in accepted_field_names(ENTITY_SHIPPING_ORDER), (
        SORENTO_FIELDS[ENTITY_SHIPPING_ORDER]
    )


def _sql_connection(db, engine: sa.engine.Engine, *, database: str, name: str) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="erp", name=name,
        config_json={
            "dbType": "postgresql", "host": "db.example.com", "port": "5432",
            "database": database, "username": "readonly",
        },
        credentials_json=encrypt_secret({"password": "S3cret!Pa55"}), is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str, *, database: str, name: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=database,
        company_name=name, name=name, is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _document_config(db, company: AcCompany, entity_type: str) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=entity_type,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x", "query": "SELECT 1", "keyColumns": ["DocKey"],
        "watermarkColumn": "LastModified", "comparedColumns": [],
    }
    config.result_columns = ["DocKey", "DocNo", "Cancelled", "Ref"]
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _engine() -> sa.engine.Engine:
    from sqlalchemy.pool import StaticPool

    return sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


def _auth(client, email="demo@example.com", password="demo1234"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_put_mapping_ref_succeeds_on_sales_order_and_422s_on_purchase_order(
    client, session_factory,
):
    db = session_factory()
    conn = _sql_connection(db, _engine(), database="AED_REF_MAP", name="src")
    so_company = _company(db, conn.id, database="AED_REF_MAP", name="Ref Map Co")
    _document_config(db, so_company, ENTITY_SALES_ORDER)
    po_company = _company(db, conn.id, database="AED_REF_MAP_PO", name="Ref Map Co PO")
    _document_config(db, po_company, ENTITY_PURCHASE_ORDER)
    so_company_id, po_company_id = so_company.id, po_company.id
    db.close()

    headers = _auth(client)
    ok = client.put(
        f"/autocount/companies/{so_company_id}/entities/{ENTITY_SALES_ORDER}/mapping",
        headers=headers,
        json={
            "rows": [
                {"sourcePath": "DocNo", "transform": "string", "sorentoField": "so_number"},
                {"sourcePath": "Cancelled", "transform": "string", "sorentoField": "status"},
                {"sourcePath": "Ref", "transform": "string", "sorentoField": "ref"},
            ],
        },
    )
    assert ok.status_code == 200, ok.text
    saved = [r for r in ok.json()["rows"] if r["sorentoField"] == "ref"]
    assert saved and saved[0]["sourcePath"] == "Ref"

    rejected = client.put(
        f"/autocount/companies/{po_company_id}/entities/{ENTITY_PURCHASE_ORDER}/mapping",
        headers=headers,
        json={
            "rows": [
                {"sourcePath": "DocNo", "transform": "string", "sorentoField": "po_number"},
                {"sourcePath": "Cancelled", "transform": "string", "sorentoField": "status"},
                {"sourcePath": "Ref", "transform": "string", "sorentoField": "ref"},
            ],
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert "ref" in str(rejected.json()).lower()


# ── AC-07-05 ─────────────────────────────────────────────────────────────────


def test_map_document_end_to_end_strips_ref_and_sink_carries_it_verbatim():
    header_rows = [
        MappingRow("DocKey", "source_ref", "string", SCOPE_HEADER),
        MappingRow("DocNo", "so_number", "string", SCOPE_HEADER),
        MappingRow("Status", "status", "string", SCOPE_HEADER),
        MappingRow("Ref", "ref", "string", SCOPE_HEADER),
        MappingRow("DtlKey", "source_ref", "string", SCOPE_LINE, is_required=True),
        MappingRow("ItemAutoKey", "product_ref", "ref_product", SCOPE_LINE, is_required=True),
        MappingRow("Qty", "qty_ordered", "decimal", SCOPE_LINE, is_required=True),
    ]
    rows = build_mapping_rows_for_run(
        ENTITY_SALES_ORDER, header_rows, is_sql_db_source=True, source_config={},
    )
    engine = MappingEngine(
        rows, entity_type=ENTITY_SALES_ORDER,
        profile=flat_profile(ENTITY_SALES_ORDER, ["DocKey"]), database_name="AED_X",
    )
    mapped = engine.map_document({
        "DocKey": "D1", "DocNo": "SO-1", "Status": "open", "Ref": "  THE MET KL ",
        "_lines": [{"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10"}],
    })
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.ref == "THE MET KL", mapped.record.ref

    payload_v2 = mapped.record.sink_payload(contract_version=2)
    assert payload_v2.get("ref") == "THE MET KL", sorted(payload_v2)

    payload_v1 = mapped.record.sink_payload(contract_version=1)
    assert "ref" not in payload_v1, sorted(payload_v1)


# ═════════════════════════ Group B - backfill for existing tasks ════════════


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


def _so_config(
    db, company: AcCompany, *, query: str, result_columns=None,
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x",
        "query": query,
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
    config.result_columns = list(
        result_columns or ["DocKey", "DocNo", "Cancelled", "DocDate", "LastModified"]
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _header_rows(db, company_id: str, entity_type: str = ENTITY_SALES_ORDER):
    return (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == entity_type,
            AcFieldMapping.scope == SCOPE_HEADER,
        )
        .order_by(AcFieldMapping.sort_order)
        .all()
    )


def _ref_rows(db, company_id: str, entity_type: str = ENTITY_SALES_ORDER):
    return [r for r in _header_rows(db, company_id, entity_type) if r.canonical_field == "ref"]


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ── AC-07-07 ─────────────────────────────────────────────────────────────────


def test_backfill_is_a_no_op_on_a_schema_that_predates_its_tables():
    helper = _backfill()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE ac_entity_config (id TEXT PRIMARY KEY, tenant_id TEXT, "
            "company_id TEXT, entity_type TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO ac_entity_config VALUES ('cfg-1', 't', 'c', 'sales_order')"
        )
    with engine.begin() as conn:
        assert helper(conn, schema=None) == 0

    bare = sa.create_engine("sqlite://")
    with bare.begin() as conn:
        assert helper(conn, schema=None) == 0


def test_manifest_version_is_bumped_past_0_8_0():
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    version = tuple(int(part) for part in manifest["version"].split("."))
    assert version > (0, 8, 0), f"manifest still at {manifest['version']}"


def test_revision_0019_chains_onto_0018_and_calls_the_helper():
    candidates = sorted(VERSIONS_DIR.glob("0019_*.py"))
    assert candidates, "no 0019_* module revision under modules/autocount/alembic/versions"
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    assert revision and len(revision.group(1)) <= 32, "revision id missing or > 32 chars"
    spec = importlib.util.spec_from_file_location("_ac_rev_0019", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS_REVISION
    assert HELPER_NAME in text, f"{path.name} does not call {HELPER_NAME}"
    for other in VERSIONS_DIR.glob("*.py"):
        if other == path:
            continue
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', other.read_text(), re.M)
        assert not (down and down.group(1) == PREVIOUS_REVISION), (
            f"{other.name} also chains onto {PREVIOUS_REVISION}"
        )


def test_update_tenant_runs_the_sales_order_ref_backfill(db):
    from modules.autocount.bootstrap import update_tenant

    company = _api_company(db, database="AED_UPD_REF")
    config = _so_config(
        db, company, query=_OLD_SO_HEADER_QUERY.replace("{database}", "AED_UPD_REF"),
    )
    config_id = config.id
    db.expire_all()

    update_tenant(db, DEFAULT_TENANT_ID, "0.7.0")
    db.commit()
    db.expire_all()

    rows = _ref_rows(db, company.id)
    assert len(rows) == 1 and rows[0].canonical_field == "ref"
    assert rows[0].is_enabled is True
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _NEW_SO_HEADER_QUERY.replace(
        "{database}", "AED_UPD_REF"
    )
    assert "Ref" in (after.result_columns or [])


# ── AC-07-08 ─────────────────────────────────────────────────────────────────


def test_backfill_replaces_a_byte_identical_old_preset_query_with_new_text_and_seeds_row(db):
    helper = _backfill()
    company = _api_company(db, database="AED_SO_OLD")
    config = _so_config(
        db, company, query=_OLD_SO_HEADER_QUERY.replace("{database}", "AED_SO_OLD"),
    )
    config_id = config.id
    # Two pre-existing header rows so the Ref row's sort_order can be pinned
    # to "next" rather than a bare 0.
    db.add(AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        scope=SCOPE_HEADER, source_path="DocNo", canonical_field="so_number",
        transform="string", is_enabled=True, is_required=True, sort_order=0,
    ))
    db.add(AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        scope=SCOPE_HEADER, source_path="Cancelled", canonical_field="status",
        transform="string", is_enabled=True, is_required=True, sort_order=1,
    ))
    db.commit()
    db.expire_all()

    touched = helper(db, schema=None)
    assert touched >= 1, f"helper reported {touched} rows touched"
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _NEW_SO_HEADER_QUERY.replace(
        "{database}", "AED_SO_OLD"
    )
    assert "{database}" not in after.source_config["query"]
    assert "Ref" in (after.result_columns or []), after.result_columns
    assert after.result_columns[:4] == ["DocKey", "DocNo", "Cancelled", "DocDate"]

    rows = _ref_rows(db, company.id)
    assert len(rows) == 1, f"{len(rows)} ref rows"
    row = rows[0]
    assert row.tenant_id == company.tenant_id
    assert row.transform == "string"
    assert row.is_enabled is True
    assert row.is_required is False
    assert row.formula is None
    assert row.sort_order == 2, "the Ref row must land at the NEXT sort_order"

    # A second pass is a silent no-op for this now-migrated config.
    db.expire_all()
    second_pass_touched = helper(db, schema=None)
    db.expire_all()
    assert len(_ref_rows(db, company.id)) == 1


# ── AC-07-09 ─────────────────────────────────────────────────────────────────


_CUSTOMISED_SO_QUERY = (
    "SELECT h.DocKey, h.DocNo, h.SalesAgent, h.DocDate, h.Note, h.Cancelled, "
    "h.DebtorCode, h.DebtorName, h.LastModified, icb.SOList AS SOList "
    "FROM {database}.dbo.SO AS h "
    "LEFT JOIN {database}.dbo.ICB_SOPlugin AS icb ON icb.DocKey = h.DocKey"
)


def test_backfill_leaves_a_customised_query_alone_and_disables_the_ref_row_without_it(
    db, caplog,
):
    helper = _backfill()
    company = _api_company(db, database="AED_SORENTO_LIKE")
    customised = _CUSTOMISED_SO_QUERY.replace("{database}", "AED_SORENTO_LIKE")
    config = _so_config(
        db, company, query=customised,
        result_columns=["DocKey", "DocNo", "SalesAgent", "DocDate", "Note", "Cancelled"],
    )
    config_id = config.id
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == customised, "a customised query was overwritten"
    assert after.result_columns == [
        "DocKey", "DocNo", "SalesAgent", "DocDate", "Note", "Cancelled",
    ], "result_columns must be left byte-untouched"

    rows = _ref_rows(db, company.id)
    assert len(rows) == 1
    assert rows[0].is_enabled is False, "no Ref in result_columns -> row must land DISABLED"

    warnings = [
        record for record in caplog.records
        if record.levelno >= logging.WARNING and config_id in record.getMessage()
    ]
    assert warnings, (
        f"no WARNING names the customised config id {config_id}; "
        f"warnings seen: {[r.getMessage() for r in caplog.records]}"
    )
    assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"


def test_backfill_enables_the_ref_row_on_a_customised_query_that_already_selects_ref(db):
    helper = _backfill()
    company = _api_company(db, database="AED_SORENTO_HAS_REF")
    customised = _CUSTOMISED_SO_QUERY.replace(
        "{database}", "AED_SORENTO_HAS_REF"
    ).replace("h.Note, ", "h.Note, h.Ref, ")
    config = _so_config(
        db, company, query=customised,
        result_columns=["DocKey", "DocNo", "SalesAgent", "DocDate", "Note", "Ref", "Cancelled"],
    )
    config_id = config.id
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == customised
    rows = _ref_rows(db, company.id)
    assert len(rows) == 1
    assert rows[0].is_enabled is True, "Ref already selected -> row must land ENABLED"


# ── AC-07-10 ─────────────────────────────────────────────────────────────────


def test_backfill_leaves_an_existing_ref_row_alone_in_any_state(db):
    helper = _backfill()
    company = _api_company(db, database="AED_SO_HAS_ROW")
    _so_config(db, company, query=_OLD_SO_HEADER_QUERY.replace("{database}", "AED_SO_HAS_ROW"))
    existing = AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        scope=SCOPE_HEADER, source_path="Ref", canonical_field="ref",
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


def test_backfill_does_not_repeat_a_warning_on_a_second_pass(db, caplog):
    helper = _backfill()
    company = _api_company(db, database="AED_SO_REPEAT")
    customised = _CUSTOMISED_SO_QUERY.replace("{database}", "AED_SO_REPEAT")
    config = _so_config(db, company, query=customised)
    config_id = config.id
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        helper(db, schema=None)
    first_pass_warnings = [r for r in caplog.records if config_id in r.getMessage()]
    assert len(first_pass_warnings) == 1
    caplog.clear()
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        second_pass = helper(db, schema=None)
    second_pass_warnings = [r for r in caplog.records if config_id in r.getMessage()]
    assert second_pass == 0, "a config with a ref row already in place must count as 0 changes"
    assert second_pass_warnings == [], "a config that already carries a ref row must not re-warn"


def test_backfill_ignores_a_query_that_matches_another_companys_database(db):
    helper = _backfill()
    company = _api_company(db, database="AED_SO_MINE")
    config = _so_config(
        db, company, query=_OLD_SO_HEADER_QUERY.replace("{database}", "AED_SO_OTHER"),
    )
    config_id = config.id
    stored = config.source_config["query"]
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    assert db.get(AcEntityConfig, config_id).source_config["query"] == stored


# ── AC-07-11 ─────────────────────────────────────────────────────────────────


def test_backfill_resolves_the_company_with_the_configs_own_tenant_id(db):
    helper = _backfill()
    tenant_a = DEFAULT_TENANT_ID
    tenant_b = "tenant-b-so-ref"
    company_a = _api_company(db, database="AED_TENANT_A", tenant_id=tenant_a)
    company_b = _api_company(db, database="AED_TENANT_B", tenant_id=tenant_b)
    config_a = _so_config(
        db, company_a, query=_OLD_SO_HEADER_QUERY.replace("{database}", "AED_TENANT_A"),
    )
    config_b = _so_config(
        db, company_b, query=_OLD_SO_HEADER_QUERY.replace("{database}", "AED_TENANT_B"),
    )
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    for company, config_id, database in (
        (company_a, config_a.id, "AED_TENANT_A"), (company_b, config_b.id, "AED_TENANT_B"),
    ):
        after = db.get(AcEntityConfig, config_id)
        assert after.source_config["query"] == _NEW_SO_HEADER_QUERY.replace(
            "{database}", database
        ), f"{company.database_name} resolved the wrong company's database name"
        rows = _ref_rows(db, company.id)
        assert len(rows) == 1 and rows[0].tenant_id == company.tenant_id


def test_backfill_skips_a_config_whose_company_id_belongs_to_another_tenant(db, caplog):
    """A config's `company_id` happens to name a real `ac_company` row, but
    that row lives under a DIFFERENT tenant - the polymorphic-target_id rule
    (CLAUDE.md) says this must resolve to "no company found", never a
    same-id cross-tenant hit."""
    helper = _backfill()
    other_tenant = "tenant-leak-so-ref"
    leaking_company = _api_company(db, database="AED_LEAK", tenant_id=other_tenant)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID,  # NOT other_tenant
        company_id=leaking_company.id,
        entity_type=ENTITY_SALES_ORDER,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x",
        "query": _OLD_SO_HEADER_QUERY.replace("{database}", "AED_LEAK"),
        "keyColumns": ["DocKey"],
    }
    config.result_columns = ["DocKey", "DocNo", "Cancelled"]
    db.add(config)
    db.commit()
    config_id = config.id
    stored_query = config.source_config["query"]
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == stored_query, (
        "a config whose company is missing under its OWN tenant must never be "
        "matched against another tenant's company of the same id"
    )
    assert (
        db.query(AcFieldMapping)
        .filter(AcFieldMapping.company_id == leaking_company.id)
        .filter(AcFieldMapping.tenant_id == DEFAULT_TENANT_ID)
        .count()
        == 0
    )
    warnings = [r for r in caplog.records if config_id in r.getMessage()]
    assert warnings, "a config whose company is missing under its own tenant must warn"
