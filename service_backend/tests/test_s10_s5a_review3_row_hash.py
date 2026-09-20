"""Sprint-5/10 S5a review round 3 - BLOCKER B1: the compared-column /
row-hash schema for a combine-carrying task must be the COMBINE OUTPUT
schema (``groupBy + carry + measures[].alias``), never the PRE-combine raw
(+ lookup-alias) columns a task's ``result_columns``/``lookups`` name.

Reproduces the reviewer's own live proof: a task groups on ``g`` and sums
``v`` into the alias ``total``. With the bug, ``HttpApiSource.__init__``
derives ``self.compared_columns`` from ``effective_result_columns(self.
result_columns, self.lookups)`` - the PRE-combine raw column set - which a
combined row (``{"g": ..., "total": ...}``) never carries at all, so
``row_hash(row, compared)`` reads ``None`` for every compared column on
EVERY run and a genuine value change (``v`` 3 -> 99, ``total`` 8 -> 99)
never registers as ``updated``.

``combine_output_columns`` (``http_source/combine.py``) is the ONE shared
helper this file, ``HttpApiSource.__init__`` and
``EtlService._validate_http_config``/``preview_http`` all now derive that
schema from, so a save, a run and a preview can never disagree about it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_WAREHOUSE
from modules.autocount.http_source.combine import combine_output_columns
from modules.autocount.http_source.source import HttpApiSource
from modules.autocount.models import AcCompany, AcEntityConfig
from modules.autocount.services.company_service import CompanyService
from modules.autocount.services.etl_service import EtlService
from modules.autocount.sources import SourceContext, Watermark

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"

SIMPLE_COMBINE: Dict[str, Any] = {
    "computed": [],
    "require": [],
    "measure": "v",
    "groupBy": ["g"],
    "measures": [{"source": "v", "op": "sum", "alias": "total"}],
    "carry": [],
    "round": [],
    "drop": [],
}


# ── combine_output_columns, the bare helper ──────────────────────────────


def test_combine_output_columns_is_groupby_plus_carry_plus_measure_aliases():
    combine = {
        "groupBy": ["item_code", "location_code"],
        "carry": ["ItemDescription"],
        "measures": [
            {"source": "qty", "op": "sum", "alias": "qty"},
            {"source": "qty", "op": "count", "alias": "n"},
        ],
    }
    assert combine_output_columns(combine) == [
        "item_code", "location_code", "ItemDescription", "qty", "n",
    ]


def test_combine_output_columns_de_duplicates_preserving_first_occurrence():
    combine = {
        "groupBy": ["g"],
        "carry": ["g"],  # deliberately re-listed; must not appear twice
        "measures": [{"source": "v", "op": "sum", "alias": "g"}],  # collides too
    }
    assert combine_output_columns(combine) == ["g"]


def test_combine_output_columns_empty_for_no_combine_or_no_group_by():
    assert combine_output_columns(None) == []
    assert combine_output_columns({}) == []
    assert combine_output_columns({"groupBy": [], "measures": []}) == []


# ── the runtime fixture rig (mirrors test_s10_s5a_source_reduce_hook.py) ──


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Mocha REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _config(
    db, company, *, entity_type=ENTITY_PRODUCT, connection_id: str, path="/rows",
    key_fields=("g",), watermark_field: Optional[str] = None,
    result_columns: Optional[List[str]] = None, compared_fields: Optional[List[str]] = None,
    combine=None,
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl="autocount_http",
        result_columns=result_columns,
        source_config={
            "connectionId": connection_id,
            "path": path,
            "keyFields": list(key_fields),
            "watermarkField": watermark_field,
            "comparedFields": compared_fields or [],
            "distinctOf": None,
            "incrementalMinutes": 15,
            "reconcileMode": "dailyAt",
            "reconcileAt": "02:00",
            "lookups": [],
            "combine": combine,
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _ctx(db, company, config) -> SourceContext:
    return SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _envelope(rows: List[Dict[str, Any]], *, page: int = 1, total_pages: int = 1) -> Dict[str, Any]:
    return {
        "TotalCount": len(rows), "Page": page, "PageSize": 1000,
        "TotalPages": total_pages, "Data": rows,
    }


def _multi_handler(pages_by_path: Dict[str, List[Dict[str, Any]]]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = next(p for p in pages_by_path if request.url.path.endswith(p))
        pages = pages_by_path[path]
        page_num = int(request.url.params.get("page", "1"))
        if page_num - 1 < len(pages):
            body = pages[page_num - 1]
        else:
            last = pages[-1]
            body = {**last, "Page": page_num, "Data": []}
        return httpx.Response(200, json=body)

    return handler


@pytest.fixture
def rig(session_factory):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    yield db, company, conn
    db.close()


# ── B1 kill scenario: a previewed (STALE, pre-combine) result_columns must
# not blind the row hash to a real change in the combined output ──────────


def test_row_hash_detects_a_combine_output_change_when_result_columns_are_stale(rig):
    db, company, conn = rig
    config = _config(
        db, company, connection_id=conn.id, path="/rows",
        key_fields=("g",), combine=SIMPLE_COMBINE,
        # A PRIOR preview stamped the RAW pre-combine columns - exactly
        # what `HttpApiSource.__init__` reads as `self.result_columns`.
        # `comparedFields` is left at its default (empty) - the bug is
        # reachable through the DEFAULT path alone, no explicit pick
        # needed.
        result_columns=["g", "v"],
    )

    def _run(value: int):
        pages_by_path = {"/rows": [_envelope([{"g": "A", "v": value}])]}
        source = HttpApiSource(
            _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
            transport=_transport(_multi_handler(pages_by_path)),
        )
        return source.fetch_changes(Watermark())

    first = _run(3)
    assert first.added_count == 1, first
    assert first.updated_count == 0, first

    second = _run(99)
    assert second.added_count == 0, second
    assert second.updated_count == 1, (
        "the second run's combined row ('total' 8 -> 99) must register as "
        "an UPDATE - compared_columns must be derived from the COMBINE "
        "OUTPUT schema, not the stale pre-combine result_columns"
    )


def test_explicit_compared_field_naming_a_measure_alias_survives_the_save(rig):
    """B1 - an operator's own explicit ``comparedFields: ["total"]`` (a
    measure ALIAS, never a raw pre-combine column) must not be silently
    pruned to ``[]`` by `compared_columns_for`'s configured-intersect-
    available rule just because "total" is not a raw/lookup column."""
    db, company, conn = rig
    config = _config(
        db, company, connection_id=conn.id, path="/rows",
        key_fields=("g",), combine=SIMPLE_COMBINE,
        result_columns=["g", "v"], compared_fields=["total"],
    )
    pages_by_path = {"/rows": [_envelope([{"g": "A", "v": 3}])]}
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler(pages_by_path)),
    )
    assert source.compared_columns == ["total"], source.compared_columns


def test_two_different_entities_derive_the_same_compared_columns_for_the_same_combine(rig):
    """AC-10-80 - "a push task combines exactly as a pull task does": the
    compared-column set (and therefore the row hash) a combine-carrying
    task uses must not depend on which ENTITY it is configured for -
    `HttpApiSource` never reads `delivery_mode` at all. There is no
    pull-only entity fixture available at this point in the suite (the
    stock balance entity lands in S5b), so this pins the same point across
    TWO DIFFERENT push-capable entities (product, warehouse) instead: the
    B1 fix is entity-agnostic, and `delivery_mode` never even enters the
    derivation, so the conclusion carries over unchanged once a genuine
    pull-only entity exists."""
    db, company, conn = rig
    product_config = _config(
        db, company, entity_type=ENTITY_PRODUCT, connection_id=conn.id, path="/rows",
        key_fields=("g",), combine=SIMPLE_COMBINE, result_columns=["g", "v"],
    )
    warehouse_config = _config(
        db, company, entity_type=ENTITY_WAREHOUSE, connection_id=conn.id, path="/rows",
        key_fields=("g",), combine=SIMPLE_COMBINE, result_columns=["g", "v"],
    )
    product_source = HttpApiSource(
        _ctx(db, company, product_config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_multi_handler({"/rows": [_envelope([{"g": "A", "v": 1}])]})),
    )
    warehouse_source = HttpApiSource(
        _ctx(db, company, warehouse_config), entity_type=ENTITY_WAREHOUSE,
        transport=_transport(_multi_handler({"/rows": [_envelope([{"g": "A", "v": 1}])]})),
    )
    assert product_source.compared_columns == warehouse_source.compared_columns == ["total"]


# ── the SAVE path: EtlService._validate_http_config's own comparedFields
# default must also be combine-output-schema-derived, mirroring the runtime
# fix (B1's own "in BOTH ... places" instruction) ──────────────────────────


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company_for_service(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=DB_NAME,
        company_name="Mocha", name="Mocha", is_active=True, sorento_company_code="MOCHA",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _combine_raw(group_by=("Code",)) -> Dict[str, Any]:
    return {
        "computed": [], "require": [], "measure": group_by[0], "groupBy": list(group_by),
        "measures": [{"source": group_by[0], "op": "count", "alias": "n"}],
        "carry": [], "round": [], "drop": [],
    }


def _http_raw(**overrides: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": "autocount_http",
        "connectionId": None,
        "path": "/warehousebypage",
        "keyFields": [],
        "watermarkField": None,
        "comparedFields": ["n"],  # explicit measure alias, never a raw column
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
    }
    raw.update(overrides)
    return raw


def test_save_time_explicit_compared_field_naming_a_measure_alias_is_not_pruned(db):
    """review round 4 (BL-2) - the FIRST save of a never-previewed task is
    vacuous for this point: `existing_result_columns` is `None`, so
    `new_effective_columns` ends up falsy and `compared_columns_for`'s own
    `or configured_compared` escape hatch substitutes the configured list
    straight back - the assertion below would pass whether or not the B1
    fix is applied at all. A REALLY previewed task (`existing_result_columns`
    genuinely stamped) is what actually exercises the fix: with the OLD
    unconditional pre-combine `new_effective_columns`, "n" (a measure
    alias, never a raw/lookup column) would be pruned to `[]` by
    `compared_columns_for`'s configured-intersect-available rule."""
    conn = _open_connection(db)
    company = _company_for_service(db, conn.id)
    raw = _http_raw(connectionId=conn.id, combine=_combine_raw())
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw)

    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE)
    config.result_columns = ["Code", "Name"]
    db.commit()

    raw2 = _http_raw(connectionId=conn.id, combine=_combine_raw())
    view = EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_WAREHOUSE, raw2)
    assert view.source_config["comparedFields"] == ["n"], view.source_config
