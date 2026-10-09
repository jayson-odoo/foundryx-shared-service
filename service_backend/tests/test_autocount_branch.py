"""Sprint-5/14 section 11 (D23-D28, 29 Sep 2026) - the `branch` entity: a
regular HTTP master entity wired like `brand` (sprint-5/08), paged like
`product`. AC-14-40..45 (AC-14-46 lives in tests/test_s14_doc_feed_branch_removed.py).

RED before the coder: `ENTITY_BRANCH` / `CanonicalBranch` do not exist in
`modules/autocount/canonical/masters.py`, `HTTP_PRESETS` has no `branch`,
`_ENTITY_PATH` / `CONTRACT_GATED_ENTITIES` only know the doc feed's plural
`branches` key. Every test imports its symbols INSIDE the test body so each
fails on its own missing symbol / wrong value, never at collection.

Contract facts pinned (sorento #1356, contract 2.7 section 13.11): the CRM door
is `POST /api/v1/external/ingest/branches`, requires top-level `companyCode`
AND `book`, each record is the raw `branchbypage` row, the CRM derives the
verdict `source_ref` as `{book}:BR:{AccNo}:{BranchCode}` itself, verdicts are
created / updated / unchanged / failed, and there is NO deletions door.

Paged vendor fixtures: `BRANCH_PAGE_FIXTURES` below is the NEW home
(`tests/fixtures/autocount_http/`, the coder `git mv`s them from
`tests/fixtures/s14_doc_feed/` per D28); `load_branch_page` falls back to the
old dir so this file fails for the RIGHT reason today, and
`test_ac_14_46_branch_fixtures_moved_to_the_autocount_http_dir` is the red pin
for the move itself.

Internal names guessed (flagged in the tester report): `CanonicalBranch`
constructor kwargs `acc_no`/`code`/`name`/`source_record` (all four named by
plan D24), and the run summary key `vanished` (named by AC-14-45).
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
from modules.autocount.models import AcCompany, AcFieldMapping, AcStagedRecord, STAGED_OP_DELETE, SINK_IMPL_SORENTO
from modules.autocount.sinks import SINK_LOGGING
from modules.autocount.sinks_sorento import SorentoContractInfo, SorentoSink

TESTS_DIR = Path(__file__).resolve().parent
BRANCH_PAGE_FIXTURES = TESTS_DIR / "fixtures" / "autocount_http"
_LEGACY_BRANCH_FIXTURES = TESTS_DIR / "fixtures" / "s14_doc_feed"

VENDOR_BASE_URL = "https://hapi.sorento.cc.cd/api/db1"
CRM_BASE_URL = "https://sorento.example.com"

# A realistic vendor row: the three mapped keys plus the address-record keys the
# live db1 endpoint returns (plan 14 section 11 "Live vendor facts").
RAW_ROW: Dict[str, Any] = {
    "AccNo": "300-A056",
    "BranchCode": "KUANTAN",
    "BranchName": "Kuantan Branch",
    "Address1": "12 Jalan Besar",
    "Address2": "",
    "PostCode": "25000",
    "Phone1": "09-5551234",
    "Contact": "Ali",
    "IsActive": "T",
    "TaxEntityID": 7,
}


def load_branch_page(number: int) -> Dict[str, Any]:
    name = f"branch-page-{number}.json"
    path = BRANCH_PAGE_FIXTURES / name
    if not path.exists():
        path = _LEGACY_BRANCH_FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


# ── shared rigs ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _vendor_connection(db, *, base_url: str = VENDOR_BASE_URL) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db REST",
        config_json={"baseUrl": base_url, "auth": "none"}, credentials_json=None, is_active=True,
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


def _branch_raw(connection_id: str) -> Dict[str, Any]:
    """The task body an operator saves after picking Branch in Add entity (the
    FE prefills exactly this from `HTTP_PRESETS.branch`)."""
    return {
        "sourceImpl": "autocount_http", "connectionId": connection_id, "path": "/branchbypage",
        "keyFields": ["AccNo", "BranchCode"], "watermarkField": None, "comparedFields": [],
        "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
        "reconcileHours": None, "reconcileAt": "02:00",
    }


@pytest.fixture
def wired(db):
    """A vendor db1 company delivering to a Sorento consumer + its saved branch task."""
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    sorento = _sorento_connection(db)
    company = _company(db, vendor, sorento_conn=sorento)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, _branch_raw(vendor.id))
    # Coder correction (round 3): the tests below read `pushed` / a vanished
    # count off a run that DELIVERS; only an ACTIVE task auto-pushes
    # (`sync.py` auto-push gate, "the activate-once ceremony IS the approval"),
    # so the rig marks the saved task active the way a completed Activate would.
    from modules.autocount.models import ETL_STATUS_ACTIVE
    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH)
    config.etl_status = ETL_STATUS_ACTIVE
    db.commit()
    return db, company, vendor


def _open_contract(monkeypatch, *, version: float = 2.7, entities=None) -> None:
    contract = SorentoContractInfo(
        version=version, entities=list(entities if entities is not None else ["branches"])
    )
    monkeypatch.setattr(SorentoSink, "fetch_contract_detail", lambda self: contract)


def _inject_sink_transport(monkeypatch, handler) -> None:
    """Route the ETL sink `sink_for_company` builds through a MockTransport."""
    import modules.autocount.services.company_service as company_module

    real = company_module.sorento_sink_from_connection

    def spy(config, credentials, *, entity_type, company_code=None, transport=None, **kw):
        return real(
            config, credentials, entity_type=entity_type, company_code=company_code,
            transport=httpx.MockTransport(handler), **kw,
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", spy)


def _echo_ingest_handler(calls: List[httpx.Request]):
    """A CRM stand-in: verdict `created` per record, `source_ref` derived the way
    the CRM does (`{book}:BR:{AccNo}:{BranchCode}`)."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content.decode("utf-8"))
        book = body.get("book")
        records = body.get("records") or []
        return httpx.Response(200, json={
            "dry_run": False, "summary": {"total": len(records), "created": len(records)},
            "records": [
                {"source_ref": f"{book}:BR:{r.get('AccNo')}:{r.get('BranchCode')}", "outcome": "created"}
                for r in records
            ],
        })

    return handler


