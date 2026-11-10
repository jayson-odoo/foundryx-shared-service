"""Plan 60 (SS-PAYMENT-TERMS, pairs with sorento-crm #2305, contract 2.14) - the
`payment_term` entity: AutoCount's Terms master read from the open REST API
(`/terms`) and pushed to the CRM's `payment_terms` ingest door, wired like
`item_class` (plan 37).

Wire facts pinned (#2305 crew-note, contract 2.14 as revised): `code` 1..100
(required, case kept), `rule` <= 200 (optional, `""` clears), `is_active`;
`description` / `term_days` are gone from the contract;
the door is `POST /api/v1/external/ingest/payment_terms` (+ `/deletions`, which
only ever DEACTIVATES), advertised from contract 2.14 with `payment_terms` in
`entities`.

Vendor fixtures (`fixtures/autocount_http/terms-db{1,2}.json`) are the crew's
recorded hapi GET of 10 Nov (17 + 21 rows): each row is `{DisplayTerm, Terms}`
only. `DisplayTerm` (the printed label, the key) is the CRM `code`; `Terms`
(AutoCount's calculation rule) is the CRM `rule`, a blank one sent as `""`.
Every listed term is `is_active: true`. No live AutoCount call is made anywhere in this file, and the
source performs GETs only (never a write to AutoCount).

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
VENDOR_BASE_URL = "https://autocount-wrapper.example.com/api/db1"
CRM_BASE_URL = "https://sorento.example.com"
ENTITY = "payment_term"
INGEST_PATH = "/api/v1/external/ingest/payment_terms"


def load_terms(book: str) -> List[Dict[str, Any]]:
    return json.loads((FIXTURES / f"terms-{book}.json").read_text(encoding="utf-8"))


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


def _terms_raw(connection_id: str) -> Dict[str, Any]:
    """The task body an operator saves after picking Payment term in Add entity
    (the FE prefills exactly this from `HTTP_PRESETS.payment_term`)."""
    return {
        "sourceImpl": "autocount_http", "connectionId": connection_id, "path": "/terms",
        "keyFields": ["DisplayTerm"], "watermarkField": None, "comparedFields": [],
        "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
        "reconcileHours": None, "reconcileAt": "02:00",
    }


@pytest.fixture
def wired(db):
    """A db1 company delivering to a Sorento consumer + its saved, ACTIVE
    payment_term task (only an active task auto-pushes)."""
    from modules.autocount.models import ETL_STATUS_ACTIVE
    from modules.autocount.repositories import EntityConfigRepository
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    sorento = _sorento_connection(db)
    company = _company(db, vendor, sorento_conn=sorento)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY, _terms_raw(vendor.id))
    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY)
    config.etl_status = ETL_STATUS_ACTIVE
    db.commit()
    return db, company


def _contract(monkeypatch, version: str, entities: List[str]) -> None:
    info = SorentoContractInfo(version=ContractVersion.parse(version), entities=list(entities))
    monkeypatch.setattr(SorentoSink, "fetch_contract_detail", lambda self: info)


def _open_contract(monkeypatch) -> None:
    _contract(monkeypatch, "2.14", ["customers", "item_classes", "payment_terms"])


def _crm(calls: List[httpx.Request]):
    """A CRM stand-in: `created` per ingested record, `deactivated` per deletion
    (the CRM only ever deactivates a term, #2305)."""

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
    """hapi `/terms`: a plain JSON array, no paging envelope."""

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
    ingest = [p for p in posts if p.url.path == "/api/v1/external/ingest/payment_terms"]
    records: List[Dict[str, Any]] = []
    for post in ingest:
        body = json.loads(post.content.decode("utf-8"))
        assert body["companyCode"] == "SRT"
        records.extend(body["records"])
    return sorted(records, key=lambda r: r["code"])


def _staged(db, company, *, op: str = None) -> List[AcStagedRecord]:
    query = db.query(AcStagedRecord).filter(
        AcStagedRecord.company_id == company.id, AcStagedRecord.entity_type == ENTITY
    )
    if op is not None:
        query = query.filter(AcStagedRecord.op == op)
    return query.all()


# ── registration ─────────────────────────────────────────────────────────────


def test_entity_payment_term_is_registered_where_item_class_is():
    from modules.autocount.canonical.masters import (
        ENTITY_PAYMENT_TERM,
        MASTER_ENTITIES,
        NO_DELETION_ENTITY_TYPES,
        CanonicalPaymentTerm,
    )
    from modules.autocount.mapping import ENTITY_PROFILES
    from modules.autocount.mapping_catalog import SORENTO_FIELDS
    from modules.autocount.services.company_service import HTTP_CAPABLE_ENTITY_TYPES, SEEDED_ENTITIES
    from modules.autocount.services.etl_service import ETL_ENTITY_TYPES, PULL_CAPABLE_ENTITY_TYPES
    from modules.autocount.services.sync_service import CANONICAL_MODELS

    assert ENTITY_PAYMENT_TERM == ENTITY
    assert ENTITY in MASTER_ENTITIES and ENTITY in ETL_ENTITY_TYPES
    assert ENTITY in HTTP_CAPABLE_ENTITY_TYPES
    assert CANONICAL_MODELS[ENTITY] is CanonicalPaymentTerm
    assert ENTITY_PROFILES[ENTITY].record_model is CanonicalPaymentTerm
    assert ENTITY in SORENTO_FIELDS
    assert ENTITY not in SEEDED_ENTITIES
    assert ENTITY not in PULL_CAPABLE_ENTITY_TYPES
    # A term gone from the list is a delete (the CRM deactivates it).
    assert ENTITY not in NO_DELETION_ENTITY_TYPES


def test_http_preset_path_keys_and_rows():
    from modules.autocount.presets import HTTP_ENTITY_TYPES, HTTP_PRESETS

    assert ENTITY in HTTP_ENTITY_TYPES
    preset = HTTP_PRESETS[ENTITY]
    assert preset.path == "/terms"
    assert preset.key_fields == ("DisplayTerm",)
    assert preset.watermark_field is None  # a full list every run
    rows = {r.canonical_field: r for r in preset.rows}
    assert set(rows) == {"code", "rule", "is_active"}
    assert rows["code"].source_path == "DisplayTerm" and rows["code"].required is True
    assert rows["rule"].source_path == "Terms" and rows["rule"].formula is None
    assert rows["rule"].required is False
    # A listed term is active; the formula reads the always-filled key column.
    assert rows["is_active"].source_path == "DisplayTerm" and rows["is_active"].formula == "true"
    assert all(r.enabled for r in preset.rows)


def test_sink_payload_keys_are_exactly_the_contract():
    from modules.autocount.canonical.masters import CanonicalPaymentTerm

    payload = CanonicalPaymentTerm(
        source_ref="DB:C.O.D.", code="C.O.D.", rule="Net 0th Next 1 Month",
        is_active=True, extras={"x": 1},
    ).sink_payload()
    assert payload == {
        "source_ref": "DB:C.O.D.", "code": "C.O.D.", "rule": "Net 0th Next 1 Month", "is_active": True,
    }


def test_a_blank_rule_is_sent_as_an_empty_string_to_clear_it():
    """AutoCount is master for the rule; `""` is the CRM's explicit clear."""
    from modules.autocount.canonical.masters import CanonicalPaymentTerm

    payload = CanonicalPaymentTerm(source_ref="R", code="C.O.D.", is_active=True).sink_payload()
    assert payload == {"source_ref": "R", "code": "C.O.D.", "rule": "", "is_active": True}


def test_the_removed_contract_fields_are_not_on_the_model():
    from modules.autocount.canonical.masters import CanonicalPaymentTerm

    assert "description" not in CanonicalPaymentTerm.model_fields
    assert "term_days" not in CanonicalPaymentTerm.model_fields
    assert set(CanonicalPaymentTerm.SINK_FIELDS) == {"source_ref", "code", "rule", "is_active"}


def test_canonical_caps_match_the_crm_columns():
    from modules.autocount.canonical.masters import CanonicalPaymentTerm

    CanonicalPaymentTerm(source_ref="R", code="C" * 100, rule="R" * 200)
    for bad in ({"code": "C" * 101}, {"code": "C", "rule": "R" * 201}):
        with pytest.raises(ValidationError):
            CanonicalPaymentTerm(source_ref="R", **bad)


def test_accepted_and_required_mapping_fields():
    from modules.autocount.mapping_catalog import accepted_field_names, required_field_names

    assert accepted_field_names(ENTITY) >= {"code", "rule", "is_active"}
    assert not ({"description", "term_days"} & set(accepted_field_names(ENTITY)))
    assert "code" in required_field_names(ENTITY)


def test_first_save_seeds_the_preset_rows(db):
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    company = _company(db, vendor)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY, _terms_raw(vendor.id))
    rows = db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == company.id, AcFieldMapping.entity_type == ENTITY,
        AcFieldMapping.scope == "header",
    ).all()
    assert {r.canonical_field for r in rows} == {"code", "rule", "is_active"}
    assert all(r.is_enabled for r in rows)


