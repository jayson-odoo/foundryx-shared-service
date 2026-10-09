"""Sprint-5/10 S3 review round 1 - NIT (foolproof-UI, AC-10-12): a PULL-mode
task must refuse ``run_task_now``/``repush_task`` with the existing
``EtlStateError`` (409) state-error pattern, naming pull mode, rather than
silently accepting the click and finishing DONE with nothing having
happened - the exact "never accept an action that will do nothing" failure
mode this plan's foolproof-UI rule forbids.

RED before the fix (proven by reverting the coder's own two guards locally,
restored after - see the final report): without them, ``run_task_now``
enqueues a REAL ``autocount_sync`` job that (under this suite's own AC-10-12
pull short-circuit) finishes ``JOB_DONE`` having done nothing, and
``repush_task`` happily clears the task's row hashes for a push that will
never happen - both silent no-ops, never the 409 an operator's foolproof-UI
click should get.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import (
    DELIVERY_MODE_PULL,
    ETL_STATUS_ACTIVE,
    AcCompany,
    AcEntityConfig,
    AcRowHash,
)
from modules.autocount.repositories import RowHashRepository
from modules.autocount.services.etl_service import EtlService, EtlStateError

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    ``test_s10_s3_delivery_mode.py``'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20). Review round 2 nit (item 6) -
    the refusals below are asserted BEFORE any extraction ever starts, but
    carried no explicit guard against a future change that let one through."""

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


def _pull_task(db, company, connection_id) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status=ETL_STATUS_ACTIVE,
        delivery_mode=DELIVERY_MODE_PULL,
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
    db.refresh(config)
    return config


def test_run_task_now_refuses_a_pull_task_with_409_naming_pull_mode(db):
    conn = _connection(db)
    company = _company(db, conn.id)
    _pull_task(db, company, conn.id)

    before_jobs = db.query(BackgroundJob).count()
    with pytest.raises(EtlStateError) as exc_info:
        EtlService(db).run_task_now(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    assert "pull mode" in str(exc_info.value).lower()
    # No job is enqueued at all - never a silently-finishing no-op.
    assert db.query(BackgroundJob).count() == before_jobs


def test_repush_task_refuses_a_pull_task_with_409_naming_pull_mode(db):
    conn = _connection(db)
    company = _company(db, conn.id)
    _pull_task(db, company, conn.id)
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, {"AED_SORENTO:SEED": "x" * 64}, seen_at=None,
    )
    db.commit()
    before_hashes = db.query(AcRowHash).filter(AcRowHash.company_id == company.id).count()
    assert before_hashes == 1

    with pytest.raises(EtlStateError) as exc_info:
        EtlService(db).repush_task(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)

    assert "pull mode" in str(exc_info.value).lower()
    # Nothing was cleared - the refusal happens BEFORE any mutation.
    assert (
        db.query(AcRowHash).filter(AcRowHash.company_id == company.id).count() == before_hashes
    )


def test_run_task_now_on_a_push_task_control_still_enqueues(db, monkeypatch):
    """Control: the SAME rig with ``delivery_mode='push'`` (today's default)
    still enqueues normally - proving the pull refusal is delivery-mode
    scoped, never a blanket regression on ``run_task_now`` itself."""
    import modules.autocount.http_source.source as http_source_module
    import httpx
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.models import DELIVERY_MODE_PUSH

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []},
        )

    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=httpx.Client(transport=httpx.MockTransport(handler))),
    )

    conn = _connection(db)
    company = _company(db, conn.id)
    config = _pull_task(db, company, conn.id)
    config.delivery_mode = DELIVERY_MODE_PUSH
    db.commit()

    before_jobs = db.query(BackgroundJob).count()
    EtlService(db).run_task_now(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert db.query(BackgroundJob).count() == before_jobs + 1


# ── kill tests ────────────────────────────────────────────────────────────
#
# * both refusal tests die (no exception raised, or a job enqueued / hashes
#   cleared) if either guard is removed - proven locally by reverting each
#   guard in turn and re-running (restored after, see the final report).
# * the control test dies if the pull refusal accidentally became a
#   blanket refusal on ``run_task_now`` regardless of delivery mode.
