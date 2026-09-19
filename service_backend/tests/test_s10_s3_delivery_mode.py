"""Sprint-5/10 S3 - Group B, delivery mode: AC-10-10..15.

RED before the coder for a plain, structural reason: ``AcEntityConfig`` has no
``delivery_mode`` column at all today (``modules/autocount/models.py``), so
every test below fails on ``AttributeError`` (direct model access) or on the
service/route simply not existing yet (``EtlService.set_delivery_mode``,
``PUT .../delivery-mode``) - never a silent pass.

ASSUMED NAMES the coder must conform to (none of these exist on this branch
yet; chosen from the plan's decision log D1/D2 + files list + AC-10-10..15):

* ``modules.autocount.models``: ``DELIVERY_MODE_PUSH = "push"``,
  ``DELIVERY_MODE_PULL = "pull"``, ``DELIVERY_MODES = (PUSH, PULL)``,
  ``AcEntityConfig.delivery_mode`` (``String NOT NULL default 'push'``,
  ``server_default='push'``).
* ``modules.autocount.backfill.backfill_delivery_mode_defaults(bind, *,
  schema=AUTOCOUNT_SCHEMA) -> int`` - same shape/contract as the sibling
  ``backfill_sink_impl_defaults`` (fills only NULL/blank rows, schema-tolerant,
  does not commit).
* ``modules.autocount.services.etl_service.EtlService.set_delivery_mode(
  tenant_id, company_id, entity_type, delivery_mode) -> EtlTaskView`` - raises
  ``EtlValidationError({"deliveryMode": "..."})`` (422) for: an unknown mode,
  ``pull`` with no ``sorento_company_code`` on the company, or ``pull``/`push`
  on an entity outside the pull-capable set
  (``modules.autocount.services.etl_service.PULL_CAPABLE_ENTITY_TYPES``,
  assumed to be a tuple containing at least ``ENTITY_PRODUCT``).
* ``PUT /autocount/companies/{company_id}/entities/{entity_type}/delivery-mode``
  body ``{"deliveryMode": "push"|"pull"}``, permission
  ``autocount.companies.manage``, response ``EntityConfigItem`` (the coordinator's
  ruling: this is the SAME wire shape the frontend mock already ships -
  ``service_frontend/services/autocount-service.real.ts``'s ``setDeliveryMode``
  PUTs exactly this path/body and reads back ``AutocountEntityConfig``, whose
  camelCase field is ``deliveryMode``). Mounted in ``routers/companies.py``
  beside ``update_entity_config`` (same router, same permission, same
  ``EntityConfigItem`` response model already imported there).
* ``EtlService.activate_task`` arms NO schedule
  (``next_incremental_at``/``next_reconcile_at`` both ``None``) for a task whose
  ``delivery_mode == DELIVERY_MODE_PULL``; ``set_delivery_mode`` itself clears
  both immediately when flipping an ACTIVE task to ``pull``, and re-arms them
  via ``EtlService.next_run_times`` (the exact function ``activate_task``
  already calls) when flipping ``pull -> push`` on an ACTIVE task.
* ``sync.py``'s two auto-push branches (~L811 ``config.etl_status ==
  ETL_STATUS_ACTIVE`` and ~L1876 the paged-path twin) additionally require
  ``config.delivery_mode == DELIVERY_MODE_PUSH``.
* ``scheduler.sweep_etl_tasks``'s due query additionally filters
  ``AcEntityConfig.delivery_mode == DELIVERY_MODE_PUSH``.

Kill-test notes are per section below.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_CUSTOMER, ENTITY_PRODUCT
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    ETL_STATUS_DRAFT,
    AcCompany,
    AcEntityConfig,
)
from modules.autocount.scheduler import sweep_etl_tasks
from modules.autocount.services.etl_service import EtlService, EtlValidationError

try:
    from modules.autocount.models import DELIVERY_MODE_PULL, DELIVERY_MODE_PUSH
except ImportError:  # pragma: no cover - expected until the coder adds them
    DELIVERY_MODE_PUSH = "push"
    DELIVERY_MODE_PULL = "pull"

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. A real
    ``httpx.Client``/``AsyncClient`` backed by an ACTUAL network transport
    (``HTTPTransport``/``AsyncHTTPTransport`` - never a ``MockTransport``,
    and never the FastAPI ``TestClient``'s in-process ASGI transport) raises
    loudly instead of making a request. Coordinator finding 2026-09-20: an
    earlier revision of ``test_sweep_fires_only_the_push_task_...`` made a
    real ~8-minute call to ``hapi.sorento.cc.cd``."""
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


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str, *, sorento_company_code="SRT") -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True,
        sorento_company_code=sorento_company_code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _http_raw(**overrides) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "sourceImpl": "autocount_http",
        "connectionId": None,
        "path": "/itembypage",
        "keyFields": ["ItemCode"],
        "watermarkField": "LastModified",
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": 15,
        "reconcileMode": "dailyAt",
        "reconcileHours": None,
        "reconcileAt": "02:00",
        "lookups": [],
    }
    raw.update(overrides)
    return raw


