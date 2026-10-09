"""Sprint-5/12 S2 - AC-12-03/04: PINS of already-true backend behaviour
(plan section 2.1 - "Group A" is a FRONTEND-only change; nothing server-side
needs to move for these two ids). The save gate already accepts a master
formula naming a previewed column or lookup alias
(`_replace_header_mapping`'s `known_vars = effective_result_columns(...) |
LINE_AGGREGATE_NAMES`), and `simulate_mapping` -> `MappingEngine.
project_document` -> `_header_facts` already evaluates a master formula
against `dict(raw)` verbatim (AC-10-73's own join formula already ships on
`PRODUCT_HTTP_PRESET`).

These tests are EXPECTED TO PASS TODAY, unchanged by this plan's S2 - they
exist so a future refactor of the save gate / `_header_facts` / the formula
engine cannot silently regress the exact promise the frontend's Group A
(AC-12-01/02/05) is built on. Reported honestly as GREEN-now in the S2
report, not claimed as new RED coverage.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig, SOURCE_IMPL_AUTOCOUNT_HTTP
from modules.autocount.presets import PRODUCT_HTTP_PRESET
from modules.autocount.services.company_service import CompanyService, MappingWriteRow

DESCRIPTION_FORMULA = (
    'trim(if(default(Desc2, "") != "", concat(Description, " ", Desc2), Description))'
)
LIST_PRICE_FORMULA = "if(number(value) <= 0, 0, number(value))"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str, *, database_name: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=database_name,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _product_config(db, company: AcCompany, connection_id: str) -> AcEntityConfig:
    """`result_columns` carries `Description`/`Desc2`; the `uom` lookup
    exposes `BaseUOMPrice` - byte-identical to `PRODUCT_HTTP_PRESET`'s own
    pre-filled lookup (AC-10-04), so `list_price`'s formula also validates."""
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP,
        source_config={
            "connectionId": connection_id, "path": "/itembypage", "keyFields": ["ItemCode"],
            "watermarkField": "LastModified", "comparedFields": [], "distinctOf": None,
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            "lookups": [dict(PRODUCT_HTTP_PRESET.lookups[0])],
        },
        result_columns=["ItemCode", "Description", "Desc2", "ItemGroup", "ItemBrand", "BaseUOM", "IsActive"],
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _row(source_path: str, sorento_field: str, *, transform: str = "string",
         formula: Optional[str] = None, is_enabled: bool = True) -> Dict[str, object]:
    return {
        "sourcePath": source_path, "transform": transform, "sorentoField": sorento_field,
        "formula": formula, "scope": "header", "isEnabled": is_enabled,
    }


def _accepted_preset_rows() -> List[Dict[str, object]]:
    """Every `PRODUCT_HTTP_PRESET` row that IS a Sorento-accepted target
    (`is_discontinued` is captured but not delivered - absent from
    `CanonicalProduct.SINK_FIELDS` - so it 422s the save gate and is
    excluded here, unrelated to what this file tests)."""
    return [
        _row(f.source_path, f.canonical_field, transform=f.transform, formula=f.formula, is_enabled=f.enabled)
        for f in PRODUCT_HTTP_PRESET.rows if f.canonical_field != "is_discontinued"
    ]


def _mapping_url(company_id: str, entity_type: str) -> str:
    return f"/autocount/companies/{company_id}/entities/{entity_type}/mapping"


def _simulate_url(company_id: str, entity_type: str) -> str:
    return f"/autocount/companies/{company_id}/entities/{entity_type}/mapping/simulate"


# ── AC-12-03: the save gate accepts a master formula naming a previewed ────
# ── column or a lookup alias (already true - pinned) ───────────────────────


