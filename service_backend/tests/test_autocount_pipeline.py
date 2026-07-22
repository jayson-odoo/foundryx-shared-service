"""AutoCount ESB — stage 2: the GRN read pipeline (AC-13-05..13, 41/42/43/46).

Every HTTP interaction is MOCKED. These tests never touch the live demo box.

The behaviours pinned here are the ones that would be expensive to discover in
production: a watermark advancing over data that failed, a silent null where a
coercion failed, half a GRN reaching a consumer, an approval pushing twice, one
company's documents surfacing under another, and an abort that the worker
overwrites.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx
import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    JOB_FAILED,
    JOB_NEEDS_REVIEW,
    BackgroundJob,
)
from app.models.connection import Connection
from app.models.integration_activity import IntegrationActivity
from app.secrets import encrypt_secret
from modules.autocount.canonical.grn import ENTITY_GOODS_RECEIVED_NOTE, CanonicalGrn
from modules.autocount.client import AutoCountClient, AutoCountError
from modules.autocount.mapping import (
    DEFAULT_GRN_MAPPING,
    MappingEngine,
    MappingRow,
    TransformError,
    resolve_path,
    t_bool,
    t_date,
    t_datetime,
    t_decimal,
)
from modules.autocount.models import (
    RUN_ABORTED,
    RUN_FAILED,
    STAGED,
    STAGED_DISCARDED,
    STAGED_FAILED,
    STAGED_PUSHED,
    AcCompany,
    AcFieldMapping,
    AcStagedRecord,
)
from modules.autocount.repositories import (
    CompanyRepository,
    StagedRecordRepository,
    SyncRunRepository,
    WatermarkRepository,
)
from modules.autocount.services import CompanyService, SyncService
from modules.autocount.sinks import LoggingSink, sink_for
from modules.autocount.sources import (
    AutoCountReadSource,
    TruncatedWindowError,
    Watermark,
)
from modules.autocount.sync import AUTOCOUNT_SYNC, compute_diff, run_autocount_sync

JWT = "eyJhbGciOi.header.signature"

OTHER_TENANT_ID = "tenant-other"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _login_body(database_name: str = "AED_VSOFT") -> List[Dict[str, Any]]:
    return [
        {
            "Token": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
            "JWTToken": JWT,
            "DatabaseName": database_name,
            "CompanyName": f"{database_name} Sdn Bhd",
        }
    ]


def _grn(
    doc_key: str = "1001",
    doc_no: str = "GRN-0001",
    *,
    last_modified: str = "2026/07/10 09:15:00",
    lines: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A GRN in the shapes the LIVE instance actually returns: string booleans,
    8-dp numeric strings, mixed numeric types, and the ``GRDTL`` detail key."""
    record = {
        "DocKey": doc_key,
        "DocNo": doc_no,
        "CreditorCode": "300-A001",
        "CompanyName": "Acme Supplies",
        "DocDate": "2026/07/09",
        "CurrencyCode": "MYR",
        "CurrencyRate": "1.00000000",
        "Description": "July delivery",
        "NetTotal": "1200.00000000",
        "TaxTotal": "72.00000000",
        "FinalTotal": "1272.00000000",
        "Cancelled": "F",
        "LastModified": last_modified,
        "LastModifiedUserID": "ADMIN",
        "CreatedTimeStamp": "2026/07/09 08:00:00",
        "CreatedUserID": "ADMIN",
        # GRN's detail key is GRDTL, NOT GRNDTL — and its detail casing is
        # ``DtlKey`` (DO's is ``Dtlkey``).
        "GRDTL": lines
        if lines is not None
        else [
            {
                "DtlKey": "9001",
                "ItemCode": "ITEM-1",
                "Description": "Widget",
                "Qty": "120.00000000",
                "UOM": "PCS",
                "UnitPrice": 10,  # int — the vendor mixes types for one field
                "SubTotal": "1200.00000000",
                "Tax": "72.00000000",
                "TaxRate": "6%",
                "Location": "HQ",
                "DeliveryDate": "2026-07-09",
            }
        ],
    }
    record.update(overrides)
    return record


class MockTransport:
    """An httpx.Client stand-in. Serves the login, then a queue of read bodies."""

    def __init__(self, reads: List[Any], *, database_name: str = "AED_VSOFT"):
        self.reads = list(reads)
        self.database_name = database_name
        self.requests: List[Dict[str, Any]] = []
        self.closed = False

    def post(self, url: str, *, headers=None, json=None, **_kw) -> httpx.Response:
        self.requests.append({"url": url, "headers": headers or {}, "json": json})
        if url.endswith("/api/Server/Login"):
            return httpx.Response(200, json=_login_body(self.database_name))
        body = self.reads.pop(0) if self.reads else []
        if isinstance(body, httpx.Response):
            return body
        return httpx.Response(200, json={"Status": "Success", "ResultTable": body})

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def transports(monkeypatch):
    """Route every client built from a connection through a scripted transport,
    keyed by connection id. Nothing in this suite opens a socket."""
    registry: Dict[str, MockTransport] = {}
    import modules.autocount.services.company_service as company_module

    real = company_module.client_from_connection

    def fake(config, credentials, *, transport=None):
        key = str(config.get("_connectionId") or "")
        return real(config, credentials, transport=transport or registry.get(key))

    monkeypatch.setattr(company_module, "client_from_connection", fake)
    return registry


def _connection(db, tenant_id: str = DEFAULT_TENANT_ID, name: str = "AutoCount") -> Connection:
    conn = Connection(
        tenant_id=tenant_id,
        provider="autocount",
        type="erp",
        name=name,
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(conn)
    db.flush()
    # The transport registry keys off this so a mock can be bound per connection.
    conn.config_json = {**conn.config_json, "_connectionId": conn.id}
    db.commit()
    return conn


def _company(
    db,
    transports,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    database_name: str = "AED_VSOFT",
    reads: Optional[List[Any]] = None,
) -> AcCompany:
    conn = _connection(db, tenant_id, name=f"AutoCount {database_name}")
    transports[conn.id] = MockTransport(reads or [], database_name=database_name)
    return CompanyService(db).create_from_connection(tenant_id, conn.id)


def _queue(db, transports, company: AcCompany, records: List[Any]) -> None:
    """Queue the next read response for a company's transport."""
    transports[company.connection_id].reads.append(records)


def _run_sync(
    db,
    company: AcCompany,
    tenant_id: str = DEFAULT_TENANT_ID,
    entity_type: str = ENTITY_GOODS_RECEIVED_NOTE,
) -> BackgroundJob:
    job = SyncService(db).sync_now(
        tenant_id, company.id, entity_type, actor_user_id=None
    )
    db.refresh(job)
    return job


# A company is seeded for SEVERAL entities since slice 2 (GRN + the two masters),
# so a positional ``[0]`` no longer means "the GRN one" — it means "whichever
# entity sorts first", which is a silent mis-target. Always name the entity.


def _config_for(db, company, entity_type: str, tenant_id: str = DEFAULT_TENANT_ID):
    return next(
        c
        for c in CompanyService(db).entity_configs(tenant_id, company.id)
        if c.entity_type == entity_type
    )


def _state_for(db, company, entity_type: str, tenant_id: str = DEFAULT_TENANT_ID):
    return next(
        s
        for s in CompanyService(db).entity_states(tenant_id, company.id)
        if s.entity_type == entity_type
    )


def _grn_config(db, company, tenant_id: str = DEFAULT_TENANT_ID):
    return _config_for(db, company, ENTITY_GOODS_RECEIVED_NOTE, tenant_id)


def _grn_state(db, company, tenant_id: str = DEFAULT_TENANT_ID):
    return _state_for(db, company, ENTITY_GOODS_RECEIVED_NOTE, tenant_id)


# ── mapping: coercion matrix (AC-13-09) ───────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [("T", True), ("F", False), ("true", True), ("N", False), (True, True), (0, False)],
)
def test_string_booleans_become_real_bools(value, expected):
    assert t_bool(value) is expected


def test_the_three_live_date_formats_all_parse():
    assert t_date("2023/12/01").isoformat() == "2023-12-01"
    assert t_datetime("2024/08/05 16:37:34").isoformat() == "2024-08-05T16:37:34+00:00"
    assert t_date("2024-09-15").isoformat() == "2024-09-15"


def test_datetimes_come_out_aware_utc():
    """House rule: a naive datetime anywhere poisons every later comparison."""
    assert t_datetime("2024/08/05 16:37:34").tzinfo is timezone.utc


def test_eight_dp_strings_and_mixed_numeric_types_both_become_decimal():
    assert t_decimal("120.00000000") == Decimal("120.00000000")
    assert t_decimal(2) == Decimal("2")  # the vendor sends int here…
    assert t_decimal("10") == Decimal("10")  # …and string there, for one field


def test_decimal_conversion_does_not_go_through_float():
    """0.1+0.2-style drift must never reach a financial figure."""
    assert str(t_decimal("0.10000000")) == "0.10000000"


@pytest.mark.parametrize(
    "fn,value",
    [
        (t_bool, "maybe"),
        (t_decimal, "twelve"),
        (t_date, "not-a-date"),
        (t_datetime, "31/12/2024"),
    ],
)
def test_an_unconvertible_value_raises_rather_than_returning_none(fn, value):
    with pytest.raises(TransformError):
        fn(value)


def test_a_blank_value_is_none_not_an_error():
    """Absent is not unconvertible — a required-but-blank field is caught by the
    mapping row's flag, so blanks must not raise here."""
    assert t_decimal("") is None
    assert t_bool(None) is None


def test_an_unconvertible_value_produces_a_named_per_field_error(db):
    """AC-13-09: a NAMED error, never a silent null. A silent null reads as
    'the customer left it blank' and lands in a document as zero."""
    engine = MappingEngine(list(DEFAULT_GRN_MAPPING))
    mapped = engine.map_document(_grn(Cancelled="maybe"))

    assert mapped.record is None  # nothing half-mapped exists
    assert [e.field for e in mapped.errors] == ["cancelled"]
    error = mapped.errors[0]
    assert error.source_path == "Cancelled"
    assert "GRN-0001" in error.message()
    assert "cancelled" in error.message()


def test_a_line_level_error_names_the_document_the_line_and_the_field(db):
    """AC-13-10: the failure must name document, line AND field."""
    lines = [
        {"DtlKey": "1", "ItemCode": "A", "Qty": "1.0"},
        {"DtlKey": "2", "ItemCode": "B", "Qty": "2.0"},
        {"DtlKey": "3", "ItemCode": "C", "Qty": "not-a-number"},
    ]
    mapped = MappingEngine(list(DEFAULT_GRN_MAPPING)).map_document(_grn(lines=lines))

    assert mapped.record is None
    assert len(mapped.errors) == 1
    error = mapped.errors[0]
    assert error.line_no == 3
    assert error.field == "qty"
    assert error.doc_no == "GRN-0001"
    assert "line 3" in error.message()


def test_the_grn_detail_key_is_grdtl_not_grndtl():
    """Getting this wrong yields a header with zero lines and NO error at all."""
    mapped = MappingEngine(list(DEFAULT_GRN_MAPPING)).map_document(_grn())
    assert len(mapped.record.lines) == 1

    wrong_key = _grn()
    wrong_key["GRNDTL"] = wrong_key.pop("GRDTL")
    assert MappingEngine(list(DEFAULT_GRN_MAPPING)).map_document(wrong_key).record.lines == []


def test_paths_are_matched_literally_so_casing_differences_survive():
    """GRN uses ``DtlKey``, DO uses ``Dtlkey``. Normalising would hide a real
    vendor difference; the mapping table must describe what the API returns."""
    record = _grn(lines=[{"Dtlkey": "9001", "ItemCode": "X"}])  # DO-style casing
    mapped = MappingEngine(list(DEFAULT_GRN_MAPPING)).map_document(record)
    assert mapped.record.lines[0].source_ref == ""  # DtlKey row did not match

    do_style = MappingEngine(
        [MappingRow("Dtlkey", "source_ref", "string", "line"), *DEFAULT_GRN_MAPPING]
    )
    assert do_style.map_document(record).record.lines[0].source_ref == "9001"


def test_header_and_all_lines_come_from_one_record(db):
    """AC-13-06: no per-document fan-out; lines nest under the header."""
    lines = [
        {"DtlKey": str(i), "ItemCode": f"ITEM-{i}", "Qty": "1.0"} for i in range(1, 6)
    ]
    mapped = MappingEngine(list(DEFAULT_GRN_MAPPING)).map_document(_grn(lines=lines))
    assert len(mapped.record.lines) == 5
    assert [line.line_no for line in mapped.record.lines] == [1, 2, 3, 4, 5]


# ── mapping IS data (AC-13-08) ────────────────────────────────────────────────


def test_udf_path_extraction_reads_a_per_customer_array():
    record = _grn(
        lines=[
            {
                "DtlKey": "1",
                "ItemCode": "A",
                "UDFDetail": [
                    {"FieldName": "DriverName", "FieldName2": "", "Value": "Ali"}
                ],
            }
        ]
    )
    assert resolve_path(record["GRDTL"][0], "UDF[UDFDetail].DriverName") == "Ali"


def test_adding_a_mapping_row_makes_a_udf_flow_with_no_code_change(db, transports):
    """AC-13-08, half one: the value does not flow, a ROW is added, it flows."""
    company = _company(db, transports)
    record = _grn(
        lines=[
            {
                "DtlKey": "1",
                "ItemCode": "A",
                "Qty": "1.0",
                "UDFDetail": [{"FieldName": "DriverName", "Value": "Ali"}],
            }
        ]
    )

    service = CompanyService(db)
    rows = service.mapping_rows(DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE)
    before = MappingEngine(rows).map_document(record)
    assert "driverName" not in before.record.lines[0].extras

    # A ROW — this is the entire change. No Python was edited.
    db.add(
        AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID,
            company_id=company.id,
            entity_type=ENTITY_GOODS_RECEIVED_NOTE,
            scope="line",
            source_path="UDF[UDFDetail].DriverName",
            canonical_field="driverName",
            transform="string",
        )
    )
    db.commit()

    after_rows = service.mapping_rows(
        DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE
    )
    after = MappingEngine(after_rows).map_document(record)
    assert after.record.lines[0].extras["driverName"] == "Ali"


def test_removing_a_mapping_row_stops_a_field_flowing_with_no_code_change(db, transports):
    """AC-13-08, half two. Removal must be as configurable as addition."""
    company = _company(db, transports)
    service = CompanyService(db)
    record = _grn()

    assert MappingEngine(
        service.mapping_rows(DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE)
    ).map_document(record).record.supplier_code == "300-A001"

    db.query(AcFieldMapping).filter(
        AcFieldMapping.tenant_id == DEFAULT_TENANT_ID,
        AcFieldMapping.company_id == company.id,
        AcFieldMapping.canonical_field == "supplier_code",
    ).delete()
    db.commit()

    assert MappingEngine(
        service.mapping_rows(DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE)
    ).map_document(record).record.supplier_code is None


def test_a_required_mapping_row_turns_an_absent_field_into_a_named_error():
    engine = MappingEngine(
        [
            *DEFAULT_GRN_MAPPING,
            MappingRow("PurchaseAgent", "agent", "string", "header", is_required=True),
        ]
    )
    mapped = engine.map_document(_grn())
    assert mapped.record is None
    assert mapped.errors[0].field == "agent"


def test_seeded_mapping_rows_are_the_db_not_the_constant(db, transports):
    """After seeding, the DATABASE is the source of truth (D5) — there is no
    fallback to DEFAULT_MAPPINGS, so deleting every row maps nothing rather than
    quietly resuming built-in behaviour the operator removed."""
    company = _company(db, transports)
    db.query(AcFieldMapping).filter(AcFieldMapping.company_id == company.id).delete()
    db.commit()

    rows = CompanyService(db).mapping_rows(
        DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE
    )
    assert rows == []
    mapped = MappingEngine(rows).map_document(_grn())
    assert mapped.record is not None
    assert mapped.record.doc_no is None  # nothing mapped, and no silent default


# ── company discovery + scoping ───────────────────────────────────────────────


def test_a_company_is_discovered_from_the_login_response(db, transports):
    company = _company(db, transports, database_name="AED_VSOFT")
    assert company.database_name == "AED_VSOFT"  # never typed by an operator
    assert company.company_name == "AED_VSOFT Sdn Bhd"


def test_a_second_company_for_the_same_tenant_is_accepted(db, transports):
    """D16: one connection per AppId, several companies per tenant."""
    first = _company(db, transports, database_name="AED_VSOFT")
    second = _company(db, transports, database_name="AED_OTHER")
    assert first.id != second.id


def test_the_same_company_cannot_be_connected_twice(db, transports):
    """``ac_company (tenant_id, database_name)`` is the real identity guard —
    two rows for one company would each hold a watermark and double-deliver."""
    from modules.autocount.services import CompanyAlreadyExists

    _company(db, transports, database_name="AED_VSOFT")
    conn = _connection(db, name="dupe")
    transports[conn.id] = MockTransport([], database_name="AED_VSOFT")
    with pytest.raises(CompanyAlreadyExists):
        CompanyService(db).create_from_connection(DEFAULT_TENANT_ID, conn.id)


