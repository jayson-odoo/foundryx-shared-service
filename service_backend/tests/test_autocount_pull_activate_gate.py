"""Prod hotfix (2026-09-21) - a PULL-mode product task must not be blocked
from Activate by a consumer-side dry-run failure count.

Defect: ``EtlService.activate_task``
(``modules/autocount/services/etl_service.py`` ~2672) raises
``EtlStateError`` whenever ``config.last_preview_failed_count`` is truthy,
regardless of ``delivery_mode``. For a PULL task the rows are never pushed by
Foundryx - the consumer (Sorento) pulls the snapshot, its OWN review page
lists per-record failures, and Confirm proceeds for the rest (plan
sprint-5/10 ruling R6, "products never block"). A pull task whose failures
are genuinely consumer-side (a ref collision no Foundryx mapping can fix) is
stuck in Draft forever today.

PUSH mode must NOT change: the gate protects the path where Foundryx itself
delivers the failing rows, so a push-mode task with the same state must keep
409ing with the EXACT existing message (control, pinned below).

Helper shape (``_open_connection``/``_company``/``_http_raw``/
``_stamp_previewed``) is lifted byte-for-byte from
``tests/test_s10_s3_delivery_mode.py`` - the sibling suite that already
builds this exact pull-mode-product rig and successfully activates it
(``test_activate_task_arms_no_schedule_for_a_pull_task``), so this file's
CONTROL cases are known-good shapes, not a new rig.

RED expectation:
* (1) and (4) FAIL today - ``activate_task`` refuses the pull-mode task with
  failed rows, so it never reaches ACTIVE and there is no post-activation
  field to read.
* (2) and (3) PASS today (controls: push-mode-with-failures still blocks;
  no-preview-at-all still blocks regardless of mode) - proving this file
  is not vacuously red end to end.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import ETL_STATUS_ACTIVE, AcCompany, AcEntityConfig
from modules.autocount.repositories import EntityConfigRepository
from modules.autocount.services.etl_service import EtlService, EtlStateError

try:
    from modules.autocount.models import DELIVERY_MODE_PULL, DELIVERY_MODE_PUSH
except ImportError:  # pragma: no cover - both already exist on this branch
    DELIVERY_MODE_PUSH = "push"
    DELIVERY_MODE_PULL = "pull"

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)

# Pinned verbatim from ``EtlService.activate_task`` - the message this file's
# push-mode control (test 2) must keep seeing UNCHANGED.
EXISTING_FAILED_ROWS_MESSAGE = (
    "The last preview reported 4 failed row(s) - re-run preview after "
    "fixing the mapping before activating."
)
# Pinned verbatim - the "preview first" gate (test 3), unchanged by this fix.
NO_PREVIEW_MESSAGE = "Run a successful preview of the initial load before activating."


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule copied from ``test_s10_s3_delivery_mode.py``: no test in
    this file may touch the network - ``activate_task`` itself never should,
    but a regression that made it call out must fail loudly, not hang."""
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


def _stamp_previewed(db, company_id: str, *, failed_count) -> None:
    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company_id, ENTITY_PRODUCT)
    config.last_preview_at = NOW
    config.result_columns = ["ItemCode", "Description", "BaseUOM", "LastModified"]
    config.last_preview_failed_count = failed_count
    db.commit()


def _config(db, connection_id: str, company_id: str, *, delivery_mode: str) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", delivery_mode=delivery_mode,
        source_config=_http_raw(connectionId=connection_id),
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


# ── (1) pull + failed rows: MUST activate ────────────────────────────────────


def test_pull_mode_activates_despite_a_failed_dry_run_count(db):
    """The defect under fix: today this raises ``EtlStateError`` and never
    reaches ACTIVE - after the fix it must succeed outright."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _config(db, conn.id, company.id, delivery_mode=DELIVERY_MODE_PULL)
    _stamp_previewed(db, company.id, failed_count=4)

    view = EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    assert view.etl_status == ETL_STATUS_ACTIVE


# ── (2) push + failed rows: CONTROL, must keep refusing verbatim ────────────


def test_push_mode_control_still_refuses_with_the_existing_message(db):
    """Push mode is untouched by this fix - same state, same 409, same
    wording as today."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _config(db, conn.id, company.id, delivery_mode=DELIVERY_MODE_PUSH)
    _stamp_previewed(db, company.id, failed_count=4)

    with pytest.raises(EtlStateError) as exc:
        EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    assert str(exc.value) == EXISTING_FAILED_ROWS_MESSAGE


# ── (3) pull + NO preview at all: the "preview first" gate is unchanged ─────


def test_pull_mode_without_any_preview_still_refuses(db):
    """The failed-count fix must not weaken the SEPARATE "a preview ran at
    all" gate - a pull task that was never previewed is still refused, with
    the same wording as today."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _config(db, conn.id, company.id, delivery_mode=DELIVERY_MODE_PULL)
    # No `_stamp_previewed` call at all: `last_preview_at` stays None.

    with pytest.raises(EtlStateError) as exc:
        EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    assert str(exc.value) == NO_PREVIEW_MESSAGE


# ── (4) the failed count survives activation, for the FE to warn from ───────


def test_pull_mode_activation_keeps_the_failed_count_on_the_task_view(db):
    """The FE's Activate tab needs ``lastPreviewFailedCount`` intact AFTER a
    successful pull-mode activation to render its warning banner - this
    field is never cleared by ``activate_task`` for any mode, only by a
    config save/re-preview (see ``update_task``/``preview_task``)."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _config(db, conn.id, company.id, delivery_mode=DELIVERY_MODE_PULL)
    _stamp_previewed(db, company.id, failed_count=4)

    view = EtlService(db).activate_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    assert view.etl_status == ETL_STATUS_ACTIVE
    assert view.last_preview_failed_count == 4

    # ...and it round-trips from the DB too, not just the in-memory view the
    # same call already had the count on.
    config = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert config.last_preview_failed_count == 4


def test_pull_mode_activation_keeps_the_failed_count_on_the_wire(client, db):
    """Router-level companion to the service-level assertion above - the
    SAME field, over the wire, is what the Activate tab's fetch actually
    reads (``EtlTaskResponse.lastPreviewFailedCount``,
    ``routers/companies.py``)."""
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _config(db, conn.id, company.id, delivery_mode=DELIVERY_MODE_PULL)
    _stamp_previewed(db, company.id, failed_count=4)

    login = client.post(
        "/auth/login", json={"email": "demo@example.com", "password": "demo1234"}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    response = client.post(
        f"/autocount/companies/{company.id}/entities/{ENTITY_PRODUCT}/etl-task/activate",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["etlStatus"] == ETL_STATUS_ACTIVE
    assert body["lastPreviewFailedCount"] == 4
