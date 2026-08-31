"""Masters fan-out (plan 22 S4, AC-22-23) - product/warehouse/product_category/
unit_of_measure/sales_agent land end-to-end through the SAME generic pipeline
suppliers/customers already proved (S1-S3): canonical shape -> flat mapping ->
Sorento sink routing -> retryable-stays-staged auto-push.

Nothing here forks a new code path - every assertion pins that the new
entities plug into the EXISTING seams (``mapping.ENTITY_PROFILES``,
``sinks_sorento._ENTITY_PATH``, ``services.sync_service.CANONICAL_MODELS``).
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, BackgroundJob
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import (
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT,
    ENTITY_PRODUCT_CATEGORY,
    ENTITY_SALES_AGENT,
    ENTITY_SUPPLIER,
    ENTITY_UNIT_OF_MEASURE,
    ENTITY_WAREHOUSE,
    CanonicalProduct,
    CanonicalProductCategory,
    CanonicalSalesAgent,
    CanonicalUnitOfMeasure,
    CanonicalWarehouse,
)
from modules.autocount.mapping import (
    MappingEngine,
    MappingRow,
    flat_profile,
    flat_source_ref,
)
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    STAGED,
    STAGED_FAILED,
    STAGED_PUSHED,
    AcCompany,
    AcEntityConfig,
    AcStagedRecord,
)
from modules.autocount.services.company_service import (
    AutocountServiceError,
    CompanyService,
)
from modules.autocount.services.sync_service import SyncService
from modules.autocount.sinks_sorento import SorentoSink
from modules.autocount.sync import AUTOCOUNT_SYNC

DB = "AED_VSOFT"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


NEW_ENTITIES = (
    ENTITY_PRODUCT_CATEGORY,
    ENTITY_UNIT_OF_MEASURE,
    ENTITY_WAREHOUSE,
    ENTITY_PRODUCT,
    ENTITY_SALES_AGENT,
)


# ── canonical shape -> sink_payload projection (golden, per entity) ──────────


def test_product_category_sink_payload_is_exactly_sorentos_field_set():
    rec = CanonicalProductCategory(
        source_ref=f"{DB}:1", source_doc_no="CAT-1", code="CAT-1", name="Beverages",
        description="Drinks", is_active=True,
    )
    assert rec.sink_payload() == {
        "source_ref": f"{DB}:1", "source_doc_no": "CAT-1", "code": "CAT-1",
        "name": "Beverages", "description": "Drinks", "is_active": True,
    }


def test_unit_of_measure_sink_payload_carries_decimal_places():
    rec = CanonicalUnitOfMeasure(
        source_ref=f"{DB}:1", source_doc_no="PCS", code="PCS", name="Pieces",
        decimal_places=2, description=None, is_active=True,
    )
    assert rec.sink_payload() == {
        "source_ref": f"{DB}:1", "source_doc_no": "PCS", "code": "PCS",
        "name": "Pieces", "decimal_places": 2, "description": None, "is_active": True,
    }


def test_unit_of_measure_decimal_places_defaults_to_zero():
    rec = CanonicalUnitOfMeasure(source_ref=f"{DB}:1", code="EA", name="Each")
    assert rec.decimal_places == 0


def test_warehouse_sink_payload_carries_location():
    rec = CanonicalWarehouse(
        source_ref=f"{DB}:1", source_doc_no="WH1", code="WH1", name="Main store",
        location="KL", is_active=True,
    )
    assert rec.sink_payload() == {
        "source_ref": f"{DB}:1", "source_doc_no": "WH1", "code": "WH1",
        "name": "Main store", "location": "KL", "is_active": True,
    }


def test_product_sink_payload_carries_category_and_uom_codes_not_refs():
    """Appendix A6 - a product resolves its category/UOM by Sorento's own
    CODE, not by the ESB's integration ``source_ref`` scheme (unlike a
    document line's ``product_ref``/``warehouse_ref``)."""
    rec = CanonicalProduct(
        source_ref=f"{DB}:1", source_doc_no="ITEM-1", code="ITEM-1", name="Widget",
        description="A widget", category_code="CAT-1", uom_code="PCS",
        brand_code="ACME", list_price=Decimal("9.99"), cost_price=Decimal("4.50"),
        is_active=True,
    )
    assert rec.sink_payload() == {
        "source_ref": f"{DB}:1", "source_doc_no": "ITEM-1", "code": "ITEM-1",
        "name": "Widget", "description": "A widget", "category_code": "CAT-1",
        "uom_code": "PCS", "brand_code": "ACME", "list_price": "9.99",
        "cost_price": "4.50", "is_active": True,
    }


