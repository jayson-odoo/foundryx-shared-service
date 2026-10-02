"""Sprint-5/10 S3 review round 1 - SHOULD-FIX 4 (AC-10-26): the partial
unique index is enforced by the DATABASE, and ``PullService.request_build``
survives losing that race cleanly.

Coordinator finding: the WIP caught the ``IntegrityError`` from a losing
INSERT with a bare top-level ``self.db.rollback()`` - correct for THIS
snapshot's own attempt, but a rollback of the WHOLE session would also
discard any OTHER, unrelated work already staged earlier in the same
request/session. The fix runs the INSERT inside its own SAVEPOINT
(``begin_nested``, the same pattern ``NumberingRepository.
get_or_create_counter_for_update`` already uses for this exact class of
unique-constraint race), so only the losing attempt unwinds.

RED before the fix (proven by reasoning): before the partial unique index
existed at all (``models.py``/migration 0020's own SHOULD-FIX 4), two
``building`` rows for the same triple could simply coexist - there was
nothing to violate, so ``test_a_second_building_insert_for_the_same_triple_
reattaches_via_the_db_race`` would find TWO rows instead of one. This suite
proves the CURRENT code (WIP + this round's fix) is correct going forward
via a genuine simulated race, not merely re-running the existing "the
in-memory guard already caught it" test.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    PULL_SNAPSHOT_STATUS_BUILDING,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcPullSnapshot,
)

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    ``test_s10_s3_delivery_mode.py``'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20: an earlier revision made a
    real ~8-minute call to ``hapi.sorento.cc.cd``)."""
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


def _patch_transport(monkeypatch, transport: httpx.Client) -> None:
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=transport),
    )


def _single_page_transport() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [{"ItemCode": "A1", "Description": "A1"}],
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


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
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _product_task(db, company, connection_id) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE, delivery_mode="pull",
        source_config={
            "connectionId": connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
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
    db.commit()
    db.refresh(config)
    return config


def _triple_count(db, company) -> int:
    return (
        db.query(AcPullSnapshot)
        .filter(
            AcPullSnapshot.tenant_id == DEFAULT_TENANT_ID,
            AcPullSnapshot.company_id == company.id,
            AcPullSnapshot.entity_type == ENTITY_PRODUCT,
        )
        .count()
    )


def test_a_second_building_insert_for_the_same_triple_reattaches_via_the_db_race(
    db, monkeypatch
):
    """A genuine DB-level race, not the in-memory guard: a REAL ``building``
    row for the triple already exists, but ``request_build``'s OWN initial
    read (``PullSnapshotRepository.latest_for_triple``) is forced to miss it
    on its FIRST call only (simulating "the winner's row was not yet
    visible/committed when this request's own read ran") - the SECOND call
    (inside the ``except IntegrityError`` handler) is the REAL, unpatched
    method. ``request_build`` must therefore attempt the INSERT, lose the
    unique-index race, and re-attach to the WINNER - never a second
    extraction, never an unhandled 500."""
    from modules.autocount.repositories import PullSnapshotRepository
    from modules.autocount.services.pull_service import PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)

    winner = AcPullSnapshot(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        company_code=company.sorento_company_code, status=PULL_SNAPSHOT_STATUS_BUILDING,
        requested_via="operator",
    )
    db.add(winner)
    db.commit()
    db.refresh(winner)

    real_latest_for_triple = PullSnapshotRepository.latest_for_triple
    calls = {"n": 0}

    def stale_read_once(self, tenant_id, company_id, entity_type):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_latest_for_triple(self, tenant_id, company_id, entity_type)

    monkeypatch.setattr(PullSnapshotRepository, "latest_for_triple", stale_read_once)

    result = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )

    assert calls["n"] == 2, "the initial (stale) read and the loser's re-fetch"
    assert result.id == winner.id
    assert _triple_count(db, company) == 1, "the loser's INSERT must never leave a second row behind"


