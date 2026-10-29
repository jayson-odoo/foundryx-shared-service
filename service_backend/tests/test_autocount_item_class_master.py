"""Plan 37 (ITEM-CLASS-SS, pairs with sorento-crm #1988, contract 2.11) - the
`item_class` entity: AutoCount's `/ItemClass` list read from the open REST API
and pushed to the CRM's `item_classes` ingest door, wired like `brand`.

Wire facts pinned (#1988 plan section 1 + `app/schemas/canonical_masters.py`
`CanonicalItemClass`): code 1..50, name 1..150, description, is_active; the door
is `POST /api/v1/external/ingest/item_classes` (+ `/deletions`), advertised from
contract 2.11 with `item_classes` in `entities`. Name falls back to the code when
`Description` is blank, a blank `Desc2` is sent as `""` (it clears the CRM's
"Auto-created by product import" placeholder) and every listed class is sent
`is_active: true` (AutoCount has no flag).

Vendor fixtures (`fixtures/autocount_http/itemclass-db{1,2}.json`) are the crew's
recorded GET of 30 Oct (`crew/state/inbox/item-class-master/hapi-itemclass-shape.md`):
a plain array, no paging. No live hapi call is made anywhere in this file.

Every test imports its symbols INSIDE the body so each fails on its own missing
symbol, never at collection.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
from pydantic import ValidationError

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.models import (
    STAGED,
    STAGED_OP_DELETE,
    STAGED_PUSHED,
    SINK_IMPL_SORENTO,
    AcCompany,
    AcFieldMapping,
    AcStagedRecord,
)
from modules.autocount.sinks import SINK_LOGGING
from modules.autocount.sinks_sorento import ContractVersion, SorentoContractInfo, SorentoSink

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "autocount_http"
VENDOR_BASE_URL = "https://hapi.sorento.cc.cd/api/db1"
CRM_BASE_URL = "https://sorento.example.com"
ENTITY = "item_class"


def load_item_classes(book: str) -> List[Dict[str, Any]]:
    return json.loads((FIXTURES / f"itemclass-{book}.json").read_text(encoding="utf-8"))


# ── rigs ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _vendor_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db REST",
        config_json={"baseUrl": VENDOR_BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _sorento_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sorento", type="erp", name="Sorento",
        config_json={"baseUrl": CRM_BASE_URL},
        credentials_json=encrypt_secret({"apiKey": "k" * 12}), is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, vendor_conn: Connection, *, sorento_conn: Connection = None) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=vendor_conn.id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
        sink_impl=SINK_IMPL_SORENTO if sorento_conn else "logging",
        sink_connection_id=sorento_conn.id if sorento_conn else None,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _item_class_raw(connection_id: str) -> Dict[str, Any]:
    """The task body an operator saves after picking Item class in Add entity
    (the FE prefills exactly this from `HTTP_PRESETS.item_class`)."""
    return {
        "sourceImpl": "autocount_http", "connectionId": connection_id, "path": "/ItemClass",
        "keyFields": ["ItemClass"], "watermarkField": None, "comparedFields": [],
        "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
        "reconcileHours": None, "reconcileAt": "02:00",
    }


@pytest.fixture
def wired(db):
    """A db1 company delivering to a Sorento consumer + its saved, ACTIVE
    item_class task (only an active task auto-pushes)."""
    from modules.autocount.models import ETL_STATUS_ACTIVE
    from modules.autocount.repositories import EntityConfigRepository
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    sorento = _sorento_connection(db)
    company = _company(db, vendor, sorento_conn=sorento)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY, _item_class_raw(vendor.id))
    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY)
    config.etl_status = ETL_STATUS_ACTIVE
    db.commit()
    return db, company


def _contract(monkeypatch, version: str, entities: List[str]) -> None:
    info = SorentoContractInfo(version=ContractVersion.parse(version), entities=list(entities))
    monkeypatch.setattr(SorentoSink, "fetch_contract_detail", lambda self: info)


def _open_contract(monkeypatch) -> None:
    _contract(monkeypatch, "2.11", ["brands", "products", "item_classes"])


def _crm(calls: List[httpx.Request]):
    """A CRM stand-in: `created` per ingested record, `deactivated` per deletion
    (the CRM never hard-deletes a class, #1988 D5)."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content.decode("utf-8"))
        if request.url.path.endswith("/deletions"):
            refs = body.get("source_refs") or []
            return httpx.Response(200, json={
                "summary": {"total": len(refs), "deleted": 0, "deactivated": len(refs),
                            "not_found": 0, "failed": 0},
                "records": [{"source_ref": r, "outcome": "deactivated", "entity_id": "x"} for r in refs],
            })
        records = body.get("records") or []
        return httpx.Response(200, json={
            "dry_run": False, "summary": {"total": len(records), "created": len(records)},
            "records": [{"source_ref": r["source_ref"], "outcome": "created"} for r in records],
        })

    return handler


def _inject_sink_transport(monkeypatch, handler) -> None:
    import modules.autocount.services.company_service as company_module

    real = company_module.sorento_sink_from_connection

    def spy(config, credentials, *, entity_type, company_code=None, transport=None, **kw):
        return real(
            config, credentials, entity_type=entity_type, company_code=company_code,
            transport=httpx.MockTransport(handler), **kw,
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", spy)


def _vendor(rows: List[Dict[str, Any]], seen: List[httpx.Request]):
    """hapi `/ItemClass`: a plain JSON array, no paging envelope."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=rows)

    return handler


def _stub_vendor_client(monkeypatch, handler) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    stub = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub),
    )


def _run_sync(db, company) -> BackgroundJob:
    from app.jobs.service import JobService
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY, "mode": "manual"},
    )
    run_autocount_sync(db, job)
    db.refresh(job)
    return job


def _ingested_records(posts: List[httpx.Request]) -> List[Dict[str, Any]]:
    ingest = [p for p in posts if p.url.path == "/api/v1/external/ingest/item_classes"]
    records: List[Dict[str, Any]] = []
    for post in ingest:
        body = json.loads(post.content.decode("utf-8"))
        assert body["companyCode"] == "SRT"
        records.extend(body["records"])
    return sorted(records, key=lambda r: r["code"])


def _wire(record: Dict[str, Any]) -> Dict[str, Any]:
    return {k: record.get(k, "<absent>") for k in ("source_ref", "code", "name", "description", "is_active")}


def _staged(db, company, *, op: str = None) -> List[AcStagedRecord]:
    query = db.query(AcStagedRecord).filter(
        AcStagedRecord.company_id == company.id, AcStagedRecord.entity_type == ENTITY
    )
    if op is not None:
        query = query.filter(AcStagedRecord.op == op)
    return query.all()


# ── registration ─────────────────────────────────────────────────────────────


def test_entity_item_class_is_registered_where_brand_is():
    from modules.autocount.canonical.masters import ENTITY_ITEM_CLASS, MASTER_ENTITIES, NO_DELETION_ENTITY_TYPES
    from modules.autocount.mapping import ENTITY_PROFILES
    from modules.autocount.mapping_catalog import SORENTO_FIELDS
    from modules.autocount.services.company_service import HTTP_CAPABLE_ENTITY_TYPES, SEEDED_ENTITIES
    from modules.autocount.services.etl_service import ETL_ENTITY_TYPES, PULL_CAPABLE_ENTITY_TYPES
    from modules.autocount.services.sync_service import CANONICAL_MODELS
    from modules.autocount.canonical.masters import CanonicalItemClass

    assert ENTITY_ITEM_CLASS == ENTITY
    assert ENTITY in MASTER_ENTITIES and ENTITY in ETL_ENTITY_TYPES
    assert ENTITY in HTTP_CAPABLE_ENTITY_TYPES
    assert CANONICAL_MODELS[ENTITY] is CanonicalItemClass
    assert ENTITY_PROFILES[ENTITY].record_model is CanonicalItemClass
    assert ENTITY in SORENTO_FIELDS
    # Reaches a company only through Add entity (no seed), push only.
    assert ENTITY not in SEEDED_ENTITIES
    assert ENTITY not in PULL_CAPABLE_ENTITY_TYPES
    # A class gone from the list is a delete (the CRM deactivates it).
    assert ENTITY not in NO_DELETION_ENTITY_TYPES


def test_http_preset_path_keys_and_rows():
    from modules.autocount.presets import HTTP_ENTITY_TYPES, HTTP_PRESETS

    assert ENTITY in HTTP_ENTITY_TYPES
    preset = HTTP_PRESETS[ENTITY]
    assert preset.path == "/ItemClass"
    assert preset.key_fields == ("ItemClass",)
    assert preset.watermark_field is None  # no LastModified: a full list every run
    rows = {r.canonical_field: r for r in preset.rows}
    assert set(rows) == {"code", "name", "description", "is_active"}
    # The formula rows read the always-filled `ItemClass`: a formula row whose
    # own source is blank short-circuits to None (`mapping.py` `MappingRow.coerce`).
    assert rows["name"].source_path == "ItemClass" and rows["name"].formula
    assert rows["is_active"].source_path == "ItemClass" and rows["is_active"].formula == "true"
    # The ItemGroup shape for the description; a blank one is sent as "" by
    # the model (every transform reads blank as absent, `mapping.py` `t_string`).
    assert rows["description"].source_path == "Desc2" and rows["description"].formula is None
    assert rows["code"].required is True and rows["code"].formula is None
    assert all(r.enabled for r in preset.rows)


def test_a_blank_description_is_sent_as_an_empty_string_and_other_blanks_are_omitted():
    """AutoCount is master for the description (#1988 D3): "" clears the CRM's
    "Auto-created by product import" placeholder. Every other None stays
    omitted (absent = untouched, `CanonicalMaster.sink_payload`)."""
    from modules.autocount.canonical.masters import CanonicalItemClass

    payload = CanonicalItemClass(source_ref="R", code="DIY", name="DIY").sink_payload()
    assert payload["description"] == ""
    assert "is_active" not in payload and "source_doc_no" not in payload
    kept = CanonicalItemClass(source_ref="R", code="DIY", name="DIY", description="Lite").sink_payload()
    assert kept["description"] == "Lite"


def test_canonical_item_class_caps_match_the_crm_columns():
    from modules.autocount.canonical.masters import CanonicalItemClass

    CanonicalItemClass(source_ref="R", code="C" * 50, name="N" * 150)
    with pytest.raises(ValidationError):
        CanonicalItemClass(source_ref="R", code="C" * 51, name="N")
    with pytest.raises(ValidationError):
        CanonicalItemClass(source_ref="R", code="C", name="N" * 151)


def test_accepted_and_required_mapping_fields():
    from modules.autocount.mapping_catalog import accepted_field_names, required_field_names

    assert {"code", "name", "description", "is_active"} <= accepted_field_names(ENTITY)
    assert "code" in required_field_names(ENTITY)


def test_first_save_seeds_the_preset_rows_and_reset_returns_them(db):
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    company = _company(db, vendor)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY, _item_class_raw(vendor.id))

    def rows():
        return [
            (r.source_path, r.canonical_field, r.formula, r.is_required, r.is_enabled)
            for r in db.query(AcFieldMapping).filter(
                AcFieldMapping.company_id == company.id, AcFieldMapping.entity_type == ENTITY,
                AcFieldMapping.scope == "header",
            ).order_by(AcFieldMapping.sort_order).all()
        ]

    seeded = rows()
    assert {r[1] for r in seeded} == {"code", "name", "description", "is_active"}
    assert all(r[4] for r in seeded), "a first save seeds every row enabled"

    db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == company.id, AcFieldMapping.entity_type == ENTITY,
        AcFieldMapping.canonical_field == "name",
    ).update({"formula": None})
    db.commit()
    assert rows() != seeded
    CompanyService(db).reset_mapping_to_preset(DEFAULT_TENANT_ID, company.id, ENTITY, dry_run=False)
    assert rows() == seeded


# ── one run: read the list, map, push to /ingest/item_classes ────────────────


def test_a_run_reads_the_db1_list_and_pushes_every_class(wired, monkeypatch):
    db, company = wired
    seen: List[httpx.Request] = []
    _stub_vendor_client(monkeypatch, _vendor(load_item_classes("db1"), seen))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    job = _run_sync(db, company)

    assert seen and seen[0].url.path == "/api/db1/ItemClass"
    assert [_wire(r) for r in _ingested_records(posts)] == [
        {"source_ref": "AED_SORENTO:DIY", "code": "DIY", "name": "SORENTO LITE - DIY",
         "description": "", "is_active": True},
        {"source_ref": "AED_SORENTO:SERENE", "code": "SERENE", "name": "SORENTO SERENE SERIES",
         "description": "", "is_active": True},
    ]
    assert job.result_json.get("pushed") == 2, job.result_json
    assert {r.status for r in _staged(db, company)} == {STAGED_PUSHED}


def test_the_db2_list_pushes_its_single_class(wired, monkeypatch):
    db, company = wired
    _stub_vendor_client(monkeypatch, _vendor(load_item_classes("db2"), []))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    _run_sync(db, company)

    assert [r["code"] for r in _ingested_records(posts)] == ["DIY"]


def test_a_blank_description_falls_back_to_the_code_and_desc2_is_trimmed(wired, monkeypatch):
    db, company = wired
    rows = [
        {"ItemClass": "BARE", "Description": "", "Desc2": "", "ShortCode": ""},
        {"ItemClass": "SPACED", "Description": "   ", "Desc2": " Second line ", "ShortCode": ""},
        # hapi always sends all four keys; a row without `Desc2` still sends "".
        {"ItemClass": "NODESC2", "Description": "No second line", "ShortCode": ""},
    ]
    _stub_vendor_client(monkeypatch, _vendor(rows, []))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    _run_sync(db, company)

    by_code = {r["code"]: _wire(r) for r in _ingested_records(posts)}
    assert by_code["BARE"]["name"] == "BARE" and by_code["BARE"]["description"] == ""
    assert by_code["SPACED"]["name"] == "SPACED"
    assert by_code["SPACED"]["description"] == "Second line"
    assert by_code["NODESC2"]["name"] == "No second line" and by_code["NODESC2"]["description"] == ""
    assert {r["is_active"] for r in by_code.values()} == {True}


def test_a_code_over_50_chars_fails_that_class_only(wired, monkeypatch):
    db, company = wired
    rows = load_item_classes("db1") + [
        {"ItemClass": "X" * 51, "Description": "Too long", "Desc2": "", "ShortCode": ""}
    ]
    _stub_vendor_client(monkeypatch, _vendor(rows, []))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    _run_sync(db, company)

    assert [r["code"] for r in _ingested_records(posts)] == ["DIY", "SERENE"]


# ── a class gone from the list -> /ingest/item_classes/deletions ─────────────


def test_a_class_gone_from_the_list_is_sent_to_the_deletions_door(wired, monkeypatch):
    from modules.autocount.repositories import RowHashRepository

    db, company = wired
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY,
        {ref: "a" * 64 for ref in ("AED_SORENTO:DIY", "AED_SORENTO:SERENE", "AED_SORENTO:RETIRED")},
        seen_at=None,
    )
    db.commit()
    _stub_vendor_client(monkeypatch, _vendor(load_item_classes("db1"), []))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    _run_sync(db, company)

    assert [r.source_ref for r in _staged(db, company, op=STAGED_OP_DELETE)] == ["AED_SORENTO:RETIRED"]
    deletions = [p for p in posts if p.url.path == "/api/v1/external/ingest/item_classes/deletions"]
    assert len(deletions) == 1, [p.url.path for p in posts]
    assert json.loads(deletions[0].content.decode("utf-8"))["source_refs"] == ["AED_SORENTO:RETIRED"]


# ── contract 2.11 gate ───────────────────────────────────────────────────────


def test_entity_path_and_gate_table_rows():
    from modules.autocount.sinks_sorento import (
        CONTRACT_GATED_ENTITIES,
        PUSH_REFUSES_LOGGING_FALLBACK,
        _ENTITY_PATH,
    )

    assert _ENTITY_PATH[ENTITY] == "item_classes"
    version, name = CONTRACT_GATED_ENTITIES[ENTITY]
    assert (version.major, version.minor, name) == (2, 11, "item_classes")
    assert ENTITY in PUSH_REFUSES_LOGGING_FALLBACK


@pytest.mark.parametrize("version,entities,expected", [
    ("2.10", ["brands", "item_classes"], False),
    ("2.9", ["item_classes"], False),  # a float compare would call 2.9 > 2.11
    ("2.11", ["brands", "products"], False),  # version alone is not enough
    ("2.11", ["item_classes"], True),
    ("2.12", ["item_classes"], True),
    ("3", ["item_classes"], True),
])
def test_supports_item_class_needs_2_11_and_the_advertised_door(version, entities, expected):
    from modules.autocount.sinks_sorento import sorento_supports_entity

    assert sorento_supports_entity(
        ENTITY, contract_version=ContractVersion.parse(version), contract_entities=entities
    ) is expected


def test_a_shut_gate_refuses_the_push_and_keeps_every_class_staged(wired, monkeypatch):
    """A 2.10 CRM: the logging fallback would mark the full list PUSHED and
    changed-only staging would never offer it again after the CRM upgrades."""
    db, company = wired
    _stub_vendor_client(monkeypatch, _vendor(load_item_classes("db1"), []))
    _contract(monkeypatch, "2.10", ["brands", "products", "ar_outstanding"])
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    _run_sync(db, company)

    assert not [p for p in posts if "item_classes" in p.url.path]
    staged = _staged(db, company)
    assert len(staged) == 2 and {r.status for r in staged} == {STAGED}


def test_classes_held_back_on_2_10_are_pushed_once_the_crm_reaches_2_11(wired, monkeypatch):
    """The point of refusing the logging fallback: nothing is lost while the
    CRM is behind; the next run after the upgrade delivers the full list."""
    db, company = wired
    _stub_vendor_client(monkeypatch, _vendor(load_item_classes("db1"), []))
    _contract(monkeypatch, "2.10", ["brands", "products", "item_classes"])
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))
    _run_sync(db, company)
    assert not _ingested_records(posts)

    _open_contract(monkeypatch)
    # Each run closes its vendor client; the next run gets a fresh stub.
    _stub_vendor_client(monkeypatch, _vendor(load_item_classes("db1"), []))
    _run_sync(db, company)

    assert [r["code"] for r in _ingested_records(posts)] == ["DIY", "SERENE"]
    assert {r.status for r in _staged(db, company)} == {STAGED_PUSHED}


def test_sink_for_company_opens_on_2_11_and_not_on_2_10(db, monkeypatch):
    from modules.autocount.services.company_service import CompanyService

    company = _company(db, _vendor_connection(db), sorento_conn=_sorento_connection(db))
    _open_contract(monkeypatch)
    assert isinstance(CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY), SorentoSink)
    _contract(monkeypatch, "2.10", ["item_classes"])
    assert CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY).name == SINK_LOGGING


def test_task_view_contract_gate_names_the_consumer_version(db, monkeypatch):
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.services.etl_service import EtlService

    company = _company(db, _vendor_connection(db), sorento_conn=_sorento_connection(db))
    required = CompanyService._CONTRACT_GATE_REQUIRED_VERSIONS[ENTITY]
    assert (required.major, required.minor) == (2, 11)

    _contract(monkeypatch, "2.10", ["brands"])
    gate = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY).contract_gate
    assert gate is not None and gate["entity"] == ENTITY
    assert gate["version"] == ContractVersion(2, 10) and gate["requiredVersion"] == ContractVersion(2, 11)

    _open_contract(monkeypatch)
    assert EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY).contract_gate is None


def test_supported_entities_label_never_claims_the_gated_item_class():
    from modules.autocount.sinks_sorento import sorento_supported_entities_label

    assert "item class" not in sorento_supported_entities_label()


# ── order: item classes before brands and products ───────────────────────────


def test_the_sweep_enqueues_item_classes_before_brands_and_products():
    from modules.autocount.scheduler import sweep_order_key

    due = ["product", "brand", "customer", ENTITY, "credit_note"]
    ordered = sorted(due, key=sweep_order_key)
    assert ordered[0] == ENTITY
    assert ordered.index("brand") < ordered.index("credit_note")
    # Every other entity keeps its relative order (a stable sort).
    assert [e for e in ordered if e not in (ENTITY, "credit_note")] == ["product", "brand", "customer"]