def _paged_vendor(rows: List[Dict[str, Any]], requests_seen: List[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json={
            "TotalCount": len(rows), "Page": page, "PageSize": 1000, "TotalPages": 1,
            "Data": rows if page == 1 else [],
        })

    return handler


def _stub_vendor_client(monkeypatch, handler) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    stub = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub),
    )


def _run_sync(db, company, entity_type: str) -> BackgroundJob:
    from app.jobs.service import JobService
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": entity_type, "mode": "manual"},
    )
    run_autocount_sync(db, job)
    db.refresh(job)
    return job


# ── AC-14-40: registration ───────────────────────────────────────────────────


def test_ac_14_40_entity_branch_is_registered_where_brand_is():
    from modules.autocount.canonical.masters import ENTITY_BRANCH, MASTER_ENTITIES
    from modules.autocount.services.etl_service import ETL_ENTITY_TYPES

    assert ENTITY_BRANCH == "branch"
    assert ENTITY_BRANCH in MASTER_ENTITIES
    assert ENTITY_BRANCH in ETL_ENTITY_TYPES


def test_ac_14_40_canonical_model_catalog_and_profile_registry():
    from modules.autocount.canonical.masters import ENTITY_BRANCH, CanonicalBranch
    from modules.autocount.mapping import ENTITY_PROFILES
    from modules.autocount.mapping_catalog import SORENTO_FIELDS
    from modules.autocount.services.sync_service import CANONICAL_MODELS

    assert CANONICAL_MODELS[ENTITY_BRANCH] is CanonicalBranch
    assert ENTITY_BRANCH in SORENTO_FIELDS
    assert ENTITY_PROFILES[ENTITY_BRANCH].record_model is CanonicalBranch


def test_ac_14_40_http_preset_path_keys_and_rows():
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.presets import HTTP_ENTITY_TYPES, HTTP_PRESETS

    preset = HTTP_PRESETS[ENTITY_BRANCH]
    assert ENTITY_BRANCH in HTTP_ENTITY_TYPES
    assert preset.path == "/branchbypage"
    assert preset.key_fields == ("AccNo", "BranchCode")
    rows = {(r.source_path, r.canonical_field): r for r in preset.rows}
    assert set(rows) == {("AccNo", "acc_no"), ("BranchCode", "code"), ("BranchName", "name")}
    assert rows[("AccNo", "acc_no")].required is True
    assert rows[("BranchCode", "code")].required is True
    assert rows[("BranchName", "name")].required is False


def test_ac_14_40_branch_is_http_only_and_push_only():
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import HTTP_CAPABLE_ENTITY_TYPES, SEEDED_ENTITIES
    from modules.autocount.services.etl_service import PULL_CAPABLE_ENTITY_TYPES

    assert ENTITY_BRANCH in HTTP_CAPABLE_ENTITY_TYPES
    assert ENTITY_BRANCH not in PULL_CAPABLE_ENTITY_TYPES
    # "Reaches a company only through Add entity, like brand (no seed)".
    assert ENTITY_BRANCH not in SEEDED_ENTITIES