# ── one run: read the list, map, push to /ingest/payment_terms ──────────────


def test_a_run_reads_the_db1_list_and_pushes_every_term(wired, monkeypatch):
    db, company = wired
    seen: List[httpx.Request] = []
    _stub_vendor_client(monkeypatch, _vendor(load_terms("db1"), seen))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    job = _run_sync(db, company)

    assert seen and seen[0].url.path == "/api/db1/terms"
    # Read only: every vendor call is a GET.
    assert {r.method for r in seen} == {"GET"}
    records = _ingested_records(posts)
    assert len(records) == 17
    by_code = {r["code"]: r for r in records}
    assert by_code["NET 30 DAYS UPON LOADING DATE"] == {
        "source_ref": "AED_SORENTO:NET 30 DAYS UPON LOADING DATE",
        "code": "NET 30 DAYS UPON LOADING DATE", "rule": "C.O.D.", "is_active": True,
    }
    assert by_code["Net 30 days"]["rule"] == "Net 0th Next 1 Month"
    assert by_code["Net 45 days"]["rule"] == "Net -14th Next 1 Month"
    # The label is sent verbatim, leading asterisk included.
    assert by_code["*C.O.D"]["source_ref"] == "AED_SORENTO:*C.O.D"
    # Exactly the contract keys.
    assert {frozenset(r) for r in records} == {frozenset({"source_ref", "code", "rule", "is_active"})}
    assert job.result_json.get("pushed") == 17, job.result_json
    assert {r.status for r in _staged(db, company)} == {STAGED_PUSHED}


