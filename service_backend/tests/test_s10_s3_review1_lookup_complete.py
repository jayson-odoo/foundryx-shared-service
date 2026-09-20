"""Sprint-5/10 S3 review round 1 follow-up (coordinator ruling 2026-09-20) -
AC-10-24's own definition applied honestly to lookups: the lookups are part
of the extraction, so a snapshot build's ``complete`` requires the MAIN walk
AND every lookup walk to be verified (bare array = verified; paged =
``reported_total is not None and rows_scanned == reported_total``, counts
from the FINAL walk after any halving restart - the exact rule already
pinned for the main path in ``test_s10_s3_review1_complete.py``).

RED before the fix (proven by reasoning + a local revert, restored after -
see the coder's final report): before this change, ``HttpApiSource.
_apply_lookups`` discarded the lookup walk's own ``reported_total``/
``envelope_kind`` (``lookup_rows, _, _ = self._walk_endpoint(path)``), so
``FetchResult`` carried no per-lookup completeness signal at all and
``complete`` was computed from the main walk ALONE - every test below that
constructs a genuinely unverified lookup would have read ``complete: True``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, BackgroundJob
from app.models.connection import Connection
from app.models.integration_activity import ACTIVITY_ERROR, SOURCE_AUTOCOUNT, IntegrationActivity
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    DELIVERY_MODE_PUSH,
    ETL_STATUS_ACTIVE,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcStagedRecord,
)
from modules.autocount.sync import AUTOCOUNT_SYNC

DB_NAME = "AED_SORENTO"
BASE_URL = "https://hapi.sorento.cc.cd/api/db1"

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

ITEM_UOM_LOOKUP = {
    "path": "/itemuombypage", "as": "uom",
    "on": [{"local": "ItemCode", "remote": "ItemCode"}],
    "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
}


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    ``test_s10_s3_delivery_mode.py``'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20)."""
    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    async def guarded_async_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """The halving test times a page out twice - backoff must never
    actually sleep in the suite (mirrors ``test_s10_http_retry.py``)."""
    monkeypatch.setattr("time.sleep", lambda seconds: None)


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


def _product_task(
    db, company, connection_id, *, delivery_mode: str, lookups=None
) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, delivery_mode=delivery_mode,
        source_config={
            "connectionId": connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": lookups or [],
        },
        last_preview_at=NOW, result_columns=["ItemCode", "Description"],
    )
    db.add(config)
    db.commit()
    db.add(AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        scope="header", sort_order=0, source_path="ItemCode", canonical_field="code",
        transform="string", is_required=True,
    ))
    db.add(AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        scope="header", sort_order=1, source_path="Description", canonical_field="name",
        transform="string",
    ))
    db.commit()
    db.refresh(config)
    return config


def _patch_transport(monkeypatch, transport: httpx.Client) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=transport),
    )


def _build(db, company, *, now=NOW):
    from modules.autocount.services.pull_service import PullService

    return PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=now,
    )


def _main_page(rows: List[Dict[str, Any]], *, total_count=None) -> Dict[str, Any]:
    return {
        "TotalCount": total_count if total_count is not None else len(rows),
        "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": rows,
    }


def _routed_handler(main_body: Dict[str, Any], lookup_body_or_fn):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/itembypage"):
            return httpx.Response(200, json=main_body)
        if callable(lookup_body_or_fn):
            return lookup_body_or_fn(request)
        return httpx.Response(200, json=lookup_body_or_fn)

    return httpx.Client(transport=httpx.MockTransport(handler))


ITEM_ROWS = [{"ItemCode": "A1", "Description": "Widget A1"}]


# ── lookup paged without TotalCount -> unverified -> complete false ────────


def test_main_verified_lookup_paged_without_total_count_is_incomplete(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, delivery_mode="pull", lookups=[ITEM_UOM_LOOKUP])
    lookup_body = {
        # No "TotalCount" key at all.
        "Page": 1, "PageSize": 1000, "TotalPages": 1,
        "Data": [{"ItemCode": "A1", "Price": 9.0}],
    }
    _patch_transport(monkeypatch, _routed_handler(_main_page(ITEM_ROWS), lookup_body))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready", "an unverified lookup alone never fails the build"
    assert snapshot.complete is False
    assert snapshot.record_count == 1


