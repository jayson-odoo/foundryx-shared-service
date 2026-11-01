"""AutoCount Debtor ``DebtorType`` on the customer feed (lane
SS-DEBTOR-TYPE, partner of sorento-crm SALES-ACCOUNT-TYPE).

RED before the implementation. Same shape as ``sales_agent_code``
(SS-DEBTOR-AGENT): every AutoCount Debtor row (vendor API AND the open REST
``/debtorbypage``) carries ``DebtorType`` (Text, 5), and the ESB dropped it.
It now travels as ``market_segment_code`` - the CRM's EXISTING contract key
for AutoCount ``Debtor.DebtorType`` - on the customer row, on the push payload
AND the pull-gateway snapshot rows (both ``CanonicalCustomer.sink_payload()``).

Wire contract:
* key ``market_segment_code``, a string, trimmed, the type exactly as
  AutoCount holds it (no case folding, no lookup);
* OMITTED (never ``null``) when the Debtor's ``DebtorType`` is blank/absent -
  the master ``sink_payload`` rule, so a blank never clears a CRM value.

Existing tenants: every existing ``customer`` task gets a
``DebtorType -> market_segment_code`` row via
``backfill_customer_debtor_type`` (module Alembic 0035 + ``update_tenant``
from < 0.21.0).
"""
from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import re
from typing import Any, Dict

import pytest
import sqlalchemy as sa