def test_sales_agent_sink_payload_is_exactly_the_A6_shape():
    """Appendix A6 §6: ``{source_ref, source_doc_no?, code, description?,
    is_active=true, person_label?}`` - no ``name``/``email``/``credit_limit``
    even though ``CanonicalMaster`` carries those fields internally."""
    rec = CanonicalSalesAgent(
        source_ref="agent:SA01", source_doc_no="SA01", code="SA01",
        description="Sales agent one", is_active=True, person_label="Sean",
    )
    assert rec.sink_payload() == {
        "source_ref": "agent:SA01", "source_doc_no": "SA01", "code": "SA01",
        "description": "Sales agent one", "is_active": True, "person_label": "Sean",
    }


def test_sales_agent_name_never_crosses_the_wire():
    rec = CanonicalSalesAgent(source_ref="agent:SA01", code="SA01", name="should not send")
    assert "name" not in rec.sink_payload()


# ── EntityProfile / flat mapping per entity (AC-22-09), one formula row each ──


def _rows(*specs):
    return [
        MappingRow(source_path=s, canonical_field=t, transform=tr, formula=f)
        for s, t, tr, f in specs
    ]


@pytest.mark.parametrize(
    "entity_type,record_model",
    [
        (ENTITY_PRODUCT_CATEGORY, CanonicalProductCategory),
        (ENTITY_UNIT_OF_MEASURE, CanonicalUnitOfMeasure),
        (ENTITY_WAREHOUSE, CanonicalWarehouse),
        (ENTITY_PRODUCT, CanonicalProduct),
        (ENTITY_SALES_AGENT, CanonicalSalesAgent),
    ],
)
def test_flat_profile_registers_the_right_canonical_model(entity_type, record_model):
    """Every new entity now has an ``EntityProfile`` - before S4 this raised
    ``UnknownEntityProfile`` (the etl_service.py NIT about ``ETL_ENTITY_TYPES``
    being wider than ``mapping.ENTITY_PROFILES``)."""
    assert flat_profile(entity_type, ["code"]).record_model is record_model


def test_product_category_maps_through_the_real_engine_with_a_formula_row():
    engine = MappingEngine(
        _rows(
            ("category_code", "code", "string", None),
            ("category_name", "name", "string", None),
            ("status", "is_active", "bool", "upper(value) == 'A'"),
        ),
        entity_type=ENTITY_PRODUCT_CATEGORY,
        profile=flat_profile(ENTITY_PRODUCT_CATEGORY, ["category_code"]),
        database_name=DB,
    )
    mapped = engine.map_document(
        {"category_code": "CAT-1", "category_name": "Beverages", "status": "a"}
    )
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.source_ref == f"{DB}:CAT-1"
    assert mapped.record.is_active is True


def test_unit_of_measure_maps_through_the_real_engine_with_a_formula_row():
    engine = MappingEngine(
        _rows(
            ("uom_code", "code", "string", None),
            ("uom_name", "name", "string", None),
            ("dp", "decimal_places", "int", "value * 1"),
        ),
        entity_type=ENTITY_UNIT_OF_MEASURE,
        profile=flat_profile(ENTITY_UNIT_OF_MEASURE, ["uom_code"]),
        database_name=DB,
    )
    mapped = engine.map_document({"uom_code": "PCS", "uom_name": "Pieces", "dp": 2})
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.decimal_places == 2