def test_the_db2_list_pushes_its_21_terms_case_distinct_codes_kept(wired, monkeypatch):
    db, company = wired
    _stub_vendor_client(monkeypatch, _vendor(load_terms("db2"), []))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    _run_sync(db, company)

    codes = [r["code"] for r in _ingested_records(posts)]
    assert len(codes) == 21
    # `C.O.D` and `C.O.D.` are two AutoCount terms; both travel.
    assert {"C.O.D", "C.O.D.", "Cash", "CASH BEFORE DELIVERY"} <= set(codes)


def test_an_over_cap_term_fails_that_term_only(wired, monkeypatch):
    db, company = wired
    rows = [
        {"DisplayTerm": "C.O.D.", "Terms": "C.O.D."},
        {"DisplayTerm": "X" * 101, "Terms": "C.O.D."},
        {"DisplayTerm": "LONGRULE", "Terms": "R" * 201},
    ]
    _stub_vendor_client(monkeypatch, _vendor(rows, []))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    _run_sync(db, company)

    assert [r["code"] for r in _ingested_records(posts)] == ["C.O.D."]


def test_an_unchanged_rerun_pushes_nothing_and_a_changed_term_pushes_once(wired, monkeypatch):
    """Idempotent per DisplayTerm per database: the row hash stages only a change."""
    db, company = wired
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    _stub_vendor_client(monkeypatch, _vendor(load_terms("db1"), []))
    _run_sync(db, company)
    assert len(_ingested_records(posts)) == 17

    posts.clear()
    _stub_vendor_client(monkeypatch, _vendor(load_terms("db1"), []))
    _run_sync(db, company)
    assert _ingested_records(posts) == []

    changed = load_terms("db1")
    assert changed[9]["DisplayTerm"] == "Net 30 days"
    changed[9]["Terms"] = "Net 30 days"
    _stub_vendor_client(monkeypatch, _vendor(changed, []))
    _run_sync(db, company)
    assert [(r["code"], r["rule"]) for r in _ingested_records(posts)] == [("Net 30 days", "Net 30 days")]


# ── a term gone from the list -> /ingest/payment_terms/deletions ────────────


def test_a_term_gone_from_the_list_is_sent_to_the_deactivating_deletions_door(wired, monkeypatch):
    from modules.autocount.repositories import RowHashRepository

    db, company = wired
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY,
        {ref: "a" * 64 for ref in ("AED_SORENTO:C.O.D.", "AED_SORENTO:RETIRED")},
        seen_at=None,
    )
    db.commit()
    _stub_vendor_client(monkeypatch, _vendor([{"DisplayTerm": "C.O.D.", "Terms": "C.O.D."}], []))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    _run_sync(db, company)

    assert [r.source_ref for r in _staged(db, company, op=STAGED_OP_DELETE)] == ["AED_SORENTO:RETIRED"]
    deletions = [p for p in posts if p.url.path == INGEST_PATH + "/deletions"]
    assert len(deletions) == 1, [p.url.path for p in posts]
    body = json.loads(deletions[0].content.decode("utf-8"))
    assert body == {"companyCode": "SRT", "source_refs": ["AED_SORENTO:RETIRED"]}


# ── contract 2.14 gate ───────────────────────────────────────────────────────