import modules.autocount as autocount_module
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_CUSTOMER, CanonicalCustomer
from modules.autocount.mapping import (
    DEFAULT_CUSTOMER_MAPPING,
    DEFAULT_SUPPLIER_MAPPING,
    SCOPE_HEADER,
    MappingEngine,
    MappingRow,
    flat_profile,
)
from modules.autocount.mapping_catalog import accepted_field_names, ac_source_fields
from modules.autocount.models import (
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    SOURCE_IMPL_AUTOCOUNT_READ,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.presets import CUSTOMER_HTTP_PRESET

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"
FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "autocount_http" / "debtor_page.json"

HELPER_NAME = "backfill_customer_debtor_type"
PREVIOUS_REVISION = "0034_autocount_item_class"


def _backfill():
    from modules.autocount import backfill

    helper = getattr(backfill, HELPER_NAME, None)
    if helper is None:
        pytest.fail(f"modules.autocount.backfill has no `{HELPER_NAME}` helper yet")
    return helper


# ═════════════════════════ Group A - canonical, preset, wire ════════════════


def test_canonical_customer_sends_market_segment_code_right_after_sales_agent_code():
    fields = CanonicalCustomer.SINK_FIELDS
    assert "market_segment_code" in fields
    assert fields.index("market_segment_code") == fields.index("sales_agent_code") + 1


def test_sink_payload_carries_market_segment_code_verbatim():
    customer = CanonicalCustomer(source_ref="DB:1", code="300-A001", name="A",
                                 market_segment_code="CERAMIC")
    assert customer.sink_payload()["market_segment_code"] == "CERAMIC"


def test_sink_payload_omits_market_segment_code_when_none():
    payload = CanonicalCustomer(source_ref="DB:1", code="300-A001", name="A").sink_payload()
    assert "market_segment_code" not in payload


def test_supplier_never_carries_market_segment_code():
    """Creditor rows have no debtor type - the field is customer-only."""
    from modules.autocount.canonical.masters import CanonicalSupplier

    assert "market_segment_code" not in CanonicalSupplier.SINK_FIELDS
    assert all(r.canonical_field != "market_segment_code" for r in DEFAULT_SUPPLIER_MAPPING)


def test_mapping_catalog_accepts_market_segment_code_for_customer_only():
    assert "market_segment_code" in accepted_field_names(ENTITY_CUSTOMER)
    assert "market_segment_code" not in accepted_field_names("supplier")


def test_customer_source_catalog_offers_debtor_type():
    assert "DebtorType" in ac_source_fields(ENTITY_CUSTOMER)


def test_default_vendor_customer_mapping_maps_debtor_type():
    rows = [r for r in DEFAULT_CUSTOMER_MAPPING if r.canonical_field == "market_segment_code"]
    assert len(rows) == 1
    row = rows[0]
    assert (row.source_path, row.transform, row.scope) == ("DebtorType", "string", SCOPE_HEADER)
    assert row.is_enabled is True and row.is_required is False


def test_customer_preset_maps_debtor_type_enabled_after_sales_agent():
    pairs = [(f.source_path, f.canonical_field) for f in CUSTOMER_HTTP_PRESET.rows]
    assert ("DebtorType", "market_segment_code") in pairs
    assert pairs.index(("DebtorType", "market_segment_code")) == pairs.index(("SalesAgent", "sales_agent_code")) + 1
    row = CUSTOMER_HTTP_PRESET.rows[pairs.index(("DebtorType", "market_segment_code"))]
    assert row.transform == "string"
    assert row.enabled is True
    assert row.required is False
    assert row.formula is None


def _engine() -> MappingEngine:
    rows = [
        MappingRow(
            source_path=f.source_path, canonical_field=f.canonical_field,
            transform=f.transform, formula=f.formula, is_required=f.required,
            is_enabled=f.enabled,
        )
        for f in CUSTOMER_HTTP_PRESET.rows
    ]
    return MappingEngine(
        rows, entity_type=ENTITY_CUSTOMER,
        profile=flat_profile(ENTITY_CUSTOMER, list(CUSTOMER_HTTP_PRESET.key_fields)),
        database_name="AED_SORENTO",
    )


def _raw(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "AccNo": "300-X001", "CompanyName": "Example Trading", "Phone1": "",
        "SalesAgent": "AGENT A", "DebtorType": "SORENTO", "IsActive": "T",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "debtor_type, expected",
    [("SORENTO", "SORENTO"), ("PROJECT", "PROJECT"), ("  G01-A ", "G01-A"), ("mixed", "mixed")],
)
def test_preset_maps_debtor_type_onto_the_wire(debtor_type, expected):
    mapped = _engine().map_document(_raw(DebtorType=debtor_type))
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.sink_payload()["market_segment_code"] == expected


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_debtor_type_is_omitted_never_null(blank):
    mapped = _engine().map_document(_raw(DebtorType=blank))
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert "market_segment_code" not in mapped.record.sink_payload()


def test_absent_debtor_type_column_is_omitted():
    raw = _raw()
    raw.pop("DebtorType")
    mapped = _engine().map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert "market_segment_code" not in mapped.record.sink_payload()


def test_blank_debtor_type_leaves_the_payload_byte_identical_to_before():
    """Only a NON-blank type changes the payload (and so the staged hash): a
    customer with a blank type never re-stages because of this lane."""
    without_row = MappingEngine(
        [r for r in _engine().header_rows if r.canonical_field != "market_segment_code"],
        entity_type=ENTITY_CUSTOMER,
        profile=flat_profile(ENTITY_CUSTOMER, list(CUSTOMER_HTTP_PRESET.key_fields)),
        database_name="AED_SORENTO",
    )
    raw = _raw(DebtorType="")
    assert _engine().map_document(dict(raw)).record.sink_payload() == \
        without_row.map_document(dict(raw)).record.sink_payload()
    raw = _raw(DebtorType="CERAMIC")
    assert _engine().map_document(dict(raw)).record.sink_payload() != \
        without_row.map_document(dict(raw)).record.sink_payload()


def test_fixture_debtor_row_delivers_debtor_type():
    """The recorded ``/debtorbypage`` rows carry ``SORENTO`` and ``CERAMIC``."""
    rows = json.loads(FIXTURE.read_text())["Data"]
    got = [_engine().map_document(dict(r)).record.sink_payload()["market_segment_code"] for r in rows]
    assert got == ["SORENTO", "CERAMIC"]


# ═════════════════════════ Group B - backfill for existing tasks ════════════


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db, *, database: str, tenant_id: str = DEFAULT_TENANT_ID) -> AcCompany:
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


def _customer_config(db, company: AcCompany, *, source_impl: str = SOURCE_IMPL_AUTOCOUNT_HTTP,
                     path: str = "/debtorbypage", result_columns=None,
                     tenant_id: str = None, seed_rows: bool = True) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=tenant_id or company.tenant_id, company_id=company.id,
        entity_type=ENTITY_CUSTOMER, source_impl=source_impl,
    )
    if source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP:
        config.source_config = {"connectionId": "conn-x", "path": path, "keyFields": ["AccNo"]}
    elif source_impl == SOURCE_IMPL_SQL_DB:
        config.source_config = {"connectionId": "conn-x", "query": "SELECT 1", "keyColumns": ["AccNo"]}
    config.result_columns = list(result_columns or [])
    db.add(config)
    db.commit()
    db.refresh(config)
    if seed_rows:
        # A real task already maps something (its default/preset seed).
        _seed_existing_rows(db, company)
    return config