def test_ac_14_40_first_class_http_task_is_accepted_for_branch(db):
    """`update_task` must accept an `autocount_http` branch task (the entity-set
    gate `entity_type not in HTTP_CAPABLE_ENTITY_TYPES` no longer refuses it)."""
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.repositories import EntityConfigRepository
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    company = _company(db, vendor)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, _branch_raw(vendor.id))
    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH)
    assert config.source_impl == "autocount_http"
    assert config.source_config["path"] == "/branchbypage"
    assert config.source_config["keyFields"] == ["AccNo", "BranchCode"]


def test_ac_14_46_branch_fixtures_moved_to_the_autocount_http_dir():
    for number in (1, 2):
        assert (BRANCH_PAGE_FIXTURES / f"branch-page-{number}.json").exists(), (
            "D28: the branch page fixtures move to tests/fixtures/autocount_http/"
        )


# ── AC-14-40: CanonicalBranch field limits ───────────────────────────────────


def _branch(**overrides):
    from modules.autocount.canonical.masters import CanonicalBranch

    values = {
        "source_ref": "db1:BR:300-A056:KUANTAN", "acc_no": "300-A056", "code": "KUANTAN",
        "name": "Kuantan Branch", "source_record": dict(RAW_ROW),
    }
    values.update(overrides)
    return CanonicalBranch(**values)


def test_ac_14_40_canonical_branch_accepts_the_boundary_lengths():
    record = _branch(acc_no="A" * 100, code="C" * 100, name="N" * 255)
    assert len(record.acc_no) == 100 and len(record.code) == 100 and len(record.name) == 255


def test_ac_14_40_acc_no_over_100_chars_rejected():
    with pytest.raises(ValidationError):
        _branch(acc_no="A" * 101)


def test_ac_14_40_code_over_100_chars_rejected():
    with pytest.raises(ValidationError):
        _branch(code="C" * 101)


def test_ac_14_40_name_over_255_chars_rejected():
    with pytest.raises(ValidationError):
        _branch(name="N" * 256)


def test_ac_14_40_blank_code_is_a_field_error():
    with pytest.raises(ValidationError) as exc_info:
        _branch(code="")
    assert "code" in str(exc_info.value)


def test_ac_14_40_missing_acc_no_is_a_field_error():
    from modules.autocount.canonical.masters import CanonicalBranch

    with pytest.raises(ValidationError) as exc_info:
        CanonicalBranch(source_ref="db1:BR::HQ", code="HQ", name="HQ")
    assert "acc_no" in str(exc_info.value)


# ── AC-14-43: sink payload = the raw row, mapped keys written over it ───────


def test_ac_14_43_sink_payload_is_the_raw_row_with_the_mapped_keys_written_over_it():
    page = load_branch_page(1)["Data"][0]
    raw = {**page, "Address1": "1 Jalan Ampang", "Phone1": "03-1234", "IsActive": "T", "TaxEntityID": 9}
    record = _branch(
        source_ref=f"db1:BR:{raw['AccNo']}:{raw['BranchCode']}",
        acc_no=raw["AccNo"], code=raw["BranchCode"], name="Head Office (renamed by mapping)",
        source_record=raw,
    )
    payload = record.sink_payload()

    assert payload == {**raw, "AccNo": raw["AccNo"], "BranchCode": raw["BranchCode"],
                       "BranchName": "Head Office (renamed by mapping)"}
    assert payload["Address1"] == "1 Jalan Ampang"  # the rest of the row rides along untouched
    # No canonical keys leak into the record: exactly the raw row's own keys.
    assert set(payload) == set(raw)
    for canonical_key in ("source_ref", "source_doc_no", "code", "name", "acc_no", "is_active", "source_record"):
        assert canonical_key not in payload


def test_ac_14_43_sink_payload_does_not_mutate_the_stored_raw_row():
    raw = dict(RAW_ROW)
    record = _branch(name="Renamed", source_record=raw)
    record.sink_payload()
    assert raw["BranchName"] == "Kuantan Branch"


# ── AC-14-42: source_ref = {book}:BR:{AccNo}:{BranchCode} ────────────────────


def _http_source(db, company, vendor, entity_type):
    from modules.autocount.http_source.source import HttpApiSource
    from modules.autocount.models import AcEntityConfig
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.sources import SourceContext

    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl="autocount_http", source_config={**_branch_raw(vendor.id), "lookups": []},
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    return HttpApiSource(
        ctx, entity_type=entity_type,
        transport=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))),
    )