def test_another_tenants_company_is_invisible(db, transports):
    """AC-13-41 — cross-tenant leakage is a critical defect."""
    mine = _company(db, transports, database_name="AED_MINE")
    theirs = AcCompany(
        tenant_id=OTHER_TENANT_ID,
        connection_id="conn-other",
        database_name="AED_THEIRS",
        company_name="Theirs",
        name="Theirs",
    )
    db.add(theirs)
    db.commit()

    repo = CompanyRepository(db)
    assert repo.get(DEFAULT_TENANT_ID, theirs.id) is None
    rows, total = repo.list(DEFAULT_TENANT_ID)
    assert [row.id for row in rows] == [mine.id] and total == 1


def test_staged_records_are_scoped_by_company_not_just_tenant(db, transports):
    """One tenant, two companies: company A must never see company B's rows."""
    company_a = _company(db, transports, database_name="AED_A")
    company_b = _company(db, transports, database_name="AED_B")
    for company, ref in ((company_a, "A1"), (company_b, "B1")):
        db.add(
            AcStagedRecord(
                tenant_id=DEFAULT_TENANT_ID,
                company_id=company.id,
                entity_type=ENTITY_GOODS_RECEIVED_NOTE,
                job_id="job-1",
                source_ref=ref,
                status=STAGED,
            )
        )
    db.commit()

    repo = StagedRecordRepository(db)
    assert [r.source_ref for r in repo.list_for_job(DEFAULT_TENANT_ID, company_a.id, "job-1")] == ["A1"]
    assert [r.source_ref for r in repo.list_for_job(DEFAULT_TENANT_ID, company_b.id, "job-1")] == ["B1"]


def test_watermarks_are_per_company(db, transports):
    company_a = _company(db, transports, database_name="AED_A")
    company_b = _company(db, transports, database_name="AED_B")
    repo = WatermarkRepository(db)
    a = repo.get_or_create(DEFAULT_TENANT_ID, company_a.id, ENTITY_GOODS_RECEIVED_NOTE)
    a.last_modified_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    db.commit()

    b = repo.get_or_create(DEFAULT_TENANT_ID, company_b.id, ENTITY_GOODS_RECEIVED_NOTE)
    assert b.last_modified_at is None  # a sibling company's progress is not ours


# ── the fetch seam ────────────────────────────────────────────────────────────


def _source(reads, *, record_cap: int = 200) -> AutoCountReadSource:
    client = AutoCountClient(
        base_url="https://ac.example.com",
        app_id="app-1",
        user_id="ADMIN",
        password="secret",
        transport=MockTransport(reads),
    )
    return AutoCountReadSource(
        client, entity_type=ENTITY_GOODS_RECEIVED_NOTE, record_cap=record_cap
    )


def test_the_fetch_sends_last_modified_from_and_to(db):
    """AC-13-05 — the delta driver, verified live to genuinely filter."""
    source = _source([[_grn()]])
    source.fetch_changes(Watermark(last_modified_at=datetime(2026, 7, 1, tzinfo=timezone.utc)))

    read = source.client._transport.requests[-1]
    assert read["url"].endswith("/api/GoodsReceivedNote/GetGoodsReceivedNote")
    assert read["json"]["LastModifiedFrom"] == "2026/07/01"
    assert "LastModifiedTo" in read["json"]
    assert isinstance(read["json"]["DocNo"], list)  # scalar = silent full scan


def test_a_missing_watermark_uses_a_bounded_lookback_never_everything(db):
    """An unbounded first fetch is guaranteed to hit the cap on a real customer;
    the full initial load is a separate supervised problem (D20)."""
    source = _source([[]])
    start, end = source.window(Watermark())
    assert timedelta(days=29) < (end - start) < timedelta(days=31)


def test_the_max_last_modified_is_reported_for_the_watermark(db):
    source = _source(
        [[_grn("1", last_modified="2026/07/10 09:15:00"),
          _grn("2", last_modified="2026/07/12 11:00:00")]]
    )
    result = source.fetch_changes(Watermark(last_modified_at=datetime(2026, 7, 1, tzinfo=timezone.utc)))
    assert result.max_last_modified == datetime(2026, 7, 12, 11, 0, tzinfo=timezone.utc)


def test_hitting_the_record_cap_fails_loudly(db, caplog):
    """AC-13-46 / AC-13-17: ``len == cap`` is the ONLY truncation signal — the
    response's "N of TOTAL" marker is computed POST-cap and is not a total.
    Silent truncation is the failure mode this exists to prevent."""
    records = [_grn(str(i)) for i in range(5)]
    source = _source([records], record_cap=5)
    with pytest.raises(TruncatedWindowError) as exc:
        source.fetch_changes(Watermark(last_modified_at=datetime(2026, 7, 1, tzinfo=timezone.utc)))
    assert "record cap" in str(exc.value)
    assert "watermark was not advanced" in str(exc.value)


def test_a_full_page_is_never_returned_as_a_complete_result(db):
    """Under the cap = trusted; at the cap = refused. No middle ground."""
    source = _source([[_grn(str(i)) for i in range(4)]], record_cap=5)
    assert len(source.fetch_changes(Watermark()).records) == 4


# ── the job handler: staging + the approval gate ──────────────────────────────


def test_a_sync_stages_records_and_holds_for_review(db, transports):
    """AC-13-11: the job reaches ``needs_review`` and NOTHING is pushed."""
    company = _company(db, transports, reads=[[_grn("1"), _grn("2"), _grn("3")]])
    job = _run_sync(db, company)

    assert job.status == JOB_NEEDS_REVIEW
    rows = StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert len(rows) == 3
    assert {row.status for row in rows} == {STAGED}
    assert all(row.pushed_at is None for row in rows)


def test_a_needs_review_job_is_never_pruned(db, transports):
    """The gate only works because the pruner treats ``needs_review`` as
    non-terminal (plan §5 — reuse, don't rebuild)."""
    from app.jobs.service import JobService

    company = _company(db, transports, reads=[[_grn("1")]])
    job = _run_sync(db, company)
    job.finished_at = datetime.now(timezone.utc) - timedelta(days=3650)
    db.commit()

    JobService(db).prune(now=datetime.now(timezone.utc))
    assert db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first() is not None


def test_the_raw_payload_is_retained_with_the_canonical_record(db, transports):
    """AC-13-07: retained so a field discovered later can be mapped
    retroactively — re-fetching history is exactly what this API makes hard."""
    company = _company(db, transports, reads=[[_grn("1")]])
    job = _run_sync(db, company)

    row = StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id)[0]
    assert row.raw_json["GRDTL"][0]["DtlKey"] == "9001"
    assert row.raw_json["Cancelled"] == "F"  # verbatim, pre-coercion
    assert row.canonical_json["cancelled"] is False  # coerced alongside it


def test_the_canonical_record_round_trips_out_of_storage(db, transports):
    company = _company(db, transports, reads=[[_grn("1")]])
    job = _run_sync(db, company)
    row = StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id)[0]

    record = CanonicalGrn(**row.canonical_json)
    assert record.source_ref == "1"
    assert record.lines[0].qty == Decimal("120.00000000")
    assert record.source_system == "autocount"


# ── per-document atomicity (AC-13-10 / D13) ───────────────────────────────────


def test_a_failing_line_kills_only_its_own_document(db, transports):
    """AC-13-10: no part of the bad GRN is pushable; siblings are unaffected."""
    bad = _grn(
        "2",
        "GRN-0002",
        lines=[
            {"DtlKey": "1", "ItemCode": "A", "Qty": "1.0"},
            {"DtlKey": "2", "ItemCode": "B", "Qty": "2.0"},
            {"DtlKey": "3", "ItemCode": "C", "Qty": "oops"},
        ],
    )
    company = _company(db, transports, reads=[[_grn("1"), bad, _grn("3")]])
    job = _run_sync(db, company)

    rows = {
        row.source_ref: row
        for row in StagedRecordRepository(db).list_for_job(
            DEFAULT_TENANT_ID, company.id, job.id
        )
    }
    assert rows["1"].status == STAGED and rows["3"].status == STAGED
    failed = rows["2"]
    assert failed.status == STAGED_FAILED
    # No half-record exists to push by accident.
    assert failed.canonical_json is None
    assert "line 3" in failed.error and "qty" in failed.error


def test_a_failed_document_is_not_pushed_on_approval(db, transports):
    bad = _grn("2", lines=[{"DtlKey": "1", "Qty": "oops"}])
    company = _company(db, transports, reads=[[_grn("1"), bad]])
    job = _run_sync(db, company)

    result = SyncService(db).approve(DEFAULT_TENANT_ID, job.id)
    assert result["pushed"] == 1  # only the clean document

    rows = {
        r.source_ref: r.status
        for r in StagedRecordRepository(db).list_for_job(
            DEFAULT_TENANT_ID, company.id, job.id
        )
    }
    assert rows == {"1": STAGED_PUSHED, "2": STAGED_FAILED}


# ── watermark advance / hold (AC-13-05, D18) ──────────────────────────────────


def test_the_watermark_advances_on_a_clean_batch(db, transports):
    company = _company(
        db,
        transports,
        reads=[[_grn("1", last_modified="2026/07/10 09:15:00"),
                _grn("2", last_modified="2026/07/12 11:00:00")]],
    )
    _run_sync(db, company)

    watermark = WatermarkRepository(db).get(
        DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE
    )
    assert watermark.last_modified_at == datetime(2026, 7, 12, 11, 0, tzinfo=timezone.utc)
    assert watermark.consecutive_failures == 0


def test_the_watermark_holds_when_any_document_fails(db, transports):
    """D18: re-reading a window is cheap and idempotent; skipping one loses a
    document silently and nobody finds out for months."""
    bad = _grn("2", lines=[{"DtlKey": "1", "Qty": "oops"}])
    company = _company(db, transports, reads=[[_grn("1"), bad]])
    _run_sync(db, company)

    watermark = WatermarkRepository(db).get(
        DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE
    )
    assert watermark.last_modified_at is None  # HELD
    assert "watermark held" in (watermark.last_error or "")


def test_a_vendor_error_is_not_flagged_as_a_truncation(db, transports):
    """``run.truncated`` tells an operator to narrow the window. Setting it for
    every vendor error would make the signal meaningless."""
    company = _company(db, transports)
    transports[company.connection_id].reads.append(
        httpx.Response(200, json={"Status": "Fail", "Message": "Nope", "ResultTable": []})
    )
    job = _run_sync(db, company)
    run = SyncRunRepository(db).get_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert run.outcome == RUN_FAILED and run.truncated is False


def test_the_watermark_holds_when_the_fetch_fails(db, transports):
    company = _company(db, transports)
    transports[company.connection_id].reads.append(
        httpx.Response(200, json={"Status": "Fail", "Message": "Bad filter", "ResultTable": []})
    )
    job = _run_sync(db, company)

    assert job.status == JOB_FAILED
    watermark = WatermarkRepository(db).get(
        DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE
    )
    assert watermark.last_modified_at is None
    assert watermark.consecutive_failures == 1
    run = SyncRunRepository(db).get_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert run.outcome == RUN_FAILED


def test_a_truncated_fetch_fails_the_run_and_holds_the_watermark(db, transports):
    """AC-13-46 — a truncated sync must never read as a complete one."""
    company = _company(db, transports)
    config = _grn_config(db, company)
    config.record_cap = 2
    db.commit()
    _queue(db, transports, company, [_grn("1"), _grn("2")])

    job = _run_sync(db, company)
    assert job.status == JOB_FAILED
    assert "record cap" in (job.error or "")
    run = SyncRunRepository(db).get_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert run.truncated is True
    assert (
        WatermarkRepository(db)
        .get(DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE)
        .last_modified_at
        is None
    )


def test_a_later_sync_starts_from_the_watermark(db, transports):
    company = _company(db, transports, reads=[[_grn("1", last_modified="2026/07/12 11:00:00")]])
    _run_sync(db, company)
    SyncService(db).approve(DEFAULT_TENANT_ID, _latest_job(db).id)

    _queue(db, transports, company, [])
    _run_sync(db, company)

    read = transports[company.connection_id].requests[-1]
    assert read["json"]["LastModifiedFrom"] == "2026/07/12"


def _latest_job(db) -> BackgroundJob:
    return (
        db.query(BackgroundJob)
        .filter(BackgroundJob.type == AUTOCOUNT_SYNC)
        .order_by(BackgroundJob.created_at.desc())
        .first()
    )


# ── diffs (AC-13-12) ──────────────────────────────────────────────────────────


def test_a_diff_reports_only_changed_fields():
    before = {"docNo": "GRN-1", "total": "100", "supplierCode": "A"}
    after = {"docNo": "GRN-1", "total": "120", "supplierCode": "A"}
    assert compute_diff(before, after) == {"total": {"from": "100", "to": "120"}}


def test_a_first_sight_record_is_marked_new_not_diffed_field_by_field():
    assert compute_diff(None, {"docNo": "GRN-1"}) == {"__new__": True}


def test_the_diff_hides_the_timestamp_that_changes_on_every_fetch():
    """``last_modified`` moving is the REASON the record came back, so listing
    it as a change is tautological noise in every single diff — and noise is
    what turns review into rubber-stamping."""
    before = {"total": "100", "last_modified": "2026-07-10T09:15:00Z"}
    after = {"total": "100", "last_modified": "2026-07-15T09:00:00Z"}
    assert compute_diff(before, after) == {}


def test_a_resynced_document_diffs_against_the_last_pushed_version(db, transports):
    company = _company(db, transports, reads=[[_grn("1", FinalTotal="1272.00000000")]])
    first = _run_sync(db, company)
    SyncService(db).approve(DEFAULT_TENANT_ID, first.id)

    _queue(db, transports, company, [_grn("1", FinalTotal="1500.00000000",
                                           last_modified="2026/07/15 09:00:00")])
    second = _run_sync(db, company)

    row = [
        r
        for r in StagedRecordRepository(db).list_for_job(
            DEFAULT_TENANT_ID, company.id, second.id
        )
    ][0]
    assert row.diff_json == {"total": {"from": "1272.00000000", "to": "1500.00000000"}}


# ── approval (AC-13-13) ───────────────────────────────────────────────────────


def test_approval_pushes_the_staged_records_once(db, transports):
    company = _company(db, transports, reads=[[_grn("1"), _grn("2")]])
    job = _run_sync(db, company)

    result = SyncService(db).approve(DEFAULT_TENANT_ID, job.id, actor_user_id="u1")
    db.refresh(job)

    assert result["pushed"] == 2
    assert job.status == JOB_DONE
    rows = StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert {row.status for row in rows} == {STAGED_PUSHED}
    assert all(row.pushed_at is not None for row in rows)


def test_approving_twice_pushes_exactly_once(db, transports):
    """AC-13-13: double-click / retry / replay. The second call is a NO-OP that
    returns the original result — an error on the second click of a successful
    action is its own kind of bug."""
    company = _company(db, transports, reads=[[_grn("1"), _grn("2")]])
    job = _run_sync(db, company)
    service = SyncService(db)

    first = service.approve(DEFAULT_TENANT_ID, job.id)
    second = service.approve(DEFAULT_TENANT_ID, job.id)

    assert first["pushed"] == 2
    assert second == first  # identical, and nothing was pushed again
    assert (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.job_id == job.id, AcStagedRecord.status == STAGED_PUSHED
        )
        .count()
        == 2
    )


def test_the_second_approval_does_not_re_enter_the_sink(db, transports, monkeypatch):
    """Belt to the claim's braces: prove the sink is not called a second time."""
    calls: List[str] = []

    class CountingSink(LoggingSink):
        def write(self, record, *, request_id):
            calls.append(request_id)
            return super().write(record, request_id=request_id)

    import modules.autocount.sinks as sinks_module

    monkeypatch.setitem(sinks_module._SINKS, sinks_module.SINK_LOGGING, CountingSink)

    company = _company(db, transports, reads=[[_grn("1")]])
    job = _run_sync(db, company)
    service = SyncService(db)
    service.approve(DEFAULT_TENANT_ID, job.id)
    service.approve(DEFAULT_TENANT_ID, job.id)

    assert len(calls) == 1


def test_approving_a_job_that_is_not_in_review_is_a_clean_conflict(db, transports):
    from modules.autocount.services import NotAwaitingApproval

    company = _company(db, transports, reads=[[_grn("1")]])
    job = _run_sync(db, company)
    service = SyncService(db)
    service.approve(DEFAULT_TENANT_ID, job.id)
    service.discard(DEFAULT_TENANT_ID, job.id)  # already done → returns result

    job.status = JOB_FAILED
    db.commit()
    with pytest.raises(NotAwaitingApproval):
        service.approve(DEFAULT_TENANT_ID, job.id)


def test_discard_closes_the_job_without_pushing(db, transports):
    company = _company(db, transports, reads=[[_grn("1"), _grn("2")]])
    job = _run_sync(db, company)

    result = SyncService(db).discard(DEFAULT_TENANT_ID, job.id, actor_user_id="u1")
    db.refresh(job)

    assert result["pushed"] == 0 and result["discarded"] == 2
    assert job.status == JOB_DONE
    rows = StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    # Marked, never deleted — the raw payloads stay for audit (AC-13-07).
    assert {row.status for row in rows} == {STAGED_DISCARDED}
    assert all(row.raw_json for row in rows)


def test_a_job_from_another_tenant_is_not_reachable(db, transports):
    """AC-13-41 — the job id alone must not be a capability."""
    from modules.autocount.services import JobNotFound

    company = _company(db, transports, reads=[[_grn("1")]])
    job = _run_sync(db, company)
    with pytest.raises(JobNotFound):
        SyncService(db).approve(OTHER_TENANT_ID, job.id)