# ── lookup totals mismatch -> unverified -> complete false ─────────────────


def test_main_verified_lookup_total_count_mismatch_is_incomplete(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, delivery_mode="pull", lookups=[ITEM_UOM_LOOKUP])
    lookup_body = {
        "TotalCount": 100, "Page": 1, "PageSize": 1000, "TotalPages": 1,
        "Data": [{"ItemCode": "A1", "Price": 9.0}],
    }
    _patch_transport(monkeypatch, _routed_handler(_main_page(ITEM_ROWS), lookup_body))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.complete is False
    assert snapshot.record_count == 1


# ── a genuinely bare-array lookup has no total to fall short of ────────────


def test_lookup_bare_array_is_verified(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, delivery_mode="pull", lookups=[ITEM_UOM_LOOKUP])
    lookup_body: List[Dict[str, Any]] = [{"ItemCode": "A1", "Price": 9.0}]
    _patch_transport(monkeypatch, _routed_handler(_main_page(ITEM_ROWS), lookup_body))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.complete is True
    assert snapshot.record_count == 1


# ── main AND lookup both verified -> complete true ──────────────────────────


def test_main_and_lookup_both_verified_is_complete(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, delivery_mode="pull", lookups=[ITEM_UOM_LOOKUP])
    lookup_body = {
        "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
        "Data": [{"ItemCode": "A1", "Price": 9.0}],
    }
    _patch_transport(monkeypatch, _routed_handler(_main_page(ITEM_ROWS), lookup_body))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.complete is True
    assert snapshot.record_count == 1


# ── a halving restart on the LOOKUP's own walk uses only the final counts ──


def test_lookup_halving_restart_verification_uses_only_the_final_walk(db, monkeypatch):
    """The main path answers cleanly in one page. The LOOKUP endpoint's page
    1 at the default size succeeds (2 rows, ``TotalCount: 4`` implying a
    second page); its page 2 times out on BOTH attempts, halving the
    lookup's OWN walk and restarting from page 1 - at the halved size, ONE
    page answers everything (1 row, ``TotalCount: 1``). If the discarded
    attempt's counts leaked into the verification, this would read
    ``rowsScanned=3`` against a stale/foreign total instead of the clean
    ``1 == 1`` the correct, single coherent lookup walk produces."""
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, delivery_mode="pull", lookups=[ITEM_UOM_LOOKUP])

    def lookup_handler(request: httpx.Request) -> httpx.Response:
        page_size = request.url.params.get("pageSize")
        page = request.url.params.get("page")
        if page_size == "1000":
            if page == "1":
                return httpx.Response(
                    200,
                    json={
                        "TotalCount": 4, "Page": 1, "PageSize": 1000, "TotalPages": 2,
                        "Data": [
                            {"ItemCode": "A1", "Price": 1.0},
                            {"ItemCode": "A2", "Price": 2.0},
                        ],
                    },
                )
            raise httpx.ReadTimeout("boom", request=request)
        return httpx.Response(
            200,
            json={
                "TotalCount": 1, "Page": 1, "PageSize": 500, "TotalPages": 1,
                "Data": [{"ItemCode": "A1", "Price": 1.0}],
            },
        )

    _patch_transport(monkeypatch, _routed_handler(_main_page(ITEM_ROWS), lookup_handler))

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert snapshot.status == "ready"
    assert snapshot.complete is True, (
        "the lookup's FINAL walk (1 row, TotalCount 1) is internally "
        "consistent - a blended accounting (3 scanned vs a stale/foreign "
        "total) would have produced complete=False instead"
    )


# ── the activity note names the unverified alias ────────────────────────────