def _seed_existing_rows(db, company: AcCompany) -> None:
    for order, (src, dst) in enumerate(
        (("AccNo", "code"), ("CompanyName", "name"), ("Phone1", "phone_number"))
    ):
        db.add(AcFieldMapping(
            tenant_id=company.tenant_id, company_id=company.id, entity_type=ENTITY_CUSTOMER,
            scope=SCOPE_HEADER, source_path=src, canonical_field=dst,
            transform="string", is_enabled=True, is_required=(dst == "code"), sort_order=order,
        ))
    db.commit()


def _rows(db, company_id: str, field: str = "market_segment_code"):
    return [
        r for r in (
            db.query(AcFieldMapping)
            .filter(
                AcFieldMapping.company_id == company_id,
                AcFieldMapping.entity_type == ENTITY_CUSTOMER,
                AcFieldMapping.scope == SCOPE_HEADER,
            )
            .order_by(AcFieldMapping.sort_order)
            .all()
        )
        if r.canonical_field == field
    ]


def test_backfill_seeds_an_enabled_row_on_an_http_debtor_task(db):
    company = _company(db, database="AED_DT_HTTP")
    _customer_config(db, company)
    db.expire_all()

    assert _backfill()(db, schema=None) == 1
    db.expire_all()

    rows = _rows(db, company.id)
    assert len(rows) == 1
    row = rows[0]
    assert (row.source_path, row.transform, row.formula) == ("DebtorType", "string", None)
    assert row.is_enabled is True and row.is_required is False and row.is_source_owned is True
    assert row.sort_order == 3  # next after the existing rows
    assert row.tenant_id == company.tenant_id


def test_backfill_enables_on_the_vendor_api_source(db):
    """The vendor Debtor payload always carries ``DebtorType`` (Postman
    collection) - the default-mapping path is a known-good source."""
    company = _company(db, database="AED_DT_READ")
    _customer_config(db, company, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [True]


def test_backfill_enables_when_result_columns_carry_debtor_type(db):
    company = _company(db, database="AED_DT_SQL_OK")
    _customer_config(db, company, source_impl=SOURCE_IMPL_SQL_DB,
                     result_columns=["AccNo", "CompanyName", "DebtorType"])
    _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [True]


def test_backfill_seeds_disabled_with_a_warning_when_source_lacks_debtor_type(db, caplog):
    company = _company(db, database="AED_DT_SQL_NO")
    config = _customer_config(db, company, source_impl=SOURCE_IMPL_SQL_DB,
                              result_columns=["AccNo", "CompanyName"])
    config_id = config.id
    with caplog.at_level(logging.WARNING):
        _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [False]
    assert [r for r in caplog.records if config_id in r.getMessage()]


def test_backfill_disables_on_a_custom_http_path(db):
    company = _company(db, database="AED_DT_PATH")
    _customer_config(db, company, path="/somethingelse")
    _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [False]


def test_backfill_skips_a_task_with_no_mapping_rows(db):
    """A never-mapped task gets its WHOLE default/preset mapping (which
    already carries the row) from the seed gated on an EMPTY mapping - a
    lone backfilled row would block that seed forever."""
    company = _company(db, database="AED_DT_EMPTY")
    _customer_config(db, company, seed_rows=False)
    assert _backfill()(db, schema=None) == 0
    db.expire_all()
    assert db.query(AcFieldMapping).filter(AcFieldMapping.company_id == company.id).count() == 0


def test_update_tenant_still_seeds_the_full_default_on_an_unmapped_vendor_task(db):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, database="AED_DT_FULLSEED")
    _customer_config(db, company, source_impl=SOURCE_IMPL_AUTOCOUNT_READ, seed_rows=False)
    update_tenant(db, DEFAULT_TENANT_ID, "0.20.0")
    db.commit()
    db.expire_all()
    fields = {
        r.canonical_field for r in db.query(AcFieldMapping).filter(
            AcFieldMapping.company_id == company.id,
            AcFieldMapping.entity_type == ENTITY_CUSTOMER,
        )
    }
    assert {r.canonical_field for r in DEFAULT_CUSTOMER_MAPPING} <= fields
    assert len(_rows(db, company.id)) == 1