def test_a_non_autocount_job_cannot_be_steered_into_this_service(db):
    from modules.autocount.services import JobNotFound

    foreign = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="storage_migration", status=JOB_NEEDS_REVIEW
    )
    db.add(foreign)
    db.commit()
    with pytest.raises(JobNotFound):
        SyncService(db).approve(DEFAULT_TENANT_ID, foreign.id)


# ── the slice-1 sink is a tagged seam, not a consumer ─────────────────────────


def test_the_slice_one_sink_reports_that_it_delivered_nothing(db, transports):
    """The Definition-of-Done gate: a mock left standing as "done" is debt. This
    sink must never let an approved batch look delivered."""
    company = _company(db, transports, reads=[[_grn("1")]])
    job = _run_sync(db, company)
    result = SyncService(db).approve(DEFAULT_TENANT_ID, job.id)

    assert result["delivered"] is False
    assert result["sink"] == "logging"
    assert "no consumer is wired" in result["sinkNote"]


def test_the_sink_write_result_is_explicit_about_not_delivering():
    sink = sink_for("logging")
    outcome = sink.write(
        CanonicalGrn(source_ref="1", doc_no="GRN-1"), request_id="job:row"
    )
    assert outcome.ok is True and outcome.delivered is False


def test_an_unregistered_sink_is_a_loud_error_not_a_fallback(db):
    """Falling back to the logging sink would silently stop delivering to a real
    consumer — the worst possible failure for an integration."""
    from modules.autocount.sinks import UnknownSinkImpl

    with pytest.raises(UnknownSinkImpl):
        sink_for("sorento")


def test_an_unregistered_source_impl_is_a_loud_error(db, transports):
    company = _company(db, transports, reads=[[_grn("1")]])
    config = _grn_config(db, company)
    config.source_impl = "does_not_exist"
    db.commit()

    job = _run_sync(db, company)
    assert job.status == JOB_FAILED


# ── cooperative abort (real interleave) ───────────────────────────────────────


def test_abort_committed_mid_run_is_not_overwritten(db, session_factory, transports):
    """AC-13-21 with a REAL interleave.

    Eager mode runs the handler INLINE, so an abort-doesn't-stop-the-worker bug
    is invisible unless the abort is committed on ANOTHER session while the
    handler holds a stale ``job`` object saying ``running``. The handler must
    re-read its own status FRESH before the terminal step.
    """
    company = _company(db, transports)
    job = SyncService(db).jobs.create(
        type=AUTOCOUNT_SYNC,
        tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_GOODS_RECEIVED_NOTE},
    )

    aborting = session_factory()
    transport = transports[company.connection_id]
    original_post = transport.post

    def post_then_abort(url, **kwargs):
        response = original_post(url, **kwargs)
        if url.endswith("GetGoodsReceivedNote"):
            # The operator hits Abort while the (slow) fetch is in flight — a
            # DIFFERENT session commits the terminal status.
            aborting.query(BackgroundJob).filter(BackgroundJob.id == job.id).update(
                {BackgroundJob.status: JOB_ABORTED}, synchronize_session=False
            )
            aborting.commit()
        return response

    transport.post = post_then_abort
    transport.reads.append([_grn("1"), _grn("2")])

    run_autocount_sync(db, job)
    aborting.close()

    fresh = db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    assert fresh.status == JOB_ABORTED  # never overwritten to needs_review/done
    run = SyncRunRepository(db).get_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert run.outcome == RUN_ABORTED
    # Nothing staged and the watermark held — only fully-committed work counts.
    assert StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id) == []
    assert (
        WatermarkRepository(db)
        .get(DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE)
        .last_modified_at
        is None
    )


# ── observability + secrets (AC-13-42, AC-13-43) ──────────────────────────────


def test_a_sync_writes_masked_activity_under_the_autocount_source(db, transports):
    company = _company(db, transports, reads=[[_grn("1")]])
    _run_sync(db, company)

    rows = (
        db.query(IntegrationActivity)
        .filter(
            IntegrationActivity.tenant_id == DEFAULT_TENANT_ID,
            IntegrationActivity.source == "autocount",
        )
        .all()
    )
    assert rows, "the ESB's calls must render in the Developer Logs console"
    blob = " ".join(str(row.request_summary_json) + str(row.response_summary_json) for row in rows)
    assert "secret" not in blob and JWT not in blob and "app-1" not in blob


def test_no_stored_row_or_result_ever_carries_a_credential(db, transports):
    """AC-13-42 — AppId, Password and Token never appear in plaintext anywhere."""
    company = _company(db, transports, reads=[[_grn("1")]])
    job = _run_sync(db, company)
    result = SyncService(db).approve(DEFAULT_TENANT_ID, job.id)

    haystack = " ".join(
        [
            str(result),
            str(job.result_json),
            str(job.logs_json),
            str([r.raw_json for r in StagedRecordRepository(db).list_for_job(
                DEFAULT_TENANT_ID, company.id, job.id)]),
        ]
    )
    assert "secret" not in haystack
    assert JWT not in haystack


def test_a_handler_crash_never_propagates_to_the_caller(db, transports, monkeypatch):
    """AC-13-43 — a sync failure must never break the triggering request."""
    from app.jobs.service import run_job

    company = _company(db, transports)

    def boom(*_a, **_kw):
        raise RuntimeError("vendor exploded")

    monkeypatch.setattr(
        "modules.autocount.repositories.CompanyRepository.get", boom
    )
    job = SyncService(db).jobs.create(
        type=AUTOCOUNT_SYNC,
        tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_GOODS_RECEIVED_NOTE},
    )
    run_job(db, job.id)  # must NOT raise

    fresh = db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    assert fresh.status == JOB_FAILED
    assert "vendor exploded" in (fresh.error or "")


# ── module hygiene (AC-13-45) ─────────────────────────────────────────────────


def test_every_module_table_carries_tenant_and_company(db):
    """AC-13-41, structurally. ``ac_company``'s own id IS the company id."""
    from modules.autocount.db import AutocountBase

    for table in AutocountBase.metadata.sorted_tables:
        assert "tenant_id" in table.c, table.name
        if table.name != "ac_company":
            assert "company_id" in table.c, table.name


def test_uninstall_wipes_only_this_tenants_rows(db, transports):
    from modules.autocount import bootstrap

    _company(db, transports, database_name="AED_MINE")
    theirs = AcCompany(
        tenant_id=OTHER_TENANT_ID,
        connection_id="c",
        database_name="AED_THEIRS",
        company_name="T",
        name="T",
    )
    db.add(theirs)
    db.commit()

    bootstrap.uninstall_tenant(db, DEFAULT_TENANT_ID)
    db.commit()

    remaining = db.query(AcCompany).all()
    assert [row.tenant_id for row in remaining] == [OTHER_TENANT_ID]


def test_the_sync_job_handler_is_registered(db):
    """Omitting the registration leaves every sync job Pending forever with NO
    error — the nastiest footgun in this codebase."""
    from app.jobs.registry import handler_for

    assert handler_for(AUTOCOUNT_SYNC).handler is run_autocount_sync


def test_the_worker_module_imports_the_handler_module():
    """The Celery worker boots no FastAPI lifespan: it only sees handlers whose
    MODULE was imported. This asserts the import line still exists."""
    from pathlib import Path

    worker = Path("app/workflow_engine/worker.py").read_text()
    assert "import modules.autocount.sync" in worker


# ── the HTTP surface ──────────────────────────────────────────────────────────


def _auth(client) -> Dict[str, str]:
    response = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_every_autocount_route_requires_authentication(client):
    """Gated by ``require_permission`` (and ``require_module``) — never open."""
    for method, path in (
        ("get", "/autocount/companies"),
        ("post", "/autocount/companies"),
        ("get", "/autocount/companies/x/runs"),
        ("get", "/autocount/jobs/x/staged"),
        ("post", "/autocount/jobs/x/preview"),
        ("post", "/autocount/jobs/x/approve"),
        ("post", "/autocount/jobs/x/discard"),
        ("patch", "/autocount/companies/x/entities/goods_received_note"),
        ("patch", "/autocount/companies/x/sink-target"),
    ):
        kwargs = {"json": {}} if method in ("post", "patch") else {}
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code in (401, 403), f"{method} {path} was reachable"


def test_the_company_list_is_scoped_to_the_callers_tenant(client, session_factory):
    """The tenant comes from the JWT, never from client input (AC-13-41)."""
    setup = session_factory()
    setup.add(
        AcCompany(
            tenant_id=OTHER_TENANT_ID,
            connection_id="c",
            database_name="AED_THEIRS",
            company_name="Theirs",
            name="Theirs",
        )
    )
    setup.commit()
    setup.close()

    response = client.get("/autocount/companies", headers=_auth(client))
    assert response.status_code == 200
    assert response.json()["data"] == []  # another tenant's company is invisible


def test_the_company_wire_shape_is_camel_case_and_leaks_no_credential(
    client, session_factory, transports
):
    setup = session_factory()
    company_id = _company(setup, transports, database_name="AED_WIRE").id
    setup.close()

    response = client.get("/autocount/companies", headers=_auth(client))
    body = response.json()["data"][0]
    assert body["databaseName"] == "AED_WIRE"
    assert body["id"] == company_id
    assert "createdAt" in body and body["createdAt"].endswith("Z")  # ApiModel
    joined = str(body).lower()
    assert "password" not in joined and "appid" not in joined


def test_an_unknown_company_is_a_clean_404_not_a_500(client):
    response = client.get("/autocount/companies/nope", headers=_auth(client))
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_approving_an_unknown_job_is_a_clean_404(client):
    response = client.post("/autocount/jobs/nope/approve", headers=_auth(client))
    assert response.status_code == 404


def test_the_entity_wire_carries_the_delta_state(client, session_factory, transports):
    """The Entities tab needs the watermark half on the wire, camelCase and
    Z-suffixed like everything else."""
    setup = session_factory()
    company_id = _company(setup, transports, database_name="AED_STATE").id
    setup.close()

    body = client.get(
        f"/autocount/companies/{company_id}", headers=_auth(client)
    ).json()
    entity = next(
        e for e in body["entities"] if e["entityType"] == ENTITY_GOODS_RECEIVED_NOTE
    )
    assert entity["entityType"] == ENTITY_GOODS_RECEIVED_NOTE
    assert entity["initialLookbackDays"] == 30
    for key in (
        "lastSuccessAt",
        "lastAttemptAt",
        "watermarkAt",
        "consecutiveFailures",
        "lastError",
    ):
        assert key in entity, f"{key} missing from the entity wire shape"
    assert entity["consecutiveFailures"] == 0
    assert entity["watermarkAt"] is None  # never synced


def test_the_lookback_patch_persists_and_rejects_nonsense(
    client, session_factory, transports
):
    setup = session_factory()
    company_id = _company(setup, transports, database_name="AED_PATCH").id
    setup.close()

    path = f"/autocount/companies/{company_id}/entities/{ENTITY_GOODS_RECEIVED_NOTE}"
    ok = client.patch(path, json={"initialLookbackDays": 180}, headers=_auth(client))
    assert ok.status_code == 200
    assert ok.json()["initialLookbackDays"] == 180

    # Persisted, not just echoed.
    detail = client.get(
        f"/autocount/companies/{company_id}", headers=_auth(client)
    ).json()
    grn = next(
        e for e in detail["entities"] if e["entityType"] == ENTITY_GOODS_RECEIVED_NOTE
    )
    assert grn["initialLookbackDays"] == 180

    # Nonsense is REJECTED, never coerced — a coerced value would silently sync
    # a window the operator did not ask for.
    for bad in (0, -5, 99_999):
        rejected = client.patch(
            path, json={"initialLookbackDays": bad}, headers=_auth(client)
        )
        assert rejected.status_code == 422, bad
        assert "between" in rejected.json()["detail"]


def test_patching_an_unconfigured_entity_is_a_clean_404(
    client, session_factory, transports
):
    setup = session_factory()
    company_id = _company(setup, transports, database_name="AED_404").id
    setup.close()

    response = client.patch(
        f"/autocount/companies/{company_id}/entities/not_an_entity",
        json={"initialLookbackDays": 90},
        headers=_auth(client),
    )
    assert response.status_code == 404


def test_every_migration_revision_id_fits_the_version_column():
    """``alembic_version.version_num`` is VARCHAR(32) — a longer id passes the
    create_all suite (conftest never runs module Alembic) and then breaks every
    real Postgres deploy. This is the only place that catches it."""
    import re
    from pathlib import Path

    versions = Path("modules/autocount/alembic/versions")
    files = sorted(versions.glob("*.py"))
    assert files, "the module must own at least one migration"
    for path in files:
        ids = re.findall(r'^(?:revision|down_revision)[^=]*=\s*"([^"]+)"', path.read_text(), re.M)
        assert ids, f"{path.name} declares no revision id"
        for value in ids:
            assert len(value) <= 32, f"{path.name}: '{value}' is {len(value)} chars"


def test_the_new_migration_chains_onto_the_baseline():
    """A dangling down_revision splits the history into two heads and the
    upgrade fails on a live deploy — invisible to pytest."""
    from pathlib import Path

    text = Path(
        "modules/autocount/alembic/versions/0002_autocount_grn.py"
    ).read_text()
    assert 'revision: str = "0002_autocount_grn"' in text
    assert '"0001_autocount_baseline"' in text


# ── code-review regressions (sprint-4/13 slice 1) ─────────────────────────────
#
# Each test below pins a defect the pre-existing suite structurally could not
# catch. They are grouped here so the "why" stays attached to the "what".


def test_a_mapping_row_pydantic_rejects_fails_one_document_not_the_batch(
    db, transports
):
    """FIX 1. ``transform`` is OPERATOR-EDITABLE DATA, so a mapping row can hand
    the canonical model a value pydantic rejects — here ``qty`` mapped
    ``string``, so a UOM lands in a ``Decimal`` field.

    Header construction was guarded; LINE construction was not. The resulting
    ValidationError escaped ``map_document`` → ``_stage_documents`` →
    ``run_autocount_sync`` and killed the WHOLE batch, taking every sibling GRN
    with it — precisely what AC-13-10 forbids.
    """
    company = _company(db, transports)
    # An operator EDITS the seeded ``qty`` row (the D5 "mapping is data" path)
    # to point at a text field with a ``string`` transform — a plausible
    # mis-edit, and one no code change is required to make. It only bites lines
    # that actually carry ``BatchNo``, which is just the one document below.
    qty_row = (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.tenant_id == DEFAULT_TENANT_ID,
            AcFieldMapping.company_id == company.id,
            AcFieldMapping.scope == "line",
            AcFieldMapping.canonical_field == "qty",
        )
        .one()
    )
    qty_row.source_path = "BatchNo"
    qty_row.transform = "string"
    db.commit()

    bad = _grn(
        "2",
        "GRN-0002",
        lines=[{"DtlKey": "9", "Qty": "1.0", "BatchNo": "BATCH-A"}],
    )
    _queue(db, transports, company, [_grn("1"), bad, _grn("3")])
    job = _run_sync(db, company)

    rows = {
        row.source_ref: row
        for row in StagedRecordRepository(db).list_for_job(
            DEFAULT_TENANT_ID, company.id, job.id
        )
    }
    # The siblings survived — the whole point.
    assert rows["1"].status == STAGED
    assert rows["3"].status == STAGED
    failed = rows["2"]
    assert failed.status == STAGED_FAILED
    assert failed.canonical_json is None  # no half-record exists
    # …and the failure NAMES the line (AC-13-10), rather than being an opaque
    # crash somewhere above the document loop.
    assert "line 1" in failed.error
    assert job.status == JOB_NEEDS_REVIEW  # the run itself completed cleanly


def test_a_stale_sync_is_visible_when_documents_keep_failing(db, transports):
    """FIX 2. ``last_success_at`` was stamped unconditionally and
    ``consecutive_failures`` only ever moved in ``_fail`` (fetch faults), so a
    permanently-BLOCKED entity presented as perfectly healthy: watermark held
    (right), fresh success timestamp, zero failures. AC-13-19's stale-sync
    monitor would never fire on the one case it exists for (plan §7 — "a
    blocked sync is always visible").
    """
    company = _company(db, transports)
    watermarks = WatermarkRepository(db)

    # Two consecutive runs in which every document fails to map.
    for _ in range(2):
        _queue(db, transports, company, [_grn("1", lines=[{"DtlKey": "1", "Qty": "oops"}])])
        _run_sync(db, company)

    watermark = watermarks.get(DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE)
    assert watermark.last_modified_at is None  # HELD, as before
    assert watermark.consecutive_failures == 2, "a blocked sync must be countable"
    assert watermark.last_success_at is None, "a failing batch is not a success"

    # …and the other branch: a clean batch clears the count and stamps success.
    _queue(db, transports, company, [_grn("2")])
    _run_sync(db, company)

    watermark = watermarks.get(DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE)
    assert watermark.consecutive_failures == 0
    assert watermark.last_success_at is not None
    assert watermark.last_success_at.tzinfo is not None  # aware-UTC discipline
    assert watermark.last_error is None