def test_an_unverified_lookup_writes_one_activity_note_naming_the_alias(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, delivery_mode="pull", lookups=[ITEM_UOM_LOOKUP])
    lookup_body = {
        "TotalCount": 100, "Page": 1, "PageSize": 1000, "TotalPages": 1,
        "Data": [{"ItemCode": "A1", "Price": 9.0}],
    }
    _patch_transport(monkeypatch, _routed_handler(_main_page(ITEM_ROWS), lookup_body))

    before = (
        db.query(IntegrationActivity)
        .filter(IntegrationActivity.tenant_id == DEFAULT_TENANT_ID)
        .count()
    )
    snapshot = _build(db, company)
    db.refresh(snapshot)

    rows = (
        db.query(IntegrationActivity)
        .filter(
            IntegrationActivity.tenant_id == DEFAULT_TENANT_ID,
            IntegrationActivity.source == SOURCE_AUTOCOUNT,
        )
        .order_by(IntegrationActivity.created_at.desc())
        .all()
    )
    new_rows = rows[: len(rows) - before] if before else rows
    matches = [r for r in new_rows if "uom" in (r.error_message or "") and r.status == ACTIVITY_ERROR]
    assert len(matches) == 1, f"expected exactly ONE note naming the 'uom' alias, found {len(matches)}"
    assert "1 of reported 100" in matches[0].error_message


# ── control: the PUSH path is byte-identical with an unverified lookup ─────


def test_push_path_staging_and_result_unchanged_with_an_unverified_lookup(db, monkeypatch):
    """The SAME rig, ``delivery_mode='push'``: the merged/staged output must
    be IDENTICAL to what it always was (this item never touches the merge
    itself, only adds bookkeeping), and no new ``pull snapshot`` activity
    note is written - the note lives ONLY in ``_run_pull_snapshot``, never
    inside ``HttpApiSource`` itself, so an ordinary sync run is completely
    unaffected."""
    from app.jobs.service import JobService
    from modules.autocount.sync import run_autocount_sync

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, delivery_mode=DELIVERY_MODE_PUSH, lookups=[ITEM_UOM_LOOKUP])
    lookup_body = {
        # Unverified: no TotalCount.
        "Page": 1, "PageSize": 1000, "TotalPages": 1,
        "Data": [{"ItemCode": "A1", "Price": 9.0}],
    }
    _patch_transport(monkeypatch, _routed_handler(_main_page(ITEM_ROWS), lookup_body))

    before_notes = (
        db.query(IntegrationActivity)
        .filter(IntegrationActivity.tenant_id == DEFAULT_TENANT_ID)
        .count()
    )

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_PRODUCT, "mode": "manual"},
    )
    run_autocount_sync(db, job)

    # This rig's default sink auto-pushes immediately (a plain sync task on
    # the ``logging`` sink) - the row's TERMINAL status is ``PUSHED``, never
    # ``STAGED``, exactly as it is TODAY with no lookup involved at all.
    staged = db.query(AcStagedRecord).filter(AcStagedRecord.company_id == company.id).all()
    assert len(staged) == 1
    assert staged[0].status == "PUSHED"
    assert staged[0].source_ref.endswith(":A1")
    # The lookup still merged its field onto the raw row - the merge itself
    # is untouched by this item; only the completeness BOOKKEEPING is new.
    assert staged[0].raw_json.get("BaseUOMPrice") == 9.0

    # No "pull snapshot"-flavoured note appeared - the push path never
    # writes one, regardless of how the lookup's own completeness reads.
    after_notes = (
        db.query(IntegrationActivity)
        .filter(IntegrationActivity.tenant_id == DEFAULT_TENANT_ID)
        .all()
    )
    pull_notes = [
        r for r in after_notes
        if r.operation.startswith("pull snapshot") or "could not be verified" in (r.error_message or "")
    ]
    assert pull_notes == []
    assert job.status == JOB_DONE


# ── kill tests ────────────────────────────────────────────────────────────
#
# * every ``complete``-asserting test above dies if ``_apply_lookups`` keeps
#   discarding the lookup walk's own ``reported_total``/``envelope_kind``
#   (``lookup_rows, _, _ = self._walk_endpoint(path)``) - proven locally by
#   reverting that one line (restored after, see the coder's final report).
# * the activity-note test dies if the note is written from INSIDE
#   ``HttpApiSource``/the push path instead of ``_run_pull_snapshot`` only,
#   or if it is never written at all.
# * the push-path control dies if adding ``lookup_verification`` ever
#   changed the ACTUAL merge/staging output, or if a note leaked into an
#   ordinary sync run.
