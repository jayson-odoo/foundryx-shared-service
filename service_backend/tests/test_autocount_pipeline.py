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
from modules.autocount.client import AutoCountClient
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


def _run_sync(db, company: AcCompany, tenant_id: str = DEFAULT_TENANT_ID) -> BackgroundJob:
    job = SyncService(db).sync_now(
        tenant_id, company.id, ENTITY_GOODS_RECEIVED_NOTE, actor_user_id=None
    )
    db.refresh(job)
    return job


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
    config = CompanyService(db).entity_configs(DEFAULT_TENANT_ID, company.id)[0]
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
    config = CompanyService(db).entity_configs(DEFAULT_TENANT_ID, company.id)[0]
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
        ("post", "/autocount/jobs/x/approve"),
        ("post", "/autocount/jobs/x/discard"),
    ):
        kwargs = {"json": {}} if method == "post" else {}
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
