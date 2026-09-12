"""Sprint-5/08 S3 - ``HttpApiSource``, the paged-REST implementation of the
``EntitySource`` seam (AC-08-22..27).

RED before the coder: ``modules/autocount/http_source/`` does not exist at
all yet (verified 2026-09-12 - only ``sources.py``/``sql_source/`` implement
``EntitySource``). Every test here imports
``modules.autocount.http_source.source.HttpApiSource`` and
``modules.autocount.http_source.errors.HttpSourceError`` and is expected to
fail with ``ImportError``/``ModuleNotFoundError`` until S3 lands.

Design assumptions pinned here for the coder (the plan names the class and
its ``(ctx, *, entity_type, mode, ...)`` shape but not every kwarg):

* ``HttpApiSource(ctx, *, entity_type, mode=RUN_MODE_MANUAL,
  persist_hashes=True, row_limit=MAX_EXTRACT_ROWS, transport=None, **_extra)``
  - mirrors ``SqlDbSource``'s own constructor shape byte-for-byte
  (``persist_hashes``/``row_limit`` for the preview-vs-real-run split, a
  ``transport`` kwarg for test stubbing exactly like ``client_from_connection``
  house convention).
* The task's ``source_config`` lives on ``ctx.entity_config.source_config``,
  same as ``SqlDbSource`` - ``{connectionId, path, keyFields, watermarkField,
  comparedFields, distinctOf, incrementalMinutes, reconcileMode, reconcileAt}``
  per the UAC's own "HTTP task" definition.
* The connection is resolved tenant+provider scoped via
  ``ConnectionRepository.get_for_provider`` (the ``autocount`` provider),
  never through ``company_service.client_for`` (which refuses a non-vendor
  company outright and is task-connection-independent per AC-08-13).
* The watermark cursor reuses the SQL source's OWN keys
  (``sql_source.source.CURSOR_MARK``/``CURSOR_COLUMN``) - plan §2.4 step 5
  says so explicitly ("stored ... exactly as SQL").
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_WAREHOUSE
from modules.autocount.models import (
    AcCompany,
    AcEntityConfig,
    AcRowHash,
    AcWatermark,
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
)
from modules.autocount.repositories import RowHashRepository
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark
from modules.autocount.sql_source.source import CURSOR_COLUMN, CURSOR_MARK

# Plain top-level import (no try/except): `modules.autocount.http_source`
# does not exist yet, so this file is expected to fail COLLECTION with
# ImportError/ModuleNotFoundError until S3 lands - never silently skip.
from modules.autocount.http_source.source import HttpApiSource
from modules.autocount.http_source.errors import HttpSourceError

DB_NAME = "MOCHA"
BASE_URL = "https://hapi.sorento.cc.cd/api/db2"


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
    db, company, *, entity_type=ENTITY_PRODUCT, connection_id: str, path="/itembypage",
    key_fields=("ItemCode",), watermark_field: Optional[str] = "LastModified",
    compared_fields=(), distinct_of=None,
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity_type,
        source_impl="autocount_http",
        source_config={
            "connectionId": connection_id,
            "path": path,
            "keyFields": list(key_fields),
            "watermarkField": watermark_field,
            "comparedFields": list(compared_fields),
            "distinctOf": distinct_of,
            "incrementalMinutes": 15,
            "reconcileMode": "dailyAt",
            "reconcileAt": "02:00",
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _ctx(db, company, config) -> "SourceContext":
    return SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )


def _transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def rig(session_factory):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    yield db, company, conn
    db.close()


def _paged_handler(pages: List[Dict[str, Any]], calls: List[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        page = int(request.url.params.get("page", "1"))
        body = pages[page - 1] if page - 1 < len(pages) else {
            "TotalCount": pages[0]["TotalCount"], "Page": page,
            "PageSize": pages[0]["PageSize"], "TotalPages": pages[0]["TotalPages"], "Data": [],
        }
        return httpx.Response(200, json=body)

    return handler


def _item(code: str, *, last_modified="2026-08-01T09:00:00", is_active="T") -> Dict[str, Any]:
    return {"ItemCode": code, "Description": code, "LastModified": last_modified, "IsActive": is_active}


# ── AC-08-22: page walk / echoed page size / dedup / distinctOf ──────────────


def test_page_walk_all_pages(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    calls: List[httpx.Request] = []
    pages = [
        {"TotalCount": 5, "Page": 1, "PageSize": 2, "TotalPages": 3, "Data": [_item("A1"), _item("A2")]},
        {"TotalCount": 5, "Page": 2, "PageSize": 2, "TotalPages": 3, "Data": [_item("A3"), _item("A4")]},
        {"TotalCount": 5, "Page": 3, "PageSize": 2, "TotalPages": 3, "Data": [_item("A5")]},
    ]
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_paged_handler(pages, calls)),
    )
    result = source.fetch_changes(Watermark())
    assert len(calls) == 3
    assert len(result.records) == 5
    assert result.reported_total == 5


def test_echoed_page_size_trusted_not_the_requested_one(rig):
    """The server CLAMPS pageSize (5000 -> 200 observed live) - the walk must
    trust the ECHOED PageSize/TotalPages, never the requested value."""
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    calls: List[httpx.Request] = []
    pages = [
        {"TotalCount": 3, "Page": 1, "PageSize": 2, "TotalPages": 2, "Data": [_item("A1"), _item("A2")]},
        {"TotalCount": 3, "Page": 2, "PageSize": 2, "TotalPages": 2, "Data": [_item("A3")]},
    ]
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_paged_handler(pages, calls)),
    )
    result = source.fetch_changes(Watermark())
    assert len(calls) == 2
    assert len(result.records) == 3
    # First request asked for 1000 (the source's own page size), never 2.
    assert calls[0].url.params.get("pageSize") == "1000"


def test_page_past_end_empty_stops(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    calls: List[httpx.Request] = []
    pages = [{"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []}]
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_paged_handler(pages, calls)),
    )
    result = source.fetch_changes(Watermark())
    assert len(calls) == 1
    assert result.records == []


def test_a_server_that_ignores_page_fails_fast_never_spins(rig):
    """SF-5 (sprint-5/08 review round 2) - a server that ignores the
    requested ``page`` and echoes the SAME ``Page``/``TotalPages`` forever
    must not spin the walk loop endlessly: detected as soon as the echoed
    ``Page`` fails to advance (the SECOND request), raised as a `shape`
    failure before any hash/watermark state is touched."""
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"TotalCount": 12, "Page": 1, "PageSize": 1, "TotalPages": 12, "Data": [_item("A1")]},
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
        # Bounds a pre-fix run (which would otherwise spin to `row_limit`
        # before ever raising) to a fast, deterministic failure either way.
        row_limit=5,
    )
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert exc.value.code == "shape"
    assert len(calls) == 2, "must fail fast after the SECOND request, never keep spinning"
    assert RowHashRepository(db).all_hashes(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT
    ) == {}


def test_clamped_last_page_empty_data_terminates_cleanly(rig):
    """Round 3 nit: some servers clamp the echoed ``Page`` back to the LAST
    real page once the walk runs past the end, rather than advancing it -
    page 1 answers ``Page: 1`` (no ``TotalPages``, so the walk keeps going),
    page 2 answers the SAME ``Page: 1`` again but with ``Data: []``. The
    page-advance guard (SF-5) must never fire on the page that is ENDING the
    scan: an empty page always terminates cleanly, never raises `shape`."""
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={"Page": 1, "PageSize": 1000, "Data": [_item("A1")]},
            )
        return httpx.Response(200, json={"Page": 1, "PageSize": 1000, "Data": []})

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())
    assert len(calls) == 2
    assert len(result.records) == 1


def test_bare_array_single_request(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, path="/location", entity_type=ENTITY_WAREHOUSE, key_fields=("Location",), watermark_field=None)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"Location": "A1", "IsActive": "T"}, {"Location": "A2", "IsActive": "F"}])

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_WAREHOUSE, transport=_transport(handler)
    )
    result = source.fetch_changes(Watermark())
    assert len(calls) == 1
    assert len(result.records) == 2


def test_duplicate_key_across_pages_first_wins_with_warning(rig, caplog):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    pages = [
        {"TotalCount": 2, "Page": 1, "PageSize": 1, "TotalPages": 2, "Data": [_item("A1", last_modified="2026-08-01T09:00:00")]},
        {"TotalCount": 2, "Page": 2, "PageSize": 1, "TotalPages": 2, "Data": [_item("A1", last_modified="2026-08-02T09:00:00")]},
    ]
    calls: List[httpx.Request] = []
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_paged_handler(pages, calls)),
    )
    result = source.fetch_changes(Watermark())
    refs = [source.source_ref(r.raw) for r in result.records]
    assert refs.count(f"{DB_NAME}:A1") == 1
    # S12 (sprint-5/08 review round 1, AC-08-22) - the drift is ALSO on the
    # activity trail an operator can actually see, not just the app log.
    activity = list(source.drain_activity())
    notes = [r for r in activity if r.method == "NOTE"]
    assert len(notes) == 1, activity
    assert "1 duplicate key" in notes[0].response["message"]


def test_distinct_of_projection_trimmed_non_blank_first_seen(rig):
    db, company, conn = rig
    config = _config(
        db, company, connection_id=conn.id, entity_type="unit_of_measure",
        key_fields=("value",), watermark_field=None,
        distinct_of=["BaseUOM", "SalesUOM", "PurchaseUOM"],
    )
    rows = [
        {"BaseUOM": " UNIT ", "SalesUOM": "UNIT", "PurchaseUOM": ""},
        {"BaseUOM": "BOX", "SalesUOM": None, "PurchaseUOM": "BOX"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    source = HttpApiSource(
        _ctx(db, company, config), entity_type="unit_of_measure", transport=_transport(handler)
    )
    result = source.fetch_changes(Watermark())
    values = [r.raw["value"] for r in result.records]
    assert values == ["UNIT", "BOX"]
    assert result.rows_scanned == 2  # rows READ, not values emitted


# ── AC-08-23: transport/shape failures fail the whole run, nothing touched ───


def test_page_error_fails_run_and_touches_nothing(rig):
    """AC-08-23. S8 (sprint-5/08 review round 1) - was a COUNT-only
    assertion, which would stay green even if the run overwrote the seed
    row's hash VALUE with a different one (same count, corrupted content).
    Now pins the ``ac_row_hash`` row byte-identical AND an ``ac_watermark``
    row's cursor untouched, per the AC's own "byte-identical" wording."""
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, {f"{DB_NAME}:SEED": "x" * 64}, seen_at=None
    )
    seed_watermark_cursor = {"cursorColumn": "LastModified", "cursorMark": "2026-08-01T00:00:00"}
    db.add(
        AcWatermark(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            cursor_json=dict(seed_watermark_cursor),
        )
    )
    db.commit()
    before_hashes = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    before_hash_count = db.query(AcRowHash).count()

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        if page == 3:
            return httpx.Response(500, text="boom")
        return httpx.Response(
            200,
            json={
                "TotalCount": 5, "Page": page, "PageSize": 1, "TotalPages": 5,
                "Data": [_item(f"A{page}")],
            },
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler)
    )
    with pytest.raises(HttpSourceError) as exc:
        source.fetch_changes(Watermark())
    assert exc.value.page == 3
    assert exc.value.status == 500
    assert db.query(AcRowHash).count() == before_hash_count
    after_hashes = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert after_hashes == before_hashes, "every ac_row_hash row must be byte-identical"
    watermark_row = (
        db.query(AcWatermark)
        .filter(
            AcWatermark.tenant_id == DEFAULT_TENANT_ID,
            AcWatermark.company_id == company.id,
            AcWatermark.entity_type == ENTITY_PRODUCT,
        )
        .one()
    )
    assert watermark_row.cursor_json == seed_watermark_cursor


def test_timeout_fails_the_run(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom", request=request)

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler)
    )
    with pytest.raises(HttpSourceError):
        source.fetch_changes(Watermark())


def test_non_json_body_fails_the_run(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler)
    )
    with pytest.raises(HttpSourceError):
        source.fetch_changes(Watermark())


def test_envelope_shape_change_mid_walk_fails(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            return httpx.Response(200, json={"TotalCount": 2, "Page": 1, "PageSize": 1, "TotalPages": 2, "Data": [_item("A1")]})
        return httpx.Response(200, json=[_item("A2")])  # bare array on page 2 - a shape change

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler)
    )
    with pytest.raises(HttpSourceError):
        source.fetch_changes(Watermark())


def test_every_request_carries_accept_json_and_timeout(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, path="/location", key_fields=("Location",), watermark_field=None)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"Location": "A1", "IsActive": "T"}])

    HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler)
    ).fetch_changes(Watermark())
    assert calls[0].headers.get("Accept") == "application/json"


# ── AC-08-24: MAX_EXTRACT_ROWS shared guard + drain_activity ─────────────────


def test_max_extract_rows_guard_same_code_as_sql(rig):
    from modules.autocount.sql_source.source import MAX_EXTRACT_ROWS

    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        calls.append(request)
        return httpx.Response(
            200,
            json={"TotalCount": 999999, "Page": page, "PageSize": 1000, "TotalPages": 999999,
                  "Data": [_item(f"A{page}-{i}") for i in range(1000)]},
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler),
        row_limit=2000,
    )
    with pytest.raises(HttpSourceError):
        source.fetch_changes(Watermark())


def test_drain_activity_one_record_per_page(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    pages = [
        {"TotalCount": 2, "Page": 1, "PageSize": 1, "TotalPages": 2, "Data": [_item("A1")]},
        {"TotalCount": 2, "Page": 2, "PageSize": 1, "TotalPages": 2, "Data": [_item("A2")]},
    ]
    calls: List[httpx.Request] = []
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT,
        transport=_transport(_paged_handler(pages, calls)),
    )
    source.fetch_changes(Watermark())
    activity = list(source.drain_activity())
    assert len(activity) == 2
    assert all(record.method == "GET" for record in activity)
    assert "page=1" in activity[0].path or activity[0].path.endswith("page=1")


# ── S10 (sprint-5/08 review round 1): never persist row bodies (PII) ────────


def test_drained_activity_never_carries_a_debtor_row_body():
    """The wrapper is public + unauthenticated (plan §2.10) - a debtor page
    carries ``CompanyName``/``Phone1``/credit-limit fields. This client's
    OWN activity record must carry counters only, never the row bodies -
    unlike the vendor/SQL client's own ``_record_call`` (untouched, never
    public)."""
    from modules.autocount.http_source.client import HttpApiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "TotalCount": 1, "Page": 1, "PageSize": 50, "TotalPages": 1,
                "Data": [
                    {
                        "AccNo": "D001",
                        "CompanyName": "Sorento Trading Sdn Bhd",
                        "Phone1": "+60123456789",
                        "CreditLimit": 50000,
                    }
                ],
            },
        )

    client = HttpApiClient(BASE_URL, transport=_transport(handler))
    client.get("/debtorbypage", {"page": 1, "pageSize": 50})
    activity = client.drain_calls()
    assert len(activity) == 1
    record = activity[0]
    serialized = repr(record.request) + repr(record.response)
    assert "CompanyName" not in serialized
    assert "Sorento Trading Sdn Bhd" not in serialized
    assert "+60123456789" not in serialized
    assert "CreditLimit" not in serialized
    assert record.response == {"statusCode": 200, "rowCount": 1, "envelope": "paged"}


# ── AC-08-25: run modes mirror sql_db ─────────────────────────────────────────


def test_incremental_keeps_rows_after_mark_iso_string_compare(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"TotalCount": 2, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": [
                _item("OLD", last_modified="2026-08-01T00:00:00"),
                _item("NEW", last_modified="2026-08-05T00:00:00"),
            ]},
        )

    since = Watermark(cursor={CURSOR_COLUMN: "LastModified", CURSOR_MARK: "2026-08-03T00:00:00"})
    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, mode="incremental",
        transport=_transport(handler),
    )
    result = source.fetch_changes(since)
    refs = {source.source_ref(r.raw) for r in result.records}
    assert refs == {f"{DB_NAME}:NEW"}


def test_incremental_new_mark_is_max_seen_and_stored_under_cursor_keys(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                       "Data": [_item("A1", last_modified="2026-08-09T00:00:00")]},
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, mode="incremental",
        transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())
    assert result.cursor is not None
    assert result.cursor.get(CURSOR_COLUMN) == "LastModified"
    assert result.cursor.get(CURSOR_MARK) == "2026-08-09T00:00:00"


def test_no_watermark_means_full_extract_mechanics(rig):
    db, company, conn = rig
    config = _config(
        db, company, connection_id=conn.id, path="/location", key_fields=("Location",),
        watermark_field=None,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"Location": "A1", "IsActive": "T"}])

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(handler)
    )
    result = source.fetch_changes(Watermark())
    assert result.cursor is None


def test_reconcile_classifies_added_updated_deleted_via_row_hash(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        {f"{DB_NAME}:GONE": "x" * 64, f"{DB_NAME}:SAME": "y" * 64}, seen_at=None,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"TotalCount": 2, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": [
                _item("SAME"), _item("NEWONE"),
            ]},
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE,
        transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())
    assert result.added_count == 1  # NEWONE
    assert f"{DB_NAME}:GONE" in result.delete_refs


def test_empty_compared_columns_falls_back_to_row_own_fields_for_hashing(rig):
    """B-A (sprint-5/08 review round 2 blocker) - a task with an empty
    effective compared set (never previewed: ``result_columns`` is None,
    ``comparedFields`` is ``[]``) must still detect a genuine field change on
    the SAME key between two runs. Before the fix ``row_hash(row, [])`` is
    ``sha256("")`` for every row, so ``updated_count`` is stuck at 0 forever
    even though the row's data changed."""
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, compared_fields=())
    assert config.result_columns is None  # never previewed

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        description = "First" if call_count["n"] == 1 else "Second"
        return httpx.Response(
            200,
            json={
                "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [{
                    "ItemCode": "A1", "Description": description,
                    "LastModified": "2026-08-01T09:00:00", "IsActive": "T",
                }],
            },
        )

    def make_source() -> HttpApiSource:
        return HttpApiSource(
            _ctx(db, company, config), entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE,
            transport=_transport(handler),
        )

    first = make_source()
    assert first.compared_columns == []
    result1 = first.fetch_changes(Watermark())
    assert result1.added_count == 1

    result2 = make_source().fetch_changes(Watermark())
    assert result2.updated_count == 1, (
        "Description changed between runs but the hash didn't move - an "
        "empty compared set fell back to sha256('') for every row."
    )


