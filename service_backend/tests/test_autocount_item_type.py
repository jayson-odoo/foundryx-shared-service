"""AutoCount ``ItemType`` on the product feed (lane ITEM-TYPE-SS, partner of
sorento #1450).

RED before the implementation. Same shape as ``brand_code``: the open REST
API's ``/itembypage`` row already carries ``ItemType`` (``MISC``,
``PROJECT``, ``WASTE``, ``KITCHEN SINK``, ``OMEX`` - see the live-replay
evidence and ``fixtures/autocount_http/item_page.json``) and the ESB dropped
it (BL-SS-201). It now travels as ``item_type_code`` on the product row -
on the push payload AND the pull-gateway snapshot rows, which are both
``CanonicalProduct.sink_payload()``.

Wire contract (what the CRM builds against):
* key ``item_type_code``, a string, trimmed, no length cap here (same as
  ``brand_code``);
* OMITTED (never ``null``) when AutoCount's ``ItemType`` is blank/absent -
  the master ``sink_payload`` rule.

Existing tenants: every existing ``product`` task gets an
``ItemType -> item_type_code`` row via ``backfill_product_item_type``
(module Alembic 0027 + ``update_tenant`` from < 0.14.0).
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
from modules.autocount.canonical.masters import ENTITY_PRODUCT, CanonicalProduct
from modules.autocount.mapping import SCOPE_HEADER, MappingEngine, MappingRow, flat_profile
from modules.autocount.mapping_catalog import accepted_field_names
from modules.autocount.models import (
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.presets import PRODUCT_HTTP_PRESET

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"
FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "autocount_http" / "item_page.json"

HELPER_NAME = "backfill_product_item_type"
PREVIOUS_REVISION = "0026_autocount_doc_feed_schedule"


def _backfill():
    from modules.autocount import backfill

    helper = getattr(backfill, HELPER_NAME, None)
    if helper is None:
        pytest.fail(f"modules.autocount.backfill has no `{HELPER_NAME}` helper yet")
    return helper


# ═════════════════════════ Group A - canonical, preset, wire ════════════════


def test_canonical_product_sends_item_type_code_right_after_brand_code():
    fields = CanonicalProduct.SINK_FIELDS
    assert "item_type_code" in fields
    assert fields.index("item_type_code") == fields.index("brand_code") + 1


def test_sink_payload_carries_item_type_code():
    product = CanonicalProduct(source_ref="1861", code="1861", brand_code="SRT-KS",
                               item_type_code="KITCHEN SINK")
    payload = product.sink_payload()
    assert payload["item_type_code"] == "KITCHEN SINK"
    assert payload["brand_code"] == "SRT-KS"


def test_sink_payload_omits_item_type_code_when_none():
    payload = CanonicalProduct(source_ref="X", code="X").sink_payload()
    assert "item_type_code" not in payload


def test_mapping_catalog_accepts_item_type_code_for_product():
    assert "item_type_code" in accepted_field_names(ENTITY_PRODUCT)


def test_product_preset_maps_item_type_enabled_right_after_item_brand():
    pairs = [(f.source_path, f.canonical_field) for f in PRODUCT_HTTP_PRESET.rows]
    assert ("ItemType", "item_type_code") in pairs
    assert pairs.index(("ItemType", "item_type_code")) == pairs.index(("ItemBrand", "brand_code")) + 1
    row = PRODUCT_HTTP_PRESET.rows[pairs.index(("ItemType", "item_type_code"))]
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
        for f in PRODUCT_HTTP_PRESET.rows
    ]
    return MappingEngine(
        rows, entity_type=ENTITY_PRODUCT,
        profile=flat_profile(ENTITY_PRODUCT, list(PRODUCT_HTTP_PRESET.key_fields)),
        database_name="AED_SORENTO",
    )


def _raw(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "ItemCode": "1861", "Description": "SINK", "Desc2": "", "ItemGroup": "SRT-KS",
        "ItemType": "KITCHEN SINK", "ItemBrand": "SRT-KS", "BaseUOM": "UNIT",
        "IsActive": "T", "Discontinued": "F", "BaseUOMPrice": 10.0,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "item_type, expected",
    [("MISC", "MISC"), ("PROJECT", "PROJECT"), ("WASTE", "WASTE"),
     ("KITCHEN SINK", "KITCHEN SINK"), ("OMEX", "OMEX"), ("  OMEX ", "OMEX")],
)
def test_preset_maps_owner_sample_item_types_onto_the_wire(item_type, expected):
    mapped = _engine().map_document(_raw(ItemType=item_type))
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.sink_payload()["item_type_code"] == expected


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_item_type_is_omitted_never_null(blank):
    mapped = _engine().map_document(_raw(ItemType=blank))
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert "item_type_code" not in mapped.record.sink_payload()


def test_absent_item_type_column_is_omitted():
    raw = _raw()
    raw.pop("ItemType")
    mapped = _engine().map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert "item_type_code" not in mapped.record.sink_payload()


def test_fixture_item_row_delivers_item_type_next_to_brand():
    """The real recorded ``/itembypage`` row: ItemGroup MISC, ItemType MISC,
    ItemBrand OTHERS (the owner's ``**NEW`` example)."""
    row = json.loads(FIXTURE.read_text())["Data"][0]
    payload = _engine().map_document(dict(row)).record.sink_payload()
    assert payload["item_type_code"] == "MISC"
    assert payload["brand_code"] == "OTHERS"
    assert payload["category_code"] == "MISC"


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


def _product_config(db, company: AcCompany, *, source_impl: str = SOURCE_IMPL_AUTOCOUNT_HTTP,
                    path: str = "/itembypage", result_columns=None,
                    tenant_id: str = None) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=tenant_id or company.tenant_id, company_id=company.id,
        entity_type=ENTITY_PRODUCT, source_impl=source_impl,
    )
    if source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP:
        config.source_config = {"connectionId": "conn-x", "path": path, "keyFields": ["ItemCode"]}
    else:
        config.source_config = {"connectionId": "conn-x", "query": "SELECT 1", "keyColumns": ["ItemCode"]}
    config.result_columns = list(result_columns or [])
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _seed_existing_rows(db, company: AcCompany) -> None:
    for order, (src, dst) in enumerate(
        (("ItemCode", "code"), ("ItemGroup", "category_code"), ("ItemBrand", "brand_code"))
    ):
        db.add(AcFieldMapping(
            tenant_id=company.tenant_id, company_id=company.id, entity_type=ENTITY_PRODUCT,
            scope=SCOPE_HEADER, source_path=src, canonical_field=dst,
            transform="string", is_enabled=True, is_required=(dst == "code"), sort_order=order,
        ))
    db.commit()


