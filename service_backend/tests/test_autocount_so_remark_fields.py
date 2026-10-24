"""AutoCount SO `ShipInfo` (header), `FurtherDescription` and `SectionHeading`
(lines) on the Sorento feed (lane FULFIL-SO-REMARK, UAC SS-1 / SS-2 / SS-3).

RED tests written before the implementation. Same shape as
`test_autocount_so_transferable.py`: preset query columns, canonical wire,
mapping catalog, and a backfill for every EXISTING `sales_order` task.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import re

import pytest

import modules.autocount as autocount_module
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    CanonicalPurchaseOrderLine,
    CanonicalSalesOrder,
    CanonicalSalesOrderLine,
    CanonicalShippingOrderLine,
)
from modules.autocount.mapping_catalog import (
    accepted_field_names,
    line_accepted_field_names,
)
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.mapping import SCOPE_HEADER, SCOPE_LINE
from modules.autocount.presets import (
    SO_PRESET,
    PO_PRESET,
    SPO_PRESET,
    PresetField,
    _SO_HEADER_QUERY,
    _SO_LINE_QUERY,
    list_mapping_presets,
)

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"

HELPER_NAME = "backfill_so_remark_fields"
PREVIOUS_REVISION = "0031_autocount_task_incident"
NEW_REVISION_GLOB = "0032_*.py"  # 0026 is long taken; 0031 is the head

# FROZEN previous preset texts (what a deployed task holds today).
_OLD_SO_HEADER_QUERY = (
    "SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, c.AutoKey AS DebtorAutoKey, "
    "h.SalesAgent AS SalesAgent, h.DocDate AS DocDate, "
    "h.UDF_DelDate AS RequestedDeliveryDate, h.Note AS Note, h.Ref AS Ref, "
    "h.Transferable AS Transferable, "
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
_OLD_SO_LINE_QUERY = (
    "SELECT d.DtlKey AS DtlKey, i.AutoKey AS ItemAutoKey, "
    "w.AutoKey AS LocationAutoKey, d.Qty AS Qty, "
    "d.TransferedQty AS TransferedQty, d.UnitPrice AS UnitPrice, "
    "d.DiscountAmt AS DiscountAmt, d.SubTotal AS SubTotal, d.UOM AS UOM, "
    "d.DeliveryDate AS DeliveryDate, d.ItemCode AS ItemCode, "
    "d.Description AS Description, d.Location AS Location, d.Seq AS Seq "
    "FROM {database}.dbo.SODTL AS d "
    "LEFT JOIN {database}.dbo.Item AS i ON i.ItemCode = d.ItemCode "
    "LEFT JOIN {database}.dbo.Location AS w ON w.Location = d.Location "
    "WHERE d.DocKey = :doc_key AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
)
_OLD_HEADER_COLUMNS = ["DocKey", "DocNo", "Cancelled", "Ref", "Transferable", "LastModified"]
_OLD_LINE_COLUMNS = ["DtlKey", "ItemAutoKey", "Qty", "Description", "Seq"]


def _backfill():
    from modules.autocount import backfill

    helper = getattr(backfill, HELPER_NAME, None)
    if helper is None:
        pytest.fail(f"modules.autocount.backfill has no `{HELPER_NAME}` helper yet")
    return helper


# ═════════════════════════ SS-1 header ShipInfo ═════════════════════════════


def test_so_header_query_selects_ship_info():  # SS-1
    assert re.search(r"\bh\.ShipInfo AS ShipInfo\b", _SO_HEADER_QUERY), _SO_HEADER_QUERY
    # the rest of the header query is untouched
    assert _SO_HEADER_QUERY.replace("h.ShipInfo AS ShipInfo, ", "") == _OLD_SO_HEADER_QUERY


def test_so_preset_header_maps_ship_info_to_ship_info():  # SS-1
    rows = [f for f in SO_PRESET.header if f.source_path == "ShipInfo"]
    assert rows == [PresetField("ShipInfo", "ship_info", "string")], rows
    assert "h.ShipInfo AS ShipInfo" in list_mapping_presets(ENTITY_SALES_ORDER, "AED_T")[0]["headerQuery"]


def test_canonical_sales_order_declares_ship_info_on_the_v2_wire():  # SS-1
    field = CanonicalSalesOrder.model_fields.get("ship_info")
    assert field is not None, "CanonicalSalesOrder has no `ship_info` field"
    assert "ship_info" in CanonicalSalesOrder.FALLBACK_FIELDS or "ship_info" in CanonicalSalesOrder.SINK_FIELDS
    so = CanonicalSalesOrder(
        source_ref="AED:SO:1", so_number="SO-1", status="open", ship_info="PR-2026-0042",
    )
    assert so.sink_payload(contract_version=2)["ship_info"] == "PR-2026-0042"


def test_mapping_catalog_accepts_ship_info_for_sales_order_only():  # SS-1
    assert "ship_info" in accepted_field_names(ENTITY_SALES_ORDER)
    assert "ship_info" not in accepted_field_names(ENTITY_PURCHASE_ORDER)
    assert "ship_info" not in accepted_field_names(ENTITY_SHIPPING_ORDER)


# ═════════════════════════ SS-2 line remark + section heading ═══════════════


def test_so_line_query_selects_raw_further_description():  # SS-2
    assert re.search(r"\bd\.FurtherDescription AS FurtherDescription\b", _SO_LINE_QUERY), _SO_LINE_QUERY
    # raw, never RTF-stripped
    assert not re.search(r"REPLACE\s*\(|PATINDEX|rtf", _SO_LINE_QUERY, re.I), _SO_LINE_QUERY


def test_so_line_query_selects_section_heading_via_outer_apply():  # SS-2
    q = _SO_LINE_QUERY
    assert "AS SectionHeading" in q, q
    assert "OUTER APPLY" in q, q
    # nearest text-only line BEFORE this one in the same document
    assert re.search(r"\.Seq\s*<\s*d\.Seq", q), q
    assert re.search(r"ORDER BY\s+\w+\.Seq\s+DESC", q, re.I), q
    assert "ItemCode IS NULL" in q and "Qty IS NULL" in q, q
    assert re.search(r"Description\s+IS\s+NOT\s+NULL|LTRIM\(RTRIM\(", q), q
    assert "DocKey = d.DocKey" in q.replace("  ", " "), q


def test_so_line_query_keeps_the_fingerprint_cut_and_old_columns():  # SS-2
    assert _SO_LINE_QUERY.endswith(
        "WHERE d.DocKey = :doc_key AND d.ItemCode IS NOT NULL AND d.Qty IS NOT NULL"
    ), _SO_LINE_QUERY
    for column in ("DtlKey", "ItemAutoKey", "LocationAutoKey", "Qty", "TransferedQty",
                   "UnitPrice", "DiscountAmt", "SubTotal", "UOM", "DeliveryDate",
                   "ItemCode", "Description", "Location", "Seq"):
        assert f"AS {column}" in _SO_LINE_QUERY, column


def test_so_preset_line_rows_map_remark_and_section_heading():  # SS-2
    by_src = {f.source_path: f for f in SO_PRESET.line}
    assert by_src["FurtherDescription"] == PresetField("FurtherDescription", "line_remark", "string")
    assert by_src["SectionHeading"] == PresetField("SectionHeading", "section_heading", "string")


def test_po_and_spo_line_presets_are_unchanged():  # SS-2
    for preset in (PO_PRESET, SPO_PRESET):
        sources = {f.source_path for f in preset.line}
        assert not ({"FurtherDescription", "SectionHeading"} & sources)
        assert "FurtherDescription" not in preset.line_query
        assert "SectionHeading" not in preset.line_query


def test_so_line_model_carries_remark_and_heading_on_the_wire():  # SS-2
    for name in ("line_remark", "section_heading"):
        assert name in CanonicalSalesOrderLine.model_fields, name
    line = CanonicalSalesOrderLine(
        source_ref="AED:SO:1:1", product_ref="P1", qty_ordered=1,
        line_remark="Rush", section_heading="Living room",
    )
    payload = line.sink_payload(contract_version=2)
    assert payload["line_remark"] == "Rush"
    assert payload["section_heading"] == "Living room"


@pytest.mark.parametrize("model", [CanonicalPurchaseOrderLine, CanonicalShippingOrderLine])
def test_po_and_spo_lines_never_carry_remark_or_heading(model):  # SS-2
    assert "line_remark" not in model.model_fields
    assert "section_heading" not in model.model_fields


def test_line_catalog_shows_new_fields_for_sales_order_only():  # SS-2
    assert {"line_remark", "section_heading"} <= line_accepted_field_names(ENTITY_SALES_ORDER)
    for entity in (ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER):
        assert not ({"line_remark", "section_heading"} & line_accepted_field_names(entity))


# ═════════════════════════ SS-3 backfill ════════════════════════════════════


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db, *, database: str) -> AcCompany:
    api = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name=f"AutoCount {database}",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name=database,
        company_name=f"{database} Sdn Bhd", name=database, is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _task(db, company, *, query, line_query, columns=None, line_columns=None) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x", "query": query, "lineQuery": line_query,
        "keyColumns": ["DocKey"], "watermarkColumn": "LastModified", "comparedColumns": [],
    }
    config.result_columns = list(_OLD_HEADER_COLUMNS if columns is None else columns)
    config.line_result_columns = list(_OLD_LINE_COLUMNS if line_columns is None else line_columns)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _rows(db, company_id, scope, field):
    return (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == ENTITY_SALES_ORDER,
            AcFieldMapping.scope == scope,
            AcFieldMapping.canonical_field == field,
        )
        .all()
    )


def _preset_task(db, database):
    company = _company(db, database=database)
    config = _task(
        db, company,
        query=_OLD_SO_HEADER_QUERY.replace("{database}", database),
        line_query=_OLD_SO_LINE_QUERY.replace("{database}", database),
    )
    return company, config.id


def test_backfill_rewrites_preset_queries_and_seeds_enabled_rows(db):  # SS-3
    helper = _backfill()
    company, config_id = _preset_task(db, "AED_RM_PRESET")
    db.expire_all()

    assert helper(db, schema=None) >= 1
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _SO_HEADER_QUERY.replace("{database}", "AED_RM_PRESET")
    assert after.source_config["lineQuery"] == _SO_LINE_QUERY.replace("{database}", "AED_RM_PRESET")
    assert "ShipInfo" in after.result_columns
    assert {"FurtherDescription", "SectionHeading"} <= set(after.line_result_columns)

    [ship] = _rows(db, company.id, SCOPE_HEADER, "ship_info")
    assert (ship.source_path, ship.transform, ship.is_enabled, ship.is_required) == (
        "ShipInfo", "string", True, False,
    )
    [remark] = _rows(db, company.id, SCOPE_LINE, "line_remark")
    [heading] = _rows(db, company.id, SCOPE_LINE, "section_heading")
    assert (remark.source_path, remark.is_enabled, remark.is_required) == ("FurtherDescription", True, False)
    assert (heading.source_path, heading.is_enabled, heading.is_required) == ("SectionHeading", True, False)

    # idempotent
    db.expire_all()
    assert helper(db, schema=None) == 0
    db.expire_all()
    for scope, field in ((SCOPE_HEADER, "ship_info"), (SCOPE_LINE, "line_remark"),
                         (SCOPE_LINE, "section_heading")):
        assert len(_rows(db, company.id, scope, field)) == 1


def test_backfill_keeps_a_hand_written_query_and_seeds_rows_disabled(db, caplog):  # SS-3
    helper = _backfill()
    company = _company(db, database="AED_RM_CUSTOM")
    custom_header = (
        "SELECT h.DocKey, h.DocNo, h.Cancelled, h.LastModified "
        "FROM {database}.dbo.SO AS h"
    ).replace("{database}", "AED_RM_CUSTOM")
    custom_line = (
        "SELECT d.DtlKey, d.Qty FROM {database}.dbo.SODTL AS d WHERE d.DocKey = :doc_key"
    ).replace("{database}", "AED_RM_CUSTOM")
    config = _task(db, company, query=custom_header, line_query=custom_line,
                   columns=["DocKey", "DocNo"], line_columns=["DtlKey", "Qty"])
    config_id = config.id
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        helper(db, schema=None)
    db.expire_all()

    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == custom_header
    assert after.source_config["lineQuery"] == custom_line
    assert after.result_columns == ["DocKey", "DocNo"]
    assert after.line_result_columns == ["DtlKey", "Qty"]
    for scope, field in ((SCOPE_HEADER, "ship_info"), (SCOPE_LINE, "line_remark"),
                         (SCOPE_LINE, "section_heading")):
        rows = _rows(db, company.id, scope, field)
        assert len(rows) == 1 and rows[0].is_enabled is False, (scope, field)
    assert [r for r in caplog.records
            if r.levelno >= logging.WARNING and config_id in r.getMessage()]


def test_backfill_rewrites_header_only_when_only_the_header_is_preset(db):  # SS-3
    helper = _backfill()
    company = _company(db, database="AED_RM_MIX")
    custom_line = "SELECT d.DtlKey, d.Qty FROM AED_RM_MIX.dbo.SODTL AS d WHERE d.DocKey = :doc_key"
    config = _task(
        db, company, query=_OLD_SO_HEADER_QUERY.replace("{database}", "AED_RM_MIX"),
        line_query=custom_line, line_columns=["DtlKey", "Qty"],
    )
    config_id = config.id
    db.expire_all()
    helper(db, schema=None)
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _SO_HEADER_QUERY.replace("{database}", "AED_RM_MIX")
    assert after.source_config["lineQuery"] == custom_line
    assert _rows(db, company.id, SCOPE_HEADER, "ship_info")[0].is_enabled is True
    assert _rows(db, company.id, SCOPE_LINE, "line_remark")[0].is_enabled is False


def test_backfill_ignores_a_query_for_another_companys_database(db):  # SS-3
    helper = _backfill()
    company = _company(db, database="AED_RM_MINE")
    config = _task(
        db, company,
        query=_OLD_SO_HEADER_QUERY.replace("{database}", "AED_RM_OTHER"),
        line_query=_OLD_SO_LINE_QUERY.replace("{database}", "AED_RM_OTHER"),
    )
    config_id, stored = config.id, config.source_config["query"]
    db.expire_all()
    helper(db, schema=None)
    db.expire_all()
    assert db.get(AcEntityConfig, config_id).source_config["query"] == stored
    assert _rows(db, company.id, SCOPE_HEADER, "ship_info")[0].is_enabled is False


def test_backfill_never_touches_existing_rows(db):  # SS-3
    helper = _backfill()
    company, _ = _preset_task(db, "AED_RM_HASROW")
    existing = AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        scope=SCOPE_HEADER, source_path="ShipInfo", canonical_field="ship_info",
        transform="string", formula="ShipInfo", is_enabled=False, is_required=False,
    )
    db.add(existing)
    db.commit()
    existing_id = existing.id
    db.expire_all()
    helper(db, schema=None)
    db.expire_all()
    rows = _rows(db, company.id, SCOPE_HEADER, "ship_info")
    assert [r.id for r in rows] == [existing_id]
    assert rows[0].is_enabled is False and rows[0].formula == "ShipInfo"


def test_update_tenant_runs_the_backfill_from_the_previous_manifest_version(db):  # SS-3
    from modules.autocount.bootstrap import update_tenant

    company, config_id = _preset_task(db, "AED_RM_UPD")
    update_tenant(db, DEFAULT_TENANT_ID, "0.16.0")
    db.commit()
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == _SO_HEADER_QUERY.replace("{database}", "AED_RM_UPD")
    assert len(_rows(db, company.id, SCOPE_LINE, "section_heading")) == 1


def test_update_tenant_never_reseeds_rows_an_operator_deleted(db):  # SS-3
    from modules.autocount.bootstrap import update_tenant

    company, _ = _preset_task(db, "AED_RM_DEL")
    update_tenant(db, DEFAULT_TENANT_ID, "0.16.0")
    db.commit()
    db.expire_all()
    for scope, field in ((SCOPE_HEADER, "ship_info"), (SCOPE_LINE, "line_remark")):
        seeded = _rows(db, company.id, scope, field)
        assert len(seeded) == 1, (scope, field)
        for row in seeded:
            db.delete(row)
    db.commit()
    update_tenant(db, DEFAULT_TENANT_ID, "0.17.0")
    db.commit()
    db.expire_all()
    assert _rows(db, company.id, SCOPE_HEADER, "ship_info") == []
    assert _rows(db, company.id, SCOPE_LINE, "line_remark") == []


def test_module_migration_chains_onto_the_head_and_calls_the_helper():  # SS-3
    candidates = sorted(VERSIONS_DIR.glob(NEW_REVISION_GLOB))
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    assert revision and len(revision.group(1)) <= 32
    spec = importlib.util.spec_from_file_location("_ac_rev_so_remark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS_REVISION
    assert HELPER_NAME in text
    for other in VERSIONS_DIR.glob("*.py"):
        if other == path:
            continue
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', other.read_text(), re.M)
        assert not (down and down.group(1) == revision.group(1)), other.name


def test_manifest_version_is_bumped_past_0_16_0():  # SS-3
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    assert tuple(int(p) for p in manifest["version"].split(".")) > (0, 16, 0)