def test_a_raising_sink_leaves_the_batch_re_approvable_not_stranded(
    db, transports, monkeypatch
):
    """FIX 3. ``_claim_review`` atomically moves ``needs_review`` → ``running``.
    A raise between that and ``finish`` stranded the job in ``running`` FOREVER:
    non-terminal so the pruner never reaps it, and no longer ``needs_review`` so
    the claim could never succeed again — no re-approve, no retry. One network
    error would have permanently killed an approved batch the moment a real sink
    landed.
    """
    from modules.autocount.services.sync_service import PushFailed
    from modules.autocount import sinks as sinks_module

    company = _company(db, transports, reads=[[_grn("1"), _grn("2")]])
    job = _run_sync(db, company)
    assert job.status == JOB_NEEDS_REVIEW

    calls = {"n": 0}
    real_write = sinks_module.LoggingSink.write

    def flaky(self, record, *, request_id):
        calls["n"] += 1
        if calls["n"] == 2:  # the FIRST record pushed, the second blew up
            raise RuntimeError("sink connection reset")
        return real_write(self, record, request_id=request_id)

    monkeypatch.setattr(sinks_module.LoggingSink, "write", flaky)

    with pytest.raises(PushFailed):
        SyncService(db).approve(DEFAULT_TENANT_ID, job.id)

    fresh = db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    assert fresh.status == JOB_NEEDS_REVIEW, "the batch was stranded in `running`"

    # The record that DID reach the sink is committed PUSHED, so the retry does
    # not deliver it twice.
    statuses = sorted(
        r.status
        for r in StagedRecordRepository(db).list_for_job(
            DEFAULT_TENANT_ID, company.id, job.id
        )
    )
    assert statuses == [STAGED_PUSHED, STAGED]  # exactly one of each

    # And it really is re-approvable — the sink recovers, the remainder goes.
    monkeypatch.setattr(sinks_module.LoggingSink, "write", real_write)
    result = SyncService(db).approve(DEFAULT_TENANT_ID, job.id)
    assert result["pushed"] == 1  # only the one still outstanding
    statuses = {
        r.source_ref: r.status
        for r in StagedRecordRepository(db).list_for_job(
            DEFAULT_TENANT_ID, company.id, job.id
        )
    }
    assert statuses == {"1": STAGED_PUSHED, "2": STAGED_PUSHED}
    assert (
        db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first().status
        == JOB_DONE
    )


def test_a_fetch_fault_after_a_committed_abort_does_not_overwrite_it(
    db, session_factory, transports
):
    """FIX 4. ``_abort`` already refuses to touch the operator's status; ``_fail``
    called ``finish(JOB_FAILED)`` with no fresh re-read, so an abort committed on
    ANOTHER session while a fetch was in flight got overwritten the instant that
    fetch then errored — erasing the fact that a human stopped this.

    Driven with a REAL interleave, as the pre-existing abort test is: eager mode
    runs the handler inline with no natural interleave, so this class of bug is
    invisible to an inline no-op.
    """
    company = _company(db, transports)
    job = SyncService(db).jobs.create(
        type=AUTOCOUNT_SYNC,
        tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_GOODS_RECEIVED_NOTE},
    )

    aborting = session_factory()
    transport = transports[company.connection_id]
    original_post = transport.post

    def post_then_abort(url, **kwargs):
        if url.endswith("GetGoodsReceivedNote"):
            # The operator hits Abort while the read is in flight; the read then
            # faults for its own unrelated reason. BOTH things really happened.
            aborting.query(BackgroundJob).filter(BackgroundJob.id == job.id).update(
                {BackgroundJob.status: JOB_ABORTED}, synchronize_session=False
            )
            aborting.commit()
        return original_post(url, **kwargs)

    transport.post = post_then_abort
    transport.reads.append(
        httpx.Response(200, json={"Status": "Fail", "Message": "Bad filter", "ResultTable": []})
    )

    run_autocount_sync(db, job)
    aborting.close()

    fresh = db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    assert fresh.status == JOB_ABORTED, "the operator's abort was overwritten"
    # The run still records WHY it stopped — the fetch genuinely did fail.
    run = SyncRunRepository(db).get_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert run.outcome == RUN_FAILED
    assert "Bad filter" in (run.error or "")
    # Watermark held either way.
    assert (
        WatermarkRepository(db)
        .get(DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE)
        .last_modified_at
        is None
    )


def test_the_connection_lookup_lives_in_the_repository_layer(db, transports):
    """FIX 7. Router → Service → Repository is enforced; the connection query
    ran inline in ``CompanyService``. Behaviour is pinned here (still tenant-
    AND provider-scoped) as well as the placement, so the move cannot silently
    drop a filter."""
    import inspect

    from modules.autocount.repositories import ConnectionRepository
    from modules.autocount.services import company_service as module

    # No raw query left in the service layer.
    source = inspect.getsource(module)
    assert "self.db.query(Connection)" not in source

    company = _company(db, transports)
    repo = ConnectionRepository(db)
    assert (
        repo.get_for_provider(DEFAULT_TENANT_ID, company.connection_id, "autocount")
        is not None
    )
    # Another tenant cannot resolve it, and neither can another provider.
    assert (
        repo.get_for_provider(OTHER_TENANT_ID, company.connection_id, "autocount")
        is None
    )
    assert (
        repo.get_for_provider(DEFAULT_TENANT_ID, company.connection_id, "stripe")
        is None
    )


# ── activity logging: real masked payloads (plan §11, AC-13-42/46) ────────────
#
# The defect these pin: for 113 real rows, ``request_summary_json`` held only
# ``{"window":…, "recordCap":200}`` (and only on 48 of them), ``status_code``
# ``latency_ms`` and ``trace_id`` were NULL on every one, and the failure paths
# logged no request at all. A customer's mapping failure could not be diagnosed
# without the actual vendor payload, and the Developer Logs console — which is
# built around status/latency/trace — rendered blank columns for this source.


def _activity(db, tenant_id: str = DEFAULT_TENANT_ID) -> List[IntegrationActivity]:
    return (
        db.query(IntegrationActivity)
        .filter(
            IntegrationActivity.tenant_id == tenant_id,
            IntegrationActivity.source == "autocount",
        )
        .all()
    )


def _http_rows(rows: List[IntegrationActivity]) -> List[IntegrationActivity]:
    """The rows representing a real HTTP leg (as opposed to a domain summary)."""
    return [r for r in rows if r.operation.startswith("POST /api/")]


def test_the_real_request_and_response_are_stored_not_a_summary(db, transports):
    company = _company(db, transports, reads=[[_grn("1")]])
    _run_sync(db, company)

    legs = _http_rows(_activity(db))
    paths = {row.operation for row in legs}
    assert "POST /api/Server/Login" in paths
    assert "POST /api/GoodsReceivedNote/GetGoodsReceivedNote" in paths

    read = next(r for r in legs if r.operation.endswith("GetGoodsReceivedNote"))
    # The ACTUAL request: method, url, headers and the real filter body — not
    # a hand-built {"window": …} summary.
    assert read.request_summary_json["method"] == "POST"
    assert read.request_summary_json["url"].endswith(
        "/api/GoodsReceivedNote/GetGoodsReceivedNote"
    )
    assert "RecordCount" in read.request_summary_json["body"]
    assert "LastModifiedFrom" in read.request_summary_json["body"]
    # The ACTUAL response envelope, with the vendor's own Status field.
    assert read.response_summary_json["body"]["Status"] == "Success"


def test_status_code_latency_and_trace_are_populated_on_success(db, transports):
    """The Developer Logs console renders these columns; they were NULL on all
    113 real autocount rows."""
    company = _company(db, transports, reads=[[_grn("1")]])
    job = _run_sync(db, company)

    legs = _http_rows(_activity(db))
    assert legs, "no HTTP leg was logged"
    for row in legs:
        assert row.status_code == 200
        assert row.latency_ms is not None and row.latency_ms >= 0
        assert row.method == "POST"
        assert row.trace_id

    # Every leg of ONE run shares ONE trace, derived from the job id so an
    # operator holding a job id can find the calls without a lookup table. The
    # company-discovery login carries its own (earlier, separate) trace.
    sync_traces = {
        row.trace_id for row in _activity(db) if row.trace_id.startswith("acsync-")
    }
    assert sync_traces == {f"acsync-{job.id}"}
    # …and the run summary shares it with the HTTP legs, so the console shows
    # ONE interaction rather than three unrelated rows.
    summary = next(
        r for r in _activity(db) if r.operation == f"sync {ENTITY_GOODS_RECEIVED_NOTE}"
    )
    assert summary.trace_id == f"acsync-{job.id}"
    assert summary.latency_ms is not None


def test_a_failed_call_is_logged_with_its_request(db, transports):
    """The failure paths were the ones missing ``request_summary_json``."""
    company = _company(db, transports)
    _queue(
        db,
        transports,
        company,
        httpx.Response(500, json={"ClassName": "X", "Message": "boom"}),
    )
    _run_sync(db, company)

    read = next(
        r
        for r in _http_rows(_activity(db))
        if r.operation.endswith("GetGoodsReceivedNote")
    )
    assert read.status == "error"
    assert read.status_code == 500
    assert read.latency_ms is not None
    # The request that produced the failure is stored — that is the whole point.
    assert read.request_summary_json["body"]["RecordCount"] > 0
    assert read.response_summary_json["body"]["Message"] == "boom"


def test_an_http_200_business_failure_is_logged_as_an_error(db, transports):
    """Success is ``Status == "Success"``, not the HTTP code. A log that badges
    an HTTP-200 ``Status:"Fail"`` green is a log nobody can diagnose from."""
    company = _company(db, transports)
    _queue(
        db,
        transports,
        company,
        httpx.Response(200, json={"Status": "Fail", "Message": "nope", "ResultTable": []}),
    )
    _run_sync(db, company)

    read = next(
        r
        for r in _http_rows(_activity(db))
        if r.operation.endswith("GetGoodsReceivedNote")
    )
    assert read.status_code == 200
    assert read.status == "error"


def test_the_authorization_header_never_lands_unmasked(db, transports):
    """BL-131 — the vendor JWT base64-decodes to the user's PASSWORD, so an
    unmasked ``Authorization`` header is a credential leak, not a nuisance.
    Asserted against the SERIALIZED row, not a field-by-field peek."""
    import json

    company = _company(db, transports, reads=[[_grn("1")]])
    _run_sync(db, company)

    rows = _activity(db)
    assert rows
    blob = json.dumps(
        [
            {
                "request": r.request_summary_json,
                "response": r.response_summary_json,
                "error": r.error_message,
            }
            for r in rows
        ],
        default=str,
    )
    # The JWT itself, the password, and the AppId — none may appear anywhere.
    assert JWT not in blob
    assert "secret" not in blob
    assert "app-1" not in blob

    # And the header key IS present (so the assertion above is meaningful —
    # it passes because the value was redacted, not because we stopped logging
    # headers at all).
    read = next(
        r
        for r in _http_rows(rows)
        if r.operation.endswith("GetGoodsReceivedNote")
    )
    headers = read.request_summary_json["headers"]
    assert headers["Authorization"] == "***"
    assert headers["AppId"] == "***"

    login = next(r for r in _http_rows(rows) if r.operation.endswith("Login"))
    assert login.request_summary_json["body"]["Password"] == "***"
    assert login.response_summary_json["body"][0]["JWTToken"] == "***"


def test_a_large_response_is_truncated_and_says_so(db, transports):
    """AC-13-46 — a truncated log must never read as a complete one. These
    responses reach 161 documents; storing megabytes per row is not an option,
    and silently dropping the tail sends a diagnostician after the wrong bug."""
    from modules.autocount.payloads import MAX_LIST_ITEMS, TRUNCATED_KEY

    many = [_grn(str(i), DocNo=f"GRN-{i}") for i in range(1, 12)]
    company = _company(db, transports, reads=[many])
    _run_sync(db, company)

    read = next(
        r
        for r in _http_rows(_activity(db))
        if r.operation.endswith("GetGoodsReceivedNote")
    )
    assert read.response_summary_json[TRUNCATED_KEY] is True
    table = read.response_summary_json["body"]["ResultTable"]
    # The SHAPE changed — a list became a marker object — so it cannot be
    # mistaken for a complete array, and the real total is recorded.
    assert table[TRUNCATED_KEY] is True
    assert table["totalItems"] == 11
    assert table["keptItems"] == MAX_LIST_ITEMS
    assert len(table["items"]) == MAX_LIST_ITEMS


def test_a_complete_payload_carries_no_truncation_marker(db, transports):
    """Absence of the marker is the positive statement "this is complete" — so
    it must not be stamped on every row."""
    from modules.autocount.payloads import TRUNCATED_KEY

    company = _company(db, transports, reads=[[_grn("1")]])
    _run_sync(db, company)

    read = next(
        r
        for r in _http_rows(_activity(db))
        if r.operation.endswith("GetGoodsReceivedNote")
    )
    assert TRUNCATED_KEY not in read.response_summary_json
    assert TRUNCATED_KEY not in read.request_summary_json


def test_company_discovery_logs_its_login_leg(db, transports):
    company = _company(db, transports)
    legs = _http_rows(_activity(db))
    assert any(r.operation == "POST /api/Server/Login" for r in legs)
    login = next(r for r in legs if r.operation.endswith("Login"))
    assert login.status_code == 200
    assert login.latency_ms is not None
    assert login.trace_id and login.trace_id.startswith("acdiscover-")
    assert company.database_name


def test_draining_twice_never_duplicates_a_row(db, transports):
    """The buffer is DRAINED, not read — so a caller that logs twice (a retry, a
    future call site) cannot write the same interaction twice."""
    from modules.autocount.activity import record_client_calls

    company = _company(db, transports, reads=[[_grn("1")]])
    _run_sync(db, company)
    before = len(_activity(db))

    client = CompanyService(db).client_for(DEFAULT_TENANT_ID, company)
    client.login()
    assert record_client_calls(db, client, tenant_id=DEFAULT_TENANT_ID) == 1
    assert record_client_calls(db, client, tenant_id=DEFAULT_TENANT_ID) == 0
    assert len(_activity(db)) == before + 1


def test_a_logging_failure_never_breaks_a_sync(db, transports, monkeypatch):
    """AC-13-43 — observability is never load-bearing."""
    import modules.autocount.activity as activity_module

    def boom(*_a, **_kw):
        raise RuntimeError("activity store is down")

    monkeypatch.setattr(activity_module.ActivityLogService, "record", boom)

    company = _company(db, transports, reads=[[_grn("1")]])
    job = _run_sync(db, company)
    assert job.status == JOB_NEEDS_REVIEW


# ── entity state on the wire (Fix 2 — a zero-record sync must be explicable) ──


def test_entity_states_carry_the_watermark_so_a_zero_sync_is_explicable(
    db, transports
):
    """``last_success_at``/``last_modified_at``/``consecutive_failures``/
    ``last_error`` were recorded by every run and shown to nobody — which is
    exactly why a legitimate zero-record sync read as silence."""
    company = _company(db, transports, reads=[[_grn("1")]])

    # Before any sync: configured, but never run.
    fresh = _grn_state(db, company)
    assert fresh.entity_type == ENTITY_GOODS_RECEIVED_NOTE
    assert fresh.last_success_at is None
    assert fresh.watermark_at is None
    assert fresh.consecutive_failures == 0
    # The first-run trap is visible rather than implicit.
    assert fresh.initial_lookback_days == 30

    _run_sync(db, company)
    synced = _grn_state(db, company)
    assert synced.last_success_at is not None
    assert synced.watermark_at is not None
    assert synced.last_error is None


def test_a_failed_sync_surfaces_its_failure_count_and_error(db, transports):
    company = _company(db, transports)
    _queue(db, transports, company, httpx.Response(500, json={"Message": "boom"}))
    _run_sync(db, company)

    state = _grn_state(db, company)
    assert state.consecutive_failures == 1
    assert state.last_error
    # The watermark held — the run failed, so nothing was accepted.
    assert state.watermark_at is None


def test_entity_states_are_scoped_to_their_own_company(db, transports):
    a = _company(db, transports, database_name="AED_A", reads=[[_grn("1")]])
    b = _company(db, transports, database_name="AED_B", reads=[[_grn("2")]])
    _run_sync(db, a)

    assert _grn_state(db, a).last_success_at
    assert (
        _grn_state(db, b).last_success_at
        is None
    )


def test_the_initial_lookback_is_editable_and_bounded(db, transports):
    from modules.autocount.services import AutocountServiceError, CompanyService

    company = _company(db, transports)
    service = CompanyService(db)

    updated = service.update_entity_config(
        DEFAULT_TENANT_ID,
        company.id,
        ENTITY_GOODS_RECEIVED_NOTE,
        initial_lookback_days=365,
    )
    assert updated.initial_lookback_days == 365

    for bad in (0, -1, 100_000):
        with pytest.raises(AutocountServiceError):
            service.update_entity_config(
                DEFAULT_TENANT_ID,
                company.id,
                ENTITY_GOODS_RECEIVED_NOTE,
                initial_lookback_days=bad,
            )


def test_another_tenants_entity_config_cannot_be_edited(db, transports):
    from modules.autocount.services import CompanyNotFound, CompanyService

    company = _company(db, transports)
    with pytest.raises(CompanyNotFound):
        CompanyService(db).update_entity_config(
            OTHER_TENANT_ID,
            company.id,
            ENTITY_GOODS_RECEIVED_NOTE,
            initial_lookback_days=90,
        )


def test_the_new_lookback_governs_the_next_first_run_window(db, transports):
    """The value is not decoration: it is the window a company with no watermark
    actually fetches over."""
    from modules.autocount.services import CompanyService
    from modules.autocount.sources import Watermark

    company = _company(db, transports)
    CompanyService(db).update_entity_config(
        DEFAULT_TENANT_ID,
        company.id,
        ENTITY_GOODS_RECEIVED_NOTE,
        initial_lookback_days=400,
    )
    config = _grn_config(db, company)

    now = datetime(2026, 7, 21, tzinfo=timezone.utc)
    start = Watermark().start(lookback_days=config.initial_lookback_days, now=now)
    assert (now - start).days == 400


