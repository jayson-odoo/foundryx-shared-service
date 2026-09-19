"""Sprint-5/10 S3 - Group C, the build job: AC-10-20, 21, 22, 24, 26, 46, 62, 63.

Driven at the HIGHEST STABLE PUBLIC SEAM (mirrors the S1 tester's own choice
in ``test_s10_http_lookups.py``): ``PullService.request_build`` - never an
invented private extraction-loop signature. Under this suite's conftest
default (``settings.celery_task_always_eager = True``), the background job
``request_build`` enqueues runs INLINE on the SAME session
(``app/jobs/service.py:run_job`` -> ``JobService.enqueue``), so by the time
``request_build`` returns, the snapshot already carries its terminal state -
no polling, no Celery, no second session.

RED before the coder: ``modules.autocount.services.pull_service`` does not
exist at all yet, so every test below fails at collection with a plain
``ImportError`` (a "missing feature" RED, never a bare ``assert False``).

ASSUMED NAMES the coder must conform to, additional to
``test_s10_s3_snapshot_store.py``'s ``SnapshotService``/``compute_content_hash``:

* ``modules.autocount.services.pull_service.PullService(db)``:
  ``request_build(tenant_id, company_id, entity_type, *, requested_via,
  requested_by=None, now=None) -> AcPullSnapshot``. Enforces (AC-10-26): at
  most ONE ``building`` snapshot per (tenant, company, entity) - a second
  call while one is building returns THAT snapshot, no second job; a build
  request within 60s of the previous build for the same triple raises
  ``PullBuildCooldownError`` (exported from the same module, carries
  ``retry_after_seconds``).
* ``modules.autocount.sync.AUTOCOUNT_PULL_SNAPSHOT = "autocount_pull_snapshot"``
  (job-type constant) and ``modules.autocount.sync._run_pull_snapshot(db,
  job)`` (the registered handler, named in the plan's own files list) -
  isolates every extraction fault INTERNALLY (mirrors ``run_autocount_sync``'s
  own ``_fail`` pattern) so ``request_build`` never raises for a FAILED
  build; it raises only for the two pre-flight guards above.
* The build writes the snapshot's ``metadata_json`` with AT LEAST
  ``excludedRows`` (list) and ``excludedCount`` (int) for every entity
  (AC-10-62), plus, for ``product``, ``zeroListPriceCount``,
  ``negativeListPriceCount`` and ``enrichMissCount`` (AC-10-63) - read back
  through ``AcPullSnapshot.metadata_json`` directly (no header-serialization
  route exists in S3; that projection is the S4 gateway's job).
* One ``AcSyncRun`` row per build, ``mode='snapshot'``
  (``modules.autocount.models.RUN_MODE_SNAPSHOT = "snapshot"``, added to
  ``RUN_MODES``), carrying ``rows_scanned`` and ``added_count ==
  record_count``.

Kill-test notes are per section below.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcStagedRecord,
)

DB_NAME = "AED_SORENTO"
REF_PREFIX = "AED_SORENTO"
BASE_URL = "https://hapi.sorento.cc.cd/api/db1"

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": BASE_URL, "auth": "none"}, credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name=DB_NAME,
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _row(source_path, canonical_field, transform="string", *, required=False, formula=None):
    return dict(
        source_path=source_path, canonical_field=canonical_field, transform=transform,
        is_required=required, formula=formula,
    )


def _product_task(
    db, company, connection_id, *, mapping_rows=None, lookups=None,
) -> AcEntityConfig:
    """A MINIMAL, hand-rolled ``product`` HTTP task - deliberately NOT the
    live preset (``PRODUCT_HTTP_PRESET``/``seed_http_preset_mapping``), so
    these build-job tests stay decoupled from S1's own preset shape and from
    the "is 'name' actually required today" gap noted in the final report.
    """
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE,
        delivery_mode="pull",
        source_config={
            "connectionId": connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": lookups or [],
        },
        last_preview_at=NOW,
        result_columns=["ItemCode", "Description"],
    )
    db.add(config)
    db.commit()
    for i, row in enumerate(mapping_rows or []):
        db.add(
            AcFieldMapping(
                tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
                scope="header", sort_order=i, **row,
            )
        )
    db.commit()
    db.refresh(config)
    return config


def _envelope(rows: List[Dict[str, Any]], *, page=1, page_size=1000, total_count=None) -> Dict[str, Any]:
    return {
        "TotalCount": total_count if total_count is not None else len(rows),
        "Page": page, "PageSize": page_size, "TotalPages": 1, "Data": rows,
    }


def _single_page_transport(body: Dict[str, Any]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _patch_transport(monkeypatch, transport: httpx.Client) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=transport),
    )


def _build(db, company, *, entity_type=ENTITY_PRODUCT, now=NOW):
    from modules.autocount.services.pull_service import PullService

    return PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, entity_type, requested_via="operator", now=now,
    )


# ── AC-10-20/21: build creates + writes rows, no staging, ONE snapshot run ──


def test_build_writes_ready_snapshot_rows_and_one_sync_run(db, monkeypatch):
    from modules.autocount.models import AcPullSnapshotRow, AcSyncRun

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(
        db, company, conn.id,
        mapping_rows=[_row("ItemCode", "code", required=True), _row("Description", "name")],
    )
    _patch_transport(
        monkeypatch,
        _single_page_transport(
            _envelope([{"ItemCode": "A1", "Description": "Widget A1"}])
        ),
    )

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"
    assert snapshot.record_count == 1
    assert snapshot.complete is True
    rows = (
        db.query(AcPullSnapshotRow)
        .filter(AcPullSnapshotRow.snapshot_id == snapshot.id)
        .order_by(AcPullSnapshotRow.row_index)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].source_ref == f"{REF_PREFIX}:A1"
    assert rows[0].payload_json["code"] == "A1"
    assert rows[0].payload_json["name"] == "Widget A1"

    # AC-10-21 - no staging/hashing/watermark writes; ONE snapshot-mode run.
    assert db.query(AcStagedRecord).filter(AcStagedRecord.company_id == company.id).count() == 0
    runs = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.company_id == company.id, AcSyncRun.entity_type == ENTITY_PRODUCT)
        .all()
    )
    assert len(runs) == 1
    assert runs[0].mode == "snapshot"
    assert runs[0].added_count == snapshot.record_count


# ── AC-10-22: set failure (page fault) vs per-record exclusion ──────────────


def test_a_source_page_failure_fails_the_whole_snapshot_with_zero_rows(db, monkeypatch):
    from modules.autocount.models import AcPullSnapshotRow

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(
        db, company, conn.id,
        mapping_rows=[_row("ItemCode", "code", required=True), _row("Description", "name")],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream boom")

    _patch_transport(monkeypatch, httpx.Client(transport=httpx.MockTransport(handler)))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "failed"
    assert snapshot.error_code == "SOURCE_PAGE_FAILED"
    assert (
        db.query(AcPullSnapshotRow)
        .filter(AcPullSnapshotRow.snapshot_id == snapshot.id)
        .count()
        == 0
    )


def test_a_per_record_mapping_failure_excludes_the_row_not_the_snapshot(db, monkeypatch):
    """The live-shaped case (AC-10-62): one of two records fails a REQUIRED
    mapping row (here ``name``, forced required by this file's own hand-rolled
    task rather than relying on today's preset - see the ambiguity note in
    the final report), the other is delivered, and the snapshot still reaches
    ``ready``."""
    from modules.autocount.models import AcPullSnapshotRow

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(
        db, company, conn.id,
        mapping_rows=[
            _row("ItemCode", "code", required=True),
            _row("Description", "name", required=True),
        ],
    )
    _patch_transport(
        monkeypatch,
        _single_page_transport(
            _envelope(
                [
                    {"ItemCode": "GOOD", "Description": "A good item"},
                    {"ItemCode": "BLANK", "Description": ""},
                ]
            )
        ),
    )

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"
    assert snapshot.record_count == 1
    rows = db.query(AcPullSnapshotRow).filter(AcPullSnapshotRow.snapshot_id == snapshot.id).all()
    assert [r.payload_json["code"] for r in rows] == ["GOOD"]
    excluded = snapshot.metadata_json.get("excludedRows")
    assert snapshot.metadata_json.get("excludedCount") == 1
    assert len(excluded) == 1
    assert excluded[0]["reason"] == "mapping_failed"
    assert excluded[0]["code"] == "BLANK"
    assert excluded[0]["source_ref"] == f"{REF_PREFIX}:BLANK"
    assert excluded[0]["message"]


# ── AC-10-24: complete computed against the echoed TotalCount ───────────────


def test_complete_is_false_when_scanned_rows_disagree_with_echoed_total_count(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(
        db, company, conn.id,
        mapping_rows=[_row("ItemCode", "code", required=True)],
    )
    _patch_transport(
        monkeypatch,
        _single_page_transport(
            _envelope([{"ItemCode": "A1", "Description": "A1"}], total_count=1000)
        ),
    )

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"  # a completeness mismatch alone never fails the build
    assert snapshot.complete is False
    assert snapshot.record_count == 1


def test_complete_is_true_when_scanned_rows_match_echoed_total_count_control(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, mapping_rows=[_row("ItemCode", "code", required=True)])
    _patch_transport(
        monkeypatch,
        _single_page_transport(_envelope([{"ItemCode": "A1", "Description": "A1"}])),
    )

    snapshot = _build(db, company)
    db.refresh(snapshot)
    assert snapshot.complete is True


# ── AC-10-26: at most one building snapshot; re-attach; cooldown ────────────


def test_a_second_request_while_one_is_building_reattaches_to_the_same_id(db):
    from modules.autocount.models import AcPullSnapshot
    from modules.autocount.services.pull_service import PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, mapping_rows=[_row("ItemCode", "code", required=True)])

    # A snapshot genuinely still ``building`` (no job run against it here) -
    # simulates a build that has not finished yet, without needing to defeat
    # this suite's eager-inline job execution.
    from modules.autocount.services.pull_service import SnapshotService

    in_flight = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )

    result = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )

    assert result.id == in_flight.id
    total = (
        db.query(AcPullSnapshot)
        .filter(AcPullSnapshot.company_id == company.id, AcPullSnapshot.entity_type == ENTITY_PRODUCT)
        .count()
    )
    assert total == 1, "a re-attach must never start a second extraction"


def test_a_build_within_60s_of_the_previous_one_is_refused(db):
    from modules.autocount.services.pull_service import (
        PullBuildCooldownError,
        PullService,
        SnapshotService,
    )

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, mapping_rows=[_row("ItemCode", "code", required=True)])

    recent = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    SnapshotService(db).stamp_ready(
        DEFAULT_TENANT_ID, recent, record_count=1, complete=True,
        content_hash="a" * 64, metadata={},
        extracted_at=NOW - timedelta(seconds=30), expires_at=NOW + timedelta(hours=24),
    )

    with pytest.raises(PullBuildCooldownError):
        PullService(db).request_build(
            DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
        )


def test_a_build_60s_after_the_previous_one_is_allowed_control(db, monkeypatch):
    from modules.autocount.services.pull_service import PullService, SnapshotService

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, mapping_rows=[_row("ItemCode", "code", required=True)])

    old = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    SnapshotService(db).stamp_ready(
        DEFAULT_TENANT_ID, old, record_count=1, complete=True,
        content_hash="a" * 64, metadata={},
        extracted_at=NOW - timedelta(minutes=5), expires_at=NOW + timedelta(hours=24),
    )
    _patch_transport(
        monkeypatch,
        _single_page_transport(_envelope([{"ItemCode": "A1", "Description": "A1"}])),
    )

    result = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    assert result.id != old.id


# ── AC-10-46: zero-row guard ──────────────────────────────────────────────


def test_a_zero_row_build_after_a_nonzero_ready_snapshot_fails_empty_extract(db, monkeypatch):
    from modules.autocount.services.pull_service import SnapshotService

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, mapping_rows=[_row("ItemCode", "code", required=True)])

    previous = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    SnapshotService(db).stamp_ready(
        DEFAULT_TENANT_ID, previous, record_count=5, complete=True,
        content_hash="a" * 64, metadata={},
        extracted_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(hours=23),
    )
    _patch_transport(monkeypatch, _single_page_transport(_envelope([])))

    snapshot = _build(db, company, now=NOW + timedelta(hours=2))
    db.refresh(snapshot)

    assert snapshot.status == "failed"
    assert snapshot.error_code == "EMPTY_EXTRACT"


def test_a_genuinely_first_zero_row_build_is_allowed_control(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, mapping_rows=[_row("ItemCode", "code", required=True)])
    _patch_transport(monkeypatch, _single_page_transport(_envelope([])))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"
    assert snapshot.record_count == 0


# ── AC-10-63: product header counters ────────────────────────────────────────


ITEM_UOM_LOOKUP = {
    "path": "/itemuombypage",
    "as": "uom",
    "on": [
        {"local": "ItemCode", "remote": "ItemCode"},
        {"local": "BaseUOM", "remote": "UOM", "match": "casefold_trim"},
    ],
    "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
}


def _multi_handler(pages_by_path: Dict[str, Dict[str, Any]]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = next(p for p in pages_by_path if request.url.path.endswith(p))
        return httpx.Response(200, json=pages_by_path[path])

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_product_header_counters_cover_zero_negative_positive_absent_nonnumeric(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(
        db, company, conn.id,
        lookups=[ITEM_UOM_LOOKUP],
        mapping_rows=[
            _row("ItemCode", "code", required=True),
            _row("Description", "name"),
            _row(
                "BaseUOMPrice", "list_price",
                formula="if(number(value) <= 0, 0, number(value))",
            ),
        ],
    )
    item_rows = [
        {"ItemCode": "ZERO", "Description": "Zero", "BaseUOM": "UNIT"},
        {"ItemCode": "NEG", "Description": "Negative", "BaseUOM": "UNIT"},
        {"ItemCode": "POS", "Description": "Positive", "BaseUOM": "UNIT"},
        {"ItemCode": "MISS", "Description": "No enrich match", "BaseUOM": "UNIT"},
        {"ItemCode": "BAD", "Description": "Non-numeric price", "BaseUOM": "UNIT"},
    ]
    uom_rows = [
        {"ItemCode": "ZERO", "UOM": "UNIT", "Price": 0.0},
        {"ItemCode": "NEG", "UOM": "UNIT", "Price": -1.0},
        {"ItemCode": "POS", "UOM": "UNIT", "Price": 12.5},
        # MISS: deliberately no matching row.
        {"ItemCode": "BAD", "UOM": "UNIT", "Price": "abc"},
    ]
    _patch_transport(
        monkeypatch,
        _multi_handler(
            {
                "/itembypage": _envelope(item_rows),
                "/itemuombypage": _envelope(uom_rows),
            }
        ),
    )

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"
    meta = snapshot.metadata_json
    assert meta["zeroListPriceCount"] == 2  # ZERO + clamped NEG
    assert meta["negativeListPriceCount"] == 1  # NEG only
    assert meta["enrichMissCount"] == 1  # MISS only
    assert meta["negativeListPriceCount"] <= meta["zeroListPriceCount"]
    # BAD's formula raises on a non-numeric source value -> the WHOLE record
    # is excluded (mapping failure), never miscounted as a price bucket.
    assert meta["excludedCount"] == 1
    assert snapshot.record_count == 4  # ZERO, NEG, POS, MISS delivered


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_build_writes_ready_snapshot_rows_and_one_sync_run dies if the build
#   writes through the ordinary push pipeline (ac_staged_record would be
#   non-empty) or skips the AcSyncRun bookkeeping entirely.
# * test_a_source_page_failure_fails_the_whole_snapshot_with_zero_rows dies
#   if a page fault is swallowed into an EXCLUDED row instead of failing the
#   whole set (R6's own line: a fault that makes the SET untrustworthy must
#   never look like a clean, partial ``ready`` snapshot).
# * test_a_per_record_mapping_failure_excludes_the_row_not_the_snapshot dies
#   if the coder reuses the push path's "one bad record fails the whole
#   batch" instinct instead of R6's per-record exclusion.
# * test_a_second_request_while_one_is_building_reattaches_to_the_same_id
#   dies if a second call starts a second extraction (the total count
#   assertion catches a silent duplicate even if the returned id happens to
#   still match the first one returned to the caller).
# * test_product_header_counters_... dies if BAD's TransformError is
#   swallowed into a delivered zero price instead of an exclusion, which
#   would silently inflate zeroListPriceCount.
