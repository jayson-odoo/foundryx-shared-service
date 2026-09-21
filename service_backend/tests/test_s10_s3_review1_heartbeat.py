"""Sprint-5/10 S3 review round 1 - MUST-FIX 1 (AC-10-26): the build job's own
heartbeat.

Coordinator finding: ``_run_pull_snapshot`` registered ``heartbeats=True``
but never actually beat - a Mocha build (roughly 25-30 minutes, AC-10-86) is
long enough that the orphan sweep's liveness window
(``background_job_orphan_after_minutes``, default 15) would fire mid-build,
stamping the snapshot ``failed``/``BUILD_ABANDONED`` out from under the
still-running handler, which would then crash on ``_assert_building``
(``SnapshotNotBuildingError``) the moment it tried to insert a row or stamp
``ready``.

RED before the fix (proven by reasoning, not by reverting the coder's own
in-progress work): before this round, ``HttpApiSource`` had no ``heartbeat``
constructor kwarg at all and ``_run_pull_snapshot`` never called
``JobService.heartbeat``/re-read the snapshot mid-build, so
``test_heartbeat_fires_at_least_once_per_source_page`` would fail with ZERO
recorded beats (``TypeError`` on the ``heartbeat=`` kwarg even earlier), and
``test_build_abandoned_mid_walk_ends_cleanly`` would fail with an
UNHANDLED ``SnapshotNotBuildingError`` escaping the handler instead of the
job ending FAILED cleanly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_FAILED
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    PULL_SNAPSHOT_STATUS_FAILED,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcPullSnapshotRow,
    AcSyncRun,
)

DB_NAME = "AED_SORENTO"
REF_PREFIX = "AED_SORENTO"
BASE_URL = "https://hapi.sorento.cc.cd/api/db1"

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


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


def _row(source_path, canonical_field, transform="string", *, required=False):
    return dict(source_path=source_path, canonical_field=canonical_field, transform=transform, is_required=required)


def _product_task(db, company, connection_id, *, mapping_rows=None, lookups=None) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, delivery_mode="pull",
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
    for i, row in enumerate(mapping_rows or []):
        db.add(AcFieldMapping(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            scope="header", sort_order=i, **row,
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


def _build(db, company, *, entity_type=ENTITY_PRODUCT, now=NOW):
    from modules.autocount.services.pull_service import PullService

    return PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, entity_type, requested_via="operator", now=now,
    )


def _spy_heartbeat(monkeypatch, *, on_call=None):
    """Wraps the REAL per-page liveness write (never a no-op stub, so a
    heartbeat that silently stopped doing anything real would still show up
    as a recorded call but the job's own liveness columns would tell a
    different story) and records every call. ``on_call`` (if given) runs
    AFTER the real beat, keyed by the 1-based call number - used to inject
    the "a concurrent orphan sweep just failed this snapshot" side effect.

    sprint-5/11 S5 (AC-11-40) - ``_beat_and_check`` now stamps liveness
    through ``JobService.beat_progress`` (heartbeat_at + progress in ONE
    UPDATE, never a second write) instead of the bare ``JobService.
    heartbeat`` this spy used to wrap - re-pointed at the SAME per-page
    checkpoint's new mechanism; every assertion in this file (beat COUNT,
    and the abandon-after-first-beat side effect) is unchanged."""
    from app.jobs.service import JobService

    calls: List[str] = []
    real_beat_progress = JobService.beat_progress

    def spy(self, job_id, *, done=None, total=None, stage=None):
        result = real_beat_progress(self, job_id, done=done, total=total, stage=stage)
        calls.append(job_id)
        if on_call is not None:
            on_call(len(calls))
        return result

    monkeypatch.setattr(JobService, "beat_progress", spy)
    return calls


def _two_page_handler(requests_seen: List[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        page = request.url.params.get("page")
        if page == "1":
            body: Dict[str, Any] = {
                "TotalCount": 2, "Page": 1, "PageSize": 1, "TotalPages": 2,
                "Data": [{"ItemCode": "A1", "Description": "Item A1"}],
            }
        else:
            body = {
                "TotalCount": 2, "Page": 2, "PageSize": 1, "TotalPages": 2,
                "Data": [{"ItemCode": "A2", "Description": "Item A2"}],
            }
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


# ── beat called >= once per page on a multi-page stub ───────────────────────


def test_heartbeat_fires_at_least_once_per_source_page(db, monkeypatch):
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, mapping_rows=[_row("ItemCode", "code", required=True)])

    requests_seen: List[httpx.Request] = []
    _patch_transport(monkeypatch, _two_page_handler(requests_seen))
    calls = _spy_heartbeat(monkeypatch)

    snapshot = _build(db, company)
    db.refresh(snapshot)

    assert len(requests_seen) == 2, "both pages must have been fetched"
    assert len(calls) >= 2, (
        f"expected at least one heartbeat per page (2 pages), got {len(calls)}"
    )
    assert snapshot.status == "ready"
    assert snapshot.record_count == 2


def test_heartbeat_fires_for_lookup_endpoint_pages_too(db, monkeypatch):
    """The heartbeat callback is threaded into ``HttpApiSource`` itself, not
    bolted onto the main path only - a lookup endpoint routes through the
    SAME ``_walk_endpoint``/``_walk_path`` and must beat too (AC-10-26's own
    "main path AND lookup endpoints")."""
    lookup = {
        "path": "/itemuombypage", "as": "uom",
        "on": [{"local": "ItemCode", "remote": "ItemCode"}],
        "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
    }
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(
        db, company, conn.id, lookups=[lookup],
        mapping_rows=[_row("ItemCode", "code", required=True)],
    )

    requests_seen: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        if request.url.path.endswith("/itembypage"):
            return httpx.Response(
                200,
                json={
                    "TotalCount": 1, "Page": 1, "PageSize": 1, "TotalPages": 1,
                    "Data": [{"ItemCode": "A1", "Description": "Item A1"}],
                },
            )
        # The lookup endpoint alone answers TWO pages.
        page = request.url.params.get("page")
        if page == "1":
            body = {
                "TotalCount": 2, "Page": 1, "PageSize": 1, "TotalPages": 2,
                "Data": [{"ItemCode": "X1", "Price": 1.0}],
            }
        else:
            body = {
                "TotalCount": 2, "Page": 2, "PageSize": 1, "TotalPages": 2,
                "Data": [{"ItemCode": "A1", "Price": 2.0}],
            }
        return httpx.Response(200, json=body)

    _patch_transport(monkeypatch, httpx.Client(transport=httpx.MockTransport(handler)))
    calls = _spy_heartbeat(monkeypatch)

    snapshot = _build(db, company)
    db.refresh(snapshot)

    # 1 main page + 2 lookup pages = 3 requests, so >= 3 beats.
    assert len(requests_seen) == 3
    assert len(calls) >= 3, (
        f"expected a beat per page INCLUDING the lookup's own pages, got {len(calls)}"
    )
    assert snapshot.status == "ready"


# ── a build abandoned mid-walk (the orphan sweep, from elsewhere) ends CLEAN ─


def test_build_abandoned_mid_walk_ends_cleanly_not_a_crash(db, monkeypatch):
    """Simulates the orphan sweep firing on a DIFFERENT session/process while
    this build is mid-walk: right after the FIRST heartbeat (page 1's own
    beat), the snapshot is flipped to ``failed``/``BUILD_ABANDONED`` - exactly
    what ``bootstrap.on_job_orphaned`` does. The handler must notice on its
    OWN next status re-read and stop CLEANLY: no second page ever requested,
    no row ever inserted, no ``ready`` stamp, the job ends FAILED with a
    clear message rather than an unhandled ``SnapshotNotBuildingError``."""
    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id, mapping_rows=[_row("ItemCode", "code", required=True)])

    requests_seen: List[httpx.Request] = []
    _patch_transport(monkeypatch, _two_page_handler(requests_seen))

    from modules.autocount.models import PULL_SNAPSHOT_STATUS_BUILDING, AcPullSnapshot

    def abandon_after_first_beat(call_number: int) -> None:
        if call_number != 1:
            return
        # The FIRST beat corresponds to page 1 - flip THIS build's own
        # snapshot NOW, from the SAME session for the test's sake (a real
        # orphan sweep runs on a fresh one, but the observable effect - the
        # row's own status column changing under the handler - is
        # identical). ``request_build`` runs the job INLINE (eager) under
        # this suite's conftest default, so the snapshot it just created is
        # already flushed and visible to a query on this SAME session even
        # though the OUTER ``request_build`` call has not committed yet -
        # found by the TRIPLE (there is exactly one ``building`` row for it
        # at this point), never by an id this callback has no way to know
        # in advance.
        snap = (
            db.query(AcPullSnapshot)
            .filter(
                AcPullSnapshot.tenant_id == DEFAULT_TENANT_ID,
                AcPullSnapshot.company_id == company.id,
                AcPullSnapshot.entity_type == ENTITY_PRODUCT,
                AcPullSnapshot.status == PULL_SNAPSHOT_STATUS_BUILDING,
            )
            .one()
        )
        snap.status = PULL_SNAPSHOT_STATUS_FAILED
        snap.error = "The worker stopped before this build finished."
        snap.error_code = "BUILD_ABANDONED"
        db.commit()

    _spy_heartbeat(monkeypatch, on_call=abandon_after_first_beat)

    from modules.autocount.services.pull_service import PullService

    snapshot = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    db.refresh(snapshot)

    assert len(requests_seen) == 1, "page 2 must NEVER be requested once abandoned"
    assert snapshot.status == PULL_SNAPSHOT_STATUS_FAILED
    assert snapshot.error_code == "BUILD_ABANDONED"
    assert (
        db.query(AcPullSnapshotRow).filter(AcPullSnapshotRow.snapshot_id == snapshot.id).count()
        == 0
    ), "no row may ever be inserted once the build is abandoned"

    job = None
    from app.models.background_job import BackgroundJob

    job = db.query(BackgroundJob).filter(BackgroundJob.id == snapshot.job_id).one()
    assert job.status == JOB_FAILED

    from modules.autocount.models import RUN_FAILED

    run = db.query(AcSyncRun).filter(AcSyncRun.job_id == job.id).one()
    assert run.outcome == RUN_FAILED
    assert run.finished_at is not None