def _rows(db, company_id: str, field: str = "item_type_code"):
    return [
        r for r in (
            db.query(AcFieldMapping)
            .filter(
                AcFieldMapping.company_id == company_id,
                AcFieldMapping.entity_type == ENTITY_PRODUCT,
                AcFieldMapping.scope == SCOPE_HEADER,
            )
            .order_by(AcFieldMapping.sort_order)
            .all()
        )
        if r.canonical_field == field
    ]


def test_backfill_seeds_an_enabled_row_on_an_http_item_task(db):
    company = _company(db, database="AED_IT_HTTP")
    _product_config(db, company)
    _seed_existing_rows(db, company)
    db.expire_all()

    assert _backfill()(db, schema=None) == 1
    db.expire_all()

    rows = _rows(db, company.id)
    assert len(rows) == 1
    row = rows[0]
    assert (row.source_path, row.transform, row.formula) == ("ItemType", "string", None)
    assert row.is_enabled is True and row.is_required is False and row.is_source_owned is True
    assert row.sort_order == 3  # next after the existing rows
    assert row.tenant_id == company.tenant_id


def test_backfill_enables_when_result_columns_carry_item_type(db):
    company = _company(db, database="AED_IT_SQL_OK")
    _product_config(db, company, source_impl=SOURCE_IMPL_SQL_DB,
                    result_columns=["ItemCode", "ItemBrand", "ItemType"])
    _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [True]


def test_backfill_seeds_disabled_with_a_warning_when_source_lacks_item_type(db, caplog):
    company = _company(db, database="AED_IT_SQL_NO")
    config = _product_config(db, company, source_impl=SOURCE_IMPL_SQL_DB,
                             result_columns=["ItemCode", "ItemBrand"])
    config_id = config.id
    with caplog.at_level(logging.WARNING):
        _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [False]
    assert [r for r in caplog.records if config_id in r.getMessage()]