def test_ac_14_42_source_ref_is_book_BR_accno_branchcode_verbatim(db):
    from modules.autocount.canonical.masters import ENTITY_BRANCH

    vendor = _vendor_connection(db)  # .../api/db1
    company = _company(db, vendor)
    source = _http_source(db, company, vendor, ENTITY_BRANCH)

    # Exactly the string the CRM derives: not upper-cased, not `|`-joined, not
    # prefixed with the AutoCount database name (`AED_SORENTO`).
    assert source.source_ref({"AccNo": "300-A056", "BranchCode": "KUANTAN"}) == "db1:BR:300-A056:KUANTAN"
    assert source.source_ref({"AccNo": "300-a056", "BranchCode": "Kuantan"}) == "db1:BR:300-a056:Kuantan"


def test_ac_14_42_book_is_the_last_path_segment_of_the_task_connection_base_url(db):
    from modules.autocount.canonical.masters import ENTITY_BRANCH

    vendor = _vendor_connection(db, base_url="https://hapi.sorento.cc.cd/api/db2")
    company = _company(db, vendor)
    source = _http_source(db, company, vendor, ENTITY_BRANCH)
    assert source.source_ref({"AccNo": "300-A056", "BranchCode": "KUANTAN"}) == "db2:BR:300-A056:KUANTAN"


def test_ac_14_42_other_entities_keep_the_company_qualified_ref_control(db):
    """Control: the book-qualified branch identity must not leak into `product`."""
    from modules.autocount.canonical.masters import ENTITY_PRODUCT

    vendor = _vendor_connection(db)
    company = _company(db, vendor)
    source = _http_source(db, company, vendor, ENTITY_PRODUCT)
    source.key_fields = ["ItemCode"]
    assert source.source_ref({"ItemCode": "SRT-01"}) == "AED_SORENTO:SRT-01"


def test_ac_14_41_ac_14_42_ac_14_43_a_full_run_walks_pages_and_pushes_the_raw_rows(wired, monkeypatch):
    """The whole chain in one run: page walk (`page`/`pageSize` on
    `/branchbypage`), mapped -> staged with the CRM-shaped `source_ref`, pushed
    to `/ingest/branches` with top-level `companyCode` + `book` and the raw rows."""
    from modules.autocount.canonical.masters import ENTITY_BRANCH

    db, company, _vendor = wired
    seen: List[httpx.Request] = []
    rows = [dict(RAW_ROW), {**RAW_ROW, "AccNo": "300-B001", "BranchCode": "HQ", "BranchName": "Head Office"}]
    _stub_vendor_client(monkeypatch, _paged_vendor(rows, seen))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _echo_ingest_handler(posts))

    job = _run_sync(db, company, ENTITY_BRANCH)

    assert seen and seen[0].url.path == "/api/db1/branchbypage"
    assert seen[0].url.params.get("page") == "1" and seen[0].url.params.get("pageSize")
    ingest = [p for p in posts if p.url.path.endswith("/api/v1/external/ingest/branches")]
    assert len(ingest) == 1, [p.url.path for p in posts]
    body = json.loads(ingest[0].content.decode("utf-8"))
    assert body["companyCode"] == "SRT" and body["book"] == "db1"
    assert sorted(body["records"], key=lambda r: r["AccNo"]) == sorted(rows, key=lambda r: r["AccNo"])
    staged = db.query(AcStagedRecord).filter(
        AcStagedRecord.company_id == company.id, AcStagedRecord.entity_type == ENTITY_BRANCH
    ).all()
    assert sorted(r.source_ref for r in staged) == ["db1:BR:300-A056:KUANTAN", "db1:BR:300-B001:HQ"]
    assert job.result_json.get("pushed") == 2, job.result_json


# ── AC-14-43: ingest body through the ETL SorentoSink ───────────────────────


def _gate_rig(db):
    vendor = _vendor_connection(db)
    sorento = _sorento_connection(db)
    return _company(db, vendor, sorento_conn=sorento)


def test_ac_14_43_ingest_body_carries_company_code_book_and_the_raw_record(db, monkeypatch):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import CompanyService

    company = _gate_rig(db)
    _open_contract(monkeypatch)
    calls: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _echo_ingest_handler(calls))

    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_BRANCH)
    assert isinstance(sink, SorentoSink)
    record = _branch()
    results = sink.write_batch([record], request_id="req-1")

    assert [c.url.path for c in calls] == ["/api/v1/external/ingest/branches"]
    body = json.loads(calls[0].content.decode("utf-8"))
    assert body["companyCode"] == "SRT"
    assert body["book"] == "db1"
    assert body["records"][0] == record.sink_payload() == RAW_ROW | {"BranchName": "Kuantan Branch"}
    assert results[0].delivered is True and results[0].outcome == "created"