def _stamp_previewed(db, company_id: str, entity_type: str = ENTITY_PRODUCT) -> None:
    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company_id, entity_type)
    config.last_preview_at = NOW
    config.result_columns = ["ItemCode", "Description", "BaseUOM", "LastModified"]
    db.commit()


def _transport(rows=None):
    body = rows if rows is not None else {"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


# ── AC-10-10: column default + backfill ──────────────────────────────────────


def test_every_existing_task_reads_push_by_default(db):
    """A row inserted with no opinion on ``delivery_mode`` at all reads
    ``push`` - the model default, matching every task that existed before
    this plan (AC-10-10)."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", source_config=_http_raw(connectionId=conn.id),
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    assert config.delivery_mode == DELIVERY_MODE_PUSH


def test_backfill_delivery_mode_defaults_fills_blank_rows_only(db):
    """Mirrors ``backfill_sink_impl_defaults``'s own contract test shape: a
    row a ``create_all``-first host may have left NULL/blank against the NOT
    NULL column is filled to ``push``; a row already holding an opinion (here
    ``pull``) is untouched. CONTROL: the blank row is asserted BEFORE the
    backfill runs too, proving the SQL bypass below genuinely produced an
    unbackfilled row (a test that only checked the post-state could pass even
    if ``server_default`` alone already fixed it on this dialect)."""
    from modules.autocount.backfill import backfill_delivery_mode_defaults

    conn = _open_connection(db)
    company = _company(db, conn.id)
    blank = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", source_config=_http_raw(connectionId=conn.id),
    )
    opinionated = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_CUSTOMER,
        source_impl="sql_db", source_config={},
    )
    db.add_all([blank, opinionated])
    db.commit()
    # Simulate a legacy row (the ADD-without-server_default order): bypass the
    # ORM default with a raw UPDATE so the row genuinely holds NULL/blank.
    db.execute(
        AcEntityConfig.__table__.update()
        .where(AcEntityConfig.id == blank.id)
        .values(delivery_mode=None)
    )
    db.execute(
        AcEntityConfig.__table__.update()
        .where(AcEntityConfig.id == opinionated.id)
        .values(delivery_mode=DELIVERY_MODE_PULL)
    )
    db.commit()
    db.refresh(blank)
    db.refresh(opinionated)
    assert blank.delivery_mode is None  # control: genuinely blank pre-backfill

    touched = backfill_delivery_mode_defaults(db.connection(), schema=None)

    db.refresh(blank)
    db.refresh(opinionated)
    assert blank.delivery_mode == DELIVERY_MODE_PUSH
    assert opinionated.delivery_mode == DELIVERY_MODE_PULL  # untouched
    assert touched == 1


# ── AC-10-11: PUT .../delivery-mode validation + route ───────────────────────


def test_set_delivery_mode_to_pull_requires_a_sorento_company_code(db):
    conn = _open_connection(db)
    company = _company(db, conn.id, sorento_company_code=None)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", source_config=_http_raw(connectionId=conn.id),
        )
    )
    db.commit()

    with pytest.raises(EtlValidationError) as exc:
        EtlService(db).set_delivery_mode(
            DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, DELIVERY_MODE_PULL
        )
    assert "deliveryMode" in exc.value.field_errors


def test_set_delivery_mode_to_pull_succeeds_with_a_company_code(db):
    conn = _open_connection(db)
    company = _company(db, conn.id, sorento_company_code="SRT")
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", source_config=_http_raw(connectionId=conn.id),
        )
    )
    db.commit()

    view = EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, DELIVERY_MODE_PULL
    )
    assert view.delivery_mode == DELIVERY_MODE_PULL


def test_set_delivery_mode_refuses_an_entity_outside_the_pull_capable_set(db):
    """A ``customer`` task (a push-only master with no pull meaning in this
    plan) 422s naming the entity rather than silently accepting a mode that
    can never be served."""
    conn = _open_connection(db)
    company = _company(db, conn.id, sorento_company_code="SRT")
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_CUSTOMER,
            source_impl="sql_db", source_config={},
        )
    )
    db.commit()

    with pytest.raises(EtlValidationError) as exc:
        EtlService(db).set_delivery_mode(
            DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER, DELIVERY_MODE_PULL
        )
    assert "deliveryMode" in exc.value.field_errors


def test_set_delivery_mode_touches_no_mapping_or_source_config(db):
    """AC-10-11: "the switch does NOT touch source_config, mapping rows,
    result_columns or ac_row_hash." """
    conn = _open_connection(db)
    company = _company(db, conn.id, sorento_company_code="SRT")
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        source_config=_http_raw(connectionId=conn.id, keyFields=["ItemCode"]),
        result_columns=["ItemCode", "Description"],
    )
    db.add(config)
    db.commit()

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, DELIVERY_MODE_PULL
    )
    db.refresh(config)
    assert config.source_config.get("keyFields") == ["ItemCode"]
    assert config.result_columns == ["ItemCode", "Description"]


