"""SS-FURTHER-DESC-SEND (partner of sorento-crm #2766): the RAW AutoCount line
`FurtherDescription` (RTF, embedded images included) on canonical SO and PO
lines as `further_description_rtf`, contract-gated at 2.16, and on the B6
single-document read (`GET /documents/{kind}/{docKey}`) for sales orders and
purchase orders. `line_remark` is unchanged. Link PO writes are untouched.

Red first: every test here failed on main @3f627be6.
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
    FURTHER_DESC_RTF_MAX_BYTES,
    CanonicalPurchaseOrderLine,
    CanonicalSalesOrderLine,
    CanonicalShippingOrderLine,
)
from modules.autocount.mapping import LINE_FIELD_ALLOWED_TRANSFORMS, SCOPE_LINE, TRANSFORMS
from modules.autocount.mapping_catalog import line_accepted_field_names
from modules.autocount.models import SOURCE_IMPL_SQL_DB, AcCompany, AcEntityConfig, AcFieldMapping
from modules.autocount.presets import PO_PRESET, SO_PRESET, SPO_PRESET, PresetField
from modules.autocount.sinks_sorento import ContractVersion, FURTHER_DESC_RTF_CONTRACT_VERSION
from modules.autocount.write_back.frame import WriteFrame
from tests.test_autocount_write_back_gateway_qtso import Gw, gw  # noqa: F401
from tests.test_autocount_write_back_gateway_read import KEYS, _get, _seed
from tests.test_autocount_write_back_operations import db as wb_db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"

# An RTF note as AutoCount stores it: leading/trailing whitespace and CRLF are
# part of the bytes and must survive.
RTF = "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Tahoma;}}\\f0\\fs16 Rush \\b delivery\\b0\\par\r\n}\r\n"
FIELD = "further_description_rtf"
AT_GATE = ContractVersion(2, 16)
BELOW_GATE = ContractVersion(2, 15)


# ═════════════════════════ wire ══════════════════════════════════════════════


def test_contract_gate_is_2_16():
    assert (FURTHER_DESC_RTF_CONTRACT_VERSION.major, FURTHER_DESC_RTF_CONTRACT_VERSION.minor) == (2, 16)


def _so_line(**kw):
    return CanonicalSalesOrderLine(source_ref="AED:SO:1:1", product_ref="P1", qty_ordered=1, **kw)


def _po_line(**kw):
    return CanonicalPurchaseOrderLine(source_ref="AED:PO:1:1", product_ref="P1", qty_ordered=1, **kw)


@pytest.mark.parametrize("make", [_so_line, _po_line])
def test_raw_rtf_rides_the_wire_byte_for_byte_at_2_16(make):
    payload = make(further_description_rtf=RTF).sink_payload(contract_version=2, advertised_contract=AT_GATE)
    assert payload[FIELD] == RTF
    assert json.loads(json.dumps(payload))[FIELD].encode("utf-8") == RTF.encode("utf-8")


@pytest.mark.parametrize("make", [_so_line, _po_line])
@pytest.mark.parametrize("advertised", [None, BELOW_GATE, 2.9, ContractVersion(1, 0)])
def test_never_sent_below_the_gate(make, advertised):
    payload = make(further_description_rtf=RTF).sink_payload(contract_version=2, advertised_contract=advertised)
    assert FIELD not in payload


@pytest.mark.parametrize("make", [_so_line, _po_line])
def test_never_sent_to_a_v1_consumer_even_when_advertised(make):
    payload = make(further_description_rtf=RTF).sink_payload(contract_version=1, advertised_contract=AT_GATE)
    assert FIELD not in payload


@pytest.mark.parametrize("make", [_so_line, _po_line])
def test_a_cleared_note_is_an_explicit_null_past_the_gate(make):
    payload = make().sink_payload(contract_version=2, advertised_contract=AT_GATE)
    assert FIELD in payload and payload[FIELD] is None


def test_line_remark_is_unchanged():
    line = _so_line(line_remark="Rush", further_description_rtf=RTF)
    below = line.sink_payload(contract_version=2, advertised_contract=BELOW_GATE)
    assert below["line_remark"] == "Rush" and FIELD not in below
    assert "line_remark" not in CanonicalPurchaseOrderLine.model_fields


def test_spo_lines_do_not_carry_it():
    assert FIELD not in CanonicalShippingOrderLine.model_fields
    assert FIELD not in line_accepted_field_names(ENTITY_SHIPPING_ORDER)


def test_catalog_offers_it_for_so_and_po():
    for entity in (ENTITY_SALES_ORDER, ENTITY_PURCHASE_ORDER):
        assert FIELD in line_accepted_field_names(entity), entity


def test_a_1_2_mb_note_passes_unchanged():
    big = "{\\rtf1 " + "a" * (1_200_000) + "}"
    assert _po_line(further_description_rtf=big).further_description_rtf == big


@pytest.mark.parametrize("make", [_so_line, _po_line])
def test_over_the_cap_is_dropped_never_cut(make, caplog):
    huge = "x" * (FURTHER_DESC_RTF_MAX_BYTES + 1)
    with caplog.at_level(logging.WARNING, logger="foundryx.autocount"):
        line = make(further_description_rtf=huge)
    assert line.further_description_rtf is None
    assert "over the" in caplog.text and "xxxx" not in caplog.text


def test_the_cap_counts_utf8_bytes():
    # 3 bytes per char: under the cap in chars, over it in bytes
    text = "中" * (FURTHER_DESC_RTF_MAX_BYTES // 3 + 1)
    assert _so_line(further_description_rtf=text).further_description_rtf is None


# ═════════════════════════ transform ═════════════════════════════════════════


def test_raw_text_keeps_every_byte():
    raw = TRANSFORMS["raw_text"]
    assert raw(RTF) == RTF
    assert raw("  padded  ") == "  padded  "
    assert raw(None) is None and raw("") is None and raw(" \r\n ") is None
    assert TRANSFORMS["string"](RTF) != RTF  # the reason raw_text exists


def test_only_raw_text_may_feed_the_field():
    assert LINE_FIELD_ALLOWED_TRANSFORMS[FIELD] == frozenset({"raw_text"})


def test_frontend_offers_the_raw_text_transform():
    meta = (MODULE_ROOT.parents[2] / "service_frontend" / "app" / "(protected)" / "autocount"
            / "components" / "autocount-meta.ts").read_text()
    assert "value: 'raw_text'" in meta


# ═════════════════════════ presets ═══════════════════════════════════════════


def test_so_preset_maps_further_description_raw_and_keeps_line_remark():
    rows = [f for f in SO_PRESET.line if f.source_path == "FurtherDescription"]
    assert PresetField("FurtherDescription", FIELD, "raw_text") in rows
    assert PresetField("FurtherDescription", "line_remark", "string") in rows


def test_po_preset_selects_and_maps_further_description():
    assert "d.FurtherDescription AS FurtherDescription" in PO_PRESET.line_query
    assert PresetField("FurtherDescription", FIELD, "raw_text") in PO_PRESET.line


def test_spo_preset_is_unchanged():
    assert "FurtherDescription" not in SPO_PRESET.line_query
    assert not [f for f in SPO_PRESET.line if f.source_path == "FurtherDescription"]


def test_frozen_po_target_equals_todays_preset():
    from modules.autocount import backfill

    assert backfill._FURTHER_DESC_PO_LINE_QUERY == PO_PRESET.line_query
    assert backfill._PRE_FURTHER_DESC_PO_LINE_QUERY == SPO_PRESET.line_query


# ═════════════════════════ backfill ══════════════════════════════════════════


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db, database):
    api = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name=f"AutoCount {database}",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}), is_active=True,
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


def _task(db, company, entity, line_query, line_columns=()):
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=entity, source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x", "query": "SELECT 1", "lineQuery": line_query,
        "keyColumns": ["DocKey"], "watermarkColumn": "LastModified", "comparedColumns": [],
    }
    config.line_result_columns = list(line_columns)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _rows(db, company_id, entity, field=FIELD):
    return db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == company_id, AcFieldMapping.entity_type == entity,
        AcFieldMapping.scope == SCOPE_LINE, AcFieldMapping.canonical_field == field,
    ).all()


def _line_row(db, company, entity, source, field, transform="string", enabled=True):
    db.add(AcFieldMapping(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=entity, scope=SCOPE_LINE,
        source_path=source, canonical_field=field, transform=transform, is_enabled=enabled, sort_order=0,
    ))
    db.commit()


def _helper():
    from modules.autocount.backfill import backfill_further_desc_fields

    return backfill_further_desc_fields


def test_po_preset_task_is_rewritten_and_gets_an_enabled_row(db):
    company = _company(db, "AED_FD_PO")
    old = SPO_PRESET.line_query.replace("{database}", "AED_FD_PO")  # the previous PO text
    cfg = _task(db, company, ENTITY_PURCHASE_ORDER, old, ["DtlKey", "Qty"])
    assert _helper()(db, schema=None) == 2
    db.expire_all()
    after = db.get(AcEntityConfig, cfg.id)
    assert after.source_config["lineQuery"] == PO_PRESET.line_query.replace("{database}", "AED_FD_PO")
    assert after.line_result_columns == ["DtlKey", "Qty", "FurtherDescription"]
    [row] = _rows(db, company.id, ENTITY_PURCHASE_ORDER)
    assert (row.source_path, row.transform, row.is_enabled, row.is_required) == (
        "FurtherDescription", "raw_text", True, False)
    db.expire_all()
    assert _helper()(db, schema=None) == 0  # idempotent


def test_po_hand_written_query_is_untouched_and_row_disabled(db, caplog):
    company = _company(db, "AED_FD_PO_HAND")
    cfg = _task(db, company, ENTITY_PURCHASE_ORDER, "SELECT * FROM PODTL WHERE DocKey = :doc_key")
    with caplog.at_level(logging.WARNING):
        assert _helper()(db, schema=None) == 1
    db.expire_all()
    assert db.get(AcEntityConfig, cfg.id).source_config["lineQuery"].startswith("SELECT * FROM PODTL")
    [row] = _rows(db, company.id, ENTITY_PURCHASE_ORDER)
    assert row.is_enabled is False
    assert cfg.id in caplog.text and "further_description_rtf" in caplog.text


def test_so_task_reading_the_column_gets_an_enabled_row_and_line_remark_is_untouched(db):
    company = _company(db, "AED_FD_SO")
    _task(db, company, ENTITY_SALES_ORDER, "SELECT custom", ["DtlKey"])
    _line_row(db, company, ENTITY_SALES_ORDER, "FurtherDescription", "line_remark")
    assert _helper()(db, schema=None) == 1
    db.expire_all()
    [row] = _rows(db, company.id, ENTITY_SALES_ORDER)
    assert (row.transform, row.is_enabled) == ("raw_text", True)
    [remark] = _rows(db, company.id, ENTITY_SALES_ORDER, "line_remark")
    assert remark.transform == "string"  # unchanged


def test_so_task_on_the_preset_text_gets_an_enabled_row(db):
    company = _company(db, "AED_FD_SO_P")
    _task(db, company, ENTITY_SALES_ORDER, SO_PRESET.line_query.replace("{database}", "AED_FD_SO_P"))
    _helper()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id, ENTITY_SALES_ORDER)] == [True]


def test_so_task_not_reading_the_column_gets_a_disabled_row(db):
    company = _company(db, "AED_FD_SO_N")
    _task(db, company, ENTITY_SALES_ORDER, "SELECT DtlKey FROM SODTL", ["DtlKey"])
    _helper()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id, ENTITY_SALES_ORDER)] == [False]


def test_an_existing_row_in_any_state_is_never_reseeded(db):
    company = _company(db, "AED_FD_EXIST")
    _task(db, company, ENTITY_SALES_ORDER, "SELECT x", ["FurtherDescription"])
    _line_row(db, company, ENTITY_SALES_ORDER, "Other", FIELD, transform="raw_text", enabled=False)
    assert _helper()(db, schema=None) == 0
    db.expire_all()
    [row] = _rows(db, company.id, ENTITY_SALES_ORDER)
    assert row.source_path == "Other" and row.is_enabled is False


def test_spo_tasks_are_never_touched(db):
    company = _company(db, "AED_FD_SPO")
    old = SPO_PRESET.line_query.replace("{database}", "AED_FD_SPO")
    cfg = _task(db, company, ENTITY_SHIPPING_ORDER, old)
    assert _helper()(db, schema=None) == 0
    db.expire_all()
    assert db.get(AcEntityConfig, cfg.id).source_config["lineQuery"] == old
    assert _rows(db, company.id, ENTITY_SHIPPING_ORDER) == []


def test_another_tenant_is_skipped_when_scoped(db):
    company = _company(db, "AED_FD_SCOPE")
    _task(db, company, ENTITY_PURCHASE_ORDER, SPO_PRESET.line_query.replace("{database}", "AED_FD_SCOPE"))
    assert _helper()(db, schema=None, tenant_id="another-tenant") == 0


def test_update_tenant_runs_it_from_0_23_0_only(db):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, "AED_FD_UPD")
    _task(db, company, ENTITY_PURCHASE_ORDER, SPO_PRESET.line_query.replace("{database}", "AED_FD_UPD"))
    update_tenant(db, DEFAULT_TENANT_ID, "0.24.0")
    db.commit()
    db.expire_all()
    assert _rows(db, company.id, ENTITY_PURCHASE_ORDER) == []
    update_tenant(db, DEFAULT_TENANT_ID, "0.23.0")
    db.commit()
    db.expire_all()
    assert len(_rows(db, company.id, ENTITY_PURCHASE_ORDER)) == 1


def test_manifest_is_0_24_0_or_later():
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    assert tuple(int(p) for p in manifest["version"].split(".")) >= (0, 24, 0)


def test_migration_0050_chains_onto_0049_single_head():
    [path] = sorted(VERSIONS_DIR.glob("0050_autocount_further_desc.py"))
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M).group(1)
    assert len(revision) <= 32
    spec = importlib.util.spec_from_file_location("_ac_rev_further_desc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0049_autocount_line_notes_conn"
    assert "backfill_further_desc_fields" in text
    downs = [re.search(r'^down_revision[^=]*=\s*"([^"]+)"', p.read_text(), re.M) for p in VERSIONS_DIR.glob("*.py")]
    assert sum(1 for d in downs if d and d.group(1) == "0049_autocount_line_notes_conn") == 1


# ═════════════════════════ B6 read ═══════════════════════════════════════════


class _SoNotes:
    """The AutoCount DB as the B6 SO read sees it: stored Further Description per DtlKey."""

    def __init__(self, notes):
        self.notes = notes
        self.calls = 0

    def read(self, kind, doc):  # PO / SPO overlay: not used by an SO read
        return None

    def read_so_notes(self, doc):
        self.calls += 1
        return self.notes


def _so_keys(gw):
    return [r["DtlKey"] for r in gw.h.vendor.rows("SO", KEYS["SO"])]


def test_so_read_carries_each_rows_raw_further_description(client, gw, monkeypatch):
    _seed(gw, "SO")
    first, second = _so_keys(gw)
    source = _SoNotes({first: RTF, second: ""})
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: source)
    r = _get(client, gw, "sales-orders", KEYS["SO"])
    assert r.status_code == 200, r.text
    rows = r.json()["document"]["Details"]
    assert [row["FurtherDescription"] for row in rows] == [RTF, ""]
    assert source.calls == 1
    assert gw.h.vendor.writes() == []


def test_so_read_with_the_db_unread_carries_no_further_description_and_no_marker(client, gw, monkeypatch):
    _seed(gw, "SO")
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _SoNotes(None))
    r = _get(client, gw, "sales-orders", KEYS["SO"])
    assert r.status_code == 200, r.text
    assert all("FurtherDescription" not in row for row in r.json()["document"]["Details"])
    assert "_dbUnread" not in r.text and "_dbLegacy" not in r.text


def test_so_read_missing_a_row_in_the_db_is_unread(client, gw, monkeypatch):
    _seed(gw, "SO")
    first, _second = _so_keys(gw)
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: _SoNotes({first: RTF}))
    rows = _get(client, gw, "sales-orders", KEYS["SO"]).json()["document"]["Details"]
    assert all("FurtherDescription" not in row for row in rows)


def test_so_read_with_no_source_is_unchanged(client, gw, monkeypatch):
    _seed(gw, "SO")
    monkeypatch.setattr(WriteFrame, "_line_notes_source", lambda self, company: None)
    r = _get(client, gw, "sales-orders", KEYS["SO"])
    assert r.status_code == 200 and all("FurtherDescription" not in row for row in r.json()["document"]["Details"])
    assert "_dbLegacy" not in r.text


def test_po_read_carries_the_raw_further_description(client, gw):
    _seed(gw, "PO")
    rows = gw.h.vendor.rows("PO", KEYS["PO"])
    rows[0]["FurtherDescription"] = RTF  # the conftest DB echo returns it as stored
    r = _get(client, gw, "purchase-orders", KEYS["PO"])
    assert r.status_code == 200, r.text
    assert r.json()["document"]["Details"][0]["FurtherDescription"] == RTF


def test_sql_so_notes_select_is_read_only_and_keyed_by_docno():
    from modules.autocount.write_back import line_notes

    sql = str(line_notes._SO_NOTES_SELECT)
    assert sql.startswith("SELECT ") and ":k" in sql and ":n" in sql
    assert not re.search(r"\b(UPDATE|INSERT|DELETE|MERGE|EXEC)\b", sql, re.I)