def test_ac_14_43_verdicts_created_updated_unchanged_deliver_and_failed_surfaces_errors(db, monkeypatch):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import CompanyService

    company = _gate_rig(db)
    _open_contract(monkeypatch)
    records = [
        _branch(source_ref=f"db1:BR:A{i}:B{i}", acc_no=f"A{i}", code=f"B{i}", source_record={**RAW_ROW, "AccNo": f"A{i}", "BranchCode": f"B{i}"})
        for i in range(4)
    ]
    outcomes = ["created", "updated", "unchanged", "failed"]

    def handler(request: httpx.Request) -> httpx.Response:
        verdicts = []
        for record, outcome in zip(records, outcomes):
            verdict = {"source_ref": record.source_ref, "outcome": outcome}
            if outcome == "failed":
                verdict["errors"] = {"BranchName": "too long"}
            verdicts.append(verdict)
        return httpx.Response(200, json={"dry_run": False, "summary": {}, "records": verdicts})

    _inject_sink_transport(monkeypatch, handler)
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_BRANCH)
    results = sink.write_batch(records, request_id="req-1")

    assert [r.delivered for r in results] == [True, True, True, False]
    assert [r.outcome for r in results] == outcomes
    assert results[3].errors == {"BranchName": "too long"}


def test_ac_14_43_batches_stay_within_1000_records(db, monkeypatch):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import CompanyService

    company = _gate_rig(db)
    _open_contract(monkeypatch)
    calls: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _echo_ingest_handler(calls))
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_BRANCH)
    records = [
        _branch(source_ref=f"db1:BR:A{i}:B{i}", acc_no=f"A{i}", code=f"B{i}", source_record={**RAW_ROW, "AccNo": f"A{i}", "BranchCode": f"B{i}"})
        for i in range(1001)
    ]
    sink.write_batch(records, request_id="req-1")

    sizes = [len(json.loads(c.content.decode("utf-8"))["records"]) for c in calls]
    assert sum(sizes) == 1001
    assert max(sizes) <= 1000


# ── AC-14-44: contract gate at 2.7 + `branches` ─────────────────────────────


def test_ac_14_44_supports_branch_false_below_2_7_and_true_at_2_7_with_branches():
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.sinks_sorento import sorento_supports_entity

    assert sorento_supports_entity(
        ENTITY_BRANCH, contract_version=2.6, contract_entities=["suppliers", "delivery_orders"]
    ) is False
    # The version boundary by behaviour: 2.6 is refused even when it lists `branches`.
    assert sorento_supports_entity(
        ENTITY_BRANCH, contract_version=2.6, contract_entities=["branches"]
    ) is False
    assert sorento_supports_entity(
        ENTITY_BRANCH, contract_version=2.7, contract_entities=["suppliers", "delivery_orders", "branches"]
    ) is True
    # Version alone is not enough: the consumer must advertise `branches`.
    assert sorento_supports_entity(
        ENTITY_BRANCH, contract_version=2.7, contract_entities=["delivery_orders"]
    ) is False


def test_ac_14_44_entity_path_and_gate_table_rows():
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.sinks_sorento import CONTRACT_GATED_ENTITIES, _ENTITY_PATH

    assert _ENTITY_PATH[ENTITY_BRANCH] == "branches"
    assert CONTRACT_GATED_ENTITIES[ENTITY_BRANCH] == (2.7, "branches")


def test_ac_14_44_sink_for_company_opens_on_2_7_and_falls_back_to_logging_on_2_6(db, monkeypatch):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import CompanyService

    company = _gate_rig(db)
    _open_contract(monkeypatch, version=2.7, entities=["branches"])
    assert isinstance(CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_BRANCH), SorentoSink)

    _open_contract(monkeypatch, version=2.6, entities=["suppliers"])
    assert CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_BRANCH).name == SINK_LOGGING


def test_ac_14_44_task_view_contract_gate_names_the_consumer_version(db, monkeypatch):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.services.etl_service import EtlService

    company = _gate_rig(db)
    assert CompanyService._CONTRACT_GATE_REQUIRED_VERSIONS[ENTITY_BRANCH] == 2.7

    _open_contract(monkeypatch, version=2.6, entities=["suppliers"])
    view = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH)
    assert view.contract_gate == {"entity": ENTITY_BRANCH, "version": 2.6, "requiredVersion": 2.7}

    _open_contract(monkeypatch, version=2.7, entities=["branches"])
    view = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH)
    assert view.contract_gate is None