def test_widening_the_lookback_never_re_widens_an_established_window(db, transports):
    """THE case that must not regress.

    Once a watermark exists it WINS: widening the first-run window must not
    reach back past it. If it did, the next sync would silently re-fetch history
    and re-stage documents the operator has already reviewed and approved —
    duplicate work presented as new work, which is worse than the gap it was
    meant to close.
    """
    from modules.autocount.services import CompanyService

    company = _company(db, transports, reads=[[_grn("1")]])
    _run_sync(db, company)

    mark = WatermarkRepository(db).get(
        DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE
    )
    established = mark.last_modified_at
    assert established is not None

    CompanyService(db).update_entity_config(
        DEFAULT_TENANT_ID,
        company.id,
        ENTITY_GOODS_RECEIVED_NOTE,
        initial_lookback_days=3650,
    )

    # The next fetch starts AT the watermark, not 10 years back.
    _queue(db, transports, company, [])
    job = _run_sync(db, company)
    run = SyncRunRepository(db).get_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert run.window_from == established

    # And the wire says the same thing, so the UI can show it as state.
    state = _grn_state(db, company)
    assert state.initial_lookback_days == 3650
    assert state.watermark_at == established


def test_a_zero_record_sync_succeeds_and_holds_the_watermark(db, transports):
    """The reported symptom: a second Sync now "did nothing". It was CORRECT —
    the vendor had no changes since the watermark, and an empty batch must not
    advance it. Pinned so the summary the UI reads stays honest."""
    company = _company(db, transports, reads=[[_grn("1")]])
    _run_sync(db, company)
    before = WatermarkRepository(db).get(
        DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE
    ).last_modified_at

    _queue(db, transports, company, [])
    job = _run_sync(db, company)

    # A successful no-op: the job CLOSES (never needs_review with nothing in it,
    # which would strand a batch nobody can act on).
    assert job.status == JOB_DONE
    assert job.result_json["fetched"] == 0
    assert job.result_json["staged"] == 0
    assert job.result_json["failed"] == 0
    assert job.result_json["awaitingApproval"] is False
    # …and the watermark did NOT move, because nothing was seen.
    assert (
        WatermarkRepository(db)
        .get(DEFAULT_TENANT_ID, company.id, ENTITY_GOODS_RECEIVED_NOTE)
        .last_modified_at
        == before
    )


def test_a_200_body_with_no_status_key_is_logged_as_a_failure():
    """The client's ``_unwrap`` treats an ABSENT ``Status`` as failure
    (``str(None or "")`` -> ``""`` != ``"success"``) and raises. The activity
    log must agree.

    Divergence here is exactly the bug the CallRecord exists to prevent: the run
    fails, the diagnostician opens the very leg the run summary points at, and
    the log badges it green with no error. A vendor error envelope carrying only
    ``Message`` -- including the login one, which ``login()`` only reads
    ``Message`` from -- is precisely this shape.
    """
    client = AutoCountClient(
        base_url="https://ac.example.com",
        app_id="app-1",
        user_id="ADMIN",
        password="secret",
        transport=MockTransport([httpx.Response(200, json={"Message": "Invalid AppId"})]),
    )

    with pytest.raises(AutoCountError):
        client.read("GoodsReceivedNote", {"DocNo": [], "RecordCount": 1})

    legs = client.drain_calls()
    assert legs, "the failing leg must still be recorded"
    read_leg = [c for c in legs if c.path.endswith("GetGoodsReceivedNote")][-1]
    assert read_leg.ok is False, "a 200 body with no Status key must log as a failure"
    assert read_leg.error_message and "Invalid AppId" in read_leg.error_message

    # And the successful login leg alongside it is still green -- a bare ARRAY
    # body never reaches the dict branch, so the stricter rule cannot
    # mis-badge it.
    login_leg = [c for c in legs if c.path.endswith("/Login")][0]
    assert login_leg.ok is True


# ══════════════════════════════════════════════════════════════════════════════
# Slice 2 — masters (AC-14-01..05, 14-10/11, 14-25/26)
#
# The failures these pin are the quiet ones: a master response read through the
# GRN unwrap, a company-unqualified ref that collides on the SECOND company
# connected, a 30-day window that imports 1 of 106 suppliers and reports success,
# and an active-flag that silently defaults to False and deactivates a live
# supplier in the consumer.
# ══════════════════════════════════════════════════════════════════════════════

from modules.autocount.backfill import backfill_entity_config_defaults  # noqa: E402
from modules.autocount.canonical.masters import (  # noqa: E402
    ENTITY_CUSTOMER,
    ENTITY_SUPPLIER,
    CanonicalCustomer,
    CanonicalSupplier,
)
from modules.autocount.envelopes import (  # noqa: E402
    ENVELOPE_ROW_ARRAY,
    ENVELOPE_STATUS_DICT,
    ROW_ARRAY,
    STATUS_DICT,
    UnknownEnvelope,
    envelope_for,
)
from modules.autocount.mapping import (  # noqa: E402
    DEFAULT_CUSTOMER_MAPPING,
    DEFAULT_SUPPLIER_MAPPING,
    IdentityError,
    company_qualified_identity,
    slash_datetime,
    t_f_bool,
)
from modules.autocount.models import AcEntityConfig  # noqa: E402
from modules.autocount.sources import (  # noqa: E402
    INITIAL_LOAD_FULL,
    INITIAL_LOAD_WINDOWED,
    UnknownInitialLoad,
)


def _creditor(
    auto_key: str = "1",
    acc_no: str = "400-J001",
    *,
    last_modified: str = "2026/03/18 16:03:21",
    is_active: str = "T",
    record_count: Any = "1 of 106",
    # EMPTY, not "Success" -- this is what the live instance actually returns on
    # every healthy master row (verified 2026-07-21: all 106 Creditor and all 172
    # Debtor rows carry Status: '' / Message: ''). This default previously read
    # "Success", mirroring GRN's dict envelope, and that single wrong character
    # sequence let the whole master pipeline pass 205 mocked tests while failing
    # against the real vendor on the first live call. A fixture that encodes a
    # guess validates the guess.
    status: str = "",
    **overrides: Any,
) -> Dict[str, Any]:
    """ONE element of a master response, in the shape the live instance returns.

    Note what is where: the row carries its OWN ``Status``/``Message``/
    ``RecordCount`` (there is no top-level envelope at all), some fields sit flat
    at this level, and the REAL DB row is nested under ``Data[0]`` — including
    ``AutoKey`` and ``LastModified``. Both levels carry ``AccNo``/``CompanyName``/
    ``IsActive``, which is exactly why the two are not flattened together.
    """
    record = {
        "Status": status,
        "Message": "",
        "RecordCount": record_count,
        "AccNo": acc_no,
        "CompanyName": "Jaya Trading Sdn Bhd",
        "EmailAddress": "ap@jaya.example",
        "RegisterNo": "199801000123",
        "TaxRegistrationNo": "",
        "IsActive": is_active,
        "UDF": [],
        "Data": [
            {
                "AutoKey": auto_key,
                "AccNo": acc_no,
                "CompanyName": "Jaya Trading Sdn Bhd",
                "IsActive": is_active,
                "CreditLimit": "50000.00000000",
                "LastModified": last_modified,
            }
        ],
    }
    record.update(overrides)
    return record


def _debtor(auto_key: str = "1", acc_no: str = "300-C001", **overrides: Any) -> Dict[str, Any]:
    record = _creditor(auto_key, acc_no)
    record.update(
        {
            "Mobile": "+60123456789",
            "TIN": "IG12345678900",
            "CreditLimit": "25000.00000000",
            # Debtor rows carry a Guid; Creditor rows do NOT — which is why the
            # ref is minted from AutoKey and not from Guid.
            "Guid": "b6c1f2e0-1111-2222-3333-444455556666",
        }
    )
    record.update(overrides)
    return record


def _rows(records: List[Dict[str, Any]]) -> httpx.Response:
    """A master response: a BARE ARRAY, not a Status dict."""
    return httpx.Response(200, json=records)


# ── AC-14-02: list-index path resolution ──────────────────────────────────────


def test_a_numeric_path_segment_indexes_a_list():
    """``Data.0.AutoKey`` — masters nest their real DB row one level down."""
    record = _creditor(auto_key="42")
    assert resolve_path(record, "Data.0.AutoKey") == "42"
    assert resolve_path(record, "Data.0.LastModified") == "2026/03/18 16:03:21"


def test_both_nesting_levels_stay_addressable():
    """The reason ``Data[0]`` is NOT flattened into its parent: unique fields on
    both levels, plus OVERLAPPING ones that a flatten would have to silently
    pick a winner for."""
    record = _creditor(acc_no="400-J001")
    record["CompanyName"] = "Top Level Name"
    record["Data"][0]["CompanyName"] = "Nested Name"

    assert resolve_path(record, "EmailAddress") == "ap@jaya.example"  # top only
    assert resolve_path(record, "Data.0.AutoKey") == "1"  # nested only
    assert resolve_path(record, "CompanyName") == "Top Level Name"
    assert resolve_path(record, "Data.0.CompanyName") == "Nested Name"


def test_an_out_of_range_index_is_missing_never_an_exception():
    """A wrong path is an operator's mapping-row mistake. It must surface as that
    row's named error (or a skipped optional), never as an exception that kills
    the whole batch."""
    from modules.autocount.mapping import _MISSING

    record = _creditor()
    assert resolve_path(record, "Data.5.AutoKey") is _MISSING
    assert resolve_path(record, "Data.0.Nope") is _MISSING
    # A numeric segment against a dict, and a named segment against a list.
    assert resolve_path(record, "0.AutoKey") is _MISSING
    assert resolve_path(record, "Data.AutoKey") is _MISSING
    # Negative indices are refused deliberately: "-1" reads as a typo and would
    # silently point at a different record as the list grows.
    assert resolve_path(record, "Data.-1.AutoKey") is _MISSING
    # A scalar with path left to walk.
    assert resolve_path(record, "AccNo.0") is _MISSING


def test_the_udf_special_case_is_untouched_by_list_indexing():
    """The UDF grammar is matched BEFORE the dotted walk and must stay so — a
    per-customer UDF array is the reason mapping is data at all."""
    from modules.autocount.mapping import _MISSING

    record = {
        "UDF": [
            {"FieldName": "DriverName", "FieldName2": None, "Value": "Ah Meng"},
            {"FieldName": None, "FieldName2": "TruckNo", "Value": "WXY 1234"},
        ]
    }
    assert resolve_path(record, "UDF[UDF].DriverName") == "Ah Meng"
    assert resolve_path(record, "UDF[UDF].TruckNo") == "WXY 1234"  # FieldName2
    assert resolve_path(record, "UDF[UDF].Absent") is _MISSING
    assert resolve_path({"UDF": "not-a-list"}, "UDF[UDF].DriverName") is _MISSING


# ── AC-14-03: two envelopes, one client ───────────────────────────────────────


def test_the_row_array_envelope_treats_each_element_as_a_record():
    unwrapped = ROW_ARRAY.unwrap([_creditor("1"), _creditor("2")])
    assert [r["Data"][0]["AutoKey"] for r in unwrapped.records] == ["1", "2"]


def test_a_master_response_through_the_grn_envelope_is_a_failure_not_a_crash():
    """AC-14-03: a bare array has no top-level ``Status``. The GRN rule must
    REJECT it — reading it as an empty success would be silent data loss."""
    verdict = STATUS_DICT.verdict([_creditor()])
    assert verdict.ok is False


def test_each_envelope_owns_both_success_rules_so_they_cannot_drift():
    """The regression 6d3e21c fixed, now structural.

    The client had TWO success rules — one deciding whether the call RAISES, one
    deciding how it is BADGED in the activity log — and they disagreed on a
    reachable input. The run failed while the log showed a green call with no
    error: the log at its least trustworthy exactly when it is being relied on.

    There is now ONE ``verdict`` per envelope, consumed by both. This asserts the
    two OBSERVABLE consequences agree for every envelope and every input, which
    is the property that actually matters.
    """
    cases = [
        # (envelope, body, expected_ok)
        (STATUS_DICT, {"Status": "Success", "ResultTable": []}, True),
        (STATUS_DICT, {"Status": "Fail", "Message": "nope"}, False),
        # The absent-key case the two old rules disagreed on.
        (STATUS_DICT, {"Message": "only a message"}, False),
        (STATUS_DICT, [], False),
        (ROW_ARRAY, [_creditor()], True),
        (ROW_ARRAY, [], True),  # zero masters is a legitimate empty result
        (ROW_ARRAY, [_creditor(status="Fail", **{"Message": "bad"})], False),
        (ROW_ARRAY, {"Message": "an error envelope"}, False),
    ]
    for envelope, body, expected in cases:
        # 1. the raise rule
        response = httpx.Response(200, json=body)
        raised = False
        try:
            AutoCountClient._unwrap(response, envelope)
        except AutoCountError:
            raised = True
        assert raised is (not expected), (envelope.key, body)
        # 2. the badge rule, from the SAME verdict
        assert envelope.verdict(body).ok is expected, (envelope.key, body)


def test_a_failing_master_row_is_badged_red_in_the_activity_log():
    """End to end through the real client: the vendor reports a per-row failure,
    the read raises, AND the leg logs ``ok=False`` carrying the vendor's own
    message. A green badge on a failed leg is the bug this prevents."""
    client = AutoCountClient(
        base_url="https://ac.example.com",
        app_id="app-1",
        user_id="ADMIN",
        password="secret",
        transport=MockTransport(
            [_rows([{"Status": "Fail", "Message": "Creditor read denied."}])]
        ),
    )
    with pytest.raises(AutoCountError) as exc:
        client.read("Creditor", {"AccNo": [], "RecordCount": 10}, envelope=ROW_ARRAY)
    assert "denied" in str(exc.value)

    legs = client.drain_calls()
    read_leg = [c for c in legs if c.path.endswith("/GetCreditor")][0]
    assert read_leg.ok is False
    assert "denied" in (read_leg.error_message or "")
    # …and the login leg beside it stays green under its OWN envelope: a bare
    # array is a SUCCESSFUL login and must not be badged red by a dict rule.
    assert [c for c in legs if c.path.endswith("/Login")][0].ok is True


def test_adding_an_envelope_needs_no_change_to_read_or_its_callers():
    """AC-14-03: the strategy is a registry lookup, not a branch."""
    from modules.autocount.envelopes import ResponseEnvelope, Unwrapped, Verdict, register_envelope

    class _Wrapped(ResponseEnvelope):
        key = "test_wrapped"

        def verdict(self, body):
            return Verdict(isinstance(body, dict) and "Payload" in body, "no payload")

        def unwrap(self, body):
            return Unwrapped(records=list(body["Payload"]), reported_total=7)

    register_envelope(_Wrapped())
    client = AutoCountClient(
        base_url="https://ac.example.com",
        app_id="app-1",
        user_id="ADMIN",
        password="secret",
        transport=MockTransport([httpx.Response(200, json={"Payload": [{"a": 1}]})]),
    )
    # Same signature, same call site.
    result = client.read(
        "Whatever", {"RecordCount": 5}, envelope=envelope_for("test_wrapped")
    )
    assert result.records == [{"a": 1}]
    assert result.reported_total == 7


def test_an_unregistered_envelope_is_a_loud_error():
    """A silent fallback would read masters through the GRN unwrap and fail every
    row with a misleading message."""
    with pytest.raises(UnknownEnvelope):
        envelope_for("does_not_exist")


# ── AC-14-05: the two master coercions ────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected", [("T", True), ("F", False), ("t", True), ("f", False), (True, True)]
)
def test_the_active_flag_becomes_a_real_bool(value, expected):
    assert t_f_bool(value) is expected


@pytest.mark.parametrize("value", ["Y", "1", "yes", "TRUE", "active", 1, 0, "X"])
def test_an_unrecognised_active_flag_fails_loudly_and_never_defaults(value):
    """AC-14-05. A silent ``False`` here would DEACTIVATE A LIVE SUPPLIER in the
    consumer, and nothing in either system would report a problem — so this
    transform is deliberately narrower than the lenient ``t_bool``."""
    with pytest.raises(TransformError) as exc:
        t_f_bool(value)
    assert "'T' or 'F'" in str(exc.value)


def test_the_slash_timestamp_parses_to_aware_utc():
    parsed = slash_datetime("2026/03/18 16:03:21")
    assert parsed == datetime(2026, 3, 18, 16, 3, 21, tzinfo=timezone.utc)
    assert parsed.tzinfo is timezone.utc  # house rule: never naive


def test_an_unparseable_timestamp_fails_that_field_by_name():
    with pytest.raises(TransformError) as exc:
        slash_datetime("18-03-2026")
    assert "2026/03/18 16:03:21" in str(exc.value)


def test_a_bad_active_flag_fails_only_its_own_record():
    """The named per-field error, and the sibling record entirely unaffected."""
    engine = MappingEngine(
        DEFAULT_SUPPLIER_MAPPING,
        entity_type=ENTITY_SUPPLIER,
        database_name="AED_VSOFT",
    )
    good, bad = engine.map_batch(
        [_creditor("1", "400-A"), _creditor("2", "400-B", is_active="MAYBE")]
    )
    assert good.ok is True
    assert bad.ok is False
    assert bad.record is None  # never a partial record
    problem = [e for e in bad.errors if e.field == "is_active"][0]
    assert problem.source_path == "IsActive"
    assert "400-B" in problem.message()