def test_backfill_leaves_an_existing_row_alone_in_any_state(db):
    company = _company(db, database="AED_DT_OWN")
    _customer_config(db, company, seed_rows=False)
    db.add(AcFieldMapping(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=ENTITY_CUSTOMER,
        scope=SCOPE_HEADER, source_path="Attention", canonical_field="market_segment_code",
        transform="string", is_enabled=False, is_required=False, sort_order=0,
    ))
    db.commit()
    existing_id = _rows(db, company.id)[0].id
    db.expire_all()

    assert _backfill()(db, schema=None) == 0
    db.expire_all()
    rows = _rows(db, company.id)
    assert [r.id for r in rows] == [existing_id]
    assert rows[0].source_path == "Attention" and rows[0].is_enabled is False


def test_backfill_is_idempotent(db):
    company = _company(db, database="AED_DT_TWICE")
    _customer_config(db, company)
    helper = _backfill()
    assert helper(db, schema=None) == 1
    assert helper(db, schema=None) == 0
    db.expire_all()
    assert len(_rows(db, company.id)) == 1


def test_backfill_touches_only_customer_tasks(db):
    company = _company(db, database="AED_DT_OTHER")
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id,
        entity_type="supplier", source_impl=SOURCE_IMPL_AUTOCOUNT_READ,
    )
    db.add(config)
    db.commit()
    assert _backfill()(db, schema=None) == 0
    assert db.query(AcFieldMapping).filter(
        AcFieldMapping.canonical_field == "market_segment_code"
    ).count() == 0


def test_backfill_skips_a_config_whose_company_belongs_to_another_tenant(db, caplog):
    leaking = _company(db, database="AED_DT_LEAK", tenant_id="tenant-leak-debtor-type")
    config = _customer_config(db, leaking, tenant_id=DEFAULT_TENANT_ID)
    config_id = config.id
    with caplog.at_level(logging.WARNING):
        _backfill()(db, schema=None)
    db.expire_all()
    assert db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == leaking.id,
        AcFieldMapping.canonical_field == "market_segment_code",
    ).count() == 0
    assert [r for r in caplog.records if config_id in r.getMessage()]


def test_backfill_is_a_no_op_on_a_schema_that_predates_its_tables():
    helper = _backfill()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE ac_entity_config (id TEXT PRIMARY KEY, tenant_id TEXT, "
            "company_id TEXT, entity_type TEXT)"
        )
        conn.exec_driver_sql("INSERT INTO ac_entity_config VALUES ('c', 't', 'c', 'customer')")
    with engine.begin() as conn:
        assert helper(conn, schema=None) == 0
    with sa.create_engine("sqlite://").begin() as conn:
        assert helper(conn, schema=None) == 0


def test_revision_0035_chains_onto_0034_and_calls_the_helper():
    candidates = sorted(VERSIONS_DIR.glob("0035_*.py"))
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    assert revision and len(revision.group(1)) <= 32
    spec = importlib.util.spec_from_file_location("_ac_rev_0035", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS_REVISION
    assert HELPER_NAME in text
    for other in VERSIONS_DIR.glob("*.py"):
        if other == path:
            continue
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', other.read_text(), re.M)
        assert not (down and down.group(1) == PREVIOUS_REVISION), other.name


def test_manifest_version_is_bumped_past_0_20_0():
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    assert tuple(int(p) for p in manifest["version"].split(".")) >= (0, 21, 0)


def test_user_agent_matches_the_manifest_version():
    from modules.autocount.http_source.client import USER_AGENT

    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    assert USER_AGENT.endswith("/" + manifest["version"])


def test_update_tenant_from_0_20_seeds_the_row(db):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, database="AED_DT_UPD")
    _customer_config(db, company)
    update_tenant(db, DEFAULT_TENANT_ID, "0.20.0")
    db.commit()
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [True]


def test_update_tenant_from_0_21_never_reseeds_a_row_an_operator_deleted(db):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, database="AED_DT_DEL")
    _customer_config(db, company)
    update_tenant(db, DEFAULT_TENANT_ID, "0.20.0")
    db.commit()
    rows = _rows(db, company.id)
    assert len(rows) == 1
    db.delete(rows[0])
    db.commit()

    update_tenant(db, DEFAULT_TENANT_ID, "0.21.0")
    db.commit()
    db.expire_all()
    assert _rows(db, company.id) == []


def test_scoped_backfill_touches_only_that_tenant(db):
    mine = _company(db, database="AED_DT_SCOPE_A")
    other = _company(db, database="AED_DT_SCOPE_B", tenant_id="tenant-debtor-type-b")
    _customer_config(db, mine)
    _customer_config(db, other)

    assert _backfill()(db, schema=None, tenant_id=DEFAULT_TENANT_ID) == 1
    db.expire_all()
    assert len(_rows(db, mine.id)) == 1
    assert _rows(db, other.id) == []