def test_ac_14_44_supported_entities_label_never_claims_the_gated_branch():
    from modules.autocount.sinks_sorento import sorento_supported_entities_label

    assert "branch" not in sorento_supported_entities_label()


# ── AC-14-45: a vanished branch is never staged or posted as a delete ───────


def _seed_known_branch_hashes(db, company, refs: List[str]) -> None:
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.repositories import RowHashRepository

    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, {ref: "a" * 64 for ref in refs}, seen_at=None,
    )
    db.commit()


def _delete_rows(db, company) -> list:
    from modules.autocount.canonical.masters import ENTITY_BRANCH

    return db.query(AcStagedRecord).filter(
        AcStagedRecord.company_id == company.id, AcStagedRecord.entity_type == ENTITY_BRANCH,
        AcStagedRecord.op == STAGED_OP_DELETE,
    ).all()


def _spy_delete_batch(monkeypatch) -> List[Any]:
    calls: List[Any] = []

    def spy(self, refs, **kwargs):
        calls.append(list(refs))
        return {"records": []}

    monkeypatch.setattr(SorentoSink, "delete_batch", spy)
    return calls


def test_ac_14_45_a_vanished_branch_stages_no_delete_and_is_counted(wired, monkeypatch):
    from modules.autocount.canonical.masters import ENTITY_BRANCH

    db, company, _vendor = wired
    _seed_known_branch_hashes(db, company, ["db1:BR:300-A056:KUANTAN", "db1:BR:300-GONE:OLD"])
    _stub_vendor_client(monkeypatch, _paged_vendor([dict(RAW_ROW)], []))
    _open_contract(monkeypatch)
    posts: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _echo_ingest_handler(posts))
    deletes = _spy_delete_batch(monkeypatch)

    job = _run_sync(db, company, ENTITY_BRANCH)

    # Control: the run really ran and delivered the surviving branch.
    assert job.result_json.get("pushed") == 1, job.result_json
    assert _delete_rows(db, company) == []
    assert job.result_json.get("vanished") == 1, job.result_json
    assert deletes == [], "delete_batch must never be called for branch"
    assert not any("deletions" in p.url.path for p in posts)


def test_ac_14_45_the_delete_guard_does_not_trip_on_a_mass_disappearance(wired, monkeypatch):
    """60 known refs, 1 returned: for every other entity this trips the 20% / 50
    row guard (`delete_guard`); a branch has no delete step to guard."""
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.repositories import EntityConfigRepository

    db, company, _vendor = wired
    known = ["db1:BR:300-A056:KUANTAN"] + [f"db1:BR:GONE{i}:B{i}" for i in range(59)]
    _seed_known_branch_hashes(db, company, known)
    _stub_vendor_client(monkeypatch, _paged_vendor([dict(RAW_ROW)], []))
    _open_contract(monkeypatch)
    _inject_sink_transport(monkeypatch, _echo_ingest_handler([]))
    deletes = _spy_delete_batch(monkeypatch)

    job = _run_sync(db, company, ENTITY_BRANCH)

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH)
    assert config.last_run_error_code != "delete_guard", config.last_run_error_code
    assert job.result_json.get("vanished") == 59, job.result_json
    assert _delete_rows(db, company) == []
    assert deletes == []


def test_ac_14_45_control_a_vanished_product_still_stages_a_delete(db, monkeypatch):
    """The no-deletion rule is branch-only: a product task on the same rig still
    stages `op=delete` for a vanished ref (proves `_delete_rows` can see one)."""
    from modules.autocount.canonical.masters import ENTITY_PRODUCT
    from modules.autocount.repositories import RowHashRepository
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    company = _company(db, vendor)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, {
        **_branch_raw(vendor.id), "path": "/itembypage", "keyFields": ["ItemCode"],
    })
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, {"AED_SORENTO:GONE": "a" * 64}, seen_at=None,
    )
    db.commit()
    _stub_vendor_client(monkeypatch, _paged_vendor([{"ItemCode": "P1", "Description": "P1", "IsActive": "T"}], []))

    _run_sync(db, company, ENTITY_PRODUCT)

    deletes = db.query(AcStagedRecord).filter(
        AcStagedRecord.company_id == company.id, AcStagedRecord.op == STAGED_OP_DELETE
    ).all()
    assert [d.source_ref for d in deletes] == ["AED_SORENTO:GONE"]