def test_put_delivery_mode_route_updates_and_returns_entity_config(client, db):
    """Router-level (AC-10-11 + AC-10-37's own precondition that these routes
    exist under the authed API). Wire shape pinned per the coordinator's
    ruling: this is NOT the public gateway's Appendix A shape - it is the
    Phase-1 FE contract already shipped in ``autocount-service.real.ts``
    (``setDeliveryMode``): ``PUT
    /autocount/companies/{id}/entities/{entityType}/delivery-mode
    {deliveryMode}`` -> the ``EntityConfigItem`` wire shape (camelCase
    ``entityType``/``etlStatus``/``deliveryMode``)."""
    conn = _open_connection(db)
    company = _company(db, conn.id, sorento_company_code="SRT")
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", source_config=_http_raw(connectionId=conn.id),
        )
    )
    db.commit()

    login = client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    response = client.put(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/delivery-mode",
        json={"deliveryMode": "pull"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entityType"] == ENTITY_PRODUCT
    assert body["deliveryMode"] == "pull"


def test_put_delivery_mode_route_422_names_the_field_on_missing_company_code(client, db):
    conn = _open_connection(db)
    company = _company(db, conn.id, sorento_company_code=None)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", source_config=_http_raw(connectionId=conn.id),
        )
    )
    db.commit()

    login = client.post("/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    token = login.json()["access_token"]
    response = client.put(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/delivery-mode",
        json={"deliveryMode": "pull"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422, response.text
    assert "deliveryMode" in response.json()["detail"]["fieldErrors"]


# ── AC-10-12: a pull task never auto-pushes ──────────────────────────────────


def test_run_autocount_sync_in_pull_mode_never_calls_auto_push(db, monkeypatch):
    """Mutation test: spies on ``SyncService.auto_push`` (never patched to a
    no-op stub that could hide a call) and asserts zero calls, plus that
    nothing landed in ``ac_staged_record`` - the same double-barrelled check
    ``sync.py``'s own review history uses for this exact class of bug (a
    push branch that looks gated but is not)."""
    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.models import AcStagedRecord
    from modules.autocount.services.sync_service import SyncService
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [{"ItemCode": "A1", "Description": "Item A1", "LastModified": "2026-08-01T09:00:00", "IsActive": "T"}],
            },
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )
    calls: list = []
    monkeypatch.setattr(
        SyncService, "auto_push",
        lambda self, *a, **kw: calls.append((a, kw)) or {"pushed": 0},
    )

    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE,
        delivery_mode=DELIVERY_MODE_PULL,
        source_config=_http_raw(connectionId=conn.id),
    )
    db.add(config)
    db.commit()

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_PRODUCT, "mode": "manual"},
    )
    run_autocount_sync(db, job)

    assert calls == [], "auto_push must never be called for a pull-mode task"
    assert db.query(AcStagedRecord).filter(AcStagedRecord.company_id == company.id).count() == 0


def test_run_autocount_sync_in_push_mode_control_still_calls_auto_push(db, monkeypatch):
    """Control for the test above: the SAME rig with ``delivery_mode='push'``
    (today's default) DOES call ``auto_push`` - proving the spy itself is
    wired correctly and the pull test above is not vacuously green."""
    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.services.sync_service import SyncService
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "TotalCount": 1, "Page": 1, "PageSize": 1000, "TotalPages": 1,
                "Data": [{"ItemCode": "A1", "Description": "Item A1", "LastModified": "2026-08-01T09:00:00", "IsActive": "T"}],
            },
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )
    calls: list = []
    monkeypatch.setattr(
        SyncService, "auto_push",
        lambda self, *a, **kw: calls.append((a, kw)) or {"pushed": 0},
    )

    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE,
        delivery_mode=DELIVERY_MODE_PUSH,
        source_config=_http_raw(connectionId=conn.id),
    )
    db.add(config)
    db.commit()

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_PRODUCT, "mode": "manual"},
    )
    run_autocount_sync(db, job)

    assert len(calls) == 1