def test_warehouse_maps_through_the_real_engine_with_a_formula_row():
    engine = MappingEngine(
        _rows(
            ("wh_code", "code", "string", None),
            ("wh_name", "name", "string", None),
            ("loc", "location", "string", "upper(value)"),
        ),
        entity_type=ENTITY_WAREHOUSE,
        profile=flat_profile(ENTITY_WAREHOUSE, ["wh_code"]),
        database_name=DB,
    )
    mapped = engine.map_document({"wh_code": "WH1", "wh_name": "Main", "loc": "kl"})
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.location == "KL"


def test_product_maps_through_the_real_engine_with_a_formula_row():
    engine = MappingEngine(
        _rows(
            ("item_code", "code", "string", None),
            ("item_name", "name", "string", None),
            ("cat", "category_code", "string", None),
            ("uom", "uom_code", "string", None),
            ("price", "list_price", "decimal", "value * 1"),
        ),
        entity_type=ENTITY_PRODUCT,
        profile=flat_profile(ENTITY_PRODUCT, ["item_code"]),
        database_name=DB,
    )
    mapped = engine.map_document(
        {"item_code": "ITEM-1", "item_name": "Widget", "cat": "CAT-1", "uom": "PCS",
         "price": "9.99"}
    )
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.category_code == "CAT-1"
    assert mapped.record.uom_code == "PCS"
    assert mapped.record.list_price == Decimal("9.99")


# ── sales-agent unqualified ref + upper/trim, end to end (Appendix A6 §6) ────


def test_sales_agent_maps_through_the_real_engine_with_a_formula_row_and_unqualified_ref():
    engine = MappingEngine(
        _rows(
            ("agent_code", "code", "string", None),
            ("agent_name", "person_label", "string", "trim(value)"),
        ),
        entity_type=ENTITY_SALES_AGENT,
        profile=flat_profile(ENTITY_SALES_AGENT, ["agent_code"]),
        database_name=DB,
    )
    mapped = engine.map_document({"agent_code": " sean i ", "agent_name": " Sean "})
    assert mapped.ok, [e.message() for e in mapped.errors]
    # Upper-cased and trimmed, and NOT company-qualified (Appendix A6 §6) - two
    # different companies' tasks resolve to the SAME shared row.
    assert mapped.record.source_ref == "agent:SEAN I"
    assert mapped.record.person_label == "Sean"


def test_two_companies_sales_agent_tasks_mint_the_same_shared_ref():
    ref_a = flat_source_ref(
        {"AgentCode": "sa01"}, database_name="COMPANY_A", key_columns=["AgentCode"],
        entity_type=ENTITY_SALES_AGENT,
    )
    ref_b = flat_source_ref(
        {"AgentCode": "SA01"}, database_name="COMPANY_B", key_columns=["AgentCode"],
        entity_type=ENTITY_SALES_AGENT,
    )
    assert ref_a == ref_b == "agent:SA01"


# ── sinks_sorento: entity-path + deletion-path routing (Appendix A6/A8) ──────