def test_backfill_disables_on_a_custom_http_path(db):
    company = _company(db, database="AED_IT_PATH")
    _product_config(db, company, path="/somethingelse")
    _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [False]


def test_backfill_leaves_an_existing_row_alone_in_any_state(db):
    company = _company(db, database="AED_IT_OWN")
    _product_config(db, company)
    db.add(AcFieldMapping(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=ENTITY_PRODUCT,
        scope=SCOPE_HEADER, source_path="ItemClass", canonical_field="item_type_code",
        transform="string", is_enabled=False, is_required=False, sort_order=0,
    ))
    db.commit()
    existing_id = _rows(db, company.id)[0].id
    db.expire_all()

    assert _backfill()(db, schema=None) == 0
    db.expire_all()
    rows = _rows(db, company.id)
    assert [r.id for r in rows] == [existing_id]
    assert rows[0].source_path == "ItemClass" and rows[0].is_enabled is False


def test_backfill_is_idempotent(db):
    company = _company(db, database="AED_IT_TWICE")
    _product_config(db, company)
    helper = _backfill()
    assert helper(db, schema=None) == 1
    assert helper(db, schema=None) == 0
    db.expire_all()
    assert len(_rows(db, company.id)) == 1


def test_backfill_touches_only_product_tasks(db):
    company = _company(db, database="AED_IT_OTHER")
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id,
        entity_type="brand", source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP,
    )
    config.source_config = {"connectionId": "conn-x", "path": "/ItemBrand"}
    db.add(config)
    db.commit()
    assert _backfill()(db, schema=None) == 0
    assert db.query(AcFieldMapping).filter(
        AcFieldMapping.canonical_field == "item_type_code"
    ).count() == 0


def test_backfill_skips_a_config_whose_company_belongs_to_another_tenant(db, caplog):
    leaking = _company(db, database="AED_IT_LEAK", tenant_id="tenant-leak-item-type")
    config = _product_config(db, leaking, tenant_id=DEFAULT_TENANT_ID)
    config_id = config.id
    with caplog.at_level(logging.WARNING):
        _backfill()(db, schema=None)
    db.expire_all()
    assert db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == leaking.id,
        AcFieldMapping.canonical_field == "item_type_code",
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
        conn.exec_driver_sql("INSERT INTO ac_entity_config VALUES ('c', 't', 'c', 'product')")
    with engine.begin() as conn:
        assert helper(conn, schema=None) == 0
    with sa.create_engine("sqlite://").begin() as conn:
        assert helper(conn, schema=None) == 0


def test_revision_0027_chains_onto_0026_and_calls_the_helper():
    candidates = sorted(VERSIONS_DIR.glob("0027_*.py"))
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    assert revision and len(revision.group(1)) <= 32
    spec = importlib.util.spec_from_file_location("_ac_rev_0027", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS_REVISION
    assert HELPER_NAME in text
    for other in VERSIONS_DIR.glob("*.py"):
        if other == path:
            continue
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', other.read_text(), re.M)
        assert not (down and down.group(1) == PREVIOUS_REVISION), other.name


def test_manifest_version_is_bumped_past_0_13_0():
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    assert tuple(int(p) for p in manifest["version"].split(".")) >= (0, 14, 0)


def test_update_tenant_from_0_13_seeds_the_row(db):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, database="AED_IT_UPD")
    _product_config(db, company)
    update_tenant(db, DEFAULT_TENANT_ID, "0.13.0")
    db.commit()
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [True]


def test_update_tenant_from_0_14_never_reseeds_a_row_an_operator_deleted(db):
    """No query text marks a product HTTP task as "already migrated", so the
    gate is the version: past 0.14.0 the backfill never runs again and an
    operator's deliberate delete sticks."""
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, database="AED_IT_DEL")
    _product_config(db, company)
    update_tenant(db, DEFAULT_TENANT_ID, "0.13.0")
    db.commit()
    rows = _rows(db, company.id)
    assert len(rows) == 1
    db.delete(rows[0])
    db.commit()

    update_tenant(db, DEFAULT_TENANT_ID, "0.14.0")
    db.commit()
    db.expire_all()
    assert _rows(db, company.id) == []
