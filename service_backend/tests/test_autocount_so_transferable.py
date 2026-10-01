"""AutoCount SO `Transferable` on the Sorento feed (lane SS-SO-TRANSFERABLE).

RED tests written before the implementation, keyed to
`documentation/plans/sprint-5/18-autocount-so-transferable-acceptance-criteria.md`.
Same shape as `test_autocount_so_ref.py` (sprint-5/07, module Alembic 0019):
a new optional SO header field, a preset query column, and a backfill for
every EXISTING `sales_order` task.
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
from modules.autocount.mapping_catalog import accepted_field_names
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.presets import (
    SO_PRESET,
    PresetField,
    _SO_FINGERPRINT_QUERY,
    _SO_HEADER_QUERY,
    _SO_LINE_QUERY,
    list_mapping_presets,
)

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"

HELPER_NAME = "backfill_sales_order_transferable"
PREVIOUS_REVISION = "0024_autocount_doc_lookup"

# ── the SO header query texts, pinned VERBATIM ──────────────────────────────
#
# PRE-REF = before 0019; REF = what 0019 rewrites to (the preset text at the
# moment this lane started); NEW = REF + `h.Transferable AS Transferable`.
_PRE_REF_SO_HEADER_QUERY = (
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
_REF_SO_HEADER_QUERY = _PRE_REF_SO_HEADER_QUERY.replace(
    "h.Note AS Note, ", "h.Note AS Note, h.Ref AS Ref, ", 1
)
_NEW_SO_HEADER_QUERY = _REF_SO_HEADER_QUERY.replace(
    "h.Ref AS Ref, ", "h.Ref AS Ref, h.Transferable AS Transferable, ", 1
)
assert _NEW_SO_HEADER_QUERY != _REF_SO_HEADER_QUERY != _PRE_REF_SO_HEADER_QUERY


def _fp(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


# Pinned against the pre-lane values (same values `test_autocount_so_ref.py`
# pins) - this lane touches the SO HEADER query only.
_SO_LINE_QUERY_FINGERPRINT = "46935582aaa88d6c5e8b5d7cc2de4283cca994af227e05fe45e7a037d6a7bbb2"
_SO_FINGERPRINT_QUERY_FINGERPRINT = (
    "e54b9cb32c3483c7649a5cf1a6665144d7580f2d5a97893e9b6ed7b1b286750f"
)


def _backfill():
    from modules.autocount import backfill

    helper = getattr(backfill, HELPER_NAME, None)
    if helper is None:
        pytest.fail(f"modules.autocount.backfill has no `{HELPER_NAME}` helper yet")
    return helper


# ═════════════════════════ Group A - preset, canonical, wire ════════════════


def test_so_header_query_selects_transferable_after_ref():  # AC-18-01
    assert _SO_HEADER_QUERY == _NEW_SO_HEADER_QUERY, _SO_HEADER_QUERY
    assert _fp(_SO_LINE_QUERY) == _SO_LINE_QUERY_FINGERPRINT
    assert _fp(_SO_FINGERPRINT_QUERY) == _SO_FINGERPRINT_QUERY_FINGERPRINT


def test_so_preset_header_carries_a_transferable_bool_field():  # AC-18-01
    rows = [f for f in SO_PRESET.header if f.source_path == "Transferable"]
    assert rows == [PresetField("Transferable", "transferable", "bool")], rows
    assert rows[0].required is False
    payload = list_mapping_presets(ENTITY_SALES_ORDER, "AED_TEST")
    assert "h.Transferable AS Transferable" in payload[0]["headerQuery"]


def test_canonical_sales_order_declares_transferable_optional_bool():  # AC-18-02
    field = CanonicalSalesOrder.model_fields.get("transferable")
    assert field is not None, "CanonicalSalesOrder has no `transferable` field"
    assert field.default is None
    assert "transferable" in CanonicalSalesOrder.FALLBACK_FIELDS


def _so(**overrides) -> CanonicalSalesOrder:
    fields = dict(source_ref="AED:SO:1", so_number="SO-00001", status="open")
    fields.update(overrides)
    return CanonicalSalesOrder(**fields)


@pytest.mark.parametrize("value", [True, False])
def test_v2_payload_carries_transferable_true_and_false(value):  # AC-18-02
    payload = _so(transferable=value).sink_payload(contract_version=2)
    assert "transferable" in payload, sorted(payload)
    assert payload["transferable"] is value


def test_v2_payload_omits_transferable_when_null():  # AC-18-02
    payload = _so(transferable=None).sink_payload(contract_version=2)
    assert "transferable" not in payload, sorted(payload)


@pytest.mark.parametrize("value", [True, False, None])
def test_v1_payload_never_carries_transferable(value):  # AC-18-02
    assert "transferable" not in _so(transferable=value).sink_payload(contract_version=1)


def test_ref_omission_still_works_alongside_transferable():
    payload = _so(ref="", transferable=False).sink_payload(contract_version=2)
    assert "ref" not in payload
    assert payload["transferable"] is False


@pytest.mark.parametrize("version", [1, 2, 3])
def test_po_and_spo_never_carry_transferable(version):  # AC-18-03
    assert "transferable" not in CanonicalPurchaseOrder.model_fields
    assert "transferable" not in CanonicalShippingOrder.model_fields
    po = CanonicalPurchaseOrder(
        source_ref="AED:PO:5", po_number="PO-5", status="open", supplier_code="400-J001",
    )
    spo = CanonicalShippingOrder(
        source_ref="AED:PO:7", spo_number="SPO-7", status="open", supplier_code="400-J001",
    )
    assert "transferable" not in po.sink_payload(contract_version=version)
    assert "transferable" not in spo.sink_payload(contract_version=version)


def test_mapping_catalog_accepts_transferable_for_sales_order_only():  # AC-18-04
    assert "transferable" in accepted_field_names(ENTITY_SALES_ORDER)
    assert "transferable" not in accepted_field_names(ENTITY_PURCHASE_ORDER)
    assert "transferable" not in accepted_field_names(ENTITY_SHIPPING_ORDER)


@pytest.mark.parametrize(
    "raw, expected", [("T", True), ("F", False), (None, None)],
)
def test_map_document_end_to_end(raw, expected):  # AC-18-04
    rows = build_mapping_rows_for_run(
        ENTITY_SALES_ORDER,
        [
            MappingRow("DocKey", "source_ref", "string", SCOPE_HEADER),
            MappingRow("DocNo", "so_number", "string", SCOPE_HEADER),
            MappingRow("Status", "status", "string", SCOPE_HEADER),
            MappingRow("Transferable", "transferable", "bool", SCOPE_HEADER),
            MappingRow("DtlKey", "source_ref", "string", SCOPE_LINE, is_required=True),
            MappingRow("ItemAutoKey", "product_ref", "ref_product", SCOPE_LINE, is_required=True),
            MappingRow("Qty", "qty_ordered", "decimal", SCOPE_LINE, is_required=True),
        ],
        is_sql_db_source=True, source_config={},
    )
    engine = MappingEngine(
        rows, entity_type=ENTITY_SALES_ORDER,
        profile=flat_profile(ENTITY_SALES_ORDER, ["DocKey"]), database_name="AED_X",
    )
    mapped = engine.map_document({
        "DocKey": "D1", "DocNo": "SO-1", "Status": "open", "Transferable": raw,
        "_lines": [{"DtlKey": "L1", "ItemAutoKey": "P1", "Qty": "10"}],
    })
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.transferable is expected
    payload = mapped.record.sink_payload(contract_version=2)
    if expected is None:
        assert "transferable" not in payload
    else:
        assert payload["transferable"] is expected


# ═════════════════════════ Group B - backfill for existing tasks ════════════


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


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


def _so_config(db, company: AcCompany, *, query: str, result_columns=None) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x", "query": query, "keyColumns": ["DocKey"],
        "watermarkColumn": "LastModified", "comparedColumns": [],
    }
    config.result_columns = list(
        result_columns or ["DocKey", "DocNo", "Cancelled", "Ref", "LastModified"]
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _rows(db, company_id: str, field: str = "transferable"):
    return [
        r for r in (
            db.query(AcFieldMapping)
            .filter(
                AcFieldMapping.company_id == company_id,
                AcFieldMapping.entity_type == ENTITY_SALES_ORDER,
                AcFieldMapping.scope == SCOPE_HEADER,
            )
            .order_by(AcFieldMapping.sort_order)
            .all()
        )
        if r.canonical_field == field
    ]


def test_backfill_rewrites_the_ref_preset_query_and_seeds_an_enabled_row(db):  # AC-18-05
    helper = _backfill()
    company = _api_company(db, database="AED_TR_PRESET")
    config = _so_config(db, company, query=_REF_SO_HEADER_QUERY.replace("{database}", "AED_TR_PRESET"))
    config_id = config.id
    for order, (src, dst) in enumerate((("DocNo", "so_number"), ("Ref", "ref"))):
        db.add(AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
            scope=SCOPE_HEADER, source_path=src, canonical_field=dst,
            transform="string", is_enabled=True, is_required=False, sort_order=order,
        ))
    db.commit()
    db.expire_all()

    assert helper(db, schema=None) == 2
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _NEW_SO_HEADER_QUERY.replace("{database}", "AED_TR_PRESET")
    assert after.result_columns == ["DocKey", "DocNo", "Cancelled", "Ref", "LastModified", "Transferable"]
    rows = _rows(db, company.id)
    assert len(rows) == 1
    row = rows[0]
    assert (row.source_path, row.transform, row.is_enabled, row.is_required, row.formula) == (
        "Transferable", "bool", True, False, None,
    )
    assert row.is_source_owned is True
    assert row.sort_order == 2

    db.expire_all()
    assert helper(db, schema=None) == 0, "second pass must be a no-op"
    db.expire_all()
    assert len(_rows(db, company.id)) == 1


def test_backfill_skips_silently_a_query_already_at_the_new_text(db, caplog):  # AC-18-05
    helper = _backfill()
    company = _api_company(db, database="AED_TR_NEW")
    query = _NEW_SO_HEADER_QUERY.replace("{database}", "AED_TR_NEW")
    config = _so_config(db, company, query=query,
                        result_columns=["DocKey", "Ref", "Transferable"])
    config_id = config.id
    db.expire_all()
    with caplog.at_level(logging.WARNING):
        helper(db, schema=None)
    db.expire_all()
    assert db.get(AcEntityConfig, config_id).source_config["query"] == query
    assert not [r for r in caplog.records if config_id in r.getMessage()]


_CUSTOMISED_SO_QUERY = (
    "SELECT h.DocKey, h.DocNo, h.SalesAgent, h.DocDate, h.Note, h.Ref, h.Cancelled, "
    "h.DebtorCode, h.DebtorName, h.LastModified, icb.SOList AS SOList "
    "FROM {database}.dbo.SO AS h "
    "LEFT JOIN {database}.dbo.ICB_SOPlugin AS icb ON icb.DocKey = h.DocKey"
)


def test_backfill_leaves_a_customised_query_alone_and_disables_the_row(db, caplog):  # AC-18-06
    helper = _backfill()
    company = _api_company(db, database="AED_SORENTO_TR")
    customised = _CUSTOMISED_SO_QUERY.replace("{database}", "AED_SORENTO_TR")
    columns = ["DocKey", "DocNo", "SalesAgent", "DocDate", "Note", "Ref", "Cancelled"]
    config = _so_config(db, company, query=customised, result_columns=columns)
    config_id = config.id
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == customised
    assert after.result_columns == columns
    rows = _rows(db, company.id)
    assert len(rows) == 1 and rows[0].is_enabled is False
    warnings = [r for r in caplog.records
                if r.levelno >= logging.WARNING and config_id in r.getMessage()]
    assert len(warnings) == 1, [r.getMessage() for r in caplog.records]

    caplog.clear()
    db.expire_all()
    with caplog.at_level(logging.WARNING):
        assert helper(db, schema=None) == 0
    assert not [r for r in caplog.records if config_id in r.getMessage()], "re-warned"


def test_backfill_enables_the_row_when_a_customised_query_already_selects_it(db):  # AC-18-06
    helper = _backfill()
    company = _api_company(db, database="AED_SORENTO_HAS_TR")
    customised = _CUSTOMISED_SO_QUERY.replace("{database}", "AED_SORENTO_HAS_TR").replace(
        "h.Ref, ", "h.Ref, h.Transferable, "
    )
    _so_config(db, company, query=customised, result_columns=["DocKey", "Ref", "Transferable"])
    db.expire_all()
    helper(db, schema=None)
    db.expire_all()
    rows = _rows(db, company.id)
    assert len(rows) == 1 and rows[0].is_enabled is True


def test_backfill_leaves_an_existing_row_alone_in_any_state(db):  # AC-18-07
    helper = _backfill()
    company = _api_company(db, database="AED_TR_HAS_ROW")
    _so_config(db, company, query=_REF_SO_HEADER_QUERY.replace("{database}", "AED_TR_HAS_ROW"))
    existing = AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        scope=SCOPE_HEADER, source_path="Transferable", canonical_field="transferable",
        transform="bool", formula="Transferable", is_enabled=False, is_required=False,
    )
    db.add(existing)
    db.commit()
    existing_id = existing.id
    db.expire_all()

    helper(db, schema=None)
    db.expire_all()

    rows = _rows(db, company.id)
    assert [r.id for r in rows] == [existing_id]
    assert rows[0].is_enabled is False and rows[0].formula == "Transferable"


def test_backfill_ignores_a_query_matching_another_companys_database(db):  # AC-18-06
    helper = _backfill()
    company = _api_company(db, database="AED_TR_MINE")
    config = _so_config(db, company, query=_REF_SO_HEADER_QUERY.replace("{database}", "AED_TR_OTHER"))
    config_id, stored = config.id, config.source_config["query"]
    db.expire_all()
    helper(db, schema=None)
    db.expire_all()
    assert db.get(AcEntityConfig, config_id).source_config["query"] == stored
    assert _rows(db, company.id)[0].is_enabled is False


def test_backfill_skips_a_config_whose_company_belongs_to_another_tenant(db, caplog):  # AC-18-08
    helper = _backfill()
    leaking = _api_company(db, database="AED_TR_LEAK", tenant_id="tenant-leak-so-tr")
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=leaking.id,
        entity_type=ENTITY_SALES_ORDER, source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x",
        "query": _REF_SO_HEADER_QUERY.replace("{database}", "AED_TR_LEAK"),
        "keyColumns": ["DocKey"],
    }
    config.result_columns = ["DocKey", "Ref"]
    db.add(config)
    db.commit()
    config_id, stored = config.id, config.source_config["query"]
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        helper(db, schema=None)
    db.expire_all()

    assert db.get(AcEntityConfig, config_id).source_config["query"] == stored
    assert db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == leaking.id,
        AcFieldMapping.canonical_field == "transferable",
    ).count() == 0
    assert [r for r in caplog.records if config_id in r.getMessage()]


def test_backfill_is_a_no_op_on_a_schema_that_predates_its_tables():  # AC-18-08
    helper = _backfill()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE ac_entity_config (id TEXT PRIMARY KEY, tenant_id TEXT, "
            "company_id TEXT, entity_type TEXT)"
        )
        conn.exec_driver_sql("INSERT INTO ac_entity_config VALUES ('c', 't', 'c', 'sales_order')")
    with engine.begin() as conn:
        assert helper(conn, schema=None) == 0
    with sa.create_engine("sqlite://").begin() as conn:
        assert helper(conn, schema=None) == 0


def test_revision_0025_chains_onto_0024_and_calls_the_helper():  # AC-18-09
    candidates = sorted(VERSIONS_DIR.glob("0025_*.py"))
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    assert revision and len(revision.group(1)) <= 32
    spec = importlib.util.spec_from_file_location("_ac_rev_0025", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS_REVISION
    assert HELPER_NAME in text
    for other in VERSIONS_DIR.glob("*.py"):
        if other == path:
            continue
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', other.read_text(), re.M)
        assert not (down and down.group(1) == PREVIOUS_REVISION), other.name


def test_manifest_version_is_bumped_past_0_12_0():  # AC-18-09
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    assert tuple(int(p) for p in manifest["version"].split(".")) > (0, 12, 0)


def test_update_tenant_walks_a_pre_ref_preset_task_to_the_new_text(db):  # AC-18-09
    """0019 then 0025 (the `update_tenant` order): a pre-`Ref` preset task
    must end on the NEW text with BOTH columns, and both rows enabled - 0019
    targets its own FROZEN text, never the live preset, or the chain would
    skip `Transferable` in `result_columns`."""
    from modules.autocount.bootstrap import update_tenant

    company = _api_company(db, database="AED_UPD_TR")
    config = _so_config(
        db, company, query=_PRE_REF_SO_HEADER_QUERY.replace("{database}", "AED_UPD_TR"),
        result_columns=["DocKey", "DocNo", "Cancelled"],
    )
    config_id = config.id
    db.expire_all()

    update_tenant(db, DEFAULT_TENANT_ID, "0.7.0")
    db.commit()
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _NEW_SO_HEADER_QUERY.replace("{database}", "AED_UPD_TR")
    assert {"Ref", "Transferable"} <= set(after.result_columns)
    assert [r.is_enabled for r in _rows(db, company.id, "ref")] == [True]
    assert [r.is_enabled for r in _rows(db, company.id)] == [True]


def test_ref_backfill_alone_targets_its_frozen_text_not_the_live_preset(db):
    from modules.autocount.backfill import backfill_sales_order_ref

    company = _api_company(db, database="AED_REF_FROZEN")
    config = _so_config(
        db, company, query=_PRE_REF_SO_HEADER_QUERY.replace("{database}", "AED_REF_FROZEN"),
        result_columns=["DocKey"],
    )
    config_id = config.id
    db.expire_all()
    backfill_sales_order_ref(db, schema=None)
    db.expire_all()
    assert db.get(AcEntityConfig, config_id).source_config["query"] == (
        _REF_SO_HEADER_QUERY.replace("{database}", "AED_REF_FROZEN")
    )


def test_frozen_0025_target_equals_todays_preset():  # review: frozen target
    from modules.autocount.backfill import _TRANSFERABLE_SO_HEADER_QUERY

    assert _TRANSFERABLE_SO_HEADER_QUERY == _NEW_SO_HEADER_QUERY == _SO_HEADER_QUERY


def test_update_tenant_never_reseeds_rows_an_operator_deleted(db):  # review: no reseed
    from modules.autocount.bootstrap import update_tenant

    company = _api_company(db, database="AED_TR_DELETED")
    _so_config(db, company, query=_PRE_REF_SO_HEADER_QUERY.replace("{database}", "AED_TR_DELETED"))
    update_tenant(db, DEFAULT_TENANT_ID, "0.12.0")
    db.commit()
    db.expire_all()
    for field in ("ref", "transferable"):
        rows = _rows(db, company.id, field)
        assert len(rows) == 1, field
        db.delete(rows[0])
    db.commit()

    update_tenant(db, DEFAULT_TENANT_ID, "0.13.0")
    db.commit()
    db.expire_all()
    assert _rows(db, company.id, "ref") == []
    assert _rows(db, company.id, "transferable") == []


def test_backfill_leaves_an_empty_result_columns_empty(db):  # review: nit 3
    helper = _backfill()
    company = _api_company(db, database="AED_TR_EMPTY")
    config = _so_config(db, company, query=_REF_SO_HEADER_QUERY.replace("{database}", "AED_TR_EMPTY"))
    config.result_columns = []
    db.commit()
    config_id = config.id
    db.expire_all()
    helper(db, schema=None)
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _NEW_SO_HEADER_QUERY.replace("{database}", "AED_TR_EMPTY")
    assert after.result_columns == []
    assert _rows(db, company.id)[0].is_enabled is True