@pytest.mark.parametrize(
    "entity_type,segment",
    [
        (ENTITY_PRODUCT_CATEGORY, "product_categories"),
        (ENTITY_UNIT_OF_MEASURE, "units_of_measure"),
        (ENTITY_WAREHOUSE, "warehouses"),
        (ENTITY_PRODUCT, "products"),
        (ENTITY_SALES_AGENT, "sales_agents"),
    ],
)
def test_entity_path_maps_to_the_plural_route(entity_type, segment):
    requests: List[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        records = [
            {"source_ref": r["source_ref"], "outcome": "created", "entity_id": "id-1"}
            for r in body["records"]
        ]
        return httpx.Response(200, json={
            "summary": {"total": len(records), "created": len(records), "updated": 0,
                        "failed": 0, "retryable": 0},
            "records": records,
        })

    sink = SorentoSink(
        base_url="http://x", api_key="k", entity_type=entity_type,
        transport=httpx.MockTransport(handle),
    )
    record = CanonicalProductCategory(source_ref="ref-1", code="C1", name="N") if (
        entity_type == ENTITY_PRODUCT_CATEGORY
    ) else CanonicalSalesAgent(source_ref="ref-1", code="C1")
    sink.write_batch([record], request_id="t")
    assert requests[0].url.path == f"/api/v1/external/ingest/{segment}"


@pytest.mark.parametrize(
    "entity_type,segment",
    [
        (ENTITY_PRODUCT_CATEGORY, "product_categories"),
        (ENTITY_UNIT_OF_MEASURE, "units_of_measure"),
        (ENTITY_WAREHOUSE, "warehouses"),
        (ENTITY_PRODUCT, "products"),
        (ENTITY_SALES_AGENT, "sales_agents"),
    ],
)
def test_deletion_path_maps_to_the_plural_route_plus_deletions(entity_type, segment):
    requests: List[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        refs = json.loads(request.content)["source_refs"]
        return httpx.Response(200, json={
            "summary": {"total": len(refs), "deleted": len(refs), "deactivated": 0,
                        "not_found": 0, "failed": 0},
            "records": [{"source_ref": r, "outcome": "deleted", "entity_id": "x"} for r in refs],
        })

    sink = SorentoSink(
        base_url="http://x", api_key="k", entity_type=entity_type,
        transport=httpx.MockTransport(handle),
    )
    sink.delete_batch(["ref-1"])
    assert requests[0].url.path == f"/api/v1/external/ingest/{segment}/deletions"


def test_sorento_supports_all_five_new_entities():
    from modules.autocount.sinks_sorento import sorento_supports_entity

    for entity_type in NEW_ENTITIES:
        assert sorento_supports_entity(entity_type)


# ── product retryable verdict: expected + carries over, never quarantined ────


def test_a_product_retryable_verdict_names_the_dependency_not_unreachable():
    """A product whose category/UOM has not synced yet is EXPECTED retryable
    (AC-22-23) - the message must not read like the AC-14-24 defect signal
    reserved for masters with no dependency reference."""
    def handle(request: httpx.Request) -> httpx.Response:
        ref = json.loads(request.content)["records"][0]["source_ref"]
        return httpx.Response(200, json={
            "summary": {"total": 1, "created": 0, "updated": 0, "failed": 0, "retryable": 1},
            "records": [{"source_ref": ref, "outcome": "retryable", "entity_id": None}],
        })

    sink = SorentoSink(
        base_url="http://x", api_key="k", entity_type=ENTITY_PRODUCT,
        transport=httpx.MockTransport(handle),
    )
    [result] = sink.write_batch(
        [CanonicalProduct(source_ref="ref-1", code="ITEM-1", name="Widget",
                           category_code="CAT-1", uom_code="PCS")],
        request_id="t",
    )
    assert result.delivered is False
    assert result.outcome == "retryable"
    assert "unreachable" not in result.message.lower()
    assert "category" in result.message.lower() or "unit of measure" in result.message.lower()


def test_a_warehouse_retryable_verdict_still_reads_as_unreachable():
    """A warehouse carries no dependency reference - AC-14-24's defect-signal
    wording still applies to it (only ``product`` is exempted)."""
    def handle(request: httpx.Request) -> httpx.Response:
        ref = json.loads(request.content)["records"][0]["source_ref"]
        return httpx.Response(200, json={
            "summary": {"total": 1, "created": 0, "updated": 0, "failed": 0, "retryable": 1},
            "records": [{"source_ref": ref, "outcome": "retryable", "entity_id": None}],
        })

    sink = SorentoSink(
        base_url="http://x", api_key="k", entity_type=ENTITY_WAREHOUSE,
        transport=httpx.MockTransport(handle),
    )
    [result] = sink.write_batch(
        [CanonicalWarehouse(source_ref="ref-1", code="WH1", name="Main")], request_id="t",
    )
    assert "unreachable" in result.message.lower()


# ── AC-22-23 dependency order, at the sync_service push layer ────────────────
# A retryable product verdict must stay STAGED (re-offered next run), never be
# quarantined - the SAME generic carry-over mechanism
# ``test_autocount_etl_task_routes.py`` already proved for customers.


def _connection(db, provider: str, config: Dict[str, Any], credentials: Dict[str, Any]) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID,
        provider=provider,
        type="erp" if provider != "sorento" else "consumer",
        name=f"{provider} conn",
        config_json=config,
        credentials_json=encrypt_secret(credentials),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


@pytest.fixture
def sorento_consumer(monkeypatch):
    """Route every ``SorentoSink`` this test builds through a scripted
    transport, mirroring ``test_autocount_reconcile_push.py``'s ``consumer``
    fixture."""
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    responses: List[Dict[str, Any]] = []
    requests: List[Dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        requests.append(body)
        return httpx.Response(200, json=responses.pop(0))

    def fake(config, credentials, *, entity_type, company_code=None, transport=None):
        return real(
            config, credentials, entity_type=entity_type, company_code=company_code,
            transport=httpx.MockTransport(handle),
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)
    return responses, requests


def _product_company(db) -> AcCompany:
    api = _connection(
        db, "autocount", {"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        {"appId": "app-1", "password": "secret"},
    )
    sorento = _connection(db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"})
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name=DB,
        company_name="AED Sdn Bhd", name="AED", is_active=True,
        sink_impl="sorento", sink_connection_id=sorento.id, sorento_company_code="SRT",
    )
    db.add(company)
    db.flush()
    db.add(AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="sql_db", etl_status=ETL_STATUS_ACTIVE,
    ))
    db.commit()
    db.refresh(company)
    return company


def _stage_product(db, company, job_id: str, *, source_ref="AED_VSOFT:ITEM-1") -> AcStagedRecord:
    record = CanonicalProduct(
        source_ref=source_ref, code="ITEM-1", name="Widget",
        category_code="CAT-1", uom_code="PCS", is_active=True,
    )
    row = AcStagedRecord(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        job_id=job_id, source_ref=source_ref, canonical_json=record.comparable(),
        status=STAGED,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _job(db) -> BackgroundJob:
    job = BackgroundJob(tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC, status=JOB_DONE)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_a_retryable_product_stays_staged_and_the_next_run_resolves_it(db, sorento_consumer):
    responses, requests = sorento_consumer
    company = _product_company(db)
    job = _job(db)
    row = _stage_product(db, company, job.id)

    # Run 1: category/UOM have not synced yet - Sorento reports retryable.
    responses.append({
        "summary": {"total": 1, "created": 0, "updated": 0, "failed": 0, "retryable": 1},
        "records": [{"source_ref": row.source_ref, "outcome": "retryable", "entity_id": None}],
    })
    summary = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job.id)
    assert summary["pushed"] == 0
    db.refresh(row)
    assert row.status == STAGED  # carried over, NEVER quarantined

    # Run 2 (a different job): category + UOM landed - Sorento now creates it.
    job2 = _job(db)
    responses.append({
        "summary": {"total": 1, "created": 1, "updated": 0, "failed": 0, "retryable": 0},
        "records": [{"source_ref": row.source_ref, "outcome": "created", "entity_id": "prod-1"}],
    })
    summary2 = SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job2.id)
    assert summary2["pushed"] == 1
    db.refresh(row)
    assert row.status == STAGED_PUSHED

    # Both pushes went to the products route.
    for body in requests:
        assert body["records"][0]["category_code"] == "CAT-1"


def test_a_failed_product_verdict_is_quarantined_not_carried_over(db, sorento_consumer):
    """A ``failed`` verdict (bad data) IS the D13 "never pushable again"
    quarantine - unlike ``retryable``, it must not carry over."""
    responses, _ = sorento_consumer
    company = _product_company(db)
    job = _job(db)
    row = _stage_product(db, company, job.id)
    responses.append({
        "summary": {"total": 1, "created": 0, "updated": 0, "failed": 1, "retryable": 0},
        "records": [{"source_ref": row.source_ref, "outcome": "failed", "entity_id": None,
                     "errors": {"name": "Field required"}}],
    })
    SyncService(db).auto_push(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, job_id=job.id)
    db.refresh(row)
    assert row.status == STAGED_FAILED


# ── source-switch guard: autocount_read refused for a DB-only entity ────────


def test_switching_a_db_only_entity_to_the_api_path_is_refused(db):
    company = _product_company(db)
    with pytest.raises(AutocountServiceError) as excinfo:
        CompanyService(db).update_entity_config(
            DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, source_impl="autocount_read",
        )
    # S4 review S1: name the REASON, not just the refusal - an operator
    # reading this must not have to guess whether it is a config mistake or a
    # genuine build limitation.
    assert "build has no working AutoCount API route" in excinfo.value.message
    assert ENTITY_PRODUCT in excinfo.value.message


def test_switching_a_seeded_entity_to_the_api_path_still_works(db):
    """The guard is narrow - it must not block the EXISTING supplier/customer/
    GRN switch-back-to-API path (AC-22-08)."""
    api = _connection(
        db, "autocount", {"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        {"appId": "app-1", "password": "secret"},
    )
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name=DB,
        company_name="AED Sdn Bhd", name="AED", is_active=True,
    )
    db.add(company)
    db.flush()
    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()
    db.refresh(company)
    state = CompanyService(db).update_entity_config(
        DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER, source_impl="autocount_read",
    )
    assert state.source_impl == "autocount_read"


# ── EntityConfigItem wire carries etlStatus (FE prerequisite-chip data) ──────


def test_entity_state_carries_etl_status(db):
    company = _product_company(db)
    [state] = [
        s for s in CompanyService(db).entity_states(DEFAULT_TENANT_ID, company.id)
        if s.entity_type == ENTITY_PRODUCT
    ]
    assert state.etl_status == ETL_STATUS_ACTIVE


# ── mapping_catalog: the Mapping tab's save-time guard admits the new fields ──
# Without a ``SORENTO_FIELDS`` entry, ``accepted_field_names`` is EMPTY and
# EVERY mapping row a database task's Mapping tab tries to save 422s (the
# guard is entity-agnostic code, DB-source or not) - AC-22-23 is not "landed
# end-to-end" if the operator can never configure the mapping.


def test_the_five_new_entities_accept_their_canonical_fields():
    from modules.autocount.mapping_catalog import accepted_field_names, required_field_names

    accepted = accepted_field_names(ENTITY_PRODUCT)
    assert {"code", "name", "category_code", "uom_code", "is_active"} <= accepted
    assert "source_ref" not in accepted  # minted, never mapped

    assert required_field_names(ENTITY_PRODUCT_CATEGORY) == {"code", "name", "is_active"}
    # sales_agent has no `name` field on Sorento's side - required narrows to
    # what it actually carries, never a phantom requirement.
    assert required_field_names(ENTITY_SALES_AGENT) == {"code", "is_active"}


def test_replace_mapping_saves_a_product_row_that_would_have_422d_before_s4(db):
    from modules.autocount.services.company_service import MappingWriteRow

    company = _product_company(db)
    view = CompanyService(db).replace_mapping(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        [
            MappingWriteRow("item_code", "string", "code"),
            MappingWriteRow("item_name", "string", "name"),
            MappingWriteRow("cat_code", "string", "category_code"),
            MappingWriteRow("uom_code", "string", "uom_code"),
        ],
    )
    fields = {row.sorento_field for row in view.rows if row.sorento_field}
    assert {"code", "name", "category_code", "uom_code"} <= fields
