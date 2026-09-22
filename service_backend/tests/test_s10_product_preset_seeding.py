"""Sprint-5/10 S1 - AC-10-04/74: a first clean save of a product HTTP task
seeds BOTH the mapping rows (now 9, not 8 - see the note below) AND
``source_config.lookups`` from ``PRODUCT_HTTP_PRESET``, through the
EXISTING seed-if-absent contract (``EtlService._update_http_task`` /
``seed_http_preset_mapping``) - never a second, parallel seeding path.

RED before the coder: today ``EtlService.update_task`` seeds only the
mapping rows (8 of them - see ``test_autocount_http_task_config.py::
test_first_clean_save_seeds_http_preset_product``) and never touches
``source_config['lookups']`` at all (``_validate_http_config``'s ``clean``
dict has no ``lookups`` key today), so the router/service round trip below
fails on a real, named mismatch.

Known side effect the coder must also make (flagged, not fixed here - this
file does not touch that test): the PRE-EXISTING
``test_autocount_http_task_config.py::
test_first_clean_save_seeds_http_preset_product`` asserts
``len(rows) == 8`` - once the shipped preset gains the ``BaseUOMPrice ->
list_price`` row (AC-10-04) that count becomes 9, and that assertion must be
bumped as part of implementing this slice.

Mirrors ``test_autocount_http_task_config.py``'s own
``_http_raw``/``_open_company``/``_transport`` helpers so the two files read
as one house style.
"""
from __future__ import annotations

from typing import Any, Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcFieldMapping, SOURCE_IMPL_AUTOCOUNT_HTTP
from modules.autocount.presets import PRODUCT_HTTP_PRESET
from modules.autocount.services.etl_service import EtlService


def _transport(rows, *, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=rows if status == 200 else None)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    db.expunge(conn)
    return conn


def _open_company(db):
    conn = _open_connection(db)
    company = EtlService(db).companies.create_from_open_connection(
        DEFAULT_TENANT_ID, conn, name="Mocha", ref_prefix="MOCHA",
        transport=_transport([{"Location": "A1"}]),
    )
    return company, conn


def _http_raw(**overrides: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": SOURCE_IMPL_AUTOCOUNT_HTTP,
        "connectionId": None,
        "path": "/itembypage",
        "keyFields": ["ItemCode"],
        "watermarkField": "LastModified",
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    raw.update(overrides)
    return raw


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_first_clean_save_seeds_eight_mapping_rows_for_product(db):
    company, conn = _open_company(db)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id)
    )
    rows = (
        db.query(AcFieldMapping)
        .filter(AcFieldMapping.company_id == company.id, AcFieldMapping.entity_type == ENTITY_PRODUCT)
        .all()
    )
    pairs = {(r.source_path, r.canonical_field) for r in rows}
    # sprint-5/12 (BL-SS-260, owner ruling 2026-09-22): 8, not 9 - the
    # `Discontinued -> is_discontinued` row is GONE. Sorento derives
    # "discontinued" from the `****` prefix of the description TEXT (plan 10
    # D22), the field is absent from `CanonicalProduct.SINK_FIELDS` and is
    # never sent, so seeding a row for it only produced one the save gate
    # refuses on a PUT and every ordinary Save swept away.
    assert len(rows) == 8, sorted(pairs)
    assert ("BaseUOMPrice", "list_price") in pairs
    assert ("Description", "description") in pairs
    assert ("Desc2", "description") not in pairs
    assert ("Discontinued", "is_discontinued") not in pairs


def test_first_clean_save_seeds_uom_code_row_disabled_despite_no_preview(db):
    """``available_columns`` is None on a genuinely first save (never
    previewed) - the OLD ``_seed_rows`` logic would enable every row in
    that case. The new preset-level ``enabled=False`` must still win."""
    company, conn = _open_company(db)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id)
    )
    row = (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.company_id == company.id,
            AcFieldMapping.entity_type == ENTITY_PRODUCT,
            AcFieldMapping.source_path == "BaseUOM",
            AcFieldMapping.canonical_field == "uom_code",
        )
        .one()
    )
    assert row.is_enabled is False


def test_first_clean_save_seeds_source_config_lookups_from_preset(db):
    company, conn = _open_company(db)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, _http_raw(connectionId=conn.id)
    )
    config = EtlService(db).configs.get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config is not None
    seeded_lookups = config.source_config.get("lookups") or []
    assert len(seeded_lookups) == 1, seeded_lookups
    assert seeded_lookups[0]["path"] == "/itemuombypage"
    assert seeded_lookups[0]["fields"] == [{"remote": "Price", "as": "BaseUOMPrice"}]
    assert list(seeded_lookups) == [dict(lookup) for lookup in PRODUCT_HTTP_PRESET.lookups]