def test_a_blank_active_flag_fails_rather_than_reaching_the_consumer_as_true():
    """The strict transform + the required flag, working as a pair: blank is
    'absent' to the transform, and the seeded row's ``is_required`` is what stops
    it falling through to the consumer's ``is_active: bool = True`` default."""
    engine = MappingEngine(
        DEFAULT_SUPPLIER_MAPPING,
        entity_type=ENTITY_SUPPLIER,
        database_name="AED_VSOFT",
    )
    mapped = engine.map_document(_creditor(is_active=""))
    assert mapped.ok is False
    assert [e for e in mapped.errors if e.field == "is_active"]


# ── AC-14-10/11: company-qualified identity ───────────────────────────────────


def test_the_source_ref_is_company_qualified():
    assert company_qualified_identity(_creditor("1"), "AED_VSOFT") == "AED_VSOFT:1"


def test_the_same_autokey_in_two_companies_does_not_collide():
    """AC-14-10, the whole reason for the prefix.

    ``AutoKey`` is a PER-COMPANY primary key, so ``AutoKey=1`` exists in every
    AutoCount company — while the consumer's uniqueness is
    ``(source_system, entity_type, source_ref)`` with NO company dimension. An
    unqualified ref means company B's first supplier silently overwrites
    company A's.
    """
    a = MappingEngine(
        DEFAULT_SUPPLIER_MAPPING, entity_type=ENTITY_SUPPLIER, database_name="AED_A"
    ).map_document(_creditor("1", "400-A"))
    b = MappingEngine(
        DEFAULT_SUPPLIER_MAPPING, entity_type=ENTITY_SUPPLIER, database_name="AED_B"
    ).map_document(_creditor("1", "400-B"))

    assert a.record.source_ref == "AED_A:1"
    assert b.record.source_ref == "AED_B:1"
    assert a.record.source_ref != b.record.source_ref
    assert a.record.identity() != b.record.identity()


def test_identity_survives_a_business_code_renumber():
    """AC-14-11: the ref is stable across an AccNo change, so the consumer row is
    UPDATED rather than duplicated — and ``source_doc_no`` shows the new code."""
    engine = MappingEngine(
        DEFAULT_SUPPLIER_MAPPING, entity_type=ENTITY_SUPPLIER, database_name="AED_VSOFT"
    )
    before = engine.map_document(_creditor("7", "400-J001")).record
    after = engine.map_document(_creditor("7", "400-Z999")).record

    assert before.source_ref == after.source_ref == "AED_VSOFT:7"
    assert before.source_doc_no == "400-J001"
    assert after.source_doc_no == "400-Z999"


def test_a_record_without_an_autokey_fails_by_name_rather_than_minting_a_bad_ref():
    engine = MappingEngine(
        DEFAULT_SUPPLIER_MAPPING, entity_type=ENTITY_SUPPLIER, database_name="AED_VSOFT"
    )
    mapped = engine.map_document(_creditor(**{"Data": []}))
    assert mapped.ok is False
    problem = [e for e in mapped.errors if e.field == "source_ref"][0]
    assert problem.source_path == "Data.0.AutoKey"


def test_an_unknown_company_name_refuses_to_mint_an_unqualified_ref():
    """Failing closed is the point: an unqualified ref would look fine and
    collide with another company later."""
    with pytest.raises(IdentityError):
        company_qualified_identity(_creditor("1"), "")


# ── AC-14-13/14: only fields the consumer persists ────────────────────────────


def test_the_canonical_supplier_claims_only_what_sorento_persists():
    """AC-14-13. Sorento ACCEPTS seven address fields on ``CanonicalSupplier``
    and ``_supplier_columns`` writes none of them, so sending them would have us
    report a sync that did not happen."""
    payload = CanonicalSupplier(source_ref="AED:1", code="400-A", name="A").sink_payload()
    assert set(payload) == {
        "source_ref",
        "source_doc_no",
        "code",
        "name",
        "email",
        "is_active",
    }


def test_no_payment_terms_field_exists_on_either_master():
    """AC-14-12: ``payment_terms_code`` is an UNCONDITIONAL permanent-retryable
    in the consumer, so any value would build a queue that can never drain."""
    for model in (CanonicalSupplier, CanonicalCustomer):
        assert "payment_terms_code" not in model.model_fields
        assert "payment_terms_days" not in model.model_fields
        assert "payment_terms_code" not in model.SINK_FIELDS
        assert "payment_terms_days" not in model.SINK_FIELDS


def test_every_field_we_send_is_one_sorento_defines():
    """AC-14-14: caught by OUR validation, not by a round-trip. Sorento sets
    ``extra="forbid"``, so an invented key is a hard per-record rejection."""
    sorento_supplier = {
        "source_ref", "source_doc_no", "code", "name", "contact_name", "email",
        "phone_number", "address_line1", "address_line2", "city", "state",
        "postal_code", "country", "payment_terms_days", "payment_terms_code",
        "is_active",
    }
    sorento_customer = {
        "source_ref", "source_doc_no", "code", "name", "email", "phone_number",
        "registration_number", "tax_id", "credit_limit", "payment_terms_days",
        "payment_terms_code", "country", "is_active",
    }
    assert set(CanonicalSupplier.SINK_FIELDS) <= sorento_supplier
    assert set(CanonicalCustomer.SINK_FIELDS) <= sorento_customer


def test_the_sink_payload_strips_our_own_provenance_and_local_fields():
    record = CanonicalCustomer(
        source_ref="AED:1",
        code="300-C",
        name="C",
        last_modified=datetime(2026, 3, 18, tzinfo=timezone.utc),
        extras={"anything": 1},
    )
    payload = record.sink_payload()
    for ours in ("source_system", "entity_type", "last_modified", "extras"):
        assert ours not in payload


# ── AC-14-05 end to end: a real master row through the real mapping ───────────


def test_a_creditor_row_maps_to_a_canonical_supplier():
    engine = MappingEngine(
        DEFAULT_SUPPLIER_MAPPING, entity_type=ENTITY_SUPPLIER, database_name="AED_VSOFT"
    )
    record = engine.map_document(_creditor("1", "400-J001")).record

    assert isinstance(record, CanonicalSupplier)
    assert record.source_ref == "AED_VSOFT:1"
    assert record.code == "400-J001"
    assert record.name == "Jaya Trading Sdn Bhd"
    assert record.email == "ap@jaya.example"
    assert record.is_active is True  # a real bool, from "T"
    assert record.last_modified == datetime(2026, 3, 18, 16, 3, 21, tzinfo=timezone.utc)


def test_a_debtor_row_maps_to_a_canonical_customer_with_its_extra_fields():
    engine = MappingEngine(
        DEFAULT_CUSTOMER_MAPPING, entity_type=ENTITY_CUSTOMER, database_name="AED_VSOFT"
    )
    record = engine.map_document(_debtor("9", "300-C001")).record

    assert isinstance(record, CanonicalCustomer)
    assert record.source_ref == "AED_VSOFT:9"
    assert record.phone_number == "+60123456789"
    assert record.tax_id == "IG12345678900"
    assert record.credit_limit == Decimal("25000.00000000")


def test_a_master_record_has_no_lines_attribute_to_half_fill():
    """Masters are flat. The profile carries no line model, so there is no empty
    ``lines`` bag for a later step to misread as "a document with no lines"."""
    record = MappingEngine(
        DEFAULT_SUPPLIER_MAPPING, entity_type=ENTITY_SUPPLIER, database_name="AED_VSOFT"
    ).map_document(_creditor()).record
    assert isinstance(record, CanonicalSupplier)
    assert "lines" not in CanonicalSupplier.model_fields


# ── AC-14-25: the unbounded initial load ──────────────────────────────────────


def _master_source(reads, *, initial_load=INITIAL_LOAD_FULL, record_cap=5000):
    client = AutoCountClient(
        base_url="https://ac.example.com",
        app_id="app-1",
        user_id="ADMIN",
        password="secret",
        transport=MockTransport(reads),
    )
    return AutoCountReadSource(
        client,
        entity_type=ENTITY_SUPPLIER,
        vendor_entity="Creditor",
        record_cap=record_cap,
        envelope=ENVELOPE_ROW_ARRAY,
        initial_load=initial_load,
        identifier_key="AccNo",
        last_modified_path="Data.0.LastModified",
    )


def test_the_first_master_fetch_sends_no_lower_bound_at_all():
    """AC-14-25 — the measured failure this prevents.

    Against slice 1's 30-day default, a live probe returned **1 of 106**
    Creditors and **2 of 172** Debtors; even 365 days missed 4 and 15. A master
    list is a standing set to be mirrored, not a document stream to be windowed,
    so the first pull must be unbounded. A lookback here imports ~1% and reports
    success — the most dangerous failure available, because nothing looks wrong.
    """
    source = _master_source([_rows([_creditor("1")])])
    start, _end = source.window(Watermark())
    assert start is None

    source.fetch_changes(Watermark())
    sent = source.client._transport.requests[-1]["json"]
    assert "LastModifiedFrom" not in sent
    assert "LastModifiedTo" not in sent
    assert isinstance(sent["AccNo"], list)  # a scalar is the silent-full-scan trap


def test_the_initial_lookback_does_not_apply_to_a_full_entity():
    source = _master_source([_rows([])])
    source.lookback_days = 30
    assert source.window(Watermark())[0] is None


def test_once_a_watermark_exists_a_full_entity_deltas_exactly_as_before():
    """The handover: ``full`` costs ONE unbounded read, not a permanent one."""
    source = _master_source([_rows([_creditor("1")])])
    mark = Watermark(last_modified_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
    start, _end = source.window(mark)
    assert start == datetime(2026, 3, 1, tzinfo=timezone.utc)

    source.fetch_changes(mark)
    sent = source.client._transport.requests[-1]["json"]
    assert sent["LastModifiedFrom"] == "2026/03/01"
    assert "LastModifiedTo" in sent


def test_a_windowed_entity_is_unchanged_by_the_new_policy():
    """The GRN path must not move: a document stream IS naturally time-bounded
    and its lookback is correct."""
    source = _source([[_grn()]])
    assert source.initial_load == INITIAL_LOAD_WINDOWED
    start, end = source.window(Watermark())
    assert start is not None
    assert timedelta(days=29) < (end - start) < timedelta(days=31)


def test_an_unknown_initial_load_policy_is_a_loud_error():
    """Silently defaulting to ``windowed`` would give a master a 30-day first
    read and report the 1-of-106 result as a clean success."""
    with pytest.raises(UnknownInitialLoad):
        _master_source([], initial_load="whatever")


def test_the_master_watermark_reads_last_modified_from_the_nested_row():
    """AC-14-02. Reading the top level finds nothing, which would fail the window
    assertion on every row AND leave the watermark stuck at None forever — so
    every sync would be a full load and no delta would ever happen."""
    result = _master_source(
        [_rows([_creditor("1", last_modified="2026/03/18 16:03:21"),
                _creditor("2", last_modified="2026/05/02 08:00:00")])]
    ).fetch_changes(Watermark())
    assert result.max_last_modified == datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc)
    assert result.window_from is None  # unbounded, and honestly reported as such


def test_the_delta_window_is_still_asserted_for_masters():
    """AC-13-04a survives the nesting: a filter the server IGNORED still fails
    loudly, now reading the stamp from ``Data[0]``."""
    source = _master_source([_rows([_creditor("1", last_modified="2020/01/01 00:00:00")])])
    with pytest.raises(AutoCountError):
        source.fetch_changes(
            Watermark(last_modified_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        )


# ── AC-14-26: a count is never reported without its denominator ───────────────


def test_the_fetch_reports_what_the_vendor_says_is_available():
    result = _master_source(
        [_rows([_creditor("1", record_count="1 of 106")])]
    ).fetch_changes(Watermark())
    assert len(result.records) == 1
    assert result.reported_total == 106


def test_a_plain_integer_marker_is_read_too_and_an_absent_one_is_not_invented():
    from modules.autocount.envelopes import _reported_total

    assert _reported_total(106) == 106
    assert _reported_total("106") == 106
    assert _reported_total("1 of 106") == 106
    # Absent must read as "the vendor did not say", NEVER as zero.
    assert _reported_total(None) is None
    assert _reported_total("") is None
    assert _reported_total("lots") is None


def test_the_sync_result_states_the_fetched_count_beside_the_reported_total(db, transports):
    """AC-14-26: "2 records" alone cannot be told apart from "nothing changed"
    and "the window excluded 170 of 172" — and the second looks exactly like
    success while being near-total data loss."""
    company = _company(db, transports)
    _queue(db, transports, company, _rows([_creditor("1"), _creditor("2")]))
    job = _run_sync(db, company, entity_type=ENTITY_SUPPLIER)

    assert job.status == JOB_NEEDS_REVIEW
    assert job.result_json["fetched"] == 2
    assert job.result_json["vendorReportedTotal"] == 106
    assert job.result_json["initialLoad"] == INITIAL_LOAD_FULL
    assert job.result_json["unboundedInitialLoad"] is True


# ── the wiring: a master sync end to end through the real handler ─────────────


def test_a_company_is_seeded_for_the_two_master_entities(db, transports):
    """AC-14-01: only entities with a CONFIRMED vendor payload are offered.
    Stock/Item/UOM return HTTP 500 with an empty Message on this wrapper build,
    so they are ABSENT from the picker rather than shown-and-disabled."""
    company = _company(db, transports)
    configured = {c.entity_type for c in CompanyService(db).entity_configs(DEFAULT_TENANT_ID, company.id)}
    assert configured == {ENTITY_GOODS_RECEIVED_NOTE, ENTITY_SUPPLIER, ENTITY_CUSTOMER}
    for absent in ("product", "stock_item", "unit_of_measure", "warehouse"):
        assert absent not in configured


def test_the_master_entities_are_seeded_with_the_right_envelope_and_policy(db, transports):
    company = _company(db, transports)
    supplier = _config_for(db, company, ENTITY_SUPPLIER)
    grn = _grn_config(db, company)

    assert supplier.envelope == ENVELOPE_ROW_ARRAY
    assert supplier.initial_load == INITIAL_LOAD_FULL
    # The GRN row is untouched by any of this.
    assert grn.envelope == ENVELOPE_STATUS_DICT
    assert grn.initial_load == INITIAL_LOAD_WINDOWED


def test_a_master_sync_stages_company_qualified_records(db, transports):
    company = _company(db, transports, database_name="AED_VSOFT")
    _queue(db, transports, company, _rows([_creditor("1", "400-J001"), _creditor("2", "400-K002")]))
    job = _run_sync(db, company, entity_type=ENTITY_SUPPLIER)

    assert job.status == JOB_NEEDS_REVIEW
    staged = StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert sorted(r.source_ref for r in staged) == ["AED_VSOFT:1", "AED_VSOFT:2"]
    # ``doc_no`` shows the ACCOUNT number, so the row is recognisable to a human
    # (AC-14-10) — read from the mapped result, since a master's attribute is
    # ``source_doc_no`` and reaching for ``record.doc_no`` would silently be None.
    assert sorted(r.doc_no for r in staged) == ["400-J001", "400-K002"]
    assert staged[0].canonical_json["entity_type"] == ENTITY_SUPPLIER


def test_two_companies_stage_the_same_autokey_without_colliding(db, transports):
    """The end-to-end form of AC-14-10, through the real handler."""
    a = _company(db, transports, database_name="AED_A")
    b = _company(db, transports, database_name="AED_B")
    _queue(db, transports, a, _rows([_creditor("1", "400-A")]))
    _queue(db, transports, b, _rows([_creditor("1", "400-B")]))

    job_a = _run_sync(db, a, entity_type=ENTITY_SUPPLIER)
    job_b = _run_sync(db, b, entity_type=ENTITY_SUPPLIER)

    refs_a = [r.source_ref for r in StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, a.id, job_a.id)]
    refs_b = [r.source_ref for r in StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, b.id, job_b.id)]
    assert refs_a == ["AED_A:1"]
    assert refs_b == ["AED_B:1"]


def test_the_second_master_sync_is_a_delta_off_the_advanced_watermark(db, transports):
    """The handover, through the handler: run one is unbounded, run two carries
    the watermark the first run established from ``Data[0].LastModified``."""
    company = _company(db, transports)
    _queue(db, transports, company, _rows([_creditor("1", last_modified="2026/05/02 08:00:00")]))
    _run_sync(db, company, entity_type=ENTITY_SUPPLIER)

    mark = WatermarkRepository(db).get_or_create(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER)
    assert mark.last_modified_at == datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc)

    _queue(db, transports, company, _rows([]))
    _run_sync(db, company, entity_type=ENTITY_SUPPLIER)
    sent = transports[company.connection_id].requests[-1]["json"]
    assert sent["LastModifiedFrom"] == "2026/05/02"


# ── the backfill (module Alembic never runs under pytest) ─────────────────────