def test_entity_path_and_gate_table_rows():
    from modules.autocount.sinks_sorento import (
        CONTRACT_GATED_ENTITIES,
        PUSH_REFUSES_LOGGING_FALLBACK,
        _ENTITY_PATH,
    )

    assert _ENTITY_PATH[ENTITY] == "payment_terms"
    version, name = CONTRACT_GATED_ENTITIES[ENTITY]
    assert (version.major, version.minor, name) == (2, 14, "payment_terms")
    assert ENTITY in PUSH_REFUSES_LOGGING_FALLBACK


@pytest.mark.parametrize("version,entities,expected", [
    ("2.13", ["payment_terms"], False),
    ("2.9", ["payment_terms"], False),  # a float compare would call 2.9 > 2.14
    ("2.14", ["customers", "item_classes"], False),  # version alone is not enough
    ("2.14", ["payment_terms"], True),
    ("2.15", ["payment_terms"], True),
    ("3", ["payment_terms"], True),
])
def test_supports_payment_term_needs_2_14_and_the_advertised_door(version, entities, expected):
    from modules.autocount.sinks_sorento import sorento_supports_entity

    assert sorento_supports_entity(
        ENTITY, contract_version=ContractVersion.parse(version), contract_entities=entities
    ) is expected


def test_a_shut_gate_refuses_the_push_and_keeps_every_term_staged(wired, monkeypatch):
    db, company = wired
    _stub_vendor_client(monkeypatch, _vendor(load_terms("db1"), []))
    _contract(monkeypatch, "2.13", ["customers", "item_classes"])
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))

    _run_sync(db, company)

    assert not [p for p in posts if "payment_terms" in p.url.path]
    staged = _staged(db, company)
    assert len(staged) == 17 and {r.status for r in staged} == {STAGED}


def test_terms_held_back_on_2_13_are_pushed_once_the_crm_reaches_2_14(wired, monkeypatch):
    db, company = wired
    _stub_vendor_client(monkeypatch, _vendor(load_terms("db1"), []))
    _contract(monkeypatch, "2.13", ["payment_terms"])
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _crm(posts))
    _run_sync(db, company)
    assert not _ingested_records(posts)

    _open_contract(monkeypatch)
    _stub_vendor_client(monkeypatch, _vendor(load_terms("db1"), []))
    _run_sync(db, company)

    assert len(_ingested_records(posts)) == 17
    assert {r.status for r in _staged(db, company)} == {STAGED_PUSHED}


def test_sink_for_company_opens_on_2_14_and_not_on_2_13(db, monkeypatch):
    from modules.autocount.services.company_service import CompanyService

    company = _company(db, _vendor_connection(db), sorento_conn=_sorento_connection(db))
    _open_contract(monkeypatch)
    assert isinstance(CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY), SorentoSink)
    _contract(monkeypatch, "2.13", ["payment_terms"])
    assert CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY).name == SINK_LOGGING


def test_task_view_contract_gate_names_the_required_version(db, monkeypatch):
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.services.etl_service import EtlService

    company = _company(db, _vendor_connection(db), sorento_conn=_sorento_connection(db))
    required = CompanyService._CONTRACT_GATE_REQUIRED_VERSIONS[ENTITY]
    assert (required.major, required.minor) == (2, 14)

    _contract(monkeypatch, "2.13", ["customers"])
    gate = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY).contract_gate
    assert gate is not None and gate["entity"] == ENTITY
    assert gate["requiredVersion"] == ContractVersion(2, 14)

    _open_contract(monkeypatch)
    assert EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY).contract_gate is None


def test_supported_entities_label_never_claims_the_gated_payment_term():
    from modules.autocount.sinks_sorento import sorento_supported_entities_label

    assert "payment term" not in sorento_supported_entities_label()


# ── order: terms before customers ────────────────────────────────────────────


def test_the_sweep_enqueues_payment_terms_before_customers():
    from modules.autocount.scheduler import sweep_order_key

    due = ["customer", "product", ENTITY, "item_class"]
    ordered = sorted(due, key=sweep_order_key)
    assert ordered.index(ENTITY) < ordered.index("customer")
    assert ordered[0] == "item_class"  # plan 37 order unchanged


def test_no_display_term_in_the_recorded_books_differs_only_by_case():
    """CRM first-push adoption by code is case-insensitive: two DisplayTerms
    differing only by case in one book would ReferenceConflict. Pinned on the
    recorded books (each still carries its own `source_ref` if one appears)."""
    for book in ("db1", "db2"):
        codes = [r["DisplayTerm"].strip() for r in load_terms(book)]
        assert len({c.casefold() for c in codes}) == len(codes), book