# ── AC-14-40/41: accepted + required mapping fields, replace_mapping ────────


def test_ac_14_40_accepted_and_required_mapping_fields():
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.mapping_catalog import (
        accepted_field_names,
        required_field_names,
        sorento_field_for,
    )

    accepted = accepted_field_names(ENTITY_BRANCH)
    assert {"acc_no", "code", "name"} <= accepted
    assert "source_ref" not in accepted  # minted by the identity, never mapped
    required = required_field_names(ENTITY_BRANCH)
    assert {"acc_no", "code"} <= required
    assert "name" not in required
    assert sorento_field_for(ENTITY_BRANCH, "acc_no") == "acc_no"
    assert sorento_field_for(ENTITY_BRANCH, "code") == "code"
    assert sorento_field_for(ENTITY_BRANCH, "source_ref") is None


def test_ac_14_40_replace_mapping_accepts_the_branch_rows(db):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import CompanyService, MappingWriteRow
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    company = _company(db, vendor)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, _branch_raw(vendor.id))

    view = CompanyService(db).replace_mapping(
        DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH,
        [
            MappingWriteRow("AccNo", "string", "acc_no"),
            MappingWriteRow("BranchCode", "string", "code"),
            MappingWriteRow("BranchName", "string", "name"),
        ],
    )
    assert {row.sorento_field for row in view.rows if row.sorento_field} >= {"acc_no", "code", "name"}


# ── AC-14-41: first save seeds the preset, Reset returns the same rows ──────


def _header_rows(db, company_id: str):
    from modules.autocount.canonical.masters import ENTITY_BRANCH

    rows = (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.tenant_id == DEFAULT_TENANT_ID, AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == ENTITY_BRANCH, AcFieldMapping.scope == "header",
        )
        .order_by(AcFieldMapping.sort_order)
        .all()
    )
    return [
        (r.source_path, r.canonical_field, r.transform, r.formula, r.is_required, r.is_enabled, r.sort_order)
        for r in rows
    ]


def test_ac_14_41_first_save_seeds_the_preset_mapping_rows(db):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    company = _company(db, vendor)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, _branch_raw(vendor.id))

    rows = _header_rows(db, company.id)
    assert {(r[0], r[1]) for r in rows} == {("AccNo", "acc_no"), ("BranchCode", "code"), ("BranchName", "name")}
    by_field = {r[1]: r for r in rows}
    assert by_field["acc_no"][4] is True and by_field["code"][4] is True  # required
    assert all(r[5] for r in rows), "a first save seeds every row enabled"


def test_ac_14_41_reset_to_preset_returns_the_same_rows_as_the_seed(db):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    company = _company(db, vendor)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, _branch_raw(vendor.id))
    seeded = _header_rows(db, company.id)
    assert seeded, "control: the first save seeded rows"

    # Drift the mapping, then reset: the seed rows come back byte-for-byte.
    db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == company.id, AcFieldMapping.entity_type == ENTITY_BRANCH,
        AcFieldMapping.canonical_field == "name",
    ).update({"source_path": "Address1"})
    db.commit()
    assert _header_rows(db, company.id) != seeded

    CompanyService(db).reset_mapping_to_preset(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, dry_run=False)
    assert _header_rows(db, company.id) == seeded


def test_ac_14_41_presets_route_offers_the_branch_preset(client, db):
    from modules.autocount.canonical.masters import ENTITY_BRANCH

    vendor = _vendor_connection(db)
    company = _company(db, vendor)
    login = client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.get(f"/autocount/presets/{ENTITY_BRANCH}", params={"companyId": company.id}, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1, body
    assert body[0]["path"] == "/branchbypage"
    assert body[0]["keyFields"] == ["AccNo", "BranchCode"]


# ═══ review round 3 ═════════════════════════════════════════════════════════


def _sql_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="database", name="AED SQL",
        config_json={}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _sink_body_for(db, monkeypatch, company):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import CompanyService

    _open_contract(monkeypatch)
    calls: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _echo_ingest_handler(calls))
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_BRANCH)
    sink.write_batch([_branch()], request_id="r1")
    return json.loads(calls[0].content.decode("utf-8"))


def test_b1_a_db_company_with_an_http_branch_task_posts_the_task_connections_book(db, monkeypatch):
    """Scenario A (production shape): the company's own connection is SQL (no
    book); the Branch task reads hapi db1. The body must still carry book db1."""
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.etl_service import EtlService

    http = _vendor_connection(db)
    company = _company(db, _sql_connection(db), sorento_conn=_sorento_connection(db))
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, _branch_raw(http.id))
    assert _sink_body_for(db, monkeypatch, company)["book"] == "db1"