def test_ac_12_03_put_accepts_a_master_formula_naming_previewed_columns_and_a_lookup_alias(client, db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-AC03-OK")
    _product_config(db, company, conn.id)

    headers = _auth(client)
    response = client.put(
        _mapping_url(company.id, ENTITY_PRODUCT),
        json={"rows": _accepted_preset_rows()},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    rows_by_field = {r["canonicalField"]: r for r in response.json()["rows"]}
    assert rows_by_field["description"]["formula"] == DESCRIPTION_FORMULA
    assert rows_by_field["list_price"]["formula"] == LIST_PRICE_FORMULA


def test_ac_12_03_put_422s_naming_the_row_and_the_unknown_column(client, db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-AC03-BAD")
    _product_config(db, company, conn.id)

    bad_rows = _accepted_preset_rows()
    for row in bad_rows:
        if row["sorentoField"] == "description":
            row["formula"] = (
                'trim(if(default(Desc3, "") != "", concat(Description, " ", Desc3), Description))'
            )

    headers = _auth(client)
    response = client.put(
        _mapping_url(company.id, ENTITY_PRODUCT), json={"rows": bad_rows}, headers=headers,
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "Desc3" in detail, detail
    assert "description" in detail, detail


# ── AC-12-04: simulate evaluates a master multi-column formula against ─────
# ── the raw row (RAW join - concat never trims inner whitespace) ───────────


def test_ac_12_04_simulate_service_returns_the_raw_desc2_join(db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-AC04-SVC")
    config = _product_config(db, company, conn.id)
    CompanyService(db).replace_mapping(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        [
            MappingWriteRow(
                r["sourcePath"], r["transform"], r["sorentoField"], formula=r["formula"], is_enabled=r["isEnabled"],
            )
            for r in _accepted_preset_rows()
        ],
    )
    del config

    service = CompanyService(db)

    def _description_value(record: Dict[str, object]) -> object:
        result = service.simulate_mapping(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, record)
        entry = next(f for f in result["headerFields"] if f["canonicalField"] == "description")
        return entry["value"]

    # Inner double space (Desc2's OWN leading/inner whitespace) is NEVER
    # collapsed - `concat` is a raw join, `trim` only strips the OUTER ends.
    assert _description_value({"Description": "ECO SERIES", "Desc2": "HIGH  LEVEL"}) == "ECO SERIES HIGH  LEVEL"
    # A blank (present, empty-string) Desc2 falls back to Description alone.
    # NOTE (scope boundary, not asserted here): a record where "Desc2" is
    # ABSENT ENTIRELY (never present, as opposed to present-and-blank) is a
    # DIFFERENT, pre-existing formula-engine edge case - `default(Desc2, "")`
    # against a facts dict with no "Desc2" key at all errors out today rather
    # than falling back, so `headerFields[description].value` comes back
    # `None`. That gap is unrelated to AC-12-04 (which only pins the "blank"
    # case, matching PRODUCT_HTTP_PRESET's own AC-10-73 formula against a
    # REAL `/itembypage` row, which always carries a `Desc2` key) and is
    # OUT OF SCOPE for this plan - flagged in the S2 report, not fixed here.
    assert _description_value({"Description": "ECO SERIES", "Desc2": ""}) == "ECO SERIES"


def test_ac_12_04_simulate_route_happy_path_returns_the_raw_desc2_join(client, db):
    conn = _connection(db)
    company = _company(db, conn.id, database_name="MOCHA-AC04-ROUTE")
    _product_config(db, company, conn.id)
    headers = _auth(client)
    put = client.put(
        _mapping_url(company.id, ENTITY_PRODUCT), json={"rows": _accepted_preset_rows()}, headers=headers,
    )
    assert put.status_code == 200, put.text

    response = client.post(
        _simulate_url(company.id, ENTITY_PRODUCT),
        json={"record": {"Description": "ECO SERIES", "Desc2": "HIGH  LEVEL"}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    entry = next(f for f in response.json()["headerFields"] if f["canonicalField"] == "description")
    assert entry["value"] == "ECO SERIES HIGH  LEVEL"