def test_reconcile_delete_guard_fires_on_mass_disappearance(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    known = {f"{DB_NAME}:K{i}": "x" * 64 for i in range(60)}
    RowHashRepository(db).upsert_many(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, known, seen_at=None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []})

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE,
        transport=_transport(handler),
    )
    with pytest.raises(Exception):
        source.fetch_changes(Watermark())


# ── AC-08-26: IsActive F is an upsert, never a delete ─────────────────────────


def test_is_active_f_is_upsert_false_never_delete(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                       "Data": [_item("INACTIVE", is_active="F")]},
        )

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE,
        transport=_transport(handler),
    )
    result = source.fetch_changes(Watermark())
    assert f"{DB_NAME}:INACTIVE" not in result.delete_refs


# ── AC-08-27: refs company-qualified same for sql and http, multi-key pipe ──


def test_ref_company_qualified_same_scheme_as_sql(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id)
    source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(lambda r: httpx.Response(200, json=[])))
    assert source.source_ref({"ItemCode": "SRT-01"}) == f"{DB_NAME}:SRT-01"


def test_multi_key_joined_with_pipe(rig):
    db, company, conn = rig
    config = _config(db, company, connection_id=conn.id, key_fields=("ItemCode", "Location"))
    source = HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT, transport=_transport(lambda r: httpx.Response(200, json=[])))
    assert source.source_ref({"ItemCode": "SRT-01", "Location": "WH1"}) == f"{DB_NAME}:SRT-01|WH1"


# ── S6 (sprint-5/08 review round 1): auth-scoped, not just provider-scoped ──


def test_basic_auth_connection_refuses_construction(rig):
    """A task's ``connectionId`` resolving to a BASIC-auth ``autocount``
    connection (the operator flipped the connection's own ``auth`` after
    saving the task, or hand-edited the row) must fail the SAME way a
    missing connection does - never silently attempt an unauthenticated GET
    against a vendor endpoint that expects a session."""
    db, company, _open_conn = rig
    basic_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="Basic AC",
        config_json={"baseUrl": BASE_URL, "auth": "basic", "userId": "ADMIN"},
        credentials_json=None, is_active=True,
    )
    db.add(basic_conn)
    db.commit()
    db.refresh(basic_conn)
    config = _config(db, company, connection_id=basic_conn.id)
    with pytest.raises(HttpSourceError):
        HttpApiSource(_ctx(db, company, config), entity_type=ENTITY_PRODUCT)