def test_the_migration_adds_both_columns_with_a_default_that_fills_existing_rows():
    """Where the backfill of pre-existing rows ACTUALLY happens.

        !!  THE ``server_default`` ON THE ADD IS THE BACKFILL.  !!

    On the only ordering where these columns are genuinely absent — a host
    already stamped at 0002, where ``create_all`` cannot ALTER an existing table
    — ``ADD COLUMN ... NOT NULL DEFAULT 'status_dict'`` is what gives every
    existing GRN row its value, atomically, in the same statement. Dropping the
    default in a later "tidy-up" would leave those rows stranded against a NOT
    NULL column, so it is asserted rather than trusted.

    Asserted by READING the revision, because pytest cannot run it: conftest
    builds the schema with ``create_all`` and ``run_module_migrations`` is a
    Postgres-only no-op, so nothing in this suite executes the file. The DDL
    itself is gated by review plus a real ``alembic upgrade head``.
    """
    import importlib.util
    import pathlib
    import types

    # A module name cannot start with a digit, so load the revision by path.
    spec = importlib.util.spec_from_file_location(
        "_ac_rev_0003",
        pathlib.Path(__file__).resolve().parents[1]
        / "modules/autocount/alembic/versions/0003_autocount_masters.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert len(module.revision) <= 32  # alembic_version.version_num is VARCHAR(32)
    assert module.down_revision == "0002_autocount_grn"

    # Drive the real ``upgrade()`` with the DB-touching seams stubbed, so what is
    # asserted is what the revision actually declares.
    added: Dict[str, Any] = {}
    module.add_column = lambda name, column: added.__setitem__(name, column)
    module.op = types.SimpleNamespace(get_bind=lambda: None)
    module.backfill_entity_config_defaults = lambda bind, schema=None: 0
    module.upgrade()

    assert set(added) == {"envelope", "initial_load"}
    assert added["envelope"].server_default.arg == ENVELOPE_STATUS_DICT
    assert added["initial_load"].server_default.arg == INITIAL_LOAD_WINDOWED
    # NOT NULL matters as much as the default: together they are what makes the
    # fill atomic on the ADD.
    assert added["envelope"].nullable is False
    assert added["initial_load"].nullable is False


def test_the_backfill_repairs_a_row_left_without_a_value(db, transports):
    """The belt-and-braces half, for the orderings the ADD's default cannot cover
    (a column added nullable out of band, or a row written empty).

        !!  A TRULY ``NULL`` ROW IS UNREACHABLE HERE, AND THAT IS THE POINT.  !!

    Both columns are NOT NULL in the model AND in the migration, so SQLite
    refuses a NULL and Postgres never produces one. The reachable empty state is
    ``''`` — which is why the backfill's WHERE covers both rather than just
    ``IS NULL``.
    """
    company = _company(db, transports)
    stranded = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID,
        company_id=company.id,
        entity_type="legacy_entity",
    )
    db.add(stranded)
    db.commit()
    # Emptied at the SQL level. Passing ``''`` through the ORM would work too,
    # but going via SQL is the honest simulation: a row that predates the column
    # was never touched by the model's python-side ``default=``.
    db.execute(
        sa.text(
            "UPDATE ac_entity_config SET envelope = '', initial_load = '' "
            "WHERE id = :id"
        ),
        {"id": stranded.id},
    )
    db.commit()

    touched = backfill_entity_config_defaults(db, schema=None)
    db.expire_all()
    assert touched >= 2  # one per column on the stranded row

    repaired = db.get(AcEntityConfig, stranded.id)
    # A pre-0.2.0 row is always a GRN one — those were the only semantics that
    # existed — so these are the values it must end up with.
    assert repaired.envelope == ENVELOPE_STATUS_DICT
    assert repaired.initial_load == INITIAL_LOAD_WINDOWED


def test_the_backfill_never_overwrites_a_row_that_already_has_a_value(db, transports):
    """It must be safe to run in either bootstrap order, and repeatedly — a
    master row already seeded ``row_array``/``full`` must survive untouched."""
    company = _company(db, transports)
    supplier = _config_for(db, company, ENTITY_SUPPLIER)

    backfill_entity_config_defaults(db, schema=None)
    backfill_entity_config_defaults(db, schema=None)
    db.expire_all()

    fresh = db.get(AcEntityConfig, supplier.id)
    assert fresh.envelope == ENVELOPE_ROW_ARRAY
    assert fresh.initial_load == INITIAL_LOAD_FULL


def test_the_version_upgrade_seeds_masters_onto_a_company_that_already_exists(db, transports):
    """The backfill that matters for EXISTING tenants: ``seed_company_defaults``
    runs once, when a company is registered, so a company registered under 0.1.0
    was seeded GRN-only. Without this pass the two master entities are silently
    invisible to exactly the tenants already using the module."""
    from modules.autocount.bootstrap import update_tenant
    from modules.autocount.repositories import EntityConfigRepository, FieldMappingRepository

    company = _company(db, transports)
    # Simulate the 0.1.0 world: masters were never seeded for this company.
    for entity_type in (ENTITY_SUPPLIER, ENTITY_CUSTOMER):
        config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, entity_type)
        db.delete(config)
        for row in FieldMappingRepository(db).list(DEFAULT_TENANT_ID, company.id, entity_type):
            db.delete(row)
    db.commit()
    assert {c.entity_type for c in CompanyService(db).entity_configs(DEFAULT_TENANT_ID, company.id)} == {
        ENTITY_GOODS_RECEIVED_NOTE
    }

    update_tenant(db, DEFAULT_TENANT_ID, "0.1.0")
    db.commit()

    configured = {c.entity_type for c in CompanyService(db).entity_configs(DEFAULT_TENANT_ID, company.id)}
    assert configured == {ENTITY_GOODS_RECEIVED_NOTE, ENTITY_SUPPLIER, ENTITY_CUSTOMER}
    assert FieldMappingRepository(db).count(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER) == len(
        DEFAULT_SUPPLIER_MAPPING
    )


def test_the_version_upgrade_leaves_an_operators_edited_mapping_alone(db, transports):
    """Re-running the seed must never revert an operator's edits — every branch
    in it is seed-if-absent, and this is the assertion that keeps it that way."""
    from modules.autocount.bootstrap import update_tenant
    from modules.autocount.repositories import FieldMappingRepository

    company = _company(db, transports)
    row = FieldMappingRepository(db).list(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER)[0]
    row.source_path = "SomeCustomField"
    db.commit()

    update_tenant(db, DEFAULT_TENANT_ID, "0.1.0")
    db.commit()
    db.expire_all()

    assert db.get(AcFieldMapping, row.id).source_path == "SomeCustomField"


# ── the empty-Status contract (live-verified 2026-07-21) ─────────────────────


@pytest.mark.parametrize(
    "status, expect_ok",
    [
        ("", True),        # what every healthy live master row actually carries
        ("   ", True),     # whitespace is still silence
        ("Success", True), # tolerated, though the live instance never sends it
        ("Fail", False),   # an affirmative failure
        ("Error", False),
    ],
)
def test_row_array_treats_empty_status_as_success(status, expect_ok):
    """Masters do NOT use GRN's ``Status: "Success"`` convention.

    Verified against the live demo instance: **all 106 Creditor rows and all 172
    Debtor rows return ``Status: ''`` with ``Message: ''``**. Empty IS healthy.

    This test exists because the opposite rule shipped first. ``RowArrayEnvelope``
    mirrored ``StatusDictEnvelope``'s ``!= "success" -> fail``, which rejects every
    valid row the vendor sends. It survived 205 mocked tests because the fixture
    ALSO defaulted to ``"Success"`` -- the mock and the code shared one wrong
    assumption, so they agreed with each other and not with reality.

    The lesson the parametrisation encodes: only an AFFIRMATIVE non-success token
    is a failure. Silence means fine.
    """
    verdict = ROW_ARRAY.verdict([_creditor(status=status)])
    assert verdict.ok is expect_ok


def test_row_array_failure_names_the_status_when_no_message_is_given():
    """A failing row with no ``Message`` must still say WHAT the vendor reported,
    otherwise the operator gets a generic sentence and has to go read the raw
    payload to learn anything."""
    verdict = ROW_ARRAY.verdict([_creditor(status="Fail")])
    assert verdict.ok is False
    assert "Fail" in (verdict.message or "")


# ══════════════════════════════════════════════════════════════════════════════
# Hop 2 — the Sorento push target wiring (plan 14 Tasks A–E)
#
# Slice 1 hardcoded the logging no-op. These pin the wiring that makes an
# operator able to configure a Sorento target and approve a REAL push: the sink
# resolver, the dry-run preview (writes nothing), the batch approve path, and
# the backfill for existing companies.
# ══════════════════════════════════════════════════════════════════════════════

import json as _json  # noqa: E402

from modules.autocount.backfill import (  # noqa: E402
    backfill_sink_impl_defaults,
    default_schema,
)
from modules.autocount.models import (  # noqa: E402
    SINK_IMPL_LOGGING,
    SINK_IMPL_SORENTO,
)
from modules.autocount.services import (  # noqa: E402
    AutocountServiceError,
    ConnectionNotFound,
    PreviewFailed,
    PushFailed,
)
from modules.autocount.sinks import UnknownSinkImpl  # noqa: E402
from modules.autocount.sinks_sorento import SorentoSink  # noqa: E402
from modules.autocount.sorento_provider import SORENTO_PROVIDER_KEY  # noqa: E402


def _sorento_connection(
    db, *, tenant_id: str = DEFAULT_TENANT_ID, api_key: str = "sk_test",
    base_url: str = "http://sorento.test",
) -> Connection:
    conn = Connection(
        tenant_id=tenant_id,
        provider=SORENTO_PROVIDER_KEY,
        type="consumer",
        name="Sorento",
        config_json={"baseUrl": base_url},
        credentials_json=encrypt_secret({"apiKey": api_key}),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _point_at_sorento(db, company, conn) -> None:
    CompanyService(db).set_sink_target(
        company.tenant_id, company.id,
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=conn.id,
    )
    db.refresh(company)


def _staged_supplier_job(
    db, company, *, refs=("AED_VSOFT:1",), tenant_id: str = DEFAULT_TENANT_ID
) -> BackgroundJob:
    """A needs_review autocount_sync job for suppliers, with STAGED canonical
    supplier rows — the exact state an operator approves from."""
    job = BackgroundJob(
        tenant_id=tenant_id,
        type=AUTOCOUNT_SYNC,
        status=JOB_NEEDS_REVIEW,
        payload_json={"companyId": company.id, "entityType": ENTITY_SUPPLIER},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    repo = StagedRecordRepository(db)
    for i, ref in enumerate(refs, start=1):
        record = CanonicalSupplier(
            source_ref=ref, source_doc_no=f"400-{i}", code=f"400-{i}",
            name=f"NAME{i}", email=None, is_active=True,
        )
        repo.add(
            AcStagedRecord(
                tenant_id=tenant_id, company_id=company.id,
                entity_type=ENTITY_SUPPLIER, job_id=job.id, source_ref=ref,
                canonical_json=record.comparable(), status=STAGED,
            )
        )
    db.commit()
    return job


class _SorentoRecorder:
    """Records every request the resolved SorentoSink makes and serves a scripted
    response, so a test asserts on exactly what crossed the wire — and that a
    preview never carried a real (non-dry-run) write."""

    def __init__(self) -> None:
        self.requests: List[httpx.Request] = []
        self.responder = lambda r: httpx.Response(
            200, json={"summary": {}, "records": []}
        )
        self._transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)


@pytest.fixture
def sorento_sink(monkeypatch):
    """Inject ONE recording MockTransport into every SorentoSink the resolver
    builds — no socket ever opens, and the request log is inspectable."""
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    rec = _SorentoRecorder()

    def fake(config, credentials, *, entity_type, transport=None):
        return real(config, credentials, entity_type=entity_type, transport=rec._transport)

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)
    return rec


def _created(request: httpx.Request, outcome: str = "created") -> httpx.Response:
    body = _json.loads(request.content)
    recs = [
        {"source_ref": r["source_ref"], "outcome": outcome,
         "entity_id": f"id-{r['source_ref']}"}
        for r in body["records"]
    ]
    n = len(recs)
    return httpx.Response(200, json={
        "summary": {"total": n, "created": n if outcome == "created" else 0,
                    "updated": n if outcome == "updated" else 0,
                    "failed": 0, "retryable": 0},
        "records": recs,
    })


# ── sink resolution (Task C) ──────────────────────────────────────────────────


def test_a_new_company_defaults_to_the_logging_sink(db, transports):
    company = _company(db, transports)
    assert company.sink_impl == SINK_IMPL_LOGGING
    assert company.sink_connection_id is None


def test_the_resolver_returns_the_logging_sink_by_default(db, transports):
    company = _company(db, transports)
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_SUPPLIER)
    assert sink.name == SINK_IMPL_LOGGING


def test_the_resolver_builds_a_sorento_sink_when_configured(db, transports):
    company = _company(db, transports)
    conn = _sorento_connection(db)
    _point_at_sorento(db, company, conn)
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_SUPPLIER)
    assert isinstance(sink, SorentoSink)
    assert sink.name == SINK_IMPL_SORENTO
    assert sink.entity_type == ENTITY_SUPPLIER


def test_sorento_without_a_connection_is_a_clean_error(db, transports):
    company = _company(db, transports)
    company.sink_impl = SINK_IMPL_SORENTO
    company.sink_connection_id = None
    db.commit()
    with pytest.raises(AutocountServiceError):
        CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_SUPPLIER)


def test_an_unknown_sink_impl_is_a_loud_error_never_a_silent_fallback(db, transports):
    company = _company(db, transports)
    company.sink_impl = "martians"
    db.commit()
    with pytest.raises(UnknownSinkImpl):
        CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_SUPPLIER)


def test_an_undecryptable_sorento_key_is_a_clean_error_not_a_500(db, transports):
    from cryptography.fernet import Fernet

    company = _company(db, transports)
    conn = _sorento_connection(db)
    _point_at_sorento(db, company, conn)
    # A valid Fernet token minted under a FOREIGN key — the process key cannot
    # read it, so decrypt raises InvalidToken, which must surface CLEAN.
    conn.credentials_json = Fernet(Fernet.generate_key()).encrypt(b'{"apiKey":"x"}').decode()
    db.commit()
    with pytest.raises(AutocountServiceError):
        CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_SUPPLIER)


def test_set_sink_target_rejects_a_foreign_connection(db, transports):
    company = _company(db, transports)
    foreign = _sorento_connection(db, tenant_id=OTHER_TENANT_ID)
    with pytest.raises(ConnectionNotFound):
        CompanyService(db).set_sink_target(
            DEFAULT_TENANT_ID, company.id,
            sink_impl=SINK_IMPL_SORENTO, sink_connection_id=foreign.id,
        )


def test_switching_back_to_logging_clears_the_connection(db, transports):
    company = _company(db, transports)
    conn = _sorento_connection(db)
    _point_at_sorento(db, company, conn)
    assert company.sink_connection_id == conn.id
    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id, sink_impl=SINK_IMPL_LOGGING
    )
    db.refresh(company)
    assert company.sink_impl == SINK_IMPL_LOGGING
    assert company.sink_connection_id is None


# ── dry-run preview (Task D, AC-14-20/21) ─────────────────────────────────────


def test_preview_returns_predictions_and_writes_nothing(db, transports, sorento_sink):
    company = _company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    job = _staged_supplier_job(db, company, refs=("AED_VSOFT:1",))

    def responder(request):
        # AC-14-21: the prediction is Sorento's OWN dry run — and it must be a
        # dry run, never a real write.
        assert request.url.params.get("dry_run") == "true"
        body = _json.loads(request.content)
        recs = [
            {"source_ref": r["source_ref"], "outcome": "updated", "entity_id": "s1",
             "diff": {"name": {"current": "OLD", "incoming": "NAME1"}}}
            for r in body["records"]
        ]
        return httpx.Response(200, json={
            "summary": {"total": 1, "created": 0, "updated": 1, "failed": 0, "retryable": 0},
            "records": recs,
        })

    sorento_sink.responder = responder

    result = SyncService(db).preview(DEFAULT_TENANT_ID, job.id)

    assert result["previewable"] is True
    assert result["summary"]["updated"] == 1
    [pred] = result["predictions"]
    assert pred["outcome"] == "updated"
    assert pred["changesLiveData"] is True
    # Exactly one call, and it carried ?dry_run=true (writes nothing).
    assert len(sorento_sink.requests) == 1
    assert sorento_sink.requests[0].url.params.get("dry_run") == "true"
    # The staged rows and the job are untouched by a preview.
    rows = StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert {r.status for r in rows} == {STAGED}
    fresh = db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    assert fresh.status == JOB_NEEDS_REVIEW


def test_preview_on_a_logging_company_offers_nothing_to_preview(db, transports):
    company = _company(db, transports)  # logging default
    job = _staged_supplier_job(db, company)
    result = SyncService(db).preview(DEFAULT_TENANT_ID, job.id)
    assert result["previewable"] is False
    assert "nothing to preview" in result["reason"].lower()


def test_a_failing_dry_run_refuses_to_offer_approval(db, transports, sorento_sink):
    company = _company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    job = _staged_supplier_job(db, company)
    sorento_sink.responder = lambda r: httpx.Response(500, json={"message": "boom"})
    with pytest.raises(PreviewFailed):
        SyncService(db).preview(DEFAULT_TENANT_ID, job.id)
    # Nothing was written, and the job stays reviewable.
    fresh = db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    assert fresh.status == JOB_NEEDS_REVIEW


# ── approve via the real sink (Task E, AC-14-16/40/41) ────────────────────────