# ── AC-10-13: a pull task never runs on the sweep; activate arms nothing ─────


def test_sweep_fires_only_the_push_task_of_one_due_push_and_one_due_pull(db, monkeypatch):
    """The sweep's ``fired`` claim enqueues a REAL job which, under this
    suite's eager job setting, runs ``run_autocount_sync`` INLINE before
    ``sweep_etl_tasks`` returns - so the due PUSH task's own HTTP call must
    be stubbed here too (coordinator finding 2026-09-20: an earlier revision
    of this test made a real, ~8-minute call to ``hapi.sorento.cc.cd``)."""
    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.http_source.client import HttpApiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []},
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    conn = _open_connection(db)
    company = _company(db, conn.id)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE,
            delivery_mode=DELIVERY_MODE_PUSH,
            source_config=_http_raw(connectionId=conn.id),
            next_incremental_at=NOW - timedelta(minutes=1),
        )
    )
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_CUSTOMER,
            source_impl="sql_db", etl_status=ETL_STATUS_ACTIVE,
            delivery_mode=DELIVERY_MODE_PULL,
            source_config={
                "connectionId": conn.id, "query": "SELECT 1 AS acc_no",
                "keyColumns": ["acc_no"], "watermarkColumn": None, "comparedColumns": [],
                "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
            },
            # A pull task's due times SHOULD be NULL by construction, but the
            # AC's own test asks for "whose due times are in the past" - the
            # gate under test is the delivery_mode FILTER itself, not merely
            # the (already-covered-elsewhere) absence of an armed schedule.
            next_incremental_at=NOW - timedelta(minutes=1),
        )
    )
    db.commit()

    result = sweep_etl_tasks(db, now=NOW)
    assert result["fired"] == 1, result


def test_activate_task_arms_no_schedule_for_a_pull_task(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", delivery_mode=DELIVERY_MODE_PULL,
            source_config=_http_raw(connectionId=conn.id),
        )
    )
    db.commit()
    _stamp_previewed(db, company.id)

    view = EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert view.etl_status == ETL_STATUS_ACTIVE

    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config.next_incremental_at is None
    assert config.next_reconcile_at is None


def test_switching_an_active_task_to_pull_clears_the_armed_schedule_immediately(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", delivery_mode=DELIVERY_MODE_PUSH,
            source_config=_http_raw(connectionId=conn.id),
        )
    )
    db.commit()
    _stamp_previewed(db, company.id)
    EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config.next_incremental_at is not None  # control: armed by activate

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, DELIVERY_MODE_PULL
    )
    db.refresh(config)
    assert config.next_incremental_at is None
    assert config.next_reconcile_at is None


# ── AC-10-14: pull -> push re-arms; push -> pull disarms; byte-identical ─────


def test_flipping_pull_to_push_on_an_active_task_rearms_the_schedule(db):
    conn = _open_connection(db)
    company = _company(db, conn.id)
    source_config = _http_raw(
        connectionId=conn.id, keyFields=["ItemCode"], incrementalMinutes=30,
    )
    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="autocount_http", delivery_mode=DELIVERY_MODE_PULL,
            source_config=source_config, result_columns=["ItemCode", "Description", "BaseUOM"],
        )
    )
    db.commit()
    _stamp_previewed(db, company.id)
    EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    from modules.autocount.repositories import EntityConfigRepository

    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config.next_incremental_at is None  # control: pull activation arms nothing
    # Captured AFTER `_stamp_previewed` (which overwrites `result_columns`
    # itself, AC-10-11's OWN concern for a different call) and BEFORE the
    # mode flips below - the byte-identical assertion must compare against
    # what `set_delivery_mode` actually received, never a fixture value it
    # never saw.
    result_columns = list(config.result_columns)

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, DELIVERY_MODE_PUSH
    )
    db.refresh(config)
    assert config.next_incremental_at is not None
    assert config.next_reconcile_at is not None
    # No re-mapping, no status change, byte-identical config.
    assert config.etl_status == ETL_STATUS_ACTIVE
    assert config.source_config.get("keyFields") == ["ItemCode"]
    assert config.result_columns == result_columns