def test_a_ready_snapshot_and_a_building_snapshot_coexist_for_the_same_triple(db, monkeypatch):
    """The partial unique index's predicate is ``status = 'building'`` ONLY
    - a ``ready`` row for the SAME triple must never collide with a fresh
    build (control: proves the index is correctly SCOPED, not a blanket
    one-row-per-triple constraint)."""
    from modules.autocount.services.pull_service import PullService, SnapshotService

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)
    _patch_transport(monkeypatch, _single_page_transport())

    ready = SnapshotService(db).create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    SnapshotService(db).stamp_ready(
        DEFAULT_TENANT_ID, ready, record_count=1, complete=True,
        content_hash="a" * 64, metadata={},
        extracted_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(hours=23),
    )

    # ``request_build`` runs the job INLINE (eager) under this suite's own
    # conftest default, so by the time it returns the row has ALREADY
    # reached its terminal state (mirrors ``test_s10_s3_snapshot_build_job.
    # py``'s own build-job tests) - what matters here is that the INSERT
    # of this SECOND row for the triple never collided with the first
    # (``ready``) one, never that it is still literally mid-flight.
    second = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator",
        now=NOW + timedelta(minutes=5),
    )

    assert second.id != ready.id
    assert second.status == "ready"
    assert _triple_count(db, company) == 2


def test_losing_the_race_never_discards_unrelated_pending_session_state(db, monkeypatch):
    """The decisive test: a bare top-level ``self.db.rollback()`` and a
    SAVEPOINT-scoped one are OBSERVATIONALLY IDENTICAL from ``request_build``'s
    own return value alone (both re-attach to the winner correctly) - this is
    why the previous test cannot tell them apart. The difference only shows
    up in what happens to OTHER, unrelated work already pending on the SAME
    session before the race: a bare ``rollback()`` discards it; a SAVEPOINT
    unwinds only the losing INSERT."""
    from modules.autocount.repositories import PullSnapshotRepository
    from modules.autocount.services.pull_service import PullService

    conn = _connection(db)
    company = _company(db, conn.id)
    _product_task(db, company, conn.id)

    winner = AcPullSnapshot(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        company_code=company.sorento_company_code, status=PULL_SNAPSHOT_STATUS_BUILDING,
        requested_via="operator",
    )
    db.add(winner)
    db.commit()
    db.refresh(winner)

    real_latest_for_triple = PullSnapshotRepository.latest_for_triple
    calls = {"n": 0}

    def stale_read_once(self, tenant_id, company_id, entity_type):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_latest_for_triple(self, tenant_id, company_id, entity_type)

    monkeypatch.setattr(PullSnapshotRepository, "latest_for_triple", stale_read_once)

    # Unrelated pending work already sitting on THIS session before the race
    # - never flushed/committed by the caller, exactly like a router that
    # touched something else earlier in the SAME request.
    other_connection = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp",
        name="an unrelated pending connection - must survive the race",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db9", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(other_connection)

    result = PullService(db).request_build(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, requested_via="operator", now=NOW,
    )
    assert result.id == winner.id

    # The caller's own later commit (unrelated to the build) must still see
    # the pending connection - a SAVEPOINT never touched it.
    db.commit()
    assert (
        db.query(Connection)
        .filter(Connection.name == "an unrelated pending connection - must survive the race")
        .count()
        == 1
    ), "the losing build attempt's error recovery discarded unrelated pending session state"


# ── kill tests ────────────────────────────────────────────────────────────
#
# * test_a_second_building_insert_for_the_same_triple_reattaches_via_the_db_race
#   dies (raw IntegrityError escapes, or a SECOND building row appears) if
#   the INSERT is not actually wrapped in a race-tolerant SAVEPOINT/retry -
#   this is the ONLY test in the round that forces execution PAST the
#   in-memory guard and into the real database-level race.
# * test_a_ready_snapshot_and_a_building_snapshot_coexist_for_the_same_triple
#   dies if the partial index's predicate is ever loosened to cover every
#   status (a blanket one-row-per-triple unique index) rather than
#   ``status = 'building'`` only.
