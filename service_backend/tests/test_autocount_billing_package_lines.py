"""SS-PACKAGE-LINES - AutoCount package parent/child keys on billing lines.

AutoCount emits a package sale as one PARENT line (blank ``ItemCode``,
``ParentDtlKey`` 0, carrying Qty / UnitPrice / SubTotal) plus N CHILD lines
whose ``ParentDtlKey`` is the parent's ``DtlKey``; the FIRST child repeats the
parent's SubTotal, the others are 0. The CRM summed both and double counted.
The shared service keeps both lines untouched and carries the keys so the CRM
decides what counts (``invoiced_sales.counted_line()``).

Fixture shaped like M2601-0858 (parent 20448971, child 20448973 IBKS8050-BL,
both Seq 16, 17 x 329 = 5593). All values are fake.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.documents import (
    ENTITY_CASH_SALE,
    ENTITY_CREDIT_NOTE,
    ENTITY_DEBIT_NOTE,
    ENTITY_INVOICE,
    PACKAGE_LINES_MIN_CONTRACT,
    CanonicalBillingDocumentLine,
)
from modules.autocount.mapping import SCOPE_LINE
from modules.autocount.mapping_catalog import line_accepted_field_names
from modules.autocount.models import SOURCE_IMPL_SQL_DB, AcCompany, AcEntityConfig, AcFieldMapping
from modules.autocount.presets import BILLING_PACKAGE_COLUMNS, DOCUMENT_PRESETS
from modules.autocount.sinks_sorento import (
    PACKAGE_LINES_CONTRACT_VERSION,
    REPLACES_LINE_REF_CONTRACT_VERSION,
    ContractVersion,
    SorentoSink,
)

from tests.test_autocount_billing_feed import DB, LINE_WIRE_KEYS, _engine, _iv_line, _iv_row, _ok

PARENT_DTL, CHILD_DTL, CHILD2_DTL = 20448971, 20448973, 20448974
DOC_KEY = 7700858
# Crew ruling 7 Nov: only IVDTL.ParentDtlKey is confirmed on the real schema.
PACKAGE_ENTITIES = (ENTITY_INVOICE,)
UNCONFIRMED_ENTITIES = (ENTITY_CASH_SALE, ENTITY_CREDIT_NOTE, ENTITY_DEBIT_NOTE)
PACKAGE_WIRE_KEYS = {"line_type", "parent_line_ref"}
NEW = ContractVersion(2, 13)


def _package_row() -> dict:
    """M2601-0858: one parent, the first child repeating its price, a 0 child."""
    common = {
        "DocKey": DOC_KEY, "UOM": "UNIT", "TaxCode": None, "TaxRate": None,
        "Tax": Decimal("0.00"), "DiscountAmt": Decimal("0.00"),
        "FromDocType": None, "FromDocNo": None, "FromDocDtlKey": None,
        "LinkSODocKey": None, "LinkDODocKey": None,
    }
    parent = _iv_line(
        **common, DtlKey=PARENT_DTL, Seq=16, ItemAutoKey=None, ItemCode=None,
        Description="Bedroom package", Qty=Decimal("17"), UnitPrice=Decimal("329"),
        SubTotalExTax=Decimal("5593.00"), SubTotal=Decimal("5593.00"),
        ParentDtlKey=0,
    )
    child = _iv_line(
        **common, DtlKey=CHILD_DTL, Seq=16, ItemAutoKey=10442, ItemCode="IBKS8050-BL",
        Description="Bed frame", Qty=Decimal("17"), UnitPrice=Decimal("329"),
        SubTotalExTax=Decimal("5593.00"), SubTotal=Decimal("5593.00"),
        ParentDtlKey=PARENT_DTL,
    )
    child2 = _iv_line(
        **common, DtlKey=CHILD2_DTL, Seq=17, ItemAutoKey=10443, ItemCode="IBKS8050-MT",
        Description="Mattress", Qty=Decimal("17"), UnitPrice=Decimal("0"),
        SubTotalExTax=Decimal("0.00"), SubTotal=Decimal("0.00"),
        ParentDtlKey=PARENT_DTL,
    )
    return _iv_row(
        DocKey=DOC_KEY, DocNo="M2601-0858", TotalExTax=Decimal("5593.00"),
        Tax=Decimal("0.00"), NetTotal=Decimal("5593.00"), LocalNetExTax=Decimal("5593.00"),
        _lines=[parent, child, child2],
    )


# ── preset ───────────────────────────────────────────────────────────────────


def test_only_the_confirmed_column_is_configured():
    assert BILLING_PACKAGE_COLUMNS == {"IVDTL": ("ParentDtlKey",)}


def test_invoice_lines_select_parent_dtl_key_only():
    preset = DOCUMENT_PRESETS[ENTITY_INVOICE]
    assert "d.ParentDtlKey AS ParentDtlKey" in preset.line_query
    assert "DtlType" not in preset.line_query and "PackageDocKey" not in preset.line_query
    rows = {f.source_path: (f.canonical_field, f.transform, f.enabled) for f in preset.line}
    assert rows["ParentDtlKey"] == ("parent_dtl_key", "int", True)
    assert "DtlType" not in rows


@pytest.mark.parametrize("entity_type", UNCONFIRMED_ENTITIES)
def test_unconfirmed_tables_select_no_package_column(entity_type):
    preset = DOCUMENT_PRESETS[entity_type]
    for column in ("DtlType", "ParentDtlKey", "PackageDocKey"):
        assert column not in preset.line_query
    assert {"DtlType", "ParentDtlKey"}.isdisjoint(f.source_path for f in preset.line)


def test_widening_is_one_config_entry(monkeypatch):
    """A newly confirmed table/column needs only a BILLING_PACKAGE_COLUMNS
    entry: the query and its line row follow from it."""
    from modules.autocount import presets

    monkeypatch.setitem(presets.BILLING_PACKAGE_COLUMNS, "CSDTL", ("ParentDtlKey", "DtlType"))
    preset = presets._billing_preset(
        "x", ENTITY_CASH_SALE, "CS", "CSDTL", transferred=True, doc_status=False,
    )
    assert "d.ParentDtlKey AS ParentDtlKey, d.DtlType AS DtlType" in preset.line_query
    rows = {f.source_path: f.canonical_field for f in preset.line}
    assert (rows["ParentDtlKey"], rows["DtlType"]) == ("parent_dtl_key", "line_type")


def test_no_line_is_cut_and_the_aggregates_are_unchanged():
    """SS never drops a package line: the cut and the sweep do not read the key."""
    preset = DOCUMENT_PRESETS[ENTITY_INVOICE]
    for query in (preset.header_query, preset.fingerprint_query):
        assert "ParentDtlKey" not in query
    assert "ParentDtlKey" not in preset.line_query.split("WHERE", 1)[1]


@pytest.mark.parametrize("entity_type", [ENTITY_INVOICE, ENTITY_CASH_SALE])
def test_the_catalog_accepts_line_type_and_the_parent_input_only(entity_type):
    accepted = line_accepted_field_names(entity_type)
    assert {"line_type", "parent_dtl_key"} <= set(accepted)
    assert "parent_line_ref" not in accepted  # minted, never mapped


# ── mapping (M2601-0858) ─────────────────────────────────────────────────────


def test_a_package_keeps_every_line_and_names_each_childs_parent():
    mapped = _engine(ENTITY_INVOICE).map_document(_package_row())
    assert mapped.ok, [e.message() for e in mapped.errors]
    header = f"{DB}:IV:{DOC_KEY}"
    parent, child, child2 = mapped.record.lines
    assert [line.source_ref for line in mapped.record.lines] == [
        f"{header}:{PARENT_DTL}", f"{header}:{CHILD_DTL}", f"{header}:{CHILD2_DTL}",
    ]
    assert parent.parent_line_ref is None
    assert child.parent_line_ref == parent.source_ref
    assert child2.parent_line_ref == parent.source_ref
    assert [line.line_type for line in mapped.record.lines] == [None, None, None]
    # Both copies of the price survive: the CRM's rule, not ours.
    assert parent.line_total == child.line_total == Decimal("5593.00")
    assert mapped.record.total == Decimal("5593.00")


def test_a_null_parent_key_is_a_top_level_line():
    row = _iv_row(_lines=[_iv_line(ParentDtlKey=None)])
    [line] = _engine(ENTITY_INVOICE).map_document(row).record.lines
    assert line.parent_line_ref is None and line.line_type is None


@pytest.mark.parametrize("parent_value", ["0", " 0 ", "", None])
def test_a_string_mapped_parent_key_of_zero_mints_no_ref(parent_value):
    """Review finding: an operator remapping ParentDtlKey with a `string`
    transform must not turn every parent line into a child of `:0`."""
    from modules.autocount.mapping import MappingEngine, MappingRow, flat_profile
    from modules.autocount.mapping import SCOPE_HEADER, SCOPE_LINE as LINE

    preset = DOCUMENT_PRESETS[ENTITY_INVOICE]
    rows = [
        MappingRow(f.source_path, f.canonical_field,
                   "string" if f.source_path == "ParentDtlKey" else f.transform,
                   scope, is_required=f.required, is_enabled=f.enabled, formula=f.formula)
        for scope, fields in ((SCOPE_HEADER, preset.header), (LINE, preset.line))
        for f in fields
    ]
    engine = MappingEngine(rows, entity_type=ENTITY_INVOICE,
                           profile=flat_profile(ENTITY_INVOICE, list(preset.key_columns)),
                           database_name=DB, link_book="fakebook")
    row = _iv_row(_lines=[_iv_line(ParentDtlKey=parent_value), _iv_line(DtlKey=2, ParentDtlKey="1")])
    mapped = engine.map_document(row)
    assert mapped.ok, [e.message() for e in mapped.errors]
    top, child = mapped.record.lines
    assert top.parent_line_ref is None
    assert child.parent_line_ref == f"{DB}:IV:88213:1"


def test_the_package_fields_survive_the_staged_json_round_trip():
    record = _engine(ENTITY_INVOICE).map_document(_package_row()).record
    again = type(record).model_validate_json(record.model_dump_json())
    assert again.sink_payload(advertised_contract=NEW) == record.sink_payload(advertised_contract=NEW)


# ── wire (contract 2.13 gate) ────────────────────────────────────────────────


def test_the_gate_is_2_13():
    assert PACKAGE_LINES_MIN_CONTRACT == (2, 13)
    assert (PACKAGE_LINES_CONTRACT_VERSION.major, PACKAGE_LINES_CONTRACT_VERSION.minor) == (2, 13)


@pytest.mark.parametrize("advertised", [None, ContractVersion(2, 6), REPLACES_LINE_REF_CONTRACT_VERSION])
def test_an_older_crm_gets_the_2_6_line_unchanged(advertised):
    payload = _engine(ENTITY_INVOICE).map_document(_package_row()).record.sink_payload(
        advertised_contract=advertised,
    )
    for line in payload["lines"]:
        assert set(line) == LINE_WIRE_KEYS


def test_a_2_13_crm_gets_line_type_and_parent_line_ref():
    payload = _engine(ENTITY_INVOICE).map_document(_package_row()).record.sink_payload(
        advertised_contract=NEW,
    )
    header = f"{DB}:IV:{DOC_KEY}"
    parent, child, child2 = payload["lines"]
    for line in payload["lines"]:
        assert set(line) == LINE_WIRE_KEYS | PACKAGE_WIRE_KEYS
        assert "parent_dtl_key" not in line
    assert (parent["line_type"], parent["parent_line_ref"]) == (None, None)
    assert (child["line_type"], child["parent_line_ref"]) == (None, f"{header}:{PARENT_DTL}")
    assert child2["parent_line_ref"] == f"{header}:{PARENT_DTL}"
    assert (child["line_total"], child2["line_total"]) == (5593, 0)


def test_the_new_fields_are_wire_fields_not_link_inputs():
    assert set(CanonicalBillingDocumentLine.PACKAGE_FIELDS) == PACKAGE_WIRE_KEYS
    assert "parent_dtl_key" in CanonicalBillingDocumentLine.LINK_INPUT_FIELDS
    assert PACKAGE_WIRE_KEYS.isdisjoint(CanonicalBillingDocumentLine.SINK_FIELDS)


@pytest.mark.parametrize("advertised,expected", [(None, False), (ContractVersion(2, 12), False), (NEW, True)])
def test_the_sink_sends_the_package_fields_on_the_advertised_contract(advertised, expected):
    requests: List[httpx.Request] = []

    def handle(request):
        requests.append(request)
        return _ok(request)

    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=ENTITY_INVOICE,
                       company_code="ABC", contract_version=2,
                       transport=httpx.MockTransport(handle))
    sink.advertised_contract_version = advertised
    record = _engine(ENTITY_INVOICE).map_document(_package_row()).record
    [result] = sink.write_batch([record], request_id="t")
    assert result.delivered is True
    [line_parent, line_child, _] = json.loads(requests[0].content)["records"][0]["lines"]
    assert ("parent_line_ref" in line_child) is expected
    if expected:
        assert line_child["parent_line_ref"] == line_parent["source_ref"]


# ── backfill (module 0.22.0 / Alembic 0041) ──────────────────────────────────


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db, database: str, tenant_id: str = DEFAULT_TENANT_ID) -> AcCompany:
    api = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name=f"AC {database}",
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


def _config(db, company, entity_type, *, line_query=None, line_columns=None) -> str:
    from modules.autocount.backfill import _PRE_PACKAGE_BILLING_LINE_QUERIES

    if line_query is None:
        line_query = _PRE_PACKAGE_BILLING_LINE_QUERIES[entity_type].replace(
            "{database}", company.database_name,
        )
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=entity_type,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {"connectionId": "conn-x", "lineQuery": line_query}
    config.line_result_columns = line_columns
    db.add(config)
    db.commit()
    return config.id


def _rows(db, company_id, entity_type, source_path) -> List[AcFieldMapping]:
    return db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == company_id,
        AcFieldMapping.entity_type == entity_type,
        AcFieldMapping.scope == SCOPE_LINE,
        AcFieldMapping.source_path == source_path,
    ).all()


def _run(db, **kwargs) -> int:
    from modules.autocount.backfill import backfill_billing_package_lines

    touched = backfill_billing_package_lines(db, schema=None, **kwargs)
    db.commit()
    db.expire_all()
    return touched


def test_the_frozen_package_texts_are_todays_preset():
    from modules.autocount.backfill import _PACKAGE_BILLING_LINE_QUERIES

    assert set(_PACKAGE_BILLING_LINE_QUERIES) == set(PACKAGE_ENTITIES)
    for entity_type, text in _PACKAGE_BILLING_LINE_QUERIES.items():
        assert text == DOCUMENT_PRESETS[entity_type].line_query, entity_type


@pytest.mark.parametrize("entity_type", PACKAGE_ENTITIES)
def test_a_preset_task_gets_the_key_and_its_row(db, entity_type):
    company = _company(db, f"FAKE_DB_PKG_{entity_type.upper()}")
    config_id = _config(db, company, entity_type, line_columns=["DocKey", "DtlKey", "LinkDODocKey"])

    assert _run(db) == 2  # the task + one row
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["lineQuery"] == DOCUMENT_PRESETS[entity_type].line_query.replace(
        "{database}", company.database_name,
    )
    assert after.source_config["connectionId"] == "conn-x"
    assert after.line_result_columns == ["DocKey", "DtlKey", "LinkDODocKey", "ParentDtlKey"]
    [parent_row] = _rows(db, company.id, entity_type, "ParentDtlKey")
    assert (parent_row.canonical_field, parent_row.transform, parent_row.is_enabled) == (
        "parent_dtl_key", "int", True,
    )
    assert _run(db) == 0  # idempotent


def test_a_never_previewed_task_keeps_null_columns(db):
    company = _company(db, "FAKE_DB_PKG_NULL")
    config_id = _config(db, company, ENTITY_INVOICE, line_columns=None)
    assert _run(db) > 0
    assert db.get(AcEntityConfig, config_id).line_result_columns is None


def test_an_operator_row_on_the_target_is_never_duplicated(db):
    company = _company(db, "FAKE_DB_PKG_OWN")
    _config(db, company, ENTITY_INVOICE)
    db.add(AcFieldMapping(
        id=str(uuid.uuid4()), tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
        entity_type=ENTITY_INVOICE, scope=SCOPE_LINE, source_path="MyParent",
        canonical_field="parent_dtl_key", transform="int", is_required=False,
        is_enabled=True, sort_order=5,
    ))
    db.commit()
    assert _run(db) == 1  # the task only
    assert _rows(db, company.id, ENTITY_INVOICE, "ParentDtlKey") == []
    assert len(_rows(db, company.id, ENTITY_INVOICE, "MyParent")) == 1


def test_a_customised_query_is_left_alone_with_a_warning(db, caplog):
    company = _company(db, "FAKE_DB_PKG_CUSTOM")
    custom = "SELECT d.DocKey AS DocKey, d.DtlKey AS DtlKey FROM X AS d WHERE d.DocKey = :doc_key"
    config_id = _config(db, company, ENTITY_INVOICE, line_query=custom)
    with caplog.at_level(logging.WARNING, logger="foundryx.autocount"):
        assert _run(db) == 0
    assert db.get(AcEntityConfig, config_id).source_config["lineQuery"] == custom
    assert _rows(db, company.id, ENTITY_INVOICE, "ParentDtlKey") == []
    assert any("package-lines backfill" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("entity_type", UNCONFIRMED_ENTITIES)
def test_unconfirmed_entities_are_never_touched(db, entity_type):
    from modules.autocount.backfill import _OLD_BILLING_DO_LINE_QUERIES

    company = _company(db, f"FAKE_DB_PKG_NO_{entity_type.upper()}")
    text = _OLD_BILLING_DO_LINE_QUERIES.get(entity_type, _OLD_BILLING_DO_LINE_QUERIES[ENTITY_INVOICE])
    text = text.replace("{database}", company.database_name)
    config_id = _config(db, company, entity_type, line_query=text)
    assert _run(db) == 0
    assert db.get(AcEntityConfig, config_id).source_config["lineQuery"] == text


def test_the_pass_scopes_to_one_tenant(db):
    company = _company(db, "FAKE_DB_PKG_SCOPE")
    config_id = _config(db, company, ENTITY_INVOICE)
    assert _run(db, tenant_id="some-other-tenant") == 0
    assert "ParentDtlKey" not in db.get(AcEntityConfig, config_id).source_config["lineQuery"]
    assert _run(db, tenant_id=DEFAULT_TENANT_ID) > 0


@pytest.mark.parametrize("from_version,rewritten", [("0.21.0", True), ("0.22.0", False)])
def test_update_tenant_runs_the_pass_below_0_22_only(db, from_version, rewritten):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, f"FAKE_DB_PKG_UPD_{from_version.replace('.', '')}")
    config_id = _config(db, company, ENTITY_INVOICE)
    update_tenant(db, DEFAULT_TENANT_ID, from_version)
    db.commit()
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    assert ("ParentDtlKey" in after.source_config["lineQuery"]) is rewritten


def test_the_manifest_is_at_least_0_22_0():
    manifest = Path(__file__).resolve().parents[1] / "modules" / "autocount" / "manifest.json"
    version = json.loads(manifest.read_text())["version"]
    assert tuple(int(p) for p in version.split(".")) >= (0, 22, 0)


def test_module_migration_0041_runs_the_pass():
    versions = Path(__file__).resolve().parents[1] / "modules" / "autocount" / "alembic" / "versions"
    [path] = list(versions.glob("0041_*.py"))
    text = path.read_text()
    revision = re.search(r'^revision: str = "([^"]+)"', text, re.M).group(1)
    assert len(revision) <= 32
    assert re.search(r'^down_revision[^=]*= "0040_autocount_write_ops"', text, re.M)
    assert "backfill_billing_package_lines" in text