def test_b1_the_body_book_is_the_task_connections_even_when_the_company_is_on_another_book(db, monkeypatch):
    """Scenario B: an http company on db2 whose branch task points at db1. The
    body's book and the ref's book both come from the TASK connection."""
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.etl_service import EtlService

    db2 = _vendor_connection(db, base_url="https://hapi.sorento.cc.cd/api/db2")
    task_conn = _vendor_connection(db)  # db1
    company = _company(db, db2, sorento_conn=_sorento_connection(db))
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, _branch_raw(task_conn.id))
    assert _sink_body_for(db, monkeypatch, company)["book"] == "db1"


def test_b1_no_derivable_book_fails_closed_with_a_named_error_and_posts_nothing(db, monkeypatch):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import AutocountServiceError, CompanyService
    from modules.autocount.services.etl_service import EtlService

    bookless = _vendor_connection(db, base_url="https://hapi.sorento.cc.cd")
    company = _company(db, bookless, sorento_conn=_sorento_connection(db))
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, _branch_raw(bookless.id))
    _open_contract(monkeypatch)
    calls: List[httpx.Request] = []
    _inject_sink_transport(monkeypatch, _echo_ingest_handler(calls))

    with pytest.raises(AutocountServiceError) as exc_info:
        CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_BRANCH)
    assert "book" in str(exc_info.value)
    assert calls == []


# ── S1: the identity pair rows are locked to AccNo / BranchCode ─────────────


def _branch_company_with_task(db):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.etl_service import EtlService

    vendor = _vendor_connection(db)
    company = _company(db, vendor)
    EtlService(db).update_task(DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH, _branch_raw(vendor.id))
    return company


@pytest.mark.parametrize(
    "acc_row, code_row",
    [
        (("AccNo", "string", None, True), ("Address1", "string", None, True)),  # code repointed
        (("AccNo", "string", None, True), ("BranchCode", "int", None, True)),  # code transform
        # A formula the earlier formula guard ACCEPTS (a known function over the
        # column) - only the lock can refuse it.
        (("AccNo", "string", None, True), ("BranchCode", "string", "upper(BranchCode)", True)),
        (("Address1", "string", None, True), ("BranchCode", "string", None, True)),  # acc_no repointed
        (("AccNo", "string", None, False), ("BranchCode", "string", None, True)),  # acc_no disabled
        (("AccNo", "string", None, True), ("BranchCode", "string", None, False)),  # code disabled
    ],
)
def test_s1_changing_an_identity_row_is_refused_by_the_lock(db, acc_row, code_row):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import AutocountServiceError, CompanyService, MappingWriteRow

    company = _branch_company_with_task(db)
    with pytest.raises(AutocountServiceError) as exc_info:
        CompanyService(db).replace_mapping(
            DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH,
            [
                MappingWriteRow(acc_row[0], acc_row[1], "acc_no", formula=acc_row[2], is_enabled=acc_row[3]),
                MappingWriteRow(code_row[0], code_row[1], "code", formula=code_row[2], is_enabled=code_row[3]),
                MappingWriteRow("BranchName", "string", "name"),
            ],
        )
    assert "is fixed to" in str(exc_info.value)


def test_n6_the_locked_rows_seed_enabled_even_when_the_columns_are_not_known():
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.presets import HTTP_PRESETS, plan_rows

    planned = plan_rows(HTTP_PRESETS[ENTITY_BRANCH].rows, [], entity_type=ENTITY_BRANCH, scope="header")
    by_field = {p.spec.canonical_field: p for p in planned}
    assert by_field["acc_no"].is_enabled and by_field["code"].is_enabled
    assert not by_field["name"].is_enabled  # a free row still follows its column


def test_s1_the_name_row_stays_freely_mappable(db):
    from modules.autocount.canonical.masters import ENTITY_BRANCH
    from modules.autocount.services.company_service import CompanyService, MappingWriteRow

    company = _branch_company_with_task(db)
    view = CompanyService(db).replace_mapping(
        DEFAULT_TENANT_ID, company.id, ENTITY_BRANCH,
        [
            MappingWriteRow("AccNo", "string", "acc_no"),
            MappingWriteRow("BranchCode", "string", "code"),
            MappingWriteRow("Address1", "string", "name"),
        ],
    )
    assert {r.source_path for r in view.rows} >= {"Address1"}