def test_approve_via_sorento_delivers_and_marks_pushed(db, transports, sorento_sink):
    company = _company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    job = _staged_supplier_job(db, company, refs=("AED_VSOFT:1", "AED_VSOFT:2"))

    def responder(request):
        # A real push, never a dry run.
        assert request.url.params.get("dry_run") is None
        return _created(request)

    sorento_sink.responder = responder

    result = SyncService(db).approve(DEFAULT_TENANT_ID, job.id, actor_user_id="u1")

    assert result["pushed"] == 2
    assert result["sink"] == SINK_IMPL_SORENTO
    assert result["delivered"] is True  # honest: really delivered (AC-14-41)
    assert "sinkNote" not in result  # no slice-1 no-op disclaimer on a real push
    rows = StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert {r.status for r in rows} == {STAGED_PUSHED}
    assert all(r.pushed_at is not None for r in rows)
    # ONE batch HTTP call for two records — not two per-record calls.
    assert len(sorento_sink.requests) == 1
    fresh = db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    assert fresh.status == JOB_DONE


def test_a_batch_error_releases_to_review_and_pushes_nothing(db, transports, sorento_sink):
    company = _company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    job = _staged_supplier_job(db, company, refs=("AED_VSOFT:1", "AED_VSOFT:2"))
    # A batch-level 500 (a guard-rail error before their fix lands) — nothing
    # resolved, so nothing may be marked pushed.
    sorento_sink.responder = lambda r: httpx.Response(500, json={"message": "guardrail"})

    with pytest.raises(PushFailed):
        SyncService(db).approve(DEFAULT_TENANT_ID, job.id)

    fresh = db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    assert fresh.status == JOB_NEEDS_REVIEW  # re-approvable, never stranded
    rows = StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    assert {r.status for r in rows} == {STAGED}  # nothing pushed


def test_a_rate_limit_beyond_the_budget_releases_to_review(db, transports, sorento_sink, monkeypatch):
    monkeypatch.setattr("modules.autocount.sinks_sorento.time.sleep", lambda *_: None)
    company = _company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    job = _staged_supplier_job(db, company)
    sorento_sink.responder = lambda r: httpx.Response(429, headers={"Retry-After": "1"}, json={})

    with pytest.raises(PushFailed):
        SyncService(db).approve(DEFAULT_TENANT_ID, job.id)
    fresh = db.query(BackgroundJob).filter(BackgroundJob.id == job.id).first()
    assert fresh.status == JOB_NEEDS_REVIEW


def test_a_per_record_rejection_is_not_reported_as_delivered(db, transports, sorento_sink):
    company = _company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    job = _staged_supplier_job(db, company, refs=("AED_VSOFT:1", "AED_VSOFT:2"))

    # Keyed by source_ref, NOT position — the two staged rows share a timestamp
    # and carry random-uuid ids, so their request order is nondeterministic.
    rejected_ref = "AED_VSOFT:2"

    def responder(request):
        body = _json.loads(request.content)
        recs = []
        for r in body["records"]:
            ref = r["source_ref"]
            if ref == rejected_ref:
                recs.append({"source_ref": ref, "outcome": "failed",
                             "entity_id": None, "errors": {"name": "bad"}})
            else:
                recs.append({"source_ref": ref, "outcome": "created",
                             "entity_id": f"id-{ref}"})
        return httpx.Response(200, json={
            "summary": {"total": 2, "created": 1, "updated": 0, "failed": 1, "retryable": 0},
            "records": recs,
        })

    sorento_sink.responder = responder
    result = SyncService(db).approve(DEFAULT_TENANT_ID, job.id)

    assert result["pushed"] == 1
    assert len(result["pushFailures"]) == 1
    # The delivered one is PUSHED; the rejected one stays STAGED (never faked).
    statuses = {
        r.source_ref: r.status
        for r in StagedRecordRepository(db).list_for_job(DEFAULT_TENANT_ID, company.id, job.id)
    }
    assert statuses == {"AED_VSOFT:1": STAGED_PUSHED, "AED_VSOFT:2": STAGED}


def test_double_click_approve_via_sorento_pushes_exactly_once(db, transports, sorento_sink):
    company = _company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    job = _staged_supplier_job(db, company, refs=("AED_VSOFT:1",))
    sorento_sink.responder = _created

    service = SyncService(db)
    first = service.approve(DEFAULT_TENANT_ID, job.id)
    second = service.approve(DEFAULT_TENANT_ID, job.id)

    assert first["pushed"] == 1
    assert second == first  # the second click is a no-op returning the original
    # And only ONE batch actually reached Sorento.
    assert len(sorento_sink.requests) == 1


# ── backfill for existing companies (Task B) ──────────────────────────────────


def test_the_sink_impl_backfill_fills_blank_rows(db, transports):
    company = _company(db, transports)
    # Simulate a company that predates the sink columns (blank, not NULL — the
    # column is NOT NULL, so a legacy create_all-first host lands it blank).
    db.execute(
        sa.text("UPDATE ac_company SET sink_impl = '' WHERE id = :id"),
        {"id": company.id},
    )
    db.commit()

    # Runs on the SESSION (the schema-translated bind), exactly as
    # ``update_tenant`` invokes it — never on a bare engine.
    touched = backfill_sink_impl_defaults(db, schema=default_schema(db.get_bind()))
    db.commit()
    db.refresh(company)

    assert touched >= 1
    assert company.sink_impl == SINK_IMPL_LOGGING


# ══════════════════════════════════════════════════════════════════════════════
#  slice 15 — review UI backend: jobs list, staged pagination, mapping read/write
#  (AC-15-02, AC-15-10/11, AC-15-40..43). Service + repository level, matching the
#  rest of this suite (every HTTP leg is mocked; nothing opens a socket).
# ══════════════════════════════════════════════════════════════════════════════

from modules.autocount import mapping_catalog  # noqa: E402
from modules.autocount.schemas import StagedRecordItem  # noqa: E402
from modules.autocount.services import (  # noqa: E402
    AutocountServiceError,
    EntityConfigNotFound,
    MappingWriteRow,
)


# ── Task 1: GET /autocount/jobs (list of sync batches) ────────────────────────


def test_jobs_list_is_tenant_scoped(db, transports):
    """A sync batch from another tenant must never appear (AC-15-02, the
    polymorphic-scope rule)."""
    mine = _company(db, transports, reads=[[_grn("1")]])
    _run_sync(db, mine)

    theirs = _company(
        db, transports, tenant_id=OTHER_TENANT_ID, database_name="OTHER_CO",
        reads=[[_grn("2")]],
    )
    _run_sync(db, theirs, tenant_id=OTHER_TENANT_ID)

    jobs, total = SyncService(db).list_jobs(DEFAULT_TENANT_ID)
    assert total == 1
    assert {j.company_id for j in jobs} == {mine.id}


def test_jobs_list_carries_company_label_and_entity(db, transports):
    company = _company(db, transports, reads=[[_grn("1")]])
    _run_sync(db, company)

    jobs, _total = SyncService(db).list_jobs(DEFAULT_TENANT_ID)
    item = jobs[0]
    assert item.company_id == company.id
    assert item.database_name == company.database_name
    assert item.company_name == company.name
    assert item.entity_type == ENTITY_GOODS_RECEIVED_NOTE
    assert item.status == JOB_NEEDS_REVIEW
    # A batch of one staged record — the counts the list column shows.
    assert item.progress_total >= 0


def test_jobs_list_status_filter(db, transports):
    a = _company(db, transports, database_name="CO_A", reads=[[_grn("1")]])
    done_job = _run_sync(db, a)
    SyncService(db).approve(DEFAULT_TENANT_ID, done_job.id)  # → done

    b = _company(db, transports, database_name="CO_B", reads=[[_grn("2")]])
    _run_sync(db, b)  # stays needs_review

    svc = SyncService(db)
    review, review_total = svc.list_jobs(DEFAULT_TENANT_ID, status="needs_review")
    done, done_total = svc.list_jobs(DEFAULT_TENANT_ID, status="done")
    everything, all_total = svc.list_jobs(DEFAULT_TENANT_ID, status="all")

    assert {j.status for j in review} == {JOB_NEEDS_REVIEW} and review_total == 1
    assert {j.status for j in done} == {JOB_DONE} and done_total == 1
    assert all_total == 2


def test_jobs_list_rejects_an_unknown_status(db, transports):
    with pytest.raises(AutocountServiceError):
        SyncService(db).list_jobs(DEFAULT_TENANT_ID, status="bogus")


def test_jobs_list_paginates_newest_first(db, transports):
    company = _company(db, transports, database_name="PAGED")
    for i in range(1, 4):
        _queue(db, transports, company, [_grn(str(i))])
        _run_sync(db, company)

    svc = SyncService(db)
    page0, total = svc.list_jobs(DEFAULT_TENANT_ID, page=0, page_size=2)
    page1, _t = svc.list_jobs(DEFAULT_TENANT_ID, page=1, page_size=2)
    assert total == 3
    assert len(page0) == 2 and len(page1) == 1
    # Newest first — no id repeats across pages.
    assert not ({j.job_id for j in page0} & {j.job_id for j in page1})


def test_jobs_list_filters_by_entity_type(db, transports):
    company = _company(db, transports)
    _queue(db, transports, company, [_grn("1")])
    _run_sync(db, company, entity_type=ENTITY_GOODS_RECEIVED_NOTE)
    _queue(db, transports, company, _rows([_creditor("1")]))
    _run_sync(db, company, entity_type=ENTITY_SUPPLIER)

    svc = SyncService(db)
    suppliers, sup_total = svc.list_jobs(DEFAULT_TENANT_ID, entity_type=ENTITY_SUPPLIER)
    assert sup_total == 1
    assert {j.entity_type for j in suppliers} == {ENTITY_SUPPLIER}


# ── Task 2: staged pagination + hasChanges + noChangeCount ────────────────────


def _resync_one_changed_one_unchanged(db, transports):
    company = _company(
        db, transports,
        reads=[[_grn("1", FinalTotal="100.00000000"),
                _grn("2", FinalTotal="200.00000000")]],
    )
    first = _run_sync(db, company)
    SyncService(db).approve(DEFAULT_TENANT_ID, first.id)
    _queue(db, transports, company, [
        _grn("1", FinalTotal="150.00000000", last_modified="2026/07/20 09:00:00"),
        _grn("2", FinalTotal="200.00000000", last_modified="2026/07/20 09:00:00"),
    ])
    return _run_sync(db, company)


def test_staged_page_counts_no_change_records(db, transports):
    """AC-15-11: a delta re-fetch stages records whose mapped fields did not
    change (only LastModified advanced). They must be COUNTED, not buried."""
    second = _resync_one_changed_one_unchanged(db, transports)
    _job, rows, total, filtered_total, no_change = SyncService(db).staged_page(
        DEFAULT_TENANT_ID, second.id
    )
    assert total == 2
    assert filtered_total == 2
    assert no_change == 1
    # hasChanges is surfaced per row (AC-15-10).
    flags = {StagedRecordItem.model_validate(r).hasChanges for r in rows}
    assert flags == {True, False}


def test_staged_page_changed_only_filter(db, transports):
    second = _resync_one_changed_one_unchanged(db, transports)
    _job, rows, _total, filtered_total, _nc = SyncService(db).staged_page(
        DEFAULT_TENANT_ID, second.id, changed=True
    )
    assert filtered_total == 1
    assert all(r.diff_json for r in rows)  # non-empty diff
    assert all(StagedRecordItem.model_validate(r).hasChanges for r in rows)


def test_staged_page_no_change_only_filter(db, transports):
    second = _resync_one_changed_one_unchanged(db, transports)
    _job, rows, _total, filtered_total, _nc = SyncService(db).staged_page(
        DEFAULT_TENANT_ID, second.id, changed=False
    )
    assert filtered_total == 1
    assert all(r.diff_json == {} for r in rows)
    assert not any(StagedRecordItem.model_validate(r).hasChanges for r in rows)


def test_staged_page_paginates(db, transports):
    grns = [_grn(str(i), FinalTotal=f"{i}00.00000000") for i in range(1, 6)]
    company = _company(db, transports, reads=[grns])
    job = _run_sync(db, company)

    svc = SyncService(db)
    _j, page0, total, _f, _nc = svc.staged_page(DEFAULT_TENANT_ID, job.id, page=0, page_size=2)
    _j, page2, _t, _f2, _nc2 = svc.staged_page(DEFAULT_TENANT_ID, job.id, page=2, page_size=2)
    assert total == 5
    assert len(page0) == 2 and len(page2) == 1


def test_staged_page_first_sync_records_all_have_changes(db, transports):
    """A first-sight record diffs as ``{"__new__": True}`` — that IS a change,
    never a no-change no-op."""
    company = _company(db, transports, reads=[[_grn("1"), _grn("2")]])
    job = _run_sync(db, company)
    _j, rows, total, _f, no_change = SyncService(db).staged_page(DEFAULT_TENANT_ID, job.id)
    assert total == 2 and no_change == 0
    assert all(StagedRecordItem.model_validate(r).hasChanges for r in rows)


# ── Task 3: mapping read/write (AC-15-40..43) ─────────────────────────────────


def test_mapping_view_projects_rows_and_catalogs(db, transports):
    company = _company(db, transports)
    view = CompanyService(db).mapping_view(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER)

    by_source = {r.source_path: r for r in view.rows}
    # A deliverable field carries its Sorento name.
    assert by_source["AccNo"].sorento_field in {"code", "source_doc_no"}
    assert by_source["EmailAddress"].sorento_field == "email"
    # A provenance/watermark row is projected as non-delivered.
    last_mod = next(r for r in view.rows if r.canonical_field == "last_modified")
    assert last_mod.sorento_field is None

    # Catalog: accepted Sorento fields with required-ness (source_ref excluded).
    accepted = {f.field for f in view.sorento_fields}
    assert "source_ref" not in accepted
    assert {"code", "name", "email", "is_active", "source_doc_no"} <= accepted
    required = {f.field for f in view.sorento_fields if f.required}
    assert {"code", "name"} <= required

    # Catalog: known AutoCount source paths, incl. a nested Data.0.* key.
    assert "AccNo" in view.ac_fields
    assert "Data.0.LastModified" in view.ac_fields


def test_mapping_view_customer_offers_the_extra_master_fields(db, transports):
    company = _company(db, transports)
    view = CompanyService(db).mapping_view(DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER)
    accepted = {f.field for f in view.sorento_fields}
    assert {"phone_number", "credit_limit", "tax_id"} <= accepted


def test_mapping_view_unknown_entity_is_a_clean_not_found(db, transports):
    company = _company(db, transports)
    with pytest.raises(EntityConfigNotFound):
        CompanyService(db).mapping_view(DEFAULT_TENANT_ID, company.id, "product")


def test_replace_mapping_round_trips(db, transports):
    company = _company(db, transports)
    svc = CompanyService(db)
    rows = [
        MappingWriteRow(source_path="AccNo", transform="string", sorento_field="code"),
        MappingWriteRow(source_path="CompanyName", transform="string", sorento_field="name"),
        MappingWriteRow(source_path="Email", transform="string", sorento_field="email"),
        MappingWriteRow(source_path="IsActive", transform="t_f_bool", sorento_field="is_active"),
    ]
    view = svc.replace_mapping(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, rows)
    by_field = {r.sorento_field: r for r in view.rows if r.sorento_field}
    # The remapped email source persisted.
    assert by_field["email"].source_path == "Email"
    # The system watermark row was PRESERVED, not wiped by the replace.
    assert any(r.canonical_field == "last_modified" for r in view.rows)


def test_replace_mapping_rejects_a_non_accepted_field(db, transports):
    """AC-15-42: a target Sorento would reject (extra=forbid) is a 422, naming
    the bad field — never silently dropped."""
    company = _company(db, transports)
    rows = [MappingWriteRow(source_path="Country", transform="string", sorento_field="country")]
    with pytest.raises(AutocountServiceError) as exc:
        CompanyService(db).replace_mapping(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, rows)
    assert "country" in str(exc.value)


def test_replace_mapping_rejects_a_blank_source_path(db, transports):
    company = _company(db, transports)
    rows = [MappingWriteRow(source_path="  ", transform="string", sorento_field="code")]
    with pytest.raises(AutocountServiceError):
        CompanyService(db).replace_mapping(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, rows)


def test_replace_mapping_rejects_an_unknown_transform(db, transports):
    company = _company(db, transports)
    rows = [MappingWriteRow(source_path="AccNo", transform="teleport", sorento_field="code")]
    with pytest.raises(AutocountServiceError):
        CompanyService(db).replace_mapping(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, rows)


def test_replace_mapping_rejects_a_duplicate_target(db, transports):
    company = _company(db, transports)
    rows = [
        MappingWriteRow(source_path="AccNo", transform="string", sorento_field="code"),
        MappingWriteRow(source_path="CompanyName", transform="string", sorento_field="code"),
    ]
    with pytest.raises(AutocountServiceError):
        CompanyService(db).replace_mapping(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, rows)


def test_replace_mapping_survives_a_reseed(db, transports):
    """AC-15-41: the write is an operator edit the next ``update_tenant`` /
    ``seed_company_defaults`` must NOT revert (seed-if-absent)."""
    company = _company(db, transports)
    svc = CompanyService(db)
    rows = [
        MappingWriteRow(source_path="AccNo", transform="string", sorento_field="code"),
        MappingWriteRow(source_path="CompanyName", transform="string", sorento_field="name"),
        MappingWriteRow(source_path="Email", transform="string", sorento_field="email"),
        MappingWriteRow(source_path="IsActive", transform="t_f_bool", sorento_field="is_active"),
    ]
    svc.replace_mapping(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, rows)

    # Re-run the defaults seed exactly as update_tenant would.
    svc.seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()

    view = svc.mapping_view(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER)
    by_field = {r.sorento_field: r for r in view.rows if r.sorento_field}
    assert by_field["email"].source_path == "Email"  # not reverted to EmailAddress
